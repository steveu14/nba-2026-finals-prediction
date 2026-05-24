"""
elo_model.py
============
ELO engine + series/finals projection.

Key changes from v1:
  - build_elo_ratings() accepts an optional playoff_games list so the model
    can be driven by live data from fetch_data.fetch_live_playoff_state().
  - project_finals_dynamic() projects from whatever round is currently active,
    automatically handling conf finals, NBA finals, or a completed tournament.
"""

import math
import itertools
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

# ── Hyperparameters ───────────────────────────────────────────────────────────
K_FACTOR       = 20     # ELO points exchanged per game
HOME_ADVANTAGE = 40     # ELO bonus for home team
SCALE          = 400    # Logistic scale
BASE_ELO       = 1500

# Weights for blending regular-season metrics into base ELO
W_NET_RTG = 0.45
W_SRS     = 0.35
W_WIN_PCT = 0.20

# Conference membership (for Finals home-court logic)
EAST = {"ATL","BOS","BKN","CHA","CHI","CLE","DET","IND","MIA","MIL","NYK","ORL","PHI","TOR","WAS"}
WEST = {"DAL","DEN","GSW","HOU","LAC","LAL","MEM","MIN","NOP","OKC","PHX","POR","SAC","SAS","UTA"}

TEAM_NAMES = {
    "OKC":"Oklahoma City Thunder","SAS":"San Antonio Spurs",
    "NYK":"New York Knicks","CLE":"Cleveland Cavaliers",
    "DET":"Detroit Pistons","PHI":"Philadelphia 76ers",
    "LAL":"Los Angeles Lakers","MIN":"Minnesota Timberwolves",
    "HOU":"Houston Rockets","DEN":"Denver Nuggets",
    "ATL":"Atlanta Hawks","TOR":"Toronto Raptors",
    "ORL":"Orlando Magic","BOS":"Boston Celtics",
    "PHX":"Phoenix Suns","POR":"Portland Trail Blazers",
}


@dataclass
class TeamELO:
    abbr:    str
    name:    str
    elo:     float
    net_rtg: float
    srs:     float
    win_pct: float
    composite: float = field(init=False)

    def __post_init__(self):
        self.composite = (
            W_NET_RTG * self.net_rtg +
            W_SRS     * self.srs +
            W_WIN_PCT * (self.win_pct - 0.5) * 20
        )


# ═════════════════════════════════════════════════════════════════════════════
#  BUILD ELO RATINGS
# ═════════════════════════════════════════════════════════════════════════════

def build_elo_ratings(stats_df,
                      playoff_games: Optional[List[Tuple]] = None
                      ) -> Dict[str, "TeamELO"]:
    """
    Build playoff-adjusted ELO ratings.

    Parameters
    ----------
    stats_df      : DataFrame from fetch_data.load_all_stats()
    playoff_games : list of (winner, loser, home) tuples; if None,
                    falls back to FALLBACK_PLAYOFF_GAMES from fetch_data.
    """
    import numpy as np
    from fetch_data import FALLBACK_PLAYOFF_GAMES

    if playoff_games is None:
        playoff_games = list(FALLBACK_PLAYOFF_GAMES)

    teams: Dict[str, TeamELO] = {}

    for abbr, row in stats_df.iterrows():
        w = row.get("wins", 45)
        l = row.get("losses", 37)
        wp = w / (w + l) if (w + l) > 0 else 0.5
        t = TeamELO(
            abbr    = abbr,
            name    = TEAM_NAMES.get(abbr, str(row.get("team_name", abbr))),
            elo     = BASE_ELO,
            net_rtg = float(row.get("net_rtg", 0.0)),
            srs     = float(row.get("srs", 0.0)),
            win_pct = wp,
        )
        teams[abbr] = t

    # Normalise composite score → ELO (mean=1500, std≈150)
    composites = np.array([t.composite for t in teams.values()])
    c_mean = composites.mean()
    c_std  = composites.std() if composites.std() > 0 else 1.0
    for t in teams.values():
        t.elo = BASE_ELO + ((t.composite - c_mean) / c_std) * 150.0

    # Apply every known playoff game result
    for winner, loser, home in playoff_games:
        if winner in teams and loser in teams:
            _apply_game(teams, winner, loser, home)

    return teams


