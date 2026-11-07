"""
Order execution: paper trading (log only) and live trading via Polymarket CLOB.

In paper mode all orders are logged but never submitted.
In live mode orders are submitted as GTC limit orders near the CLOB price.
"""

import logging
from datetime import datetime, timezone, timedelta

from signals import Signal

log = logging.getLogger(__name__)


def _expiry_unix(minutes: int) -> int:
    """Return UNIX timestamp minutes from now."""
    return int((datetime.now(timezone.utc) + timedelta(minutes=minutes)).timestamp())


def execute_paper(signal: Signal, stake_usd: float) -> None:
    """Log a paper trade without submitting anything."""
    log.info(
        "[PAPER] %s | %s | outcome=%s | side=%s | "
        "fair=%.4f | mid=%.4f | edge=%.4f | stake=$%.2f",
        signal.market_type.upper(),
        signal.question,
        signal.outcome,
        signal.side,
        signal.fair_prob,
        signal.clob_mid,
        signal.edge,
        stake_usd,
    )


def execute_live(signal: Signal, stake_usd: float,
                 expiry_minutes: int = 5) -> bool:
    """
    Submit a GTC limit order on the Polymarket CLOB.

    Returns True on success, False on failure.

    For a YES bet : buy `token_id` near the mid price
    For a NO bet  : not supported here (complement token is not tracked)
    """
    try:
        from polymarket_apis.types.clob_types import OrderArgs, OrderType
        import market_data

        if signal.side != "YES":
            log.warning("Live NO bets not yet supported; skipping %s", signal.outcome)
            return False

        # Price to submit: mid + one tick to improve fill probability
        price = round(min(signal.clob_mid + 0.01, 0.99), 4)
        # Shares = stake / price
        size = round(stake_usd / price, 2)

        order_args = OrderArgs(
            token_id=signal.token_id,
            price=price,
            size=size,
            side="BUY",
            expiration=_expiry_unix(expiry_minutes),
        )

        client = market_data.get_authenticated_clob_client()
        resp = client.create_and_post_order(order_args, order_type=OrderType.GTC)

        log.info(
            "[LIVE] %s | %s | outcome=%s | price=%.4f | size=%.2f | resp=%s",
            signal.market_type.upper(),
            signal.question,
            signal.outcome,
            price,
            size,
            resp,
        )
        return True

    except Exception as exc:
        log.error("[LIVE] Order failed for %s: %s", signal.outcome, exc)
        return False


def execute(signal: Signal, stake_usd: float,
            paper: bool = True,
            expiry_minutes: int = 5) -> bool:
    """
    Dispatch to paper or live execution.

    Returns True if the order was submitted (live) or logged (paper).
    """
    if stake_usd <= 0:
        return False
    if paper:
        execute_paper(signal, stake_usd)
        return True
    return execute_live(signal, stake_usd, expiry_minutes)
