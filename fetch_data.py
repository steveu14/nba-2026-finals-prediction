"""
fetch_data.py
=============
Two jobs:
  1. Regular-season team stats (net rating, SRS) for building base ELO.
  2. Live playoff game log so the model always reflects the latest results.
"""

import time
import warnings
import requests
import pandas as pd
from collections import defaultdict

warnings.filterwarnings("ignore")

# ── Conference membership ─────────────────────────────────────────────────────
EAST = {"ATL","BOS","BKN","CHA","CHI","CLE","DET","IND","MIA","MIL","NYK","ORL","PHI","TOR","WAS"}
WEST = {"DAL","DEN","GSW","HOU","LAC","LAL","MEM","MIN","NOP","OKC","PHX","POR","SAC","SAS","UTA"}

# ── Fallback regular-season data (2025-26) ────────────────────────────────────
FALLBACK_NET_RATINGS = {
    "OKC": 11.2, "SAS":  8.7, "NYK":  6.1, "CLE":  4.9,
    "DET":  5.8, "PHI":  3.2, "LAL":  4.1, "MIN":  3.8,
    "HOU":  2.1, "DEN":  5.5, "ATL":  1.4, "TOR": -1.2,
    "ORL":  2.8, "BOS":  6.9, "PHX":  0.5, "POR": -3.1,
}
FALLBACK_SRS = {
    "OKC":  8.9, "SAS":  6.8, "NYK":  4.9, "CLE":  3.7,
    "DET":  4.3, "PHI":  2.4, "LAL":  3.2, "MIN":  2.9,
    "HOU":  1.4, "DEN":  4.1, "ATL":  1.0, "TOR": -0.9,
    "ORL":  1.8, "BOS":  5.2, "PHX":  0.3, "POR": -2.5,
}
FALLBACK_RECORDS = {
    "OKC": (68,14), "SAS": (58,24), "NYK": (52,30), "CLE": (50,32),
    "DET": (53,29), "PHI": (46,36), "LAL": (49,33), "MIN": (48,34),
    "HOU": (43,39), "DEN": (51,31), "ATL": (40,42), "TOR": (36,46),
    "ORL": (44,38), "BOS": (51,31), "PHX": (38,44), "POR": (29,53),
}

# ── Hardcoded playoff games (fallback through May 22 2026) ───────────────────
# Format: (winner, loser, home_team)
FALLBACK_PLAYOFF_GAMES = [
    # Round 1 - East
    ("DET","ORL","DET"),("DET","ORL","DET"),("ORL","DET","ORL"),("ORL","DET","ORL"),
    ("DET","ORL","DET"),("ORL","DET","ORL"),("DET","ORL","DET"),
    ("CLE","TOR","CLE"),("CLE","TOR","CLE"),("TOR","CLE","TOR"),("TOR","CLE","TOR"),
    ("CLE","TOR","CLE"),("TOR","CLE","TOR"),("CLE","TOR","CLE"),
    ("NYK","ATL","NYK"),("NYK","ATL","NYK"),("ATL","NYK","ATL"),("NYK","ATL","ATL"),
    ("NYK","ATL","NYK"),("NYK","ATL","ATL"),
    ("PHI","BOS","BOS"),("PHI","BOS","BOS"),("BOS","PHI","PHI"),("BOS","PHI","PHI"),
    ("PHI","BOS","BOS"),("BOS","PHI","PHI"),("PHI","BOS","PHI"),
    # Round 1 - West
    ("OKC","PHX","OKC"),("OKC","PHX","OKC"),("OKC","PHX","PHX"),("OKC","PHX","PHX"),
    ("LAL","HOU","LAL"),("LAL","HOU","LAL"),("HOU","LAL","HOU"),("LAL","HOU","HOU"),
    ("LAL","HOU","LAL"),("LAL","HOU","HOU"),
    ("SAS","POR","SAS"),("SAS","POR","SAS"),("POR","SAS","POR"),("SAS","POR","POR"),
    ("SAS","POR","SAS"),
    ("MIN","DEN","DEN"),("DEN","MIN","DEN"),("MIN","DEN","MIN"),("MIN","DEN","MIN"),
    ("DEN","MIN","DEN"),("MIN","DEN","MIN"),
    # Round 2 - East
    ("NYK","PHI","NYK"),("NYK","PHI","NYK"),("NYK","PHI","PHI"),("NYK","PHI","PHI"),
    ("DET","CLE","DET"),("DET","CLE","DET"),("CLE","DET","CLE"),("CLE","DET","CLE"),
    ("CLE","DET","DET"),("DET","CLE","CLE"),("CLE","DET","DET"),
    # Round 2 - West
    ("OKC","LAL","OKC"),("OKC","LAL","OKC"),("OKC","LAL","LAL"),("OKC","LAL","LAL"),
    ("SAS","MIN","SAS"),("SAS","MIN","SAS"),("MIN","SAS","MIN"),("SAS","MIN","MIN"),
    ("SAS","MIN","SAS"),("SAS","MIN","MIN"),
    # Round 3 - Conf Finals (through May 22)
    ("NYK","CLE","NYK"),("NYK","CLE","NYK"),                      # East: NYK leads 2-0
    ("SAS","OKC","OKC"),("OKC","SAS","OKC"),("OKC","SAS","SAS"),  # West: OKC leads 2-1
]


