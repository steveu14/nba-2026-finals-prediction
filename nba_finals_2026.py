#!/usr/bin/env python3
"""
nba_finals_2026.py  —  Local CLI (unchanged usage: python nba_finals_2026.py)
Prints a console report and saves nba_2026_report.html.
"""

import os, sys
sys.path.insert(0, os.path.dirname(__file__))

from fetch_data    import load_all_stats, fetch_live_playoff_state
from elo_model     import build_elo_ratings, project_finals_dynamic, TEAM_NAMES

FINAL_FOUR = ["NYK", "CLE", "OKC", "SAS"]

def pct(p): return f"{p * 100:.1f}%"
def bar(p, w=30): return "█" * round(p * w) + "░" * (w - round(p * w))
def div(c="─", n=65): return c * n

def main():
    print("\n" + "═"*65)
    print("  🏀  2026 NBA FINALS PROJECTOR  (local CLI)")
    print("═"*65)

    stats_df = load_all_stats()
    pstate   = fetch_live_playoff_state()
    teams    = build_elo_ratings(stats_df, pstate["playoff_games"])
    proj     = project_finals_dynamic(teams, pstate["active_series"],
                                       pstate["series_states"], pstate["series_wins"])

    remaining = pstate["remaining_teams"]

    print(f"\n  Data source: {pstate['source'].upper()}")
    print(f"  Teams remaining: {', '.join(remaining)}")

    print(f"\n  TEAM RATINGS")
    print(div())
    print(f"  {'Team':<28} {'ELO':>7} {'Net Rtg':>8} {'SRS':>7} {'Win%':>6}")
    print(div())
    for abbr in remaining:
        if abbr not in teams: continue
        t = teams[abbr]
        print(f"  {TEAM_NAMES.get(abbr,abbr):<28} {t.elo:>7.0f} {t.net_rtg:>+8.1f} {t.srs:>+7.1f} {t.win_pct:>6.3f}")
    print(div())

    print(f"\n  🏆  CHAMPIONSHIP PROBABILITY")
    print(div())
    for abbr, p in sorted(proj["champion_probs"].items(), key=lambda x: -x[1]):
        print(f"  {TEAM_NAMES.get(abbr,abbr):<30}  {pct(p):>7}  {bar(p, 35)}")
    print(div())

    if proj.get("matchup_details"):
        print(f"\n  POSSIBLE FINALS MATCHUPS")
        print(div("─"))
        print(f"  {'Matchup':<35} {'P(matchup)':>11} {'P(East)':>9} {'P(West)':>9}")
        for m in proj["matchup_details"]:
            e, w = m["east"], m["west"]
            name = f"{TEAM_NAMES.get(e,e)} vs {TEAM_NAMES.get(w,w)}"
            print(f"  {name:<35} {m['prob_matchup']:>10.1f}% {m['prob_east_wins']:>8.1f}% {m['prob_west_wins']:>8.1f}%")
        print(div())

    winner = max(proj["champion_probs"], key=proj["champion_probs"].get)
    print(f"\n  🏆  PROJECTED CHAMPION: {TEAM_NAMES.get(winner, winner)}")
    print("═"*65 + "\n")

if __name__ == "__main__":
    main()