import os
import json
import math
import sqlite3
import time
from datetime import date, datetime, timedelta
from itertools import combinations

import requests
import streamlit as st

# ============================================================
# FOOT AI PRO — football-data.org v4
# Matchs, probabilités Poisson, classement, IA, combinés, historique
# ============================================================

st.set_page_config(
    page_title="FOOT AI PRO",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_BASE = "https://api.football-data.org/v4"
DB_PATH = "foot_ai_pro_history.db"
COMPETITIONS = {
    "Ligue 1 (France)": "FL1",
    "Premier League (Angleterre)": "PL",
    "Liga (Espagne)": "PD",
    "Bundesliga (Allemagne)": "BL1",
    "Serie A (Italie)": "SA",
    "Ligue des Champions": "CL",
}
MARKET_LABELS = {
    "HOME": "Victoire domicile",
    "DRAW": "Match nul",
    "AWAY": "Victoire extérieur",
    "OVER15": "Plus de 1,5 but",
    "OVER25": "Plus de 2,5 buts",
    "OVER35": "Plus de 3,5 buts",
    "UNDER25": "Moins de 2,5 buts",
    "UNDER35": "Moins de 3,5 buts",
    "BTTS_YES": "Les deux équipes marquent : oui",
    "BTTS_NO": "Les deux équipes marquent : non",
}

st.markdown("""
<style>
/* FOOT AI PRO — interface premium, fond stade sombre */
:root { color-scheme: dark; }
.stApp {
    background-color: #06100e;
    background-image:
        linear-gradient(90deg, rgba(3,10,12,.94) 0%, rgba(3,10,12,.80) 55%, rgba(3,10,12,.70) 100%),
        linear-gradient(0deg, rgba(2,8,10,.94) 0%, rgba(2,8,10,.35) 100%),
        url("https://images.unsplash.com/photo-1522778119026-d647f0596c20?auto=format&fit=crop&w=2000&q=85");
    background-position: center, center, center;
    background-size: cover, cover, cover;
    background-attachment: fixed;
    color: #f4f8f6;
}
[data-testid="stHeader"] { background: rgba(3,10,12,.72); }
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, rgba(5,20,17,.98), rgba(7,16,28,.98));
    border-right: 1px solid rgba(67,255,157,.22);
}
[data-testid="stSidebar"] * { color: #eefbf4; }
.block-container { padding-top: 1.6rem; padding-bottom: 3rem; }
h1, h2, h3 { letter-spacing: -.025em; }
h1 { text-shadow: 0 0 24px rgba(47,255,143,.18); }
.hero {
    padding: 22px; border-radius: 18px; margin-bottom: 18px;
    background: linear-gradient(105deg, rgba(5,42,29,.92), rgba(7,22,32,.80));
    border: 1px solid rgba(75,255,159,.35);
    box-shadow: 0 12px 36px rgba(0,0,0,.22);
}
.hero h1 { margin: 0; color: #f5fff9; }
.hero p { margin: 6px 0 0; color: #c1d8ce; }
/* Cartes vitrées et métriques */
div[data-testid="stMetric"] {
    background: linear-gradient(145deg, rgba(12,37,32,.94), rgba(10,23,34,.94));
    padding: 16px 18px; border-radius: 16px;
    border: 1px solid rgba(69,255,161,.28);
    box-shadow: 0 8px 28px rgba(0,0,0,.22);
}
div[data-testid="stMetricLabel"] { color: #b8d8c8; }
div[data-testid="stMetricValue"] { color: #54ffa1; font-weight: 800; }
[data-testid="stVerticalBlockBorderWrapper"] {
    border-color: rgba(85,255,165,.18) !important;
    border-radius: 16px !important;
}
.stButton > button, .stDownloadButton > button {
    border-radius: 11px; border: 1px solid #39e98c;
    background: linear-gradient(120deg, #0c6b43, #0a453b);
    color: white; font-weight: 700; transition: .18s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover {
    border-color: #8affbd; color: white;
    box-shadow: 0 0 18px rgba(57,233,140,.24);
}
[data-baseweb="tab-list"] { gap: 7px; }
[data-baseweb="tab"] {
    background: rgba(10,30,28,.78); border-radius: 10px 10px 0 0;
    padding: 8px 14px;
}
[data-baseweb="tab"][aria-selected="true"] {
    background: rgba(14,90,58,.88); border-bottom: 2px solid #54ffa1;
}
[data-testid="stDataFrame"] { border: 1px solid rgba(69,255,161,.20); border-radius: 12px; }
input, textarea, [data-baseweb="select"] > div {
    background-color: rgba(8,24,25,.92) !important;
    border-color: rgba(69,255,161,.22) !important;
}
hr { border-color: rgba(69,255,161,.20); }
small, .stCaption { color: #b2c7c0 !important; }
@media (max-width: 700px) {
    .block-container { padding-left: 1rem; padding-right: 1rem; }
    .stApp { background-attachment: scroll; }
}
</style>
""", unsafe_allow_html=True)


# ------------------------- API / CONFIG -------------------------

def get_api_key():
    key = os.getenv("FOOTBALL_DATA_API_KEY", "").strip()
    try:
        key = (st.secrets.get("FOOTBALL_DATA_API_KEY", "") or key).strip()
    except Exception:
        pass
    return key


API_KEY = get_api_key()


def api_get(path, params=None, timeout=20):
    """Appel API avec messages d'erreur explicites."""
    if not API_KEY:
        raise RuntimeError(
            "Clé API manquante. Dans Streamlit : Settings → Secrets, ajoute "
            'FOOTBALL_DATA_API_KEY = "TA_CLE_API".'
        )
    headers = {"X-Auth-Token": API_KEY}
    url = f"{API_BASE}{path}"
    try:
        response = requests.get(url, headers=headers, params=params or {}, timeout=timeout)
    except requests.RequestException as exc:
        raise RuntimeError(f"Connexion à football-data.org impossible : {exc}") from exc

    if response.status_code == 429:
        raise RuntimeError("Limite de requêtes API atteinte (HTTP 429). Réessaie plus tard.")
    if response.status_code == 403:
        raise RuntimeError(
            "Accès refusé par l'API (HTTP 403). Vérifie que ton abonnement autorise "
            "cette compétition et cette saison."
        )
    if response.status_code == 401:
        raise RuntimeError("Clé API refusée (HTTP 401). Vérifie ta clé dans Streamlit Secrets.")
    if response.status_code >= 400:
        detail = ""
        try:
            detail = response.json().get("message", "")
        except Exception:
            pass
        raise RuntimeError(f"Erreur API HTTP {response.status_code}. {detail}".strip())
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError("La réponse de l'API n'est pas un JSON valide.") from exc


@st.cache_data(ttl=900, show_spinner=False)
def fetch_matches(date_from, date_to, competition_codes):
    """Un seul appel pour récupérer les rencontres de la période sélectionnée."""
    params = {
        "dateFrom": date_from,
        "dateTo": date_to,
        "competitions": ",".join(competition_codes),
    }
    data = api_get("/matches", params=params)
    return data.get("matches", [])


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_team_history(team_id):
    """Historique récent d'une équipe ; cache de 6 heures pour limiter les appels."""
    data = api_get(f"/teams/{int(team_id)}/matches", params={"status": "FINISHED", "limit": 10})
    matches = data.get("matches", [])
    # Du plus récent au plus ancien si l'API ne renvoie pas déjà cet ordre.
    matches.sort(key=lambda m: m.get("utcDate", ""), reverse=True)
    return matches[:10]


# ------------------------- PERSISTENT HISTORY -------------------------

def init_db():
    """Crée l'historique et met à niveau les anciennes bases SQLite sans perdre les données."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                match_id INTEGER PRIMARY KEY,
                match_date TEXT,
                competition TEXT,
                home_team TEXT,
                away_team TEXT,
                home_goals REAL,
                away_goals REAL,
                p_home REAL,
                p_draw REAL,
                p_away REAL,
                p_over15 REAL,
                p_over25 REAL,
                p_over35 REAL,
                p_under25 REAL,
                p_under35 REAL,
                p_btts_yes REAL,
                p_btts_no REAL,
                selected_market TEXT,
                selected_probability REAL,
                actual_home INTEGER,
                actual_away INTEGER,
                settled INTEGER DEFAULT 0,
                saved_at TEXT
            )
        """)
        # Une base déjà créée par une ancienne version peut ne pas avoir
        # toutes les colonnes attendues par read_history() et save_prediction().
        existing = {
            row[1] for row in conn.execute("PRAGMA table_info(predictions)").fetchall()
        }
        required_columns = {
            "match_date": "TEXT",
            "competition": "TEXT",
            "home_team": "TEXT",
            "away_team": "TEXT",
            "home_goals": "REAL",
            "away_goals": "REAL",
            "p_home": "REAL",
            "p_draw": "REAL",
            "p_away": "REAL",
            "p_over15": "REAL",
            "p_over25": "REAL",
            "p_over35": "REAL",
            "p_under25": "REAL",
            "p_under35": "REAL",
            "p_btts_yes": "REAL",
            "p_btts_no": "REAL",
            "selected_market": "TEXT",
            "selected_probability": "REAL",
            "actual_home": "INTEGER",
            "actual_away": "INTEGER",
            "settled": "INTEGER DEFAULT 0",
            "saved_at": "TEXT",
        }
        for column, definition in required_columns.items():
            if column not in existing:
                conn.execute(
                    f"ALTER TABLE predictions ADD COLUMN {column} {definition}"
                )
        conn.commit()


