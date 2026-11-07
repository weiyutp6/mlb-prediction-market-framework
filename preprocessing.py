"""
Preprocessing: filter MLB events to live games, classify their markets, and
assemble structured quote snapshots.

Usage:
    games = preprocess_live_games()      # Gamma metadata prices only
    games = enrich_with_clob(games)      # add live order-book depth
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

import market_data
from parsers import parse_field, parse_outcomes, parse_prices, parse_token_ids


# -- Market type classification -------------------------------------------------------

_ML_TYPES = {"moneyline", "winner", "ml"}
_RL_TYPES = {"spreads", "spread", "runline", "run_line", "rl"}   # 'spreads' is Polymarket's value
_TOT_TYPES = {"totals", "total", "over_under", "ou"}
_SKIP_TYPES = {"nrfi", "props", "player_props"}                  # prop bets: skipped

# Keyword fallbacks when sports_market_type is absent or unrecognised
_RL_KEYWORDS = ("run line", "runline", "-1.5", "+1.5")
_TOT_KEYWORDS = ("total runs", "over/under", " over ", " under ")
_ML_KEYWORDS = ("will ", "win the game", "win?", "moneyline")

# Question-text patterns that always indicate a prop to skip
_SKIP_KEYWORDS = (
    "inning", "first 5", "first five", " f5 ", "hits", "strikeout",
    "pitcher", "home run", " rbi", "1st 5", "ks ", "first inning",
)


def _classify(market) -> str | None:
    """Return 'moneyline', 'runline', 'totals', or None (skip)."""
    smt = (getattr(market, "sports_market_type", None) or "").lower().strip()

    if smt in _SKIP_TYPES:
        return None
    if smt in _ML_TYPES:
        return "moneyline"
    if smt in _RL_TYPES:
        return "runline"
    if smt in _TOT_TYPES:
        return "totals"

    # Keyword fallback for markets with no/unknown sports_market_type
    q = (parse_field(market, "question") or "").lower()
    if any(k in q for k in _SKIP_KEYWORDS):
        return None
    if any(k in q for k in _RL_KEYWORDS):
        return "runline"
    if any(k in q for k in _TOT_KEYWORDS):
        return "totals"
    if any(k in q for k in _ML_KEYWORDS):
        return "moneyline"
    return None


# -- Data structures -----------------------------------------------------------------

@dataclass
class OutcomeQuote:
    outcome: str            # "Home", "Away", "Over", "Under", team abbrev, etc.
    token_id: str
    last_price: float       # last-traded price (from Gamma outcome_prices)
    best_bid: float | None = None
    best_ask: float | None = None
    mid: float | None = None
    spread: float | None = None
    bid_depth: float = 0.0
    ask_depth: float = 0.0


@dataclass
class GameMarket:
    market_type: str        # "moneyline" | "runline" | "totals"
    question: str
    line: float | None      # run line or total; None for moneyline
    outcomes: list[OutcomeQuote] = field(default_factory=list)


@dataclass
class LiveGame:
    event_slug: str
    title: str
    game_status: str | None     # "in_progress" | "pregame" | None
    score: str | None           # raw score string from Polymarket, e.g. "3-2"
    period: str | None          # raw period/inning string, e.g. "7"
    game_id: int | None         # Polymarket game_id
    start_time: datetime | None = None   # scheduled first pitch (pre-game only)
    markets: list[GameMarket] = field(default_factory=list)


# -- Builders ------------------------------------------------------------------------

def _build_market(market) -> GameMarket | None:
    market_type = _classify(market)
    if market_type is None:
        return None

    question = parse_field(market, "question") or ""
    line = getattr(market, "line", None)

    # token_ids is a typed list[str] on GammaMarket; fall back to raw parsing
    token_ids = (getattr(market, "token_ids", None)
                 or parse_token_ids(parse_field(market, "clob_token_ids", "clobTokenIds")))
    outcomes = parse_outcomes(parse_field(market, "outcomes"))
    prices = parse_prices(parse_field(market, "outcome_prices", "outcomePrices"))

    if not token_ids or not outcomes:
        return None

    outcome_quotes = []
    for i, (name, tid) in enumerate(zip(outcomes, token_ids)):
        last_price = prices[i] if i < len(prices) else 0.0
        outcome_quotes.append(OutcomeQuote(
            outcome=name, token_id=tid, last_price=last_price,
        ))

    return GameMarket(market_type=market_type, question=question,
                      line=line, outcomes=outcome_quotes)


def _build_game_markets(event) -> list[GameMarket]:
    game_markets = []
    for market in market_data.get_event_markets(event):
        gm = _build_market(market)
        if gm is not None:
            game_markets.append(gm)
    return game_markets


def preprocess_live_games() -> list[LiveGame]:
    """
    Return structured LiveGame objects for all MLB games currently in progress.

    Prices come from Gamma metadata (last_trade_price via outcome_prices).
    Call enrich_with_clob() afterwards for live order-book bid/ask/depth.
    """
    games = []

    for event in market_data.get_active_mlb_events():
        if not getattr(event, "live", False) or getattr(event, "ended", False):
            continue

        game_markets = _build_game_markets(event)
        if not game_markets:
            continue

        games.append(LiveGame(
            event_slug=getattr(event, "slug", None) or "",
            title=getattr(event, "title", None) or "",
            game_status=getattr(event, "game_status", None),
            score=getattr(event, "score", None),
            period=getattr(event, "period", None),
            game_id=getattr(event, "game_id", None),
            markets=game_markets,
        ))

    return games


def preprocess_pregame_games(lookahead_hours: int = 24) -> list[LiveGame]:
    """
    Return upcoming MLB games (not yet started) with pre-game lines.

    Filters to individual game events that have a start_time within the next
    lookahead_hours and have not yet gone live, ended, or closed.
    Results are sorted by first-pitch time.
    """
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=lookahead_hours)

    games = []
    for event in market_data.get_active_mlb_events():
        game_id = getattr(event, "game_id", None)
        start_time = getattr(event, "start_time", None)

        # Must be an individual game event, not a season-long market
        if not game_id or not start_time:
            continue
        # Must not have started yet and be within the lookahead window
        if (getattr(event, "live", None)
                or getattr(event, "ended", False)
                or getattr(event, "closed", False)):
            continue
        if not (now <= start_time <= cutoff):
            continue

        game_markets = _build_game_markets(event)
        if not game_markets:
            continue

        games.append(LiveGame(
            event_slug=getattr(event, "slug", None) or "",
            title=getattr(event, "title", None) or "",
            game_status="pregame",
            score=None,
            period=None,
            game_id=game_id,
            start_time=start_time,
            markets=game_markets,
        ))

    return sorted(games, key=lambda g: g.start_time or now)


def enrich_with_clob(games: list[LiveGame]) -> list[LiveGame]:
    """
    Batch-fetch live CLOB order books for every outcome token across all games
    and update OutcomeQuote fields (best_bid, best_ask, mid, spread, depth) in-place.

    Returns the same list for chaining:
        games = enrich_with_clob(preprocess_live_games())
    """
    all_tids = [
        oq.token_id
        for game in games
        for gm in game.markets
        for oq in gm.outcomes
        if oq.token_id
    ]
    if not all_tids:
        return games

    quotes = market_data.get_quotes(all_tids)

    for game in games:
        for gm in game.markets:
            for oq in gm.outcomes:
                q = quotes.get(oq.token_id)
                if not q or "error" in q:
                    continue
                oq.best_bid = q["best_bid"]
                oq.best_ask = q["best_ask"]
                oq.mid = q["mid"]
                oq.spread = q["spread"]
                oq.bid_depth = q["bid_depth"]
                oq.ask_depth = q["ask_depth"]

    return games