# ═════════════════════════════════════════════════════════════════════════════
#  REGULAR SEASON STATS
# ═════════════════════════════════════════════════════════════════════════════

def fetch_nba_api_stats(season="2025-26") -> pd.DataFrame:
    try:
        from nba_api.stats.endpoints import leaguedashteamstats
        from nba_api.stats.static import teams as nba_teams
        print("  [nba_api] Fetching team stats …")
        time.sleep(0.6)

        # Try both param naming styles across nba_api versions
        try:
            stats = leaguedashteamstats.LeagueDashTeamStats(
                season=season, per_mode_nullable="Per100Possessions",
                measure_type_nullable="Advanced", timeout=15,
            )
        except TypeError:
            stats = leaguedashteamstats.LeagueDashTeamStats(
                season=season, per_mode_simple="Per100Possessions",
                measure_type_simple="Advanced", timeout=15,
            )

        df = stats.get_data_frames()[0]
        id_to_abbr = {t["id"]: t["abbreviation"] for t in nba_teams.get_teams()}
        df["ABBR"] = df["TEAM_ID"].map(id_to_abbr)
        df = df.dropna(subset=["ABBR"])
        result = df[["ABBR","TEAM_NAME","W","L","NET_RATING","OFF_RATING","DEF_RATING","PACE"]].copy()
        result.columns = ["abbr","team_name","wins","losses","net_rtg","off_rtg","def_rtg","pace"]
        result = result.set_index("abbr")
        print(f"  [nba_api] ✓ {len(result)} teams retrieved.")
        return result
    except Exception as e:
        print(f"  [nba_api] ✗ {e}. Using fallback.")
        rows = []
        for abbr, nr in FALLBACK_NET_RATINGS.items():
            w, l = FALLBACK_RECORDS.get(abbr, (45, 37))
            rows.append({"abbr": abbr, "team_name": abbr, "wins": w, "losses": l,
                         "net_rtg": nr, "off_rtg": 115 + nr/2, "def_rtg": 115 - nr/2, "pace": 98.5})
        return pd.DataFrame(rows).set_index("abbr")


