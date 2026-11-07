"""
Signal generation: parse live game state and compare fair probabilities
against CLOB mid prices to produce actionable bet signals.

Signal.edge = fair_prob - clob_mid (positive => market underprices outcome)
Signal.side = "YES" (buy the outcome) or "NO" (buy the complement)
"""

import re
from dataclasses import dataclass

import heatmaps
from preprocessing import LiveGame, GameMarket, OutcomeQuote


# -- Game state --------------------------------------------------------------------

@dataclass
class GameState:
    inning: int        # 1-9 (extra innings clamped to 9)
    half: str          # "top" | "bot"
    away_score: int    # 0-10 (clamped)
    home_score: int    # 0-10 (clamped)


def parse_game_state(score: str | None, period: str | None) -> GameState | None:
    """
    Parse Polymarket's raw score and period strings into a GameState.

    Score formats seen: "3-2", "0-0", "10-7"
    Period formats seen: "7", "T7", "7T", "B3", "3B", "top 7", "bot 3",
                         "mid 5", "end 5" (treated as bot of that inning)

    Returns None if either value is missing or unparseable.
    """
    if not score or not period:
        return None

    # --- parse score ---
    m = re.match(r"(\d+)\s*[-:]\s*(\d+)", score.strip())
    if not m:
        return None
    away_score = min(int(m.group(1)), 10)
    home_score = min(int(m.group(2)), 10)

    # --- parse inning / half ---
    p = period.strip().lower()

    # Patterns: "T7", "top7", "top 7" -> top of inning 7
    #           "B3", "bot3", "bot 3", "bottom 3" -> bot of inning 3
    #           "mid5", "end5" -> treat as bot (between halves / end of inning)
    #           "7" -> assume top (no half info; conservative default)
    m2 = re.fullmatch(r"(t(?:op)?|b(?:ot(?:tom)?)?|mid|end)\s*(\d+)", p)
    if m2:
        half_raw, inn_str = m2.group(1), m2.group(2)
        half = "top" if half_raw.startswith("t") else "bot"
        return GameState(min(int(inn_str), 9), half, away_score, home_score)

    m3 = re.fullmatch(r"(\d+)\s*(t(?:op)?|b(?:ot(?:tom)?)?)", p)
    if m3:
        inn_str, half_raw = m3.group(1), m3.group(2)
        half = "top" if half_raw.startswith("t") else "bot"
        return GameState(min(int(inn_str), 9), half, away_score, home_score)

    m4 = re.fullmatch(r"(\d+)", p)
    if m4:
        return GameState(min(int(m4.group(1)), 9), "top", away_score, home_score)

    return None


# -- Signal ------------------------------------------------------------------------

@dataclass
class Signal:
    market_type: str   # "moneyline" | "runline" | "totals"
    question: str
    outcome: str       # outcome label ("Home", "Away", "Over", "Under", ...)
    token_id: str
    fair_prob: float   # model probability
    clob_mid: float    # CLOB mid price
    edge: float        # fair_prob - clob_mid
    side: str          # "YES" = buy outcome | "NO" = buy complement
    bid_depth: float   # available liquidity on buy side
    ask_depth: float   # available liquidity on sell side


def _make_signal(gm: GameMarket, oq: OutcomeQuote, fair: float,
                 min_edge: float, min_depth: float) -> Signal | None:
    """Shared edge / depth filter used by every market type."""
    if oq.mid is None:
        return None
    edge = fair - oq.mid
    if abs(edge) < min_edge:
        return None
    if edge > 0:
        bet_side, depth = "YES", oq.ask_depth
    else:
        bet_side, depth = "NO", oq.bid_depth
    if depth < min_depth:
        return None
    return Signal(
        market_type=gm.market_type,
        question=gm.question,
        outcome=oq.outcome,
        token_id=oq.token_id,
        fair_prob=fair,
        clob_mid=oq.mid,
        edge=edge,
        side=bet_side,
        bid_depth=oq.bid_depth,
        ask_depth=oq.ask_depth,
    )


# -- Moneyline ---------------------------------------------------------------------