def save_prediction(match, model):
    comp = (match.get("competition") or {}).get("name", "Compétition")
    home = (match.get("homeTeam") or {}).get("name", "Domicile")
    away = (match.get("awayTeam") or {}).get("name", "Extérieur")
    p = model["markets"]
    selected_market, selected_probability = model["best_market"]
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO predictions (
                match_id, match_date, competition, home_team, away_team,
                home_goals, away_goals, p_home, p_draw, p_away,
                p_over15, p_over25, p_over35, p_under25, p_under35,
                p_btts_yes, p_btts_no, selected_market, selected_probability,
                actual_home, actual_away, settled, saved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 0, ?)
            ON CONFLICT(match_id) DO UPDATE SET
                home_goals=excluded.home_goals, away_goals=excluded.away_goals,
                p_home=excluded.p_home, p_draw=excluded.p_draw, p_away=excluded.p_away,
                p_over15=excluded.p_over15, p_over25=excluded.p_over25,
                p_over35=excluded.p_over35, p_under25=excluded.p_under25,
                p_under35=excluded.p_under35, p_btts_yes=excluded.p_btts_yes,
                p_btts_no=excluded.p_btts_no, selected_market=excluded.selected_market,
                selected_probability=excluded.selected_probability
        """, (
            int(match["id"]), match.get("utcDate", ""), comp, home, away,
            model["lambda_home"], model["lambda_away"],
            p["HOME"], p["DRAW"], p["AWAY"], p["OVER15"], p["OVER25"],
            p["OVER35"], p["UNDER25"], p["UNDER35"], p["BTTS_YES"], p["BTTS_NO"],
            selected_market, selected_probability, datetime.now().isoformat(timespec="seconds")
        ))
        conn.commit()


def settle_predictions(matches):
    """Met à jour les scores réels à partir des rencontres terminées récupérées."""
    updates = []
    for match in matches:
        status = match.get("status")
        score = match.get("score", {}).get("fullTime", {})
        hg, ag = score.get("home"), score.get("away")
        if status == "FINISHED" and hg is not None and ag is not None:
            updates.append((int(hg), int(ag), int(match["id"])))
    if updates:
        with sqlite3.connect(DB_PATH) as conn:
            conn.executemany(
                "UPDATE predictions SET actual_home=?, actual_away=?, settled=1 WHERE match_id=?",
                updates
            )
            conn.commit()
    return len(updates)



def evaluate_saved_market(market, home_goals, away_goals):
    """Retourne True si le marché enregistré est gagnant, False s'il est perdant."""
    if home_goals is None or away_goals is None:
        return None
    total = int(home_goals) + int(away_goals)
    checks = {
        "HOME": home_goals > away_goals,
        "DRAW": home_goals == away_goals,
        "AWAY": home_goals < away_goals,
        "OVER15": total >= 2,
        "OVER25": total >= 3,
        "OVER35": total >= 4,
        "UNDER25": total <= 2,
        "UNDER35": total <= 3,
        "BTTS_YES": home_goals > 0 and away_goals > 0,
        "BTTS_NO": home_goals == 0 or away_goals == 0,
    }
    return checks.get(str(market).upper())