def fetch_bbref_srs(season_year=2026) -> pd.DataFrame:
    url = f"https://www.basketball-reference.com/leagues/NBA_{season_year}.html"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        print("  [bbref]   Fetching SRS …")
        resp = requests.get(url, headers=headers, timeout=12)
        resp.raise_for_status()
        tables = pd.read_html(resp.text)
        rows = []
        for tbl in tables:
            if "SRS" in tbl.columns and "Team" in tbl.columns:
                sub = tbl[["Team","SRS"]].copy()
                sub = sub[pd.to_numeric(sub["SRS"], errors="coerce").notna()]
                sub["SRS"] = sub["SRS"].astype(float)
                rows.append(sub)
        if not rows:
            raise ValueError("No SRS table found")
        srs = pd.concat(rows, ignore_index=True)
        name_map = _bbref_name_to_abbr()
        srs["abbr"] = srs["Team"].map(name_map)
        srs = srs.dropna(subset=["abbr"])[["abbr","SRS"]].rename(columns={"SRS":"srs"})
        print(f"  [bbref]   ✓ {len(srs)} teams.")
        return srs.set_index("abbr")
    except Exception as e:
        print(f"  [bbref]   ✗ {e}. Using fallback SRS.")
        return pd.DataFrame([{"abbr": k, "srs": v} for k, v in FALLBACK_SRS.items()]).set_index("abbr")


def load_all_stats(season="2025-26", season_year=2026) -> pd.DataFrame:
    print("\n── Regular season stats ──────────────────────────────────────")
    nba_df = fetch_nba_api_stats(season)
    srs_df  = fetch_bbref_srs(season_year)
    merged  = nba_df.join(srs_df, how="left")
    for abbr, val in FALLBACK_SRS.items():
        if abbr in merged.index and pd.isna(merged.loc[abbr, "srs"]):
            merged.loc[abbr, "srs"] = val
    merged["srs"] = pd.to_numeric(merged["srs"], errors="coerce").fillna(0.0)
    return merged


# ═════════════════════════════════════════════════════════════════════════════
#  LIVE PLAYOFF STATE
# ═════════════════════════════════════════════════════════════════════════════

def fetch_live_playoff_state(season="2025-26") -> dict:
    """
    Fetches all 2026 playoff game results from nba_api and derives:
      - playoff_games   : list of (winner, loser, home) for the ELO model
      - series_states   : {frozenset(t1,t2): {t1:wins, t2:wins, 'complete':bool}}
      - active_series   : list of incomplete series with metadata
      - series_wins     : {team: number_of_series_won}
      - remaining_teams : teams not yet eliminated
    Falls back to hardcoded data if the API is unavailable.
    """
    try:
        from nba_api.stats.endpoints import LeagueGameLog
        print("  [live]    Fetching playoff game log …")
        time.sleep(0.6)

        try:
            glf = LeagueGameLog(
                season=season, season_type_nullable="Playoffs",
                direction_nullable="ASC", timeout=20,
            )
        except TypeError:
            glf = LeagueGameLog(
                season=season, season_type_all_star="Playoffs",
                direction="ASC", timeout=20,
            )

        df = glf.get_data_frames()[0]
        if df.empty:
            raise ValueError("Empty game log returned")

        games = _parse_game_log(df)
        print(f"  [live]    ✓ {len(games)} playoff games found.")
        return _build_playoff_state(games, source="live")

    except Exception as e:
        print(f"  [live]    ✗ {e}. Using hardcoded fallback.")
        return _build_playoff_state(list(FALLBACK_PLAYOFF_GAMES), source="fallback")


def _parse_game_log(df) -> list:
    """Convert nba_api game log DataFrame into (winner, loser, home) tuples."""
    games = []
    for game_id, group in df.groupby("GAME_ID"):
        if len(group) < 2:
            continue
        w_rows = group[group["WL"] == "W"]
        l_rows = group[group["WL"] == "L"]
        if w_rows.empty or l_rows.empty:
            continue
        w_row = w_rows.iloc[0]
        l_row = l_rows.iloc[0]
        winner = w_row["TEAM_ABBREVIATION"]
        loser  = l_row["TEAM_ABBREVIATION"]
        # 'vs.' in matchup means that team is HOME
        home = winner if " vs. " in str(w_row.get("MATCHUP", "")) else loser
        games.append((winner, loser, home))
    return games


def _build_playoff_state(games: list, source: str) -> dict:
    series_states   = _compute_series_states(games)
    series_wins     = _get_series_wins_per_team(series_states)
    active_series   = _get_active_series(series_states, series_wins)
    remaining_teams = _get_remaining_teams(series_states)
    return {
        "playoff_games":    games,
        "series_states":    series_states,
        "active_series":    active_series,
        "series_wins":      series_wins,
        "remaining_teams":  list(remaining_teams),
        "source":           source,
    }


