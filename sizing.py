"""
Position sizing using fractional Kelly criterion.

Kelly formula:
    f* = edge / (1 - market_price)

where edge = fair_prob - market_price (positive => we have an edge buying YES).

The dollar stake is then:
    stake = bankroll * kelly_fraction * f*
    stake = min(stake, MAX_POSITION_USD)

For a NO bet the complementary probability is used:
    market_price_no = 1 - market_price_yes
    fair_prob_no    = 1 - fair_prob_yes
    edge_no = fair_prob_no - market_price_no = -(fair_prob_yes - market_price_yes)

Signals already carry the correct edge sign regardless of YES/NO side.
"""

from signals import Signal


def kelly_stake(signal: Signal,
                bankroll: float,
                kelly_fraction: float,
                max_position_usd: float) -> float:
    """
    Return the dollar amount to stake on signal, or 0.0 if unprofitable.

    signal.clob_mid is the market price of the outcome we are evaluating.
    For a YES bet: market_price = signal.clob_mid
    For a NO bet:  market_price = 1 - signal.clob_mid
    """
    if signal.side == "YES":
        market_price = signal.clob_mid
        edge = signal.edge          # fair_prob - clob_mid, already > 0 for YES
    else:
        market_price = 1.0 - signal.clob_mid
        edge = -signal.edge         # edge is negative for NO bets in Signal

    if edge <= 0 or market_price <= 0 or market_price >= 1:
        return 0.0

    # Full Kelly fraction of bankroll
    f_star = edge / (1.0 - market_price)
    stake = bankroll * kelly_fraction * f_star
    return min(stake, max_position_usd)
