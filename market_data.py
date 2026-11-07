"""
Central data-access layer for Polymarket Gamma (event metadata) and CLOB (pricing).

Clients are module-level singletons -- import and call the functions directly.
"""

from datetime import datetime
from polymarket_apis import PolymarketGammaClient, PolymarketReadOnlyClobClient

from parsers import parse_field, parse_outcomes, parse_prices, parse_token_ids

gamma = PolymarketGammaClient()
clob = PolymarketReadOnlyClobClient()

_auth_clob = None  # lazy-initialised on first live order


def get_authenticated_clob_client():
    """Return a PolymarketClobClient authenticated with env-var credentials."""
    global _auth_clob
    if _auth_clob is None:
        import config
        from polymarket_apis import PolymarketClobClient
        _auth_clob = PolymarketClobClient(
            private_key=config.WALLET_PRIVATE_KEY,
            address=config.WALLET_ADDRESS,
        )
    return _auth_clob


# Polymarket tag ID for MLB individual game events (tag slug: "mlb")
_MLB_TAG_ID = 100381


# -- Event discovery -----------------------------------------------------------------

def get_active_mlb_events() -> list:
    """Return all currently active (in-play or pre-game, not yet resolved) MLB events."""
    result = []
    for offset in range(0, 5000, 100):
        try:
            batch = gamma.get_events(
                active=True,
                closed=False,
                tag_id=_MLB_TAG_ID,
                limit=100,
                offset=offset,
            )
        except Exception:
            continue
        if not batch:
            break
        result.extend(batch)
        if len(batch) < 100:
            break
    return result


def get_historical_mlb_events(date: str) -> list:
    """
    Return resolved MLB events for a given calendar date (YYYY-MM-DD, UTC).

    Polymarket's date fields don't align with game date -- start_date is the
    market creation date, end_date is the weekly betting window. The slug
    reliably encodes the game date (e.g. mlb-hou-tex-2026-05-25), so we
    paginate with the MLB tag filter and match client-side by slug.

    Each page is wrapped in try/except to tolerate a known polymarket_apis
    Pydantic bug where non-MLB events with UUID game_ids crash event parsing.
    """
    result = []
    for offset in range(0, 5000, 100):
        try:
            batch = gamma.get_events(
                closed=True,
                active=True,   # MLB game events keep active=True after resolving
                tag_id=_MLB_TAG_ID,
                limit=100,
                offset=offset,
            )
        except Exception:
            continue
        if not batch:
            break
        for e in batch:
            if date in (parse_field(e, "slug") or ""):
                result.append(e)
        if len(batch) < 100:
            break
    return result


def get_event_by_slug(slug: str):
    """Fetch a single event by slug. Returns None if not found or on error."""
    try:
        return gamma.get_event_by_slug(slug)
    except Exception:
        return None


# -- CLOB quotes ---------------------------------------------------------------------

def _summarise_book(book) -> dict:
    bids = book.bids or []
    asks = book.asks or []
    best_bid = float(bids[0].price) if bids else None
    best_ask = float(asks[0].price) if asks else None
    mid = round((best_bid + best_ask) / 2, 4) if best_bid and best_ask else None
    spread = round(best_ask - best_bid, 4) if best_bid and best_ask else None
    bid_depth = round(sum(float(b.size) for b in bids), 1)
    ask_depth = round(sum(float(a.size) for a in asks), 1)
    return dict(best_bid=best_bid, best_ask=best_ask,
                mid=mid, spread=spread,
                bid_depth=bid_depth, ask_depth=ask_depth)


def get_quote(token_id: str) -> dict:
    """
    Return bid/ask/mid/spread/depth for a single outcome token.

    Keys: best_bid, best_ask, mid, spread, bid_depth, ask_depth
    Returns {"error": str} if the call fails.
    """
    try:
        return _summarise_book(clob.get_order_book(token_id))
    except Exception as e:
        return {"error": str(e)}


def get_quotes(token_ids: list[str]) -> dict[str, dict]:
    """
    Batch version of get_quote. Returns {token_id: quote_dict}.

    Falls back to individual calls if the batch endpoint fails.
    """
    if not token_ids:
        return {}
    try:
        books = clob.get_order_books(token_ids)
        return {book.asset_id: _summarise_book(book) for book in books}
    except Exception:
        return {tid: get_quote(tid) for tid in token_ids}


# -- Price history -------------------------------------------------------------------

def get_price_history(token_id: str, interval: str = "1d"):
    """
    Recent CLOB price history for a token.

    interval options: '1h', '6h', '1d', '1w', '1m', 'max'
    """
    return clob.get_recent_history(token_id, interval=interval)


def get_full_price_history(token_id: str,
                           start: datetime | None = None,
                           end: datetime | None = None):
    """Full CLOB price history, optionally bounded by start/end datetimes."""
    if start or end:
        return clob.get_history(token_id, start_time=start, end_time=end)
    return clob.get_all_history(token_id)


# -- Market helpers ------------------------------------------------------------------

def get_event_markets(event, skip_keywords: tuple[str, ...] = ()) -> list:
    """
    Return markets from an event, optionally skipping questions that contain
    any of the given keywords (case-insensitive).
    """
    markets = parse_field(event, "markets") or []
    if not skip_keywords:
        return markets
    return [
        m for m in markets
        if not any(k in (parse_field(m, "question") or "").lower() for k in skip_keywords)
    ]


def get_market_outcomes(market) -> list[tuple[str, str, float]]:
    """
    Return [(outcome_name, token_id, last_price), ...] for a market.
    last_price is 0.0 when unavailable.
    """
    outcomes = parse_outcomes(parse_field(market, "outcomes"))
    token_ids = parse_token_ids(parse_field(market, "clob_token_ids", "clobTokenIds", "token_ids"))
    prices = parse_prices(parse_field(market, "outcome_prices", "outcomePrices"))

    result = []
    for i, (outcome, tid) in enumerate(zip(outcomes, token_ids)):
        price = prices[i] if i < len(prices) else 0.0
        result.append((outcome, tid, price))
    return result
