"""
api/projections.py — self-contained Vercel serverless function.
Fixes:
  1. get_states() now always initialises BOTH teams (sweep bug was crashing on
     series like OKC 4-0 PHX where PHX never had a win entry).
  2. handler is a plain WSGI callable — required by Vercel's new Python runtime
     (the old BaseHTTPRequestHandler no longer works with uv-based deployments).
"""

import json, itertools
from datetime import datetime, timezone
from collections import defaultdict
from urllib.request import urlopen, Request

# ── Inlined frontend (avoids filesystem dependency on Vercel) ────────────────
INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>2026 NBA Finals Projector</title>

  <!-- React + Babel (no build step needed) -->
  <script src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>

  <style>
    /* ── Reset & base ────────────────────────────────────────────────── */
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --bg:       #0d1117;
      --surface:  #161b22;
      --surface2: #1c2128;
      --border:   #30363d;
      --text:     #e6edf3;
      --muted:    #8b949e;
      --gold:     #e3b341;
      --green:    #3fb950;
      --red:      #f85149;

      --okc-1: #007AC1; --okc-2: #EF3B24;
      --sas-1: #8A8D8F; --sas-2: #000;
      --nyk-1: #006BB6; --nyk-2: #F58426;
      --cle-1: #860038; --cle-2: #FDBB30;
    }

    body {
      background: var(--bg);
      color: var(--text);
      font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
      line-height: 1.5;
      min-height: 100vh;
    }

    /* ── Layout ─────────────────────────────────────────────────────── */
    .container { max-width: 1080px; margin: 0 auto; padding: 24px 16px 48px; }

    /* ── Header ─────────────────────────────────────────────────────── */
    .header {
      display: flex; flex-wrap: wrap; align-items: flex-start;
      justify-content: space-between; gap: 12px;
      background: linear-gradient(135deg, #1a2035, var(--bg));
      border: 1px solid var(--border); border-radius: 12px;
      padding: 24px 28px; margin-bottom: 28px;
    }
    .header-left h1 {
      font-size: clamp(1.3rem, 4vw, 1.8rem);
      font-weight: 800; letter-spacing: -0.5px;
    }
    .header-left .subtitle {
      color: var(--muted); font-size: 0.85rem; margin-top: 4px;
    }
    .header-right { text-align: right; font-size: 0.8rem; color: var(--muted); }
    .header-right .refresh-btn {
      background: var(--surface2); border: 1px solid var(--border);
      color: var(--text); padding: 6px 14px; border-radius: 20px;
      cursor: pointer; font-size: 0.8rem; margin-top: 8px;
      transition: background .15s;
    }
    .header-right .refresh-btn:hover { background: var(--border); }

    /* ── Pill badges ─────────────────────────────────────────────────── */
    .pill {
      display: inline-block; padding: 2px 10px; border-radius: 20px;
      font-size: 0.7rem; font-weight: 700; letter-spacing: .5px;
      vertical-align: middle; margin-left: 8px;
    }
    .pill-live    { background: #238636; color: #fff; }
    .pill-fallback{ background: #9e6a03; color: #fff; }
    .pill-loading { background: var(--surface2); color: var(--muted); }

    /* ── Section titles ──────────────────────────────────────────────── */
    .section-title {
      font-size: 0.72rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: 1.2px; color: var(--gold); margin-bottom: 14px;
    }

    /* ── Grid helpers ────────────────────────────────────────────────── */
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    @media (max-width: 600px) { .grid-2 { grid-template-columns: 1fr; } }

    /* ── Card ────────────────────────────────────────────────────────── */
    .card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 10px; padding: 20px;
    }

    /* ── Championship odds ───────────────────────────────────────────── */
    .champ-row {
      display: flex; align-items: center; gap: 12px;
      padding: 12px 0; border-bottom: 1px solid var(--border);
    }
    .champ-row:last-child { border-bottom: none; }
    .champ-rank { font-size: 1.2rem; min-width: 28px; }
    .champ-info { flex: 1; min-width: 0; }
    .champ-name { font-weight: 700; font-size: 0.95rem; }
    .champ-conf { font-size: 0.72rem; color: var(--muted); }
    .champ-pct  { font-size: 1.3rem; font-weight: 800; min-width: 60px; text-align: right; }
    .bar-wrap   {
      flex: 2; background: var(--surface2); border-radius: 4px;
      height: 10px; overflow: hidden; min-width: 80px;
    }
    .bar-fill   { height: 100%; border-radius: 4px; transition: width .6s ease; }

    /* ── Series boxes ────────────────────────────────────────────────── */
    .series-card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 10px; padding: 18px;
    }
    .series-conf {
      font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: .8px; color: var(--muted); margin-bottom: 14px;
    }
    .series-teams {
      display: flex; align-items: center; gap: 10px;
    }
    .series-team   { flex: 1; text-align: center; }
    .st-abbr       { font-size: 1.6rem; font-weight: 900; }
    .st-full       { font-size: 0.7rem; color: var(--muted); margin: 2px 0 6px; line-height: 1.3; }
    .st-pips       { font-size: 1rem; letter-spacing: 3px; margin-bottom: 4px; }
    .st-prob       { font-size: 1.1rem; font-weight: 800; }
    .vs-circle {
      width: 30px; height: 30px; border-radius: 50%;
      background: var(--surface2); border: 1px solid var(--border);
      display: flex; align-items: center; justify-content: center;
      font-size: 0.65rem; font-weight: 800; color: var(--muted);
      flex-shrink: 0;
    }
    .series-home {
      font-size: 0.68rem; color: var(--muted); text-align: center;
      margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--border);
    }

    /* ── Stats table ─────────────────────────────────────────────────── */
    .stats-table { width: 100%; border-collapse: collapse; }
    .stats-table th {
      text-align: left; font-size: 0.68rem; font-weight: 700;
      text-transform: uppercase; letter-spacing: .5px;
      color: var(--muted); padding: 8px 10px;
      border-bottom: 1px solid var(--border);
    }
    .stats-table td { padding: 10px 10px; font-size: 0.88rem; }
    .stats-table tr:not(:last-child) td { border-bottom: 1px solid var(--border); }
    .td-team { font-weight: 700; }
    .td-team-abbr { font-size: 0.75rem; color: var(--muted); display: block; }
    .td-right { text-align: right; }
    .td-conf-badge {
      display: inline-block; padding: 1px 6px; border-radius: 3px;
      font-size: 0.65rem; font-weight: 700;
      background: var(--surface2); color: var(--muted);
    }

    /* ── Matchup breakdown ───────────────────────────────────────────── */
    .matchup-row {
      display: flex; align-items: center; padding: 10px 0;
      border-bottom: 1px solid var(--border); gap: 10px;
      font-size: 0.85rem;
    }
    .matchup-row:last-child { border-bottom: none; }
    .matchup-teams { flex: 1; font-weight: 700; }
    .matchup-pct   { min-width: 52px; text-align: right; font-weight: 700; }
    .matchup-label { font-size: 0.68rem; color: var(--muted); min-width: 70px; text-align: right; }

    /* ── Loading / error ─────────────────────────────────────────────── */
    .loading-wrap {
      display: flex; flex-direction: column; align-items: center;
      justify-content: center; min-height: 300px; gap: 16px;
      color: var(--muted);
    }
    .spinner {
      width: 36px; height: 36px; border: 3px solid var(--border);
      border-top-color: var(--gold); border-radius: 50%;
      animation: spin .8s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .error-box {
      background: rgba(248,81,73,.1); border: 1px solid var(--red);
      border-radius: 8px; padding: 16px; color: var(--red);
      text-align: center;
    }
  </style>
</head>
<body>
<div id="root"></div>

<script type="text/babel">
const { useState, useEffect, useCallback, useRef } = React;

// ── Team colours ──────────────────────────────────────────────────────────────
const COLOURS = {
  OKC: "#007AC1", SAS: "#8A8D8F", NYK: "#006BB6", CLE: "#860038",
  DET: "#1D42BA", PHI: "#006BB6", LAL: "#552583", MIN: "#0C2340",
  HOU: "#CE1141", DEN: "#0E2240", ATL: "#E03A3E", TOR: "#CE1141",
  ORL: "#0077C0", BOS: "#007A33", PHX: "#1D1160", POR: "#E03A3E",
};

const RANK_ICONS = ["🏆","🥈","🥉","4️⃣"];

// ── Helpers ──────────────────────────────────────────────────────────────────
const pct   = v  => `${v.toFixed(1)}%`;
const pips  = (n) => "⬤".repeat(n) + "○".repeat(4 - n);
const color = (abbr) => COLOURS[abbr] || "#888";

// ── App ───────────────────────────────────────────────────────────────────────
function App() {
  const [data,      setData]      = useState(null);
  const [loading,   setLoading]   = useState(true);
  const [error,     setError]     = useState(null);
  const [countdown, setCountdown] = useState(300);   // seconds
  const timerRef  = useRef(null);
  const cdRef     = useRef(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/projections");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
      setCountdown(300);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial fetch
  useEffect(() => { fetchData(); }, [fetchData]);

  // Auto-refresh timer
  useEffect(() => {
    cdRef.current = setInterval(() => {
      setCountdown(c => {
        if (c <= 1) { fetchData(); return 300; }
        return c - 1;
      });
    }, 1000);
    return () => clearInterval(cdRef.current);
  }, [fetchData]);

  const fmtCountdown = (s) => `${Math.floor(s/60)}:${String(s%60).padStart(2,"0")}`;
  const fmtTime = (iso) => {
    if (!iso) return "—";
    return new Date(iso).toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"});
  };

  return (
    <div className="container">
      {/* ── Header ─────────────────────────────────────────────────── */}
      <div className="header">
        <div className="header-left">
          <h1>
            🏀 2026 NBA Finals Projector
            {data && (
              <span className={`pill ${data.data_source === "live" ? "pill-live" : "pill-fallback"}`}>
                {data.data_source === "live" ? "LIVE" : "CACHED"}
              </span>
            )}
            {loading && <span className="pill pill-loading">loading…</span>}
          </h1>
          <div className="subtitle">
            ELO + Net Rating + SRS · Updates after every game
          </div>
        </div>
        <div className="header-right">
          {data && <div>Last updated: {fmtTime(data.updated_at)}</div>}
          <div style={{marginTop: 4}}>Next refresh: {fmtCountdown(countdown)}</div>
          <button className="refresh-btn" onClick={fetchData}>↻ Refresh now</button>
        </div>
      </div>

      {/* ── Error ──────────────────────────────────────────────────── */}
      {error && (
        <div className="error-box" style={{marginBottom: 24}}>
          ⚠️ Could not load projections: {error}
          <div style={{marginTop:8}}>
            <button className="refresh-btn" onClick={fetchData}>Try again</button>
          </div>
        </div>
      )}

      {/* ── Loading skeleton ───────────────────────────────────────── */}
      {loading && !data && (
        <div className="loading-wrap">
          <div className="spinner" />
          <div>Running the model…</div>
        </div>
      )}

      {/* ── Main content ───────────────────────────────────────────── */}
      {data && <Dashboard data={data} />}
    </div>
  );
}

// ── Dashboard ─────────────────────────────────────────────────────────────────
function Dashboard({ data }) {
  const sorted = Object.entries(data.champion_probs)
    .sort(([,a],[,b]) => b - a);

  return (
    <>
      {/* Championship odds */}
      <div style={{marginBottom: 28}}>
        <div className="section-title">🏆 Championship Probability</div>
        <div className="card">
          {sorted.map(([abbr, prob], i) => (
            <div className="champ-row" key={abbr}>
              <div className="champ-rank">{RANK_ICONS[i] || `${i+1}`}</div>
              <div className="champ-info">
                <div className="champ-name" style={{color: color(abbr)}}>
                  {data.team_ratings.find(t=>t.abbr===abbr)?.name || abbr}
                </div>
                <div className="champ-conf">
                  {data.team_ratings.find(t=>t.abbr===abbr)?.conf || ""}
                </div>
              </div>
              <div className="bar-wrap">
                <div className="bar-fill"
                     style={{width: `${Math.min(prob,100)}%`, background: color(abbr)}} />
              </div>
              <div className="champ-pct" style={{color: color(abbr)}}>{pct(prob)}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Series status */}
      {data.active_series.length > 0 && (
        <div style={{marginBottom: 28}}>
          <div className="section-title">
            {data.status === "finals" ? "🏆 NBA Finals" : "🏀 Conference Finals"}
          </div>
          <div className={data.active_series.length > 1 ? "grid-2" : ""}>
            {data.active_series.map((s, i) => (
              <SeriesCard key={i} series={s} confProbs={data.conf_final_probs} champProbs={data.champion_probs} />
            ))}
          </div>
        </div>
      )}

      {/* Team stats */}
      {data.team_ratings.length > 0 && (
        <div style={{marginBottom: 28}}>
          <div className="section-title">📊 Team Ratings (Remaining Teams)</div>
          <div className="card">
            <table className="stats-table">
              <thead>
                <tr>
                  <th>Team</th>
                  <th>Conf</th>
                  <th className="td-right">Playoff ELO</th>
                  <th className="td-right">Net Rtg</th>
                  <th className="td-right">SRS</th>
                  <th className="td-right">Win %</th>
                </tr>
              </thead>
              <tbody>
                {data.team_ratings.map(t => (
                  <tr key={t.abbr}>
                    <td className="td-team">
                      <span style={{color: color(t.abbr)}}>{t.name}</span>
                      <span className="td-team-abbr">{t.abbr}</span>
                    </td>
                    <td><span className="td-conf-badge">{t.conf}</span></td>
                    <td className="td-right">{t.elo}</td>
                    <td className="td-right" style={{color: t.net_rtg >= 0 ? "var(--green)" : "var(--red)"}}>
                      {t.net_rtg >= 0 ? "+" : ""}{t.net_rtg}
                    </td>
                    <td className="td-right" style={{color: t.srs >= 0 ? "var(--green)" : "var(--red)"}}>
                      {t.srs >= 0 ? "+" : ""}{t.srs}
                    </td>
                    <td className="td-right">{t.win_pct}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Possible matchups */}
      {data.matchup_details.length > 0 && (
        <div style={{marginBottom: 28}}>
          <div className="section-title">🎯 Possible Finals Matchups</div>
          <div className="card">
            {data.matchup_details.map((m, i) => (
              <div className="matchup-row" key={i}>
                <div className="matchup-teams">
                  <span style={{color: color(m.east)}}>{m.east}</span>
                  <span style={{color: "var(--muted)", margin: "0 6px"}}>vs</span>
                  <span style={{color: color(m.west)}}>{m.west}</span>
                </div>
                <div className="matchup-label">P(matchup)</div>
                <div className="matchup-pct">{m.prob_matchup}%</div>
                <div className="matchup-label" style={{color: color(m.east)}}>
                  {m.east} wins
                </div>
                <div className="matchup-pct" style={{color: color(m.east)}}>
                  {m.prob_east_wins}%
                </div>
                <div className="matchup-label" style={{color: color(m.west)}}>
                  {m.west} wins
                </div>
                <div className="matchup-pct" style={{color: color(m.west)}}>
                  {m.prob_west_wins}%
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Footer */}
      <div style={{textAlign:"center", color:"var(--muted)", fontSize:"0.75rem", marginTop: 16}}>
        Model: ELO + Net Rating + SRS · Data: nba_api (stats.nba.com) + Basketball-Reference
        · Updates every 5 min
      </div>
    </>
  );
}

// ── SeriesCard ────────────────────────────────────────────────────────────────
function SeriesCard({ series, confProbs, champProbs }) {
  const { team_a, team_b, name_a, name_b, wins_a, wins_b, home, conference } = series;
  const p_a = confProbs[team_a] ?? champProbs[team_a] ?? 50;
  const p_b = confProbs[team_b] ?? champProbs[team_b] ?? 50;
  const TEAM_NAMES = { a: name_a, b: name_b };

  return (
    <div className="series-card">
      <div className="series-conf">{conference} Conference Finals</div>
      <div className="series-teams">
        <div className="series-team">
          <div className="st-abbr" style={{color: color(team_a)}}>{team_a}</div>
          <div className="st-full">{name_a}</div>
          <div className="st-pips" style={{color: color(team_a)}}>{pips(wins_a)}</div>
          <div className="st-prob">{pct(p_a)}</div>
        </div>
        <div className="vs-circle">VS</div>
        <div className="series-team">
          <div className="st-abbr" style={{color: color(team_b)}}>{team_b}</div>
          <div className="st-full">{name_b}</div>
          <div className="st-pips" style={{color: color(team_b)}}>{pips(wins_b)}</div>
          <div className="st-prob">{pct(p_b)}</div>
        </div>
      </div>
      <div className="series-home">
        🏠 Home court: {home === team_a ? name_a : name_b}
      </div>
    </div>
  );
}

// ── Mount ─────────────────────────────────────────────────────────────────────
const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<App />);
</script>
</body>
</html>
"""


# ── Fallback regular-season data (2025-26) ────────────────────────────────────
FALLBACK_STATS = {
    "OKC": {"net_rtg": 11.2, "srs": 8.9,  "wins": 68, "losses": 14},
    "SAS": {"net_rtg":  8.7, "srs": 6.8,  "wins": 58, "losses": 24},
    "NYK": {"net_rtg":  6.1, "srs": 4.9,  "wins": 52, "losses": 30},
    "CLE": {"net_rtg":  4.9, "srs": 3.7,  "wins": 50, "losses": 32},
    "DET": {"net_rtg":  5.8, "srs": 4.3,  "wins": 53, "losses": 29},
    "PHI": {"net_rtg":  3.2, "srs": 2.4,  "wins": 46, "losses": 36},
    "LAL": {"net_rtg":  4.1, "srs": 3.2,  "wins": 49, "losses": 33},
    "MIN": {"net_rtg":  3.8, "srs": 2.9,  "wins": 48, "losses": 34},
    "HOU": {"net_rtg":  2.1, "srs": 1.4,  "wins": 43, "losses": 39},
    "DEN": {"net_rtg":  5.5, "srs": 4.1,  "wins": 51, "losses": 31},
    "ATL": {"net_rtg":  1.4, "srs": 1.0,  "wins": 40, "losses": 42},
    "TOR": {"net_rtg": -1.2, "srs": -0.9, "wins": 36, "losses": 46},
    "ORL": {"net_rtg":  2.8, "srs": 1.8,  "wins": 44, "losses": 38},
    "BOS": {"net_rtg":  6.9, "srs": 5.2,  "wins": 51, "losses": 31},
    "PHX": {"net_rtg":  0.5, "srs": 0.3,  "wins": 38, "losses": 44},
    "POR": {"net_rtg": -3.1, "srs": -2.5, "wins": 29, "losses": 53},
}

TEAM_NAMES = {
    "OKC":"Oklahoma City Thunder","SAS":"San Antonio Spurs",
    "NYK":"New York Knicks",      "CLE":"Cleveland Cavaliers",
    "DET":"Detroit Pistons",      "PHI":"Philadelphia 76ers",
    "LAL":"Los Angeles Lakers",   "MIN":"Minnesota Timberwolves",
    "HOU":"Houston Rockets",      "DEN":"Denver Nuggets",
    "ATL":"Atlanta Hawks",        "TOR":"Toronto Raptors",
    "ORL":"Orlando Magic",        "BOS":"Boston Celtics",
    "PHX":"Phoenix Suns",         "POR":"Portland Trail Blazers",
}

EAST = {"ATL","BOS","BKN","CHA","CHI","CLE","DET","IND","MIA","MIL","NYK","ORL","PHI","TOR","WAS"}
WEST = {"DAL","DEN","GSW","HOU","LAC","LAL","MEM","MIN","NOP","OKC","PHX","POR","SAC","SAS","UTA"}

FALLBACK_GAMES = [
    # Round 1 – East
    ("DET","ORL","DET"),("DET","ORL","DET"),("ORL","DET","ORL"),("ORL","DET","ORL"),
    ("DET","ORL","DET"),("ORL","DET","ORL"),("DET","ORL","DET"),
    ("CLE","TOR","CLE"),("CLE","TOR","CLE"),("TOR","CLE","TOR"),("TOR","CLE","TOR"),
    ("CLE","TOR","CLE"),("TOR","CLE","TOR"),("CLE","TOR","CLE"),
    ("NYK","ATL","NYK"),("NYK","ATL","NYK"),("ATL","NYK","ATL"),("NYK","ATL","ATL"),
    ("NYK","ATL","NYK"),("NYK","ATL","ATL"),
    ("PHI","BOS","BOS"),("PHI","BOS","BOS"),("BOS","PHI","PHI"),("BOS","PHI","PHI"),
    ("PHI","BOS","BOS"),("BOS","PHI","PHI"),("PHI","BOS","PHI"),
    # Round 1 – West
    ("OKC","PHX","OKC"),("OKC","PHX","OKC"),("OKC","PHX","PHX"),("OKC","PHX","PHX"),
    ("LAL","HOU","LAL"),("LAL","HOU","LAL"),("HOU","LAL","HOU"),("LAL","HOU","HOU"),
    ("LAL","HOU","LAL"),("LAL","HOU","HOU"),
    ("SAS","POR","SAS"),("SAS","POR","SAS"),("POR","SAS","POR"),("SAS","POR","POR"),
    ("SAS","POR","SAS"),
    ("MIN","DEN","DEN"),("DEN","MIN","DEN"),("MIN","DEN","MIN"),("MIN","DEN","MIN"),
    ("DEN","MIN","DEN"),("MIN","DEN","MIN"),
    # Round 2 – East
    ("NYK","PHI","NYK"),("NYK","PHI","NYK"),("NYK","PHI","PHI"),("NYK","PHI","PHI"),
    ("DET","CLE","DET"),("DET","CLE","DET"),("CLE","DET","CLE"),("CLE","DET","CLE"),
    ("CLE","DET","DET"),("DET","CLE","CLE"),("CLE","DET","DET"),
    # Round 2 – West
    ("OKC","LAL","OKC"),("OKC","LAL","OKC"),("OKC","LAL","LAL"),("OKC","LAL","LAL"),
    ("SAS","MIN","SAS"),("SAS","MIN","SAS"),("MIN","SAS","MIN"),("SAS","MIN","MIN"),
    ("SAS","MIN","SAS"),("SAS","MIN","MIN"),
    # Round 3 – Conf Finals (through May 22 2026)
    ("NYK","CLE","NYK"),("NYK","CLE","NYK"),          # East: NYK leads 2-0
    ("SAS","OKC","OKC"),("OKC","SAS","OKC"),("OKC","SAS","SAS"),  # West: OKC leads 2-1
]


# ═════════════════════════════════════════════════════════════════════════════
#  LIVE DATA  (direct NBA stats API, stdlib only)
# ═════════════════════════════════════════════════════════════════════════════

def fetch_live_games(season="2025-26"):
    url = (
        "https://stats.nba.com/stats/leaguegamelog"
        f"?LeagueID=00&Season={season}&SeasonType=Playoffs"
        "&Direction=ASC&Sorter=DATE&DateFrom=&DateTo="
        "&GameSegment=&LastNGames=0&Location=&MeasureType=Base"
        "&Month=0&OpponentTeamID=0&Outcome=&PORound=0"
        "&PerMode=Totals&PaceAdjust=N&PlusMinus=N&Rank=N"
        "&VsConference=&VsDivision="
    )
    req = Request(url, headers={
        "User-Agent":         "Mozilla/5.0",
        "Referer":            "https://www.nba.com/",
        "x-nba-stats-origin": "stats",
        "x-nba-stats-token":  "true",
    })
    with urlopen(req, timeout=10) as r:
        data = json.loads(r.read().decode())
    hdrs = data["resultSets"][0]["headers"]
    rows = data["resultSets"][0]["rowSet"]
    ai = hdrs.index("TEAM_ABBREVIATION")
    wi = hdrs.index("WL")
    gi = hdrs.index("GAME_ID")
    mi = hdrs.index("MATCHUP")

    by_game = defaultdict(list)
    for row in rows:
        by_game[row[gi]].append(row)

    games = []
    for gid, pair in by_game.items():
        if len(pair) < 2:
            continue
        w = next((r for r in pair if r[wi] == "W"), None)
        l = next((r for r in pair if r[wi] == "L"), None)
        if not w or not l:
            continue
        winner = w[ai]
        loser  = l[ai]
        home   = winner if " vs. " in str(w[mi]) else loser
        games.append((winner, loser, home))
    return games


# ═════════════════════════════════════════════════════════════════════════════
#  SERIES STATE  — BUG FIX: both teams always initialised
# ═════════════════════════════════════════════════════════════════════════════

def get_states(games):
    """
    Returns {frozenset({t1,t2}): {t1: wins, t2: wins, 'complete': bool}}.
    Both teams are always present even in a sweep (fixes KeyError on 0-win side).
    """
    series_teams = defaultdict(set)
    win_counts   = defaultdict(lambda: defaultdict(int))

    for w, l, _ in games:
        pair = frozenset({w, l})
        win_counts[pair][w] += 1
        series_teams[pair].add(w)
        series_teams[pair].add(l)

    states = {}
    for pair in series_teams:
        t1, t2 = tuple(pair)
        w1 = win_counts[pair].get(t1, 0)   # .get() — never KeyError
        w2 = win_counts[pair].get(t2, 0)
        states[pair] = {t1: w1, t2: w2, "complete": max(w1, w2) >= 4}
    return states


def get_series_wins(states):
    sw = defaultdict(int)
    for pair, d in states.items():
        if d["complete"]:
            t1, t2 = tuple(pair)
            sw[t1 if d[t1] > d[t2] else t2] += 1
    return dict(sw)


def get_active(states, sw):
    out = []
    for pair, d in states.items():
        if d["complete"]:
            continue
        t1, t2 = tuple(pair)
        same_conf = (t1 in EAST) == (t2 in EAST)
        conf = ("East" if t1 in EAST else "West") if same_conf else "Finals"
        home = t1 if sw.get(t1, 0) >= sw.get(t2, 0) else t2
        out.append({
            "teams":      (t1, t2),
            "wins":       {t1: d[t1], t2: d[t2]},
            "home":       home,
            "conference": conf,
            "round_num":  sw.get(t1, 0) + 1,
        })
    return out


def get_remaining(states):
    elim = set()
    for pair, d in states.items():
        if d["complete"]:
            t1, t2 = tuple(pair)
            elim.add(t1 if d[t1] < d[t2] else t2)
    return list({t for pair in states for t in pair} - elim)


# ═════════════════════════════════════════════════════════════════════════════
#  ELO MODEL  (pure Python — no numpy/pandas)
# ═════════════════════════════════════════════════════════════════════════════

K, HOME_ADV, SCALE = 20, 40, 400


def _exp(ra, rb):
    return 1.0 / (1.0 + 10 ** ((rb - ra) / SCALE))


def build_elo(games):
    def mean(v): return sum(v) / len(v) if v else 0
    def std(v):
        m = mean(v)
        s = (sum((x - m) ** 2 for x in v) / len(v)) ** 0.5 if v else 1
        return s or 1

    comp = {}
    for a, s in FALLBACK_STATS.items():
        tot = s["wins"] + s["losses"] or 82
        comp[a] = (0.45 * s["net_rtg"] +
                   0.35 * s["srs"] +
                   0.20 * (s["wins"] / tot - 0.5) * 20)

    vals = list(comp.values())
    cm, cs = mean(vals), std(vals)
    elo = {a: 1500 + ((c - cm) / cs) * 150 for a, c in comp.items()}

    for w, l, h in games:
        if w not in elo or l not in elo:
            continue
        rw = elo[w] + (HOME_ADV if w == h else -HOME_ADV)
        rl = elo[l] + (HOME_ADV if l == h else -HOME_ADV)
        ew = _exp(rw, rl)
        elo[w] += K * (1 - ew)
        elo[l] += K * (0 - (1 - ew))
    return elo


def gpob(ta, tb, h, elo):
    ra = elo.get(ta, 1500) + (HOME_ADV if h == ta else -HOME_ADV if h == tb else 0)
    rb = elo.get(tb, 1500) + (HOME_ADV if h == tb else -HOME_ADV if h == ta else 0)
    return _exp(ra, rb)


def spob(ta, tb, ht, elo, wa=0, wb=0, gtw=4):
    na, nb = gtw - wa, gtw - wb
    if na <= 0: return 1.0
    if nb <= 0: return 0.0
    memo = {}

    def r(na, nb):
        if na == 0: return 1.0
        if nb == 0: return 0.0
        if (na, nb) in memo: return memo[(na, nb)]
        gn = (gtw - na + wa) + (gtw - nb + wb) + 1
        hg = ht if gn in {1, 2, 5, 7} else (tb if ht == ta else ta)
        p  = gpob(ta, tb, hg, elo)
        res = p * r(na - 1, nb) + (1 - p) * r(na, nb - 1)
        memo[(na, nb)] = res
        return res

    return r(na, nb)


# ═════════════════════════════════════════════════════════════════════════════
#  PROJECTION
# ═════════════════════════════════════════════════════════════════════════════

def project(elo, act, sw):
    if not act:
        champ = max(sw, key=sw.get) if sw else None
        return {"champion_probs": {champ: 1.0} if champ else {},
                "conf_final_probs": {}, "matchup_details": [], "status": "complete"}

    finals = [s for s in act if s["conference"] == "Finals"]
    conf   = [s for s in act if s["conference"] != "Finals"]

    if finals:
        s = finals[0]
        t1, t2 = s["teams"]
        west   = t1 if t1 in WEST else t2
        p      = spob(t1, t2, west, elo, s["wins"][t1], s["wins"][t2])
        return {"champion_probs": {t1: p, t2: 1 - p}, "conf_final_probs": {},
                "matchup_details": [], "status": "finals"}

    if len(conf) >= 2:
        es = next((s for s in conf if s["conference"] == "East"), None)
        ws = next((s for s in conf if s["conference"] == "West"), None)

        if not es or not ws:
            s = conf[0]; t1, t2 = s["teams"]
            p = spob(t1, t2, s["home"], elo, s["wins"][t1], s["wins"][t2])
            return {"champion_probs": {t1: p, t2: 1 - p},
                    "conf_final_probs": {t1: p, t2: 1 - p},
                    "matchup_details": [], "status": "conf_finals"}

        ea, eb = es["teams"]; wa_e, wb_e = es["wins"][ea], es["wins"][eb]
        wa, wb = ws["teams"]; ww_a, ww_b = ws["wins"][wa], ws["wins"][wb]
        pea = spob(ea, eb, es["home"], elo, wa_e, wb_e)
        pwa = spob(wa, wb, ws["home"], elo, ww_a, ww_b)

        champ   = defaultdict(float)
        details = []
        for (ec, pec), (wc, pwc) in itertools.product(
                [(ea, pea), (eb, 1 - pea)],
                [(wa, pwa), (wb, 1 - pwa)]):
            pm = pec * pwc
            pe = spob(ec, wc, wc, elo)   # West team hosts Finals G1-G2
            champ[ec] += pm * pe
            champ[wc] += pm * (1 - pe)
            details.append({"east": ec, "west": wc,
                             "prob_matchup":   round(pm  * 100, 1),
                             "prob_east_wins": round(pe  * 100, 1),
                             "prob_west_wins": round((1 - pe) * 100, 1)})

        return {"champion_probs":    dict(champ),
                "conf_final_probs":  {ea: pea, eb: 1-pea, wa: pwa, wb: 1-pwa},
                "matchup_details":   sorted(details, key=lambda x: -x["prob_matchup"]),
                "status":            "conf_finals"}

    champ = {}
    for s in act:
        t1, t2 = s["teams"]
        p = spob(t1, t2, s["home"], elo, s["wins"][t1], s["wins"][t2])
        champ[t1] = p; champ[t2] = 1 - p
    return {"champion_probs": champ, "conf_final_probs": champ,
            "matchup_details": [], "status": "early"}


# ═════════════════════════════════════════════════════════════════════════════
#  MODEL RUNNER
# ═════════════════════════════════════════════════════════════════════════════

def run_model():
    source = "live"
    try:
        games = fetch_live_games()
        if not games:
            raise ValueError("empty response")
    except Exception:
        games  = list(FALLBACK_GAMES)
        source = "fallback"

    states = get_states(games)
    sw     = get_series_wins(states)
    act    = get_active(states, sw)
    remain = get_remaining(states)
    elo    = build_elo(games)
    proj   = project(elo, act, sw)

    def fp(d): return {k: round(v * 100, 1) for k, v in d.items()}

    ratings = []
    for a in remain:
        if a not in elo:
            continue
        s   = FALLBACK_STATS.get(a, {})
        tot = s.get("wins", 45) + s.get("losses", 37) or 82
        ratings.append({
            "abbr":    a,
            "name":    TEAM_NAMES.get(a, a),
            "conf":    "East" if a in EAST else "West",
            "elo":     round(elo[a]),
            "net_rtg": s.get("net_rtg", 0),
            "srs":     s.get("srs", 0),
            "win_pct": round(s.get("wins", 45) / tot * 100, 1),
        })
    ratings.sort(key=lambda x: -x["elo"])

    series_out = []
    for s in act:
        t1, t2 = s["teams"]
        series_out.append({
            "team_a": t1, "name_a": TEAM_NAMES.get(t1, t1),
            "team_b": t2, "name_b": TEAM_NAMES.get(t2, t2),
            "wins_a": s["wins"].get(t1, 0),
            "wins_b": s["wins"].get(t2, 0),
            "home":        s["home"],
            "conference":  s["conference"],
            "round_num":   s["round_num"],
        })

    return {
        "updated_at":       datetime.now(timezone.utc).isoformat(),
        "data_source":      source,
        "status":           proj.get("status", "unknown"),
        "champion":         proj.get("champion"),
        "champion_probs":   fp(proj.get("champion_probs", {})),
        "conf_final_probs": fp(proj.get("conf_final_probs", {})),
        "matchup_details":  proj.get("matchup_details", []),
        "active_series":    series_out,
        "remaining_teams":  remain,
        "team_ratings":     ratings,
    }


# ═════════════════════════════════════════════════════════════════════════════
#  VERCEL HANDLER  — plain WSGI callable (required by new Vercel Python runtime)
# ═════════════════════════════════════════════════════════════════════════════

def handler(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET")
    path   = environ.get("PATH_INFO", "/")

    # ── CORS preflight ────────────────────────────────────────────────────────
    if method == "OPTIONS":
        start_response("200 OK", [
            ("Access-Control-Allow-Origin",  "*"),
            ("Access-Control-Allow-Methods", "GET, OPTIONS"),
        ])
        return [b""]

    # ── API: return JSON projections ─────────────────────────────────────────
    if path in ("/projections", "/api/projections"):
        try:
            payload = run_model()
            body    = json.dumps(payload).encode()
            start_response("200 OK", [
                ("Content-Type",  "application/json"),
                ("Cache-Control", "public, s-maxage=300, stale-while-revalidate=60"),
                ("Access-Control-Allow-Origin", "*"),
            ])
            return [body]
        except Exception as exc:
            err = json.dumps({"error": str(exc), "type": type(exc).__name__}).encode()
            start_response("500 Internal Server Error", [
                ("Content-Type", "application/json"),
                ("Access-Control-Allow-Origin", "*"),
            ])
            return [err]

    # ── Frontend: serve inlined index.html (no filesystem dependency) ───────
    start_response("200 OK", [
        ("Content-Type",  "text/html; charset=utf-8"),
        ("Cache-Control", "public, max-age=60"),
    ])
    return [INDEX_HTML.encode("utf-8")]