def _ml_signals(gm: GameMarket, state: GameState,
                min_edge: float, min_depth: float) -> list[Signal]:
    if len(gm.outcomes) < 2:
        return []
    away_oq, home_oq = gm.outcomes[0], gm.outcomes[1]
    signals = []

    for side_str, oq in (("away", away_oq), ("home", home_oq)):
        fair = heatmaps.lookup_ml(side_str, state.inning, state.half,
                                  state.away_score, state.home_score)
        if fair is None:
            continue
        sig = _make_signal(gm, oq, fair, min_edge, min_depth)
        if sig:
            signals.append(sig)
    return signals


# -- Run line ----------------------------------------------------------------------

def _parse_rl_question(question: str, event_title: str) -> tuple[str, str] | None:
    """
    Return (handicapped_side, favored_side_str) where handicapped_side is
    'home' or 'away' (the team receiving -1.5).

    event_title format: "Away Team vs. Home Team"
    question format:    "Spread: {Team} (-1.5)" or similar
    """
    title_m = re.search(r"^(.+?)\s+vs\.?\s+(.+)$", event_title, re.IGNORECASE)
    if not title_m:
        return None
    away_name = title_m.group(1).strip().lower()
    home_name = title_m.group(2).strip().lower()

    q_lower = question.lower()
    # Extract team name from question: first word(s) before (-1.5) / -1.5
    team_m = re.search(r"spread[:\s]+(.+?)\s*[\(\-]1\.5", q_lower)
    if not team_m:
        return None
    q_team = team_m.group(1).strip()

    # Match against away/home name substrings
    if q_team in away_name or away_name in q_team:
        return ("away", "home")   # away team favored (-1.5 on away)
    if q_team in home_name or home_name in q_team:
        return ("home", "away")   # home team favored
    return None


def _rl_signals(gm: GameMarket, state: GameState, event_title: str,
                min_edge: float, min_depth: float) -> list[Signal]:
    if gm.line != -1.5 or len(gm.outcomes) < 2:
        return []

    parsed = _parse_rl_question(gm.question, event_title)
    if parsed is None:
        return []

    handicapped_side, other_side = parsed
    # outcomes[0] = team receiving -1.5, outcomes[1] = team receiving +1.5
    fav_oq, dog_oq = gm.outcomes[0], gm.outcomes[1]
    signals = []

    for side_str, oq in ((handicapped_side, fav_oq), (other_side, dog_oq)):
        fair = heatmaps.lookup_rl(side_str, state.inning, state.half,
                                  state.away_score, state.home_score)
        if fair is None:
            continue
        sig = _make_signal(gm, oq, fair, min_edge, min_depth)
        if sig:
            signals.append(sig)
    return signals


# -- Totals ------------------------------------------------------------------------

def _totals_signals(gm: GameMarket, state: GameState,
                    min_edge: float, min_depth: float) -> list[Signal]:
    if gm.line is None or len(gm.outcomes) < 2:
        return []

    current_total = state.away_score + state.home_score
    threshold = int(gm.line - current_total)   # floor: line ends in .5
    if not (1 <= threshold <= 6):
        return []

    p_under = heatmaps.lookup_totals(state.inning, state.half,
                                     state.away_score, state.home_score,
                                     threshold)
    if p_under is None:
        return []
    p_over = 1.0 - p_under

    # Convention: outcomes[0] = Over, outcomes[1] = Under
    over_oq, under_oq = gm.outcomes[0], gm.outcomes[1]
    signals = []

    for fair, oq in ((p_over, over_oq), (p_under, under_oq)):
        sig = _make_signal(gm, oq, fair, min_edge, min_depth)
        if sig:
            signals.append(sig)
    return signals


# -- Public API --------------------------------------------------------------------

def generate_signals(game: LiveGame, state: GameState,
                     min_edge: float = 0.10,
                     min_depth: float = 100.0) -> list[Signal]:
    """
    Compare fair probabilities against live CLOB mids for every market in
    game, returning Signals that exceed the edge and depth thresholds.
    """
    signals = []
    for gm in game.markets:
        if gm.market_type == "moneyline":
            signals.extend(_ml_signals(gm, state, min_edge, min_depth))
        elif gm.market_type == "runline":
            signals.extend(_rl_signals(gm, state, game.title, min_edge, min_depth))
        elif gm.market_type == "totals":
            signals.extend(_totals_signals(gm, state, min_edge, min_depth))
    return signals
