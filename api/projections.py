import json
import math
import itertools
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timezone
from collections import defaultdict
from urllib.request import urlopen, Request

# ── Fallback data (2025-26 regular season) ────────────────────────────────────
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
    "OKC": "Oklahoma City Thunder", "SAS": "San Antonio Spurs",
    "NYK": "New York Knicks",       "CLE": "Cleveland Cavaliers",
    "DET": "Detroit Pistons",       "PHI": "Philadelphia 76ers",
    "LAL": "Los Angeles Lakers",    "MIN": "Minnesota Timberwolves",
    "HOU": "Houston Rockets",       "DEN": "Denver Nuggets",
    "ATL": "Atlanta Hawks",         "TOR": "Toronto Raptors",
    "ORL": "Orlando Magic",         "BOS": "Boston Celtics",
    "PHX": "Phoenix Suns",          "POR": "Portland Trail Blazers",
}

EAST = {"ATL","BOS","BKN","CHA","CHI","CLE","DET","IND","MIA","MIL","NYK","ORL","PHI","TOR","WAS"}
WEST = {"DAL","DEN","GSW","HOU","LAC","LAL","MEM","MIN","NOP","OKC","PHX","POR","SAC","SAS","UTA"}

FALLBACK_GAMES = [
    ("DET","ORL","DET"),("DET","ORL","DET"),("ORL","DET","ORL"),("ORL","DET","ORL"),
    ("DET","ORL","DET"),("ORL","DET","ORL"),("DET","ORL","DET"),
    ("CLE","TOR","CLE"),("CLE","TOR","CLE"),("TOR","CLE","TOR"),("TOR","CLE","TOR"),
    ("CLE","TOR","CLE"),("TOR","CLE","TOR"),("CLE","TOR","CLE"),
    ("NYK","ATL","NYK"),("NYK","ATL","NYK"),("ATL","NYK","ATL"),("NYK","ATL","ATL"),
    ("NYK","ATL","NYK"),("NYK","ATL","ATL"),
    ("PHI","BOS","BOS"),("PHI","BOS","BOS"),("BOS","PHI","PHI"),("BOS","PHI","PHI"),
    ("PHI","BOS","BOS"),("BOS","PHI","PHI"),("PHI","BOS","PHI"),
    ("OKC","PHX","OKC"),("OKC","PHX","OKC"),("OKC","PHX","PHX"),("OKC","PHX","PHX"),
    ("LAL","HOU","LAL"),("LAL","HOU","LAL"),("HOU","LAL","HOU"),("LAL","HOU","HOU"),
    ("LAL","HOU","LAL"),("LAL","HOU","HOU"),
    ("SAS","POR","SAS"),("SAS","POR","SAS"),("POR","SAS","POR"),("SAS","POR","POR"),
    ("SAS","POR","SAS"),
    ("MIN","DEN","DEN"),("DEN","MIN","DEN"),("MIN","DEN","MIN"),("MIN","DEN","MIN"),
    ("DEN","MIN","DEN"),("MIN","DEN","MIN"),
    ("NYK","PHI","NYK"),("NYK","PHI","NYK"),("NYK","PHI","PHI"),("NYK","PHI","PHI"),
    ("DET","CLE","DET"),("DET","CLE","DET"),("CLE","DET","CLE"),("CLE","DET","CLE"),
    ("CLE","DET","DET"),("DET","CLE","CLE"),("CLE","DET","DET"),
    ("OKC","LAL","OKC"),("OKC","LAL","OKC"),("OKC","LAL","LAL"),("OKC","LAL","LAL"),
    ("SAS","MIN","SAS"),("SAS","MIN","SAS"),("MIN","SAS","MIN"),("SAS","MIN","MIN"),
    ("SAS","MIN","SAS"),("SAS","MIN","MIN"),
    ("NYK","CLE","NYK"),("NYK","CLE","NYK"),
    ("SAS","OKC","OKC"),("OKC","SAS","OKC"),("OKC","SAS","SAS"),
]

# ── Live data ─────────────────────────────────────────────────────────────────
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
    ai, wi, gi, mi = (hdrs.index(k) for k in
                      ("TEAM_ABBREVIATION","WL","GAME_ID","MATCHUP"))
    by_game = defaultdict(list)
    for row in rows:
        by_game[row[gi]].append(row)
    games = []
    for gid, pair in by_game.items():
        if len(pair) < 2: continue
        w = next((r for r in pair if r[wi]=="W"), None)
        l = next((r for r in pair if r[wi]=="L"), None)
        if not w or not l: continue
        winner, loser = w[ai], l[ai]
        home = winner if " vs. " in str(w[mi]) else loser
        games.append((winner, loser, home))
    return games