def read_history():
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("""
            SELECT match_id, match_date, competition, home_team, away_team,
                   p_home, p_draw, p_away, selected_market, selected_probability,
                   actual_home, actual_away, settled
            FROM predictions ORDER BY match_date DESC
        """).fetchall()


init_db()


# ------------------------- MODEL: FORM + POISSON -------------------------

def poisson_pmf(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def get_team_stats(team_id, team_name):
    history = fetch_team_history(team_id)
    gf_home, ga_home, n_home = [], [], []
    gf_away, ga_away, n_away = [], [], []
    all_gf, all_ga = [], []
    for m in history:
        if m.get("status") != "FINISHED":
            continue
        score = m.get("score", {}).get("fullTime", {})
        hg, ag = score.get("home"), score.get("away")
        if hg is None or ag is None:
            continue
        home_id = (m.get("homeTeam") or {}).get("id")
        away_id = (m.get("awayTeam") or {}).get("id")
        if home_id == int(team_id):
            gf_home.append(hg); ga_home.append(ag)
            all_gf.append(hg); all_ga.append(ag)
        elif away_id == int(team_id):
            gf_away.append(ag); ga_away.append(hg)
            all_gf.append(ag); all_ga.append(hg)

    def avg(values, fallback):
        return sum(values) / len(values) if values else fallback

    return {
        "name": team_name,
        "matches": len(all_gf),
        "gf": avg(all_gf, 1.25),
        "ga": avg(all_ga, 1.25),
        "gf_home": avg(gf_home, avg(all_gf, 1.25)),
        "ga_home": avg(ga_home, avg(all_ga, 1.25)),
        "gf_away": avg(gf_away, avg(all_gf, 1.10)),
        "ga_away": avg(ga_away, avg(all_ga, 1.35)),
    }


def analyze_match(match):
    home_team = match.get("homeTeam") or {}
    away_team = match.get("awayTeam") or {}
    if not home_team.get("id") or not away_team.get("id"):
        raise RuntimeError("Identifiants des équipes absents de l'API.")

    hs = get_team_stats(home_team["id"], home_team.get("name", "Domicile"))
    aws = get_team_stats(away_team["id"], away_team.get("name", "Extérieur"))

    # Estimation simple fondée sur les buts récents domicile/extérieur.
    # Les coefficients sont volontairement modérés pour éviter des valeurs extrêmes.
    league_home_baseline = 1.45
    league_away_baseline = 1.15
    home_attack = hs["gf_home"] / max(league_home_baseline, 0.25)
    away_defence = aws["ga_away"] / max(league_home_baseline, 0.25)
    away_attack = aws["gf_away"] / max(league_away_baseline, 0.25)
    home_defence = hs["ga_home"] / max(league_away_baseline, 0.25)

    lam_home = league_home_baseline * (0.65 * home_attack + 0.35 * away_defence)
    lam_away = league_away_baseline * (0.65 * away_attack + 0.35 * home_defence)
    lam_home = min(max(lam_home, 0.15), 3.8)
    lam_away = min(max(lam_away, 0.15), 3.5)

    max_goals = 10
    home_probs = [poisson_pmf(i, lam_home) for i in range(max_goals + 1)]
    away_probs = [poisson_pmf(i, lam_away) for i in range(max_goals + 1)]
    p_home = p_draw = p_away = p_btts_yes = 0.0
    p_over15 = p_over25 = p_over35 = 0.0
    for hg, ph in enumerate(home_probs):
        for ag, pa in enumerate(away_probs):
            prob = ph * pa
            if hg > ag: p_home += prob
            elif hg == ag: p_draw += prob
            else: p_away += prob
            if hg + ag >= 2: p_over15 += prob
            if hg + ag >= 3: p_over25 += prob
            if hg + ag >= 4: p_over35 += prob
            if hg > 0 and ag > 0: p_btts_yes += prob

    total = p_home + p_draw + p_away
    if total:
        p_home, p_draw, p_away = p_home / total, p_draw / total, p_away / total
    p_under25 = 1 - p_over25
    p_under35 = 1 - p_over35
    p_btts_no = 1 - p_btts_yes

    markets = {
        "HOME": p_home, "DRAW": p_draw, "AWAY": p_away,
        "OVER15": p_over15, "OVER25": p_over25, "OVER35": p_over35,
        "UNDER25": p_under25, "UNDER35": p_under35,
        "BTTS_YES": p_btts_yes, "BTTS_NO": p_btts_no,
    }
    # Évite de présenter une victoire à 1X2 comme le meilleur marché par défaut
    # si un marché de buts est plus probable. On affiche le meilleur marché parmi tous.
    best_market = max(markets.items(), key=lambda item: item[1])
    likely_scores = []
    for hg, ph in enumerate(home_probs[:6]):
        for ag, pa in enumerate(away_probs[:6]):
            likely_scores.append((ph * pa, hg, ag))
    likely_scores.sort(reverse=True)
    confidence = min(1.0, (hs["matches"] + aws["matches"]) / 12.0)
    return {
        "lambda_home": lam_home,
        "lambda_away": lam_away,
        "markets": markets,
        "best_market": best_market,
        "scores": [(hg, ag, prob) for prob, hg, ag in likely_scores[:3]],
        "home_stats": hs,
        "away_stats": aws,
        "data_confidence": confidence,
    }


# ------------------------- UI HELPERS -------------------------

def pct(x):
    return f"{x * 100:.1f} %"


def status_fr(status):
    return {
        "SCHEDULED": "À venir",
        "TIMED": "Programmé",
        "IN_PLAY": "En direct",
        "PAUSED": "Pause",
        "FINISHED": "Terminé",
        "POSTPONED": "Reporté",
        "CANCELLED": "Annulé",
        "SUSPENDED": "Suspendu",
    }.get(status, status or "Statut inconnu")


def match_time(match):
    raw = match.get("utcDate")
    if not raw:
        return "Heure inconnue"
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone()
        return dt.strftime("%H:%M")
    except Exception:
        return raw


def match_name(match):
    return f'{(match.get("homeTeam") or {}).get("name", "Domicile")} - {(match.get("awayTeam") or {}).get("name", "Extérieur")}'


def probability_badge(value):
    if value >= 0.75:
        return "Élevée"
    if value >= 0.60:
        return "Modérée"
    return "Prudence"


# ------------------------- SIDEBAR -------------------------

st.sidebar.title("⚽ FOOT AI PRO")
st.sidebar.caption("Analyse statistique des matchs")
selected_competitions = st.sidebar.multiselect(
    "Compétitions",
    options=list(COMPETITIONS.keys()),
    default=list(COMPETITIONS.keys()),
)
date_mode = st.sidebar.selectbox(
    "Période des matchs",
    ["Aujourd'hui", "7 prochains jours", "Date personnalisée"],
)
today = date.today()
if date_mode == "Aujourd'hui":
    date_from, date_to = today, today
elif date_mode == "7 prochains jours":
    date_from, date_to = today, today + timedelta(days=6)
else:
    date_from = st.sidebar.date_input("Du", value=today, key="date_from")
    date_to = st.sidebar.date_input("Au", value=today, key="date_to")
    if date_to < date_from:
        st.sidebar.error("La date de fin doit être après la date de début.")

max_analyses = st.sidebar.slider(
    "Nombre maximum de matchs à analyser",
    min_value=2, max_value=12, value=6,
    help="Limite les appels API pour éviter d'épuiser le quota. Les matchs restants restent visibles."
)
st.sidebar.markdown("---")
st.sidebar.caption("Données : football-data.org v4")
st.sidebar.caption("Les probabilités sont des estimations statistiques, pas des garanties.")


st.markdown("""
<div class="hero">
    <h1>⚽ FOOT AI PRO</h1>
    <p>Matchs du jour • Probabilités • Classement IA • Combinés • Historique</p>
</div>
""", unsafe_allow_html=True)

if not API_KEY:
    st.error(
        "🔑 **Clé API manquante.** Dans Streamlit, ouvre **Manage app → Settings → Secrets** "
        'et ajoute :\n\n`FOOTBALL_DATA_API_KEY = "TA_CLE_API"`\n\n'
        "Ne publie jamais ta clé API dans le code visible sur GitHub."
    )
    st.stop()

if not selected_competitions:
    st.warning("Sélectionne au moins une compétition dans le menu de gauche.")
    st.stop()

codes = [COMPETITIONS[name] for name in selected_competitions]
tab_matches, tab_ai, tab_combos, tab_history = st.tabs([
    "📅 Matchs", "🤖 Analyse IA & classement", "🎲 Combinés", "📈 Historique"
])

# Store data for current run/session
if "matches_loaded" not in st.session_state:
    st.session_state.matches_loaded = None
if "analyses" not in st.session_state:
    st.session_state.analyses = {}
if "last_match_query" not in st.session_state:
    st.session_state.last_match_query = None

query_key = (str(date_from), str(date_to), tuple(codes))
reload_matches = st.sidebar.button("🔄 Actualiser les matchs")
if st.session_state.matches_loaded is None or st.session_state.last_match_query != query_key or reload_matches:
    try:
        with st.spinner("Récupération des rencontres..."):
            fetched = fetch_matches(str(date_from), str(date_to), codes)
        st.session_state.matches_loaded = fetched
        st.session_state.last_match_query = query_key
    except Exception as exc:
        st.error(str(exc))
        st.stop()

matches = st.session_state.matches_loaded or []
matches = sorted(matches, key=lambda m: m.get("utcDate", ""))
if not matches:
    st.info("Aucun match trouvé pour cette période et ces compétitions. Essaie une autre date ou vérifie l'accès de ton API.")
    # Tabs remain useful for history.
else:
    st.sidebar.success(f"{len(matches)} rencontre(s) trouvée(s)")

# Match list page
with tab_matches:
    st.subheader("📅 Rencontres de la période")
    if matches:
        filter_status = st.selectbox(
            "Filtrer les rencontres",
            ["Toutes", "À venir", "En direct", "Terminées"],
        )
        def matches_filter(m):
            status = m.get("status")
            if filter_status == "À venir":
                return status in ("SCHEDULED", "TIMED")
            if filter_status == "En direct":
                return status in ("IN_PLAY", "PAUSED")
            if filter_status == "Terminées":
                return status == "FINISHED"
            return True

        filtered = [m for m in matches if matches_filter(m)]
        for match in filtered:
            comp = (match.get("competition") or {}).get("name", "Compétition")
            home = (match.get("homeTeam") or {}).get("name", "Domicile")
            away = (match.get("awayTeam") or {}).get("name", "Extérieur")
            score = match.get("score", {}).get("fullTime", {})
            if match.get("status") == "FINISHED" and score.get("home") is not None:
                score_txt = f'{score["home"]} - {score["away"]}'
            else:
                score_txt = status_fr(match.get("status"))
            st.markdown(
                f'<div class="match-card"><b>{home} vs {away}</b>'
                f'<br><span class="small-muted">{comp} · {match_time(match)} · {score_txt}</span></div>',
                unsafe_allow_html=True,
            )
        st.caption("Pour limiter les appels API, les analyses détaillées sont calculées uniquement lorsque tu les demandes.")
    else:
        st.info("Aucune rencontre à afficher.")

# Analysis page: calculate only on click, and limited number of matches
with tab_ai:
    st.subheader("🤖 Analyse IA et classement des meilleurs marchés")
    st.write(
        "Le modèle estime les buts attendus à partir des derniers résultats domicile/extérieur, "
        "puis calcule les probabilités avec une distribution de Poisson."
    )
    if matches:
        candidate_matches = [
            m for m in matches
            if m.get("status") not in ("CANCELLED", "POSTPONED", "SUSPENDED")
            and (m.get("homeTeam") or {}).get("id")
            and (m.get("awayTeam") or {}).get("id")
        ]
        st.caption(f"{len(candidate_matches)} matchs analysables · limite actuelle : {max_analyses} par lancement")
        if st.button("🧠 Analyser automatiquement les matchs", type="primary", key="analyze_all"):
            selected = candidate_matches[:max_analyses]
            progress = st.progress(0)
            status_box = st.empty()
            new_analyses = {}
            errors = []
            for idx, match in enumerate(selected):
                key = str(match["id"])
                try:
                    status_box.write(f"Analyse : {match_name(match)}")
                    model = analyze_match(match)
                    new_analyses[key] = model
                    save_prediction(match, model)
                except Exception as exc:
                    errors.append(f'{match_name(match)} : {exc}')
                progress.progress((idx + 1) / max(1, len(selected)))
                # Small pause to avoid sending requests too quickly.
                time.sleep(0.25)
            st.session_state.analyses.update(new_analyses)
            status_box.empty()
            progress.empty()
            if new_analyses:
                st.success(f"{len(new_analyses)} analyse(s) enregistrée(s) dans l'historique.")
            for err in errors[:5]:
                st.warning(err)
            if len(errors) > 5:
                st.warning(f"{len(errors) - 5} autre(s) erreur(s) non affichée(s).")

        analyses = st.session_state.analyses
        rows = []
        for match in candidate_matches:
            key = str(match["id"])
            model = analyses.get(key)
            if not model:
                continue
            best_key, best_prob = model["best_market"]
            rows.append({
                "Match": match_name(match),
                "Compétition": (match.get("competition") or {}).get("name", ""),
                "Heure": match_time(match),
                "Meilleur marché": MARKET_LABELS[best_key],
                "Probabilité": best_prob,
                "Fiabilité des données": model["data_confidence"],
                "ID": key,
            })
        if rows:
            rows.sort(key=lambda r: (r["Probabilité"] * (0.65 + 0.35 * r["Fiabilité des données"])), reverse=True)
            st.markdown("### 🏆 Classement des analyses disponibles")
            st.dataframe(
                [{
                    "Match": r["Match"],
                    "Compétition": r["Compétition"],
                    "Heure": r["Heure"],
                    "Marché conseillé": r["Meilleur marché"],
                    "Probabilité estimée": pct(r["Probabilité"]),
                    "Données": probability_badge(r["Fiabilité des données"]),
                } for r in rows],
                use_container_width=True,
                hide_index=True,
            )

            st.markdown("### Détail par rencontre")
            labels = {f'{r["Match"]} · {r["Compétition"]}': r["ID"] for r in rows}
            chosen_label = st.selectbox("Choisir une rencontre", list(labels.keys()))
            chosen_id = labels[chosen_label]
            chosen_match = next((m for m in candidate_matches if str(m["id"]) == chosen_id), None)
            model = analyses[chosen_id]
            if chosen_match:
                hs, aws = model["home_stats"], model["away_stats"]
                c1, c2, c3 = st.columns(3)
                c1.metric("Victoire domicile", pct(model["markets"]["HOME"]))
                c2.metric("Match nul", pct(model["markets"]["DRAW"]))
                c3.metric("Victoire extérieur", pct(model["markets"]["AWAY"]))
                c1, c2, c3 = st.columns(3)
                c1.metric("+ 1,5 but", pct(model["markets"]["OVER15"]))
                c2.metric("+ 2,5 buts", pct(model["markets"]["OVER25"]))
                c3.metric("+ 3,5 buts", pct(model["markets"]["OVER35"]))
                c1, c2 = st.columns(2)
                c1.metric("Moins de 2,5 buts", pct(model["markets"]["UNDER25"]))
                c2.metric("Moins de 3,5 buts", pct(model["markets"]["UNDER35"]))
                c1, c2 = st.columns(2)
                c1.metric("Les deux marquent : oui", pct(model["markets"]["BTTS_YES"]))
                c2.metric("Les deux marquent : non", pct(model["markets"]["BTTS_NO"]))

                st.markdown("**Scores exacts les plus probables (estimation)**")
                st.write(" · ".join([f"{hg}-{ag} ({pct(prob)})" for hg, ag, prob in model["scores"]]))
                st.markdown("**Forme récente utilisée**")
                st.write(
                    f'{hs["name"]} : {hs["matches"]} matchs exploitables, '
                    f'{hs["gf"]:.2f} but(s) marqué(s)/match, {hs["ga"]:.2f} encaissé(s)/match.'
                )
                st.write(
                    f'{aws["name"]} : {aws["matches"]} matchs exploitables, '
                    f'{aws["gf"]:.2f} but(s) marqué(s)/match, {aws["ga"]:.2f} encaissé(s)/match.'
                )
                if model["data_confidence"] < 0.65:
                    st.warning("Données limitées : l'estimation est moins robuste, interprète les probabilités avec prudence.")
                best_key, best_prob = model["best_market"]
                st.info(f'🤖 Sélection automatique : **{MARKET_LABELS[best_key]} — {pct(best_prob)}**. Ce n’est pas une garantie.')
        else:
            st.info("Clique sur « Analyser automatiquement les matchs » pour lancer les calculs. Les analyses ne sont pas lancées automatiquement à chaque rafraîchissement afin de protéger le quota API.")
    else:
        st.info("Aucun match pour la période sélectionnée.")

# Combos page: only use analyses currently calculated and prefer varied markets
with tab_combos:
    st.subheader("🎲 Combinaisons de 2 à 4 matchs")
    st.warning("Les probabilités d'un combiné sont approximatives. Les événements ne sont pas nécessairement indépendants ; un combiné reste risqué.")
    available = []
    for match in matches:
        model = st.session_state.analyses.get(str(match.get("id")))
        if not model:
            continue
        best_key, best_prob = model["best_market"]
        # Keep markets at least 60% probability to avoid extremely weak selections.
        if best_prob >= 0.60:
            available.append({
                "match": match,
                "model": model,
                "market": best_key,
                "prob": best_prob,
                "name": match_name(match),
            })
    combo_size = st.selectbox("Nombre de sélections", [2, 3, 4], index=0)
    min_prob = st.slider("Probabilité minimale par sélection", 50, 85, 60, 5) / 100
    if len(available) < combo_size:
        st.info(
            f"Il faut au moins {combo_size} matchs analysés avec un marché atteignant "
            f"{int(min_prob*100)} %. Va dans « Analyse IA » et lance l'analyse."
        )
    else:
        # Try to vary markets; score combinations using joint probability and a mild diversity bonus.
        combos = []
        pool = [x for x in available if x["prob"] >= min_prob]
        for combo in combinations(pool, combo_size):
            raw_prob = math.prod(x["prob"] for x in combo)
            distinct_markets = len(set(x["market"] for x in combo))
            score = raw_prob * (1 + 0.04 * (distinct_markets - 1))
            combos.append((score, raw_prob, combo, distinct_markets))
        combos.sort(key=lambda x: x[0], reverse=True)
        if not combos:
            st.info("Aucune combinaison ne respecte ce seuil. Diminue le seuil ou analyse davantage de matchs.")
        else:
            for idx, (score, raw_prob, combo, diversity) in enumerate(combos[:5], start=1):
                risk = "Élevé" if raw_prob < 0.20 else ("Modéré" if raw_prob < 0.40 else "Plus faible (mais réel)")
                with st.container(border=True):
                    st.markdown(f"### Proposition {idx} · {combo_size} sélections")
                    for item in combo:
                        st.write(f'• **{item["name"]}** — {MARKET_LABELS[item["market"]]} ({pct(item["prob"])})')
                    st.write(f"Probabilité combinée théorique : **{pct(raw_prob)}**")
                    st.write(f"Risque estimé : **{risk}**")
                    st.caption(f"Diversité des marchés : {diversity}/{combo_size}. Les probabilités ne sont pas des cotes et ne prédisent pas le gain financier.")
                    st.caption("Cette estimation multiplie les probabilités individuelles et peut être inexacte, notamment si les événements sont corrélés.")

# History page
with tab_history:
    st.subheader("📈 Historique des pronostics")
    st.write("Les scores réels sont récupérés depuis football-data.org. Après synchronisation, chaque pronostic terminé est marqué GAGNÉ ou PERDU.")
    if st.button("🔄 Vérifier les résultats des 45 derniers jours", key="sync_history"):
        try:
            sync_from = date.today() - timedelta(days=45)
            sync_to = date.today()
            with st.spinner("Vérification des scores et mise à jour des pronostics..."):
                past_matches = fetch_matches(str(sync_from), str(sync_to), codes)
            updated = settle_predictions(past_matches)
            st.success(f"Vérification terminée : {updated} match(s) terminé(s) synchronisé(s).")
        except Exception as exc:
            st.error(str(exc))

    history = read_history()
    if history:
        settled = [r for r in history if r[12] == 1 and r[10] is not None and r[11] is not None]
        pending = len(history) - len(settled)
        outcomes = [(r, evaluate_saved_market(r[8], r[10], r[11])) for r in settled]
        decided = [(r, hit) for r, hit in outcomes if hit is not None]
        wins = sum(1 for _, hit in decided if hit is True)
        losses = sum(1 for _, hit in decided if hit is False)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Pronostics enregistrés", len(history))
        c2.metric("Matchs terminés", len(settled))
        c3.metric("Gagnés", wins)
        c4.metric("Perdus", losses)
        if decided:
            st.metric("Taux de réussite observé", pct(wins / len(decided)))
            st.caption("Ce taux est calculé uniquement sur les marchés évaluables dont le score est disponible. Il ne garantit pas les résultats futurs.")

        st.markdown("### Derniers pronostics")
        table = []
        for r in history[:100]:
            score_text = "En attente du match"
            result_text = "EN ATTENTE"
            if r[12] == 1 and r[10] is not None and r[11] is not None:
                score_text = f"{r[10]} - {r[11]}"
                hit = evaluate_saved_market(r[8], r[10], r[11])
                result_text = "GAGNÉ ✅" if hit is True else ("PERDU ❌" if hit is False else "SCORE REÇU — MARCHÉ NON ÉVALUÉ")
            table.append({
                "Date": r[1][:16].replace("T", " ") if r[1] else "",
                "Compétition": r[2],
                "Match": f"{r[3]} - {r[4]}",
                "Pronostic": MARKET_LABELS.get(r[8], r[8]),
                "Probabilité": pct(r[9] or 0),
                "Score réel": score_text,
                "Résultat du pronostic": result_text,
            })
        st.dataframe(table, use_container_width=True, hide_index=True)
        csv_data = json.dumps(table, ensure_ascii=False, indent=2)
        st.download_button(
            "Télécharger l'historique (JSON)",
            data=csv_data,
            file_name="foot_ai_pro_historique.json",
            mime="application/json",
        )
    else:
        st.info("Aucun pronostic enregistré pour le moment. Lance une analyse dans l'onglet « Analyse IA ».")

st.markdown("---")
st.caption(
    "FOOT AI PRO est un outil statistique informatif. Les probabilités sont des estimations issues de données historiques, "
    "elles peuvent être inexactes et ne garantissent aucun résultat. Joue de manière responsable."