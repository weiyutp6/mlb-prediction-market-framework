"""
MLB prediction-market bot (paper trading by default).

Each polling cycle:
    1. Fetch all live MLB games with CLOB quotes
    2. Parse each game's current score + inning
    3. Generate fair-probability-vs-CLOB signals
    4. Size bets with fractional Kelly
    5. Execute (paper or live); skip tokens already bet this session

Usage:
    python bot.py
"""

import logging
import time

import config
from preprocessing import preprocess_live_games, enrich_with_clob
from signals import parse_game_state, generate_signals
from sizing import kelly_stake
from executor import execute

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def run_cycle(bet_tokens: set[str]) -> None:
    """
    Run one polling cycle.

    bet_tokens is updated in-place with token_ids that were bet this session
    so the same outcome is never double-bet.
    """
    games = enrich_with_clob(preprocess_live_games())
    if not games:
        log.info("No live games.")
        return

    log.info("%d live game(s) found.", len(games))

    for game in games:
        state = parse_game_state(game.score, game.period)
        if state is None:
            log.warning("Cannot parse game state for %s (score=%r period=%r)",
                        game.title, game.score, game.period)
            continue

        log.info(
            "%s | Inn %d%s | %s-%s",
            game.title,
            state.inning,
            state.half,
            state.away_score,
            state.home_score,
        )

        signals = generate_signals(
            game, state,
            min_edge=config.MIN_EDGE,
            min_depth=config.MIN_DEPTH_SHARES,
        )

        if config.ALLOWED_MARKET_TYPES:
            signals = [s for s in signals if s.market_type in config.ALLOWED_MARKET_TYPES]

        if not signals:
            log.info("  No signals above threshold.")
            continue

        for sig in signals:
            if sig.token_id in bet_tokens:
                log.debug("  Skipping already-bet token %s", sig.token_id)
                continue

            stake = kelly_stake(
                sig,
                bankroll=config.BANKROLL,
                kelly_fraction=config.KELLY_FRACTION,
                max_position_usd=config.MAX_POSITION_USD,
            )
            if stake <= 0:
                continue

            placed = execute(
                sig,
                stake_usd=stake,
                paper=config.PAPER_TRADING,
                expiry_minutes=config.ORDER_EXPIRY_MINUTES,
            )
            if placed:
                bet_tokens.add(sig.token_id)


def main() -> None:
    mode = "PAPER" if config.PAPER_TRADING else "LIVE"
    log.info("=== MLB prediction-market bot [%s MODE] started ===", mode)
    if not config.PAPER_TRADING and not config.WALLET_PRIVATE_KEY:
        log.error("POLYMARKET_PRIVATE_KEY not set. Set env var or enable PAPER_TRADING.")
        return

    bet_tokens: set[str] = set()

    while True:
        try:
            run_cycle(bet_tokens)
        except KeyboardInterrupt:
            log.info("Stopped by user.")
            break
        except Exception as exc:
            log.error("Cycle error: %s", exc, exc_info=True)

        log.info("Sleeping %ds...", config.POLL_INTERVAL_SEC)
        time.sleep(config.POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()
