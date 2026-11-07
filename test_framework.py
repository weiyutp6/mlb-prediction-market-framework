"""Offline checks for the parts of the framework that need no network."""
import heatmaps
from signals import parse_game_state, Signal
from sizing import kelly_stake


def test_parse_game_state():
    s = parse_game_state("3-2", "B7")
    assert (s.inning, s.half, s.away_score, s.home_score) == (7, "bot", 3, 2)
    assert parse_game_state("0-0", "top 1").half == "top"
    assert parse_game_state("1-0", "T7").half == "top"
    assert parse_game_state("1-0", "7B").half == "bot"
    assert parse_game_state("1-0", "mid 5").half == "bot"
    assert parse_game_state(None, "7") is None


def test_moneyline_is_complementary():
    for inning in (1, 5, 9):
        for half in ("top", "bot"):
            home = heatmaps.lookup_ml("home", inning, half, 2, 3)
            away = heatmaps.lookup_ml("away", inning, half, 2, 3)
            assert abs(home + away - 1.0) < 1e-9


def test_leading_team_is_favoured_late():
    leading = heatmaps.lookup_ml("home", 8, "top", 1, 4)
    trailing = heatmaps.lookup_ml("home", 8, "top", 4, 1)
    assert leading > 0.9 > 0.1 > trailing


def test_totals_cdf_is_monotone_in_threshold():
    probs = [heatmaps.lookup_totals(5, "top", 1, 1, k) for k in range(1, 7)]
    assert probs == sorted(probs)
    assert heatmaps.lookup_totals(5, "top", 1, 1, 7) is None


def test_runline_never_exceeds_moneyline():
    ml = heatmaps.lookup_ml("home", 6, "bot", 2, 2)
    rl = heatmaps.lookup_rl("home", 6, "bot", 2, 2)
    assert rl < ml


def _signal(side, mid, edge):
    return Signal("moneyline", "q", "Home", "tok", mid + edge, mid, edge, side, 500, 500)


def test_kelly_stake_scales_and_caps():
    small = kelly_stake(_signal("YES", 0.40, 0.10), 1000, 0.10, 100)
    big = kelly_stake(_signal("YES", 0.40, 0.20), 1000, 0.10, 100)
    assert 0 < small < big
    assert kelly_stake(_signal("YES", 0.40, 0.20), 1000, 0.10, 1.0) == 1.0
    assert kelly_stake(_signal("NO", 0.60, -0.10), 1000, 0.10, 100) > 0