# ── Series state ──────────────────────────────────────────────────────────────
def get_states(games):
    wins = defaultdict(lambda: defaultdict(int))
    for w, l, _ in games:
        wins[frozenset({w,l})][w] += 1
    return {p: {**tw, "complete": max(tw.values()) >= 4}
            for p, tw in wins.items()}

def get_series_wins(states):
    sw = defaultdict(int)
    for pair, d in states.items():
        if d["complete"]:
            t1,t2 = tuple(pair)
            sw[t1 if d[t1]>d[t2] else t2] += 1
    return dict(sw)

def get_active(states, sw):
    out = []
    for pair, d in states.items():
        if d["complete"]: continue
        t1,t2 = tuple(pair)
        conf = ("East" if t1 in EAST else "West") if (t1 in EAST)==(t2 in EAST) else "Finals"
        home = t1 if sw.get(t1,0) >= sw.get(t2,0) else t2
        out.append({"teams":(t1,t2),"wins":{t1:d[t1],t2:d[t2]},
                    "home":home,"conference":conf,"round_num":sw.get(t1,0)+1})
    return out

def get_remaining(states):
    elim = set()
    for pair, d in states.items():
        if d["complete"]:
            t1,t2=tuple(pair); elim.add(t1 if d[t1]<d[t2] else t2)
    return list({t for pair in states for t in pair} - elim)

# ── ELO model ─────────────────────────────────────────────────────────────────
K, HOME, SCALE = 20, 40, 400

def _exp(ra, rb): return 1/(1+10**((rb-ra)/SCALE))

def build_elo(games):
    def mean(v): return sum(v)/len(v) if v else 0
    def std(v):
        m=mean(v); s=(sum((x-m)**2 for x in v)/len(v))**0.5 if v else 1
        return s or 1
    comp = {a: 0.45*s["net_rtg"]+0.35*s["srs"]+0.20*(s["wins"]/(s["wins"]+s["losses"] or 82)-0.5)*20
            for a,s in FALLBACK_STATS.items()}
    vals = list(comp.values()); cm,cs = mean(vals),std(vals)
    elo = {a: 1500+((c-cm)/cs)*150 for a,c in comp.items()}
    for w,l,h in games:
        if w not in elo or l not in elo: continue
        rw = elo[w]+(HOME if w==h else -HOME)
        rl = elo[l]+(HOME if l==h else -HOME)
        ew = _exp(rw,rl)
        elo[w] += K*(1-ew); elo[l] += K*(0-(1-ew))
    return elo

def gpob(ta,tb,h,elo):
    ra=elo.get(ta,1500)+(HOME if h==ta else -HOME if h==tb else 0)
    rb=elo.get(tb,1500)+(HOME if h==tb else -HOME if h==ta else 0)
    return _exp(ra,rb)

def spob(ta,tb,ht,elo,wa=0,wb=0,gtw=4):
    na,nb=gtw-wa,gtw-wb
    if na<=0: return 1.0
    if nb<=0: return 0.0
    memo={}
    def r(na,nb):
        if na==0: return 1.0
        if nb==0: return 0.0
        if (na,nb) in memo: return memo[(na,nb)]
        gn=(gtw-na+wa)+(gtw-nb+wb)+1
        hg=ht if gn in{1,2,5,7} else (tb if ht==ta else ta)
        p=gpob(ta,tb,hg,elo)
        res=p*r(na-1,nb)+(1-p)*r(na,nb-1)
        memo[(na,nb)]=res; return res
    return r(na,nb)

