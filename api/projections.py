"""
api/projections.py
==================
Vercel serverless function.  GET /api/projections → JSON.

The frontend polls this endpoint every 5 minutes.
Vercel's CDN caches the response for 5 minutes (s-maxage=300) so the
underlying Lambda only runs once per 5 minutes, not on every request.

After each playoff game the nba_api data updates on stats.nba.com,
so the next cache-miss will pull fresh results automatically.
"""

import sys
import os
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

# ── Make root-level modules importable from inside api/ ──────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fetch_data import load_all_stats, fetch_live_playoff_state
from elo_model  import build_elo_ratings, project_finals_dynamic, TEAM_NAMES, EAST, WEST


class handler(BaseHTTPRequestHandler):
    """Vercel Python runtime expects a class called `handler`."""

    def do_GET(self):
        # Allow browser preflight (CORS)
        if self.path == "/api/projections" or True:
            try:
                payload = _run_model()
                body    = json.dumps(payload, default=str).encode()
                self.send_response(200)
                self.send_header("Content-Type",  "application/json")
                self.send_header("Cache-Control", "public, s-maxage=300, stale-while-revalidate=60")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                err  = json.dumps({"error": str(exc)}).encode()
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(err)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()

    # Silence noisy default request logging in Vercel logs
    def log_message(self, fmt, *args):
        pass


# ═════════════════════════════════════════════════════════════════════════════
#  MODEL RUNNER
# ═════════════════════════════════════════════════════════════════════════════

def _run_model() -> dict:
    # 1. Regular-season stats (base ELO inputs)
    stats_df = load_all_stats()

    # 2. Live playoff game log + current series state
    pstate = fetch_live_playoff_state()

    # 3. Build playoff-adjusted ELO ratings
    teams = build_elo_ratings(stats_df, pstate["playoff_games"])

    # 4. Project finals
    proj = project_finals_dynamic(
        teams         = teams,
        active_series = pstate["active_series"],
        series_states = pstate["series_states"],
        series_wins   = pstate["series_wins"],
    )

    # 5. Serialise
    return {
        "updated_at":      datetime.now(timezone.utc).isoformat(),
        "data_source":     pstate["source"],
        "status":          proj.get("status", "unknown"),
        "champion":        proj.get("champion"),           # set when tournament is done
        "champion_probs":  _fmt_probs(proj.get("champion_probs", {})),
        "conf_final_probs":_fmt_probs(proj.get("conf_final_probs", {})),
        "matchup_details": proj.get("matchup_details", []),
        "active_series":   _fmt_series(pstate["active_series"]),
        "remaining_teams": pstate["remaining_teams"],
        "team_ratings":    _fmt_ratings(teams, pstate["remaining_teams"]),
    }


# ── Formatters ────────────────────────────────────────────────────────────────

def _fmt_probs(probs: dict) -> dict:
    return {k: round(v * 100, 1) for k, v in probs.items()}


def _fmt_series(active_series: list) -> list:
    out = []
    for s in active_series:
        t1, t2 = s["teams"]
        out.append({
            "team_a":      t1,
            "team_b":      t2,
            "name_a":      TEAM_NAMES.get(t1, t1),
            "name_b":      TEAM_NAMES.get(t2, t2),
            "wins_a":      s["wins"].get(t1, 0),
            "wins_b":      s["wins"].get(t2, 0),
            "home":        s["home"],
            "conference":  s["conference"],
            "round_num":   s["round_num"],
        })
    return out


def _fmt_ratings(teams, remaining: list) -> list:
    out = []
    for abbr in remaining:
        if abbr not in teams:
            continue
        t = teams[abbr]
        out.append({
            "abbr":    abbr,
            "name":    TEAM_NAMES.get(abbr, abbr),
            "conf":    "East" if abbr in EAST else "West",
            "elo":     round(t.elo, 0),
            "net_rtg": round(t.net_rtg, 1),
            "srs":     round(t.srs, 1),
            "win_pct": round(t.win_pct * 100, 1),
        })
    return sorted(out, key=lambda x: -x["elo"])