def _apply_game(teams, winner, loser, home):
    r_w = teams[winner].elo + (HOME_ADVANTAGE if winner == home else -HOME_ADVANTAGE)
    r_l = teams[loser].elo  + (HOME_ADVANTAGE if loser  == home else -HOME_ADVANTAGE)
    exp_w = _expected(r_w, r_l)
    teams[winner].elo += K_FACTOR * (1 - exp_w)
    teams[loser].elo  += K_FACTOR * (0 - (1 - exp_w))


def _expected(ra, rb):
    return 1.0 / (1.0 + 10 ** ((rb - ra) / SCALE))


# ═════════════════════════════════════════════════════════════════════════════
#  SERIES WIN PROBABILITY
# ═════════════════════════════════════════════════════════════════════════════

def game_win_prob(team_a: str, team_b: str, home: str,
                  teams: Dict[str, TeamELO]) -> float:
    ra = teams[team_a].elo + (HOME_ADVANTAGE if home == team_a else
                              -HOME_ADVANTAGE if home == team_b else 0)
    rb = teams[team_b].elo + (HOME_ADVANTAGE if home == team_b else
                              -HOME_ADVANTAGE if home == team_a else 0)
    return _expected(ra, rb)


def series_win_prob(team_a: str, team_b: str,
                    home_team: str,
                    teams: Dict[str, TeamELO],
                    wins_a: int = 0, wins_b: int = 0,
                    games_to_win: int = 4) -> float:
    """
    Probability that team_a wins the series given current state.
    Uses recursive enumeration of all remaining game paths.
    """
    need_a = games_to_win - wins_a
    need_b = games_to_win - wins_b
    if need_a <= 0: return 1.0
    if need_b <= 0: return 0.0
    memo = {}
    return _p_win(team_a, team_b, need_a, need_b,
                  home_team, teams, memo, games_to_win, wins_a, wins_b)


def _p_win(ta, tb, need_a, need_b, home_team, teams, memo,
           gtw, orig_wa, orig_wb):
    if need_a == 0: return 1.0
    if need_b == 0: return 0.0
    key = (need_a, need_b)
    if key in memo: return memo[key]

    games_played = (gtw - need_a + orig_wa) + (gtw - need_b + orig_wb)
    home = _home_for_game(games_played + 1, home_team, ta, tb)
    p = game_win_prob(ta, tb, home, teams)

    result = (p       * _p_win(ta, tb, need_a-1, need_b,   home_team, teams, memo, gtw, orig_wa, orig_wb) +
              (1 - p) * _p_win(ta, tb, need_a,   need_b-1, home_team, teams, memo, gtw, orig_wa, orig_wb))
    memo[key] = result
    return result


def _home_for_game(game_num: int, home_team: str, ta: str, tb: str) -> str:
    """NBA 2-2-1-1-1 home court schedule."""
    home_games = {1, 2, 5, 7}
    away_team = tb if home_team == ta else ta
    return home_team if game_num in home_games else away_team


# ═════════════════════════════════════════════════════════════════════════════
#  DYNAMIC FINALS PROJECTION (works from any round)
# ═════════════════════════════════════════════════════════════════════════════