def _compute_series_states(games: list) -> dict:
    """
    Returns {frozenset({t1,t2}): {t1: wins, t2: wins, 'complete': bool}}.
    A series is complete when either team reaches 4 wins.
    """
    wins = defaultdict(lambda: defaultdict(int))
    for winner, loser, _ in games:
        pair = frozenset({winner, loser})
        wins[pair][winner] += 1

    states = {}
    for pair, team_wins in wins.items():
        t1, t2 = tuple(pair)
        w1 = team_wins.get(t1, 0)
        w2 = team_wins.get(t2, 0)
        states[pair] = {t1: w1, t2: w2, "complete": max(w1, w2) >= 4}
    return states


def _get_series_wins_per_team(series_states: dict) -> dict:
    """How many series has each team won (completed series only)."""
    wins = defaultdict(int)
    for pair, data in series_states.items():
        if data["complete"]:
            t1, t2 = tuple(pair)
            winner = t1 if data[t1] > data[t2] else t2
            wins[winner] += 1
    return dict(wins)


def _get_active_series(series_states: dict, series_wins: dict) -> list:
    """
    Returns incomplete series enriched with metadata:
      {teams, wins, home, conference, round_num}
    """
    active = []
    for pair, data in series_states.items():
        if data["complete"]:
            continue
        t1, t2 = tuple(pair)
        w1, w2 = data[t1], data[t2]

        # Determine conference (same conference = conf series; mixed = finals)
        t1_conf = "East" if t1 in EAST else "West"
        t2_conf = "East" if t2 in EAST else "West"
        if t1_conf == t2_conf:
            conference = t1_conf
        else:
            conference = "Finals"

        # Round number = series wins of participants + 1
        round_num = series_wins.get(t1, 0) + 1

        # Home court: team with more series wins, else t1
        sw1 = series_wins.get(t1, 0)
        sw2 = series_wins.get(t2, 0)
        # Use series wins as proxy for seeding; equal → use t1 as placeholder
        home = t1 if sw1 >= sw2 else t2

        active.append({
            "teams":       (t1, t2),
            "wins":        {t1: w1, t2: w2},
            "home":        home,
            "conference":  conference,
            "round_num":   round_num,
        })
    return active


def _get_remaining_teams(series_states: dict) -> set:
    """Teams that have not been eliminated (lost a series)."""
    eliminated = set()
    for pair, data in series_states.items():
        if data["complete"]:
            t1, t2 = tuple(pair)
            loser = t1 if data[t1] < data[t2] else t2
            eliminated.add(loser)
    all_teams = {t for pair in series_states for t in pair}
    return all_teams - eliminated


def _bbref_name_to_abbr() -> dict:
    return {
        "Atlanta Hawks":"ATL","Boston Celtics":"BOS","Brooklyn Nets":"BKN",
        "Charlotte Hornets":"CHA","Chicago Bulls":"CHI","Cleveland Cavaliers":"CLE",
        "Dallas Mavericks":"DAL","Denver Nuggets":"DEN","Detroit Pistons":"DET",
        "Golden State Warriors":"GSW","Houston Rockets":"HOU","Indiana Pacers":"IND",
        "Los Angeles Clippers":"LAC","Los Angeles Lakers":"LAL","Memphis Grizzlies":"MEM",
        "Miami Heat":"MIA","Milwaukee Bucks":"MIL","Minnesota Timberwolves":"MIN",
        "New Orleans Pelicans":"NOP","New York Knicks":"NYK","Oklahoma City Thunder":"OKC",
        "Orlando Magic":"ORL","Philadelphia 76ers":"PHI","Phoenix Suns":"PHX",
        "Portland Trail Blazers":"POR","Sacramento Kings":"SAC","San Antonio Spurs":"SAS",
        "Toronto Raptors":"TOR","Utah Jazz":"UTA","Washington Wizards":"WAS",
    }