# ── Projection ────────────────────────────────────────────────────────────────
def project(elo, act, sw):
    if not act:
        champ=max(sw,key=sw.get) if sw else None
        return {"champion_probs":{champ:1.0} if champ else {},"conf_final_probs":{},
                "matchup_details":[],"status":"complete"}
    finals=[s for s in act if s["conference"]=="Finals"]
    conf=[s for s in act if s["conference"]!="Finals"]
    if finals:
        s=finals[0]; t1,t2=s["teams"]; w=t1 if t1 in WEST else t2
        p=spob(t1,t2,w,elo,s["wins"][t1],s["wins"][t2])
        return {"champion_probs":{t1:p,t2:1-p},"conf_final_probs":{},
                "matchup_details":[],"status":"finals"}
    if len(conf)>=2:
        es=next((s for s in conf if s["conference"]=="East"),None)
        ws=next((s for s in conf if s["conference"]=="West"),None)
        if not es or not ws:
            s=conf[0]; t1,t2=s["teams"]
            p=spob(t1,t2,s["home"],elo,s["wins"][t1],s["wins"][t2])
            return {"champion_probs":{t1:p,t2:1-p},"conf_final_probs":{t1:p,t2:1-p},
                    "matchup_details":[],"status":"conf_finals"}
        ea,eb=es["teams"]; wa_e,wb_e=es["wins"][ea],es["wins"][eb]
        wa,wb=ws["teams"]; ww_a,ww_b=ws["wins"][wa],ws["wins"][wb]
        pea=spob(ea,eb,es["home"],elo,wa_e,wb_e)
        pwa=spob(wa,wb,ws["home"],elo,ww_a,ww_b)
        champ=defaultdict(float); details=[]
        for (ec,pec),(wc,pwc) in itertools.product([(ea,pea),(eb,1-pea)],[(wa,pwa),(wb,1-pwa)]):
            pm=pec*pwc; pe=spob(ec,wc,wc,elo)
            champ[ec]+=pm*pe; champ[wc]+=pm*(1-pe)
            details.append({"east":ec,"west":wc,"prob_matchup":round(pm*100,1),
                             "prob_east_wins":round(pe*100,1),"prob_west_wins":round((1-pe)*100,1)})
        return {"champion_probs":dict(champ),
                "conf_final_probs":{ea:pea,eb:1-pea,wa:pwa,wb:1-pwa},
                "matchup_details":sorted(details,key=lambda x:-x["prob_matchup"]),"status":"conf_finals"}
    champ={}
    for s in act:
        t1,t2=s["teams"]; p=spob(t1,t2,s["home"],elo,s["wins"][t1],s["wins"][t2])
        champ[t1]=p; champ[t2]=1-p
    return {"champion_probs":champ,"conf_final_probs":champ,"matchup_details":[],"status":"early"}

# ── Runner ────────────────────────────────────────────────────────────────────
def run_model():
    source="live"
    try:
        games=fetch_live_games()
        if not games: raise ValueError("empty")
    except:
        games=list(FALLBACK_GAMES); source="fallback"

    states=get_states(games); sw=get_series_wins(states)
    act=get_active(states,sw); remain=get_remaining(states)
    elo=build_elo(games); proj=project(elo,act,sw)

    def fp(d): return {k:round(v*100,1) for k,v in d.items()}

    ratings=[]
    for a in remain:
        if a not in elo: continue
        s=FALLBACK_STATS.get(a,{}); tot=s.get("wins",45)+s.get("losses",37) or 82
        ratings.append({"abbr":a,"name":TEAM_NAMES.get(a,a),
                        "conf":"East" if a in EAST else "West",
                        "elo":round(elo[a]),"net_rtg":s.get("net_rtg",0),
                        "srs":s.get("srs",0),"win_pct":round(s.get("wins",45)/tot*100,1)})
    ratings.sort(key=lambda x:-x["elo"])

    series_out=[]
    for s in act:
        t1,t2=s["teams"]
        series_out.append({"team_a":t1,"name_a":TEAM_NAMES.get(t1,t1),
                           "team_b":t2,"name_b":TEAM_NAMES.get(t2,t2),
                           "wins_a":s["wins"].get(t1,0),"wins_b":s["wins"].get(t2,0),
                           "home":s["home"],"conference":s["conference"],"round_num":s["round_num"]})
    return {
        "updated_at":datetime.now(timezone.utc).isoformat(),
        "data_source":source,"status":proj.get("status","unknown"),
        "champion":proj.get("champion"),
        "champion_probs":fp(proj.get("champion_probs",{})),
        "conf_final_probs":fp(proj.get("conf_final_probs",{})),
        "matchup_details":proj.get("matchup_details",[]),
        "active_series":series_out,"remaining_teams":remain,"team_ratings":ratings,
    }

# ── Vercel handler ────────────────────────────────────────────────────────────
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            body=json.dumps(run_model()).encode()
            self.send_response(200)
            self.send_header("Content-Type","application/json")
            self.send_header("Cache-Control","public, s-maxage=300, stale-while-revalidate=60")
            self.send_header("Access-Control-Allow-Origin","*")
            self.end_headers(); self.wfile.write(body)
        except Exception as e:
            err=json.dumps({"error":str(e),"type":type(e).__name__}).encode()
            self.send_response(500)
            self.send_header("Content-Type","application/json")
            self.send_header("Access-Control-Allow-Origin","*")
            self.end_headers(); self.wfile.write(err)
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers()
    def log_message(self,fmt,*args): pass