def project_finals_dynamic(teams: Dict[str, TeamELO],
                            active_series: list,
                            series_states: dict,
                            series_wins: dict) -> dict:
    """
    Projects the NBA champion from the current playoff state.
    Handles:
      - Conference Finals in progress (2 active series)
      - NBA Finals in progress (1 active series)
      - Tournament complete (0 active series)
    """
    if not active_series:
        # Tournament finished — find champion
        if series_wins:
            champ = max(series_wins, key=series_wins.get)
            return {
                "champion_probs":   {champ: 1.0},
                "conf_final_probs": {},
                "matchup_details":  [],
                "status":           "complete",
                "champion":         champ,
            }
        return {"champion_probs": {}, "status": "unknown"}

    # Separate series by conference label
    conf_series  = [s for s in active_series if s["conference"] in ("East","West")]
    final_series = [s for s in active_series if s["conference"] == "Finals"]

    # ── NBA Finals in progress ────────────────────────────────────────────────
    if final_series:
        s = final_series[0]
        t1, t2 = s["teams"]
        w1, w2 = s["wins"][t1], s["wins"][t2]
        # Home court: West team hosts Games 1-2 in the Finals by NBA convention
        west_team = t1 if t1 in WEST else t2
        p_t1 = series_win_prob(t1, t2, west_team, teams, w1, w2)
        return {
            "champion_probs":   {t1: p_t1, t2: 1 - p_t1},
            "conf_final_probs": {},
            "matchup_details":  [{
                "east": t1 if t1 in EAST else t2,
                "west": t1 if t1 in WEST else t2,
                "prob_matchup":    1.0,
                "prob_east_wins":  p_t1 if t1 in EAST else 1 - p_t1,
                "prob_west_wins":  p_t1 if t1 in WEST else 1 - p_t1,
            }],
            "status": "finals",
        }

    # ── Conference Finals in progress ─────────────────────────────────────────
    if len(conf_series) >= 2:
        east_s = next((s for s in conf_series if s["conference"] == "East"), None)
        west_s = next((s for s in conf_series if s["conference"] == "West"), None)

        if not east_s or not west_s:
            # Only one conf final active (the other hasn't started or is done)
            return _project_single_conf(teams, conf_series, series_wins)

        ea, eb = east_s["teams"]
        wa_e, wb_e = east_s["wins"][ea], east_s["wins"][eb]
        p_ea = series_win_prob(ea, eb, east_s["home"], teams, wa_e, wb_e)

        wa, wb = west_s["teams"]
        ww_a, ww_b = west_s["wins"][wa], west_s["wins"][wb]
        p_wa = series_win_prob(wa, wb, west_s["home"], teams, ww_a, ww_b)

        # All 4 possible Finals matchups
        champ_probs    = defaultdict(float)
        matchup_details = []
        for (ec, p_ec), (wc, p_wc) in itertools.product(
            [(ea, p_ea), (eb, 1 - p_ea)],
            [(wa, p_wa), (wb, 1 - p_wa)],
        ):
            p_matchup    = p_ec * p_wc
            west_home    = wc   # West team hosts G1-G2 of Finals
            p_ec_wins    = series_win_prob(ec, wc, west_home, teams)
            champ_probs[ec] += p_matchup * p_ec_wins
            champ_probs[wc] += p_matchup * (1 - p_ec_wins)
            matchup_details.append({
                "east": ec, "west": wc,
                "prob_matchup":   round(p_matchup   * 100, 1),
                "prob_east_wins": round(p_ec_wins   * 100, 1),
                "prob_west_wins": round((1-p_ec_wins)* 100, 1),
            })

        return {
            "champion_probs": dict(champ_probs),
            "conf_final_probs": {
                ea: p_ea, eb: 1 - p_ea,
                wa: p_wa, wb: 1 - p_wa,
            },
            "matchup_details": sorted(matchup_details, key=lambda x: -x["prob_matchup"]),
            "status": "conf_finals",
        }

    # ── Earlier rounds or edge cases ─────────────────────────────────────────
    # Just return win probabilities for each active series
    champ_probs = {}
    for s in active_series:
        t1, t2 = s["teams"]
        w1, w2 = s["wins"][t1], s["wins"][t2]
        p = series_win_prob(t1, t2, s["home"], teams, w1, w2)
        champ_probs[t1] = p
        champ_probs[t2] = 1 - p

    return {
        "champion_probs":   champ_probs,
        "conf_final_probs": champ_probs,
        "matchup_details":  [],
        "status":           "early_round",
    }


def _project_single_conf(teams, conf_series, series_wins):
    """Handle the edge case where only one conf final is active."""
    s = conf_series[0]
    t1, t2 = s["teams"]
    w1, w2 = s["wins"][t1], s["wins"][t2]
    p = series_win_prob(t1, t2, s["home"], teams, w1, w2)
    return {
        "champion_probs": {t1: p * 0.5, t2: (1 - p) * 0.5},
        "conf_final_probs": {t1: p, t2: 1 - p},
        "matchup_details": [],
        "status": "conf_finals",
    }


# ── Legacy helper kept for nba_finals_2026.py CLI compatibility ──────────────
def _home_court_for_game(game_num, home_team, ta, tb):
    return _home_for_game(game_num, home_team, ta, tb)