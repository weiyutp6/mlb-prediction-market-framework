"""
Fair-probability lookup tables for in-game MLB markets.

This public version builds its tables from a deliberately simple model:
every half-inning, each team scores Poisson(RUNS_PER_HALF_INNING) runs,
independently. It is a stand-in so the pipeline can run end to end. It is
NOT calibrated to real data and it carries no trading edge.

The lookup API is the one the rest of the framework uses, so a table
calibrated on historical data can be dropped in by replacing the three
builder functions below.

Lookup keys
-----------
ML / RL : (side, inning, half, away_score, home_score) -> float | None
Totals  : (inning, half, away_score, home_score, threshold) -> float | None

where
    side      : "home" or "away"
    inning    : 1-9 (clamped to 9 for extra innings)
    half      : "top" or "bot"   (the half-inning about to be played)
    away/home : 0-10 (clamped to 10)
    threshold : 1-6, runs remaining <= threshold

Simplifications of the demo model
---------------------------------
* The full current half-inning is still to be played.
* The bottom of the 9th is always played (no walk-off truncation).
* A tie after nine innings counts as half a win for each side.
"""
from functools import lru_cache
from math import exp, factorial

RUNS_PER_HALF_INNING = 0.5          # about 4.5 runs per team per 9 innings
MAX_RUNS = 30                       # truncation point of the Poisson tail


def _poisson_pmf(mean: float) -> list[float]:
    if mean <= 0:
        return [1.0] + [0.0] * MAX_RUNS
    return [exp(-mean) * mean ** k / factorial(k) for k in range(MAX_RUNS + 1)]


def _half_innings_left(inning: int, half: str) -> tuple[int, int]:
    """(away batting halves left, home batting halves left), counting the
    half-inning in progress."""
    inning = min(inning, 9)
    if half == "top":
        away = 9 - inning + 1
        home = 9 - inning + 1
    else:
        away = 9 - inning
        home = 9 - inning + 1
    return away, home


@lru_cache(maxsize=None)
def _margin_distribution(inning: int, half: str, away: int, home: int) -> dict[int, float]:
    """P(final home margin = d) for every d."""
    n_away, n_home = _half_innings_left(inning, half)
    pa = _poisson_pmf(RUNS_PER_HALF_INNING * n_away)
    ph = _poisson_pmf(RUNS_PER_HALF_INNING * n_home)
    base = home - away
    dist: dict[int, float] = {}
    for ra, p_a in enumerate(pa):
        for rh, p_h in enumerate(ph):
            d = base + rh - ra
            dist[d] = dist.get(d, 0.0) + p_a * p_h
    return dist


@lru_cache(maxsize=None)
def _runs_remaining_cdf(inning: int, half: str, threshold: int) -> float:
    n_away, n_home = _half_innings_left(inning, half)
    pmf = _poisson_pmf(RUNS_PER_HALF_INNING * (n_away + n_home))
    return sum(pmf[: threshold + 1])


# -- Public API ----------------------------------------------------------------

def lookup_ml(side: str, inning: int, half: str, away: int, home: int) -> float | None:
    """Fair win probability for the money line."""
    if side not in ("home", "away") or half not in ("top", "bot"):
        return None
    dist = _margin_distribution(min(inning, 9), half, min(away, 10), min(home, 10))
    p_home = sum(p for d, p in dist.items() if d > 0) + 0.5 * dist.get(0, 0.0)
    return p_home if side == "home" else 1.0 - p_home


def lookup_rl(side: str, inning: int, half: str, away: int, home: int) -> float | None:
    """Fair probability for the run line (-1.5): the side wins by 2 or more."""
    if side not in ("home", "away") or half not in ("top", "bot"):
        return None
    dist = _margin_distribution(min(inning, 9), half, min(away, 10), min(home, 10))
    if side == "home":
        return sum(p for d, p in dist.items() if d >= 2)
    return sum(p for d, p in dist.items() if d <= -2)


def lookup_totals(inning: int, half: str, away: int, home: int, threshold: int) -> float | None:
    """
    P(runs_remaining <= threshold) for a totals bet.

    To price an over/under line X given current_total = away + home:
        threshold = int(line - current_total)     # floor, since lines end in .5
        P(under)  = lookup_totals(..., threshold)
        P(over)   = 1 - P(under)
    """
    if not (1 <= threshold <= 6) or half not in ("top", "bot"):
        return None
    return _runs_remaining_cdf(min(inning, 9), half, threshold)
