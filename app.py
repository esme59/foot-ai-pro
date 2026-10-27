import os
import json
import math
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import pandas as pd
import streamlit as st

# ============================================================
# FOOT AI PRO - FOOTBALL LIVE + IA PREMIUM
# Interface uniquement : aucun pari réel
# API : football-data.org v4
# Ne modifie pas bot.py ni data/bankroll.json
# ============================================================

st.set_page_config(
    page_title="FOOT AI PRO",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_BASE = "https://api.football-data.org/v4"
DATA_FILE = Path("data/bankroll.json")
PARIS = ZoneInfo("Europe/Paris")

COMPETITIONS = {
    "FL1": "Ligue 1",
    "PL": "Premier League",
    "PD": "Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "CL": "Ligue des Champions",
}

# ------------------------------------------------------------
# DESIGN
# ------------------------------------------------------------

st.markdown("""
<style>
    .stApp {
        background:
            radial-gradient(ellipse at top left, #102b36 0%, transparent 38%),
            linear-gradient(160deg, #07111b 0%, #0b1522 55%, #101c2a 100%);
        color: #edf4f8;
    }

    [data-testid="stSidebar"] {
        background: #0b1723;
        border-right: 1px solid #203746;
    }

    [data-testid="stHeader"] {
        background: transparent;
    }

    h1, h2, h3 {
        color: #f2f7fa !important;
    }

    p, label, span {
        color: inherit;
    }

    .hero {
        padding: 25px;
        border: 1px solid #244452;
        border-radius: 22px;
        background: linear-gradient(120deg, #102a35, #132033 70%, #173126);
        margin-bottom: 20px;
    }

    .hero-title {
        font-size: 32px;
        font-weight: 900;
        letter-spacing: 1px;
        margin-bottom: 5px;
    }

    .hero-sub {
        color: #a9c0ca;
        font-size: 14px;
    }

    .pill {
        display: inline-block;
        padding: 5px 10px;
        border-radius: 20px;
        background: #173c32;
        color: #75edb1;
        font-size: 12px;
        font-weight: 700;
        margin-top: 10px;
    }

    .metric-card {
        background: linear-gradient(145deg, #132536, #0d1b29);
        border: 1px solid #243c4c;
        border-radius: 17px;
        padding: 16px;
        min-height: 108px;
        margin-bottom: 10px;
    }

    .metric-label {
        color: #9eb4c1;
        font-size: 12px;
        margin-bottom: 8px;
    }

    .metric-value {
        color: #f4f8fb;
        font-size: 25px;
        font-weight: 800;
    }

    .metric-note {
        color: #75edb1;
        font-size: 12px;
        margin-top: 5px;
    }

    .match-card {
        background: linear-gradient(145deg, #132333, #0d1925);
        border: 1px solid #243a49;
        border-radius: 17px;
        padding: 16px;
        margin-bottom: 13px;
    }

    .match-league {
        color: #75edb1;
        font-size: 12px;
        font-weight: 700;
        margin-bottom: 10px;
    }

    .match-teams {
        font-size: 17px;
        font-weight: 800;
        color: #f4f8fb;
        margin-bottom: 8px;
    }

    .match-meta {
        color: #9eb4c1;
        font-size: 12px;
    }

    .probability {
        background: #173b32;
        border: 1px solid #28624b;
        border-radius: 10px;
        padding: 8px;
        text-align: center;
        margin-top: 6px;
    }

    .probability strong {
        display: block;
        color: #83f2b9;
        font-size: 19px;
    }

    .probability small {
        color: #bfd6d1;
        font-size: 11px;
    }

    .section-label {
        color: #8ce8b8;
        font-size: 12px;
        font-weight: 800;
        letter-spacing: 1px;
        text-transform: uppercase;
        margin-bottom: 8px;
    }

    div[data-testid="stTabs"] button {
        border-radius: 10px;
    }

    div.stButton > button {
        border-radius: 11px;
        border: 1px solid #315b67;
        background: #163441;
        color: white;
        font-weight: 700;
    }

    div.stButton > button:hover {
        border-color: #75edb1;
        color: #75edb1;
    }

    div[data-testid="stAlert"] {
        border-radius: 12px;
    }

    [data-testid="stDataFrame"] {
        border: 1px solid #243a49;
        border-radius: 12px;
    }

    @media (max-width: 700px) {
        .hero {
            padding: 18px;
        }
        .hero-title {
            font-size: 25px;
        }
        .metric-value {
            font-size: 21px;
        }
    }
</style>
""", unsafe_allow_html=True)


# ------------------------------------------------------------
# UTILITAIRES
# ------------------------------------------------------------

def now_paris():
    return datetime.now(PARIS)


def parse_date(value):
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=PARIS)

        return dt.astimezone(PARIS)
    except (ValueError, TypeError):
        return None


def number(value, default=0.0):
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def money(value):
    return f"{number(value):.2f} €".replace(".", ",")


def percent(value):
    return f"{number(value) * 100:.1f} %".replace(".", ",")


def metric_card(label, value, note=""):
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def match_name(bet):
    home = bet.get("home_team", bet.get("homeTeam", "?"))
    away = bet.get("away_team", bet.get("awayTeam", "?"))
    return f"{home} - {away}"


def bet_status(bet):
    return str(bet.get("status", "PENDING")).upper()


def is_settled(bet):
    return bet_status(bet) in {
        "WON", "LOST", "VOID", "CANCELLED", "CANCELED", "REMBOURSE"
    }


def bet_date(bet):
    for key in (
        "match_date",
        "created_date",
        "created_day",
        "created_at",
        "date",
    ):
        value = bet.get(key)
        if value:
            dt = parse_date(value)
            if dt:
                return dt
    return None


def bet_market(bet):
    return str(bet.get("market", bet.get("type", "Pronostic")))


def bet_odds(bet):
    return number(bet.get("odds", bet.get("virtual_odds", 0)))


def bet_probability(bet):
    value = number(bet.get("probability", 0))

    # Le bot enregistre normalement la probabilité entre 0 et 1.
    if value > 1:
        value /= 100

    return max(0.0, min(1.0, value))


def bet_profit(bet):
    if "profit" in bet and bet.get("profit") is not None:
        return number(bet.get("profit"))

    status = bet_status(bet)
    stake = number(bet.get("stake", 0))
    odds = bet_odds(bet)

    if status == "WON":
        return stake * (odds - 1)

    if status in {"LOST"}:
        return -stake

    return 0.0


def competition_name(bet):
    code = bet.get("competition", bet.get("competition_code", ""))
    return bet.get(
        "competition_name",
        COMPETITIONS.get(str(code), str(code or "Compétition")),
    )


# ------------------------------------------------------------
# CAPITAL ET HISTORIQUE : LECTURE UNIQUEMENT
# ------------------------------------------------------------

def load_state():
    default = {
        "initial_bankroll": 20.0,
        "bankroll": 20.0,
        "bets": [],
        "history": [],
    }

    if not DATA_FILE.exists():
        return default, False

    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            state = json.load(f)

        if not isinstance(state, dict):
            return default, False

        initial = state.get(
            "initial_bankroll",
            state.get("starting_bankroll", state.get("bankroll_initiale", 20)),
        )

        current = state.get(
            "bankroll",
            state.get("bankroll_actuelle", state.get("capital", initial)),
        )

        bets = state.get("bets", state.get("paris", []))
        history = state.get("history", state.get("historique", []))

        if not isinstance(bets, list):
            bets = []

        if not isinstance(history, list):
            history = []

        normalized = dict(state)
        normalized["initial_bankroll"] = number(initial, 20)
        normalized["bankroll"] = number(current, number(initial, 20))
        normalized["bets"] = bets
        normalized["history"] = history

        return normalized, True

    except (OSError, json.JSONDecodeError, TypeError):
        return default, False


state, state_loaded = load_state()
bets = state.get("bets", [])

# ------------------------------------------------------------
# API FOOTBALL-DATA.ORG
# Une requête par compétition, mise en cache 6 heures.
# ------------------------------------------------------------

def get_api_key():
    try:
        secret = st.secrets.get("FOOTBALL_DATA_API_KEY", "")
        if secret:
            return str(secret).strip()
    except Exception:
        pass

    return os.getenv("FOOTBALL_DATA_API_KEY", "").strip()


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_competition_matches(code, date_from, date_to, api_key):
    if not api_key:
        return {"ok": False, "error": "Clé API manquante", "matches": []}

    url = f"{API_BASE}/competitions/{code}/matches"

    try:
        response = requests.get(
            url,
            headers={"X-Auth-Token": api_key},
            params={
                "dateFrom": date_from,
                "dateTo": date_to,
            },
            timeout=20,
        )

        if response.status_code == 429:
            return {
                "ok": False,
                "error": "Limite de requêtes API atteinte. Réessaie plus tard.",
                "matches": [],
            }

        if response.status_code == 403:
            return {
                "ok": False,
                "error": (
                    "Accès refusé pour cette compétition ou cette période "
                    "avec ton abonnement API."
                ),
                "matches": [],
            }

        if response.status_code == 401:
            return {
                "ok": False,
                "error": "Clé API invalide ou non reconnue.",
                "matches": [],
            }

        response.raise_for_status()
        payload = response.json()

        return {
            "ok": True,
            "error": "",
            "matches": payload.get("matches", []),
        }

    except requests.RequestException as exc:
        return {
            "ok": False,
            "error": f"Erreur réseau : {exc}",
            "matches": [],
        }

    except (ValueError, TypeError):
        return {
            "ok": False,
            "error": "Réponse API impossible à lire.",
            "matches": [],
        }


def fetch_all_matches(selected_codes, days_ahead=7):
    api_key = get_api_key()

    if not api_key:
        return [], ["Clé API manquante : vérifie FOOTBALL_DATA_API_KEY."], 0

    today = now_paris().date()
    date_from = (today - timedelta(days=180)).isoformat()
    date_to = (today + timedelta(days=days_ahead)).isoformat()

    all_matches = []
    errors = []
    successful = 0

    for code in selected_codes:
        result = fetch_competition_matches(
            code,
            date_from,
            date_to,
            api_key,
        )

        if result["ok"]:
            successful += 1

            for match in result["matches"]:
                item = dict(match)
                item["_competition_code"] = code
                item["_competition_name"] = COMPETITIONS.get(code, code)
                all_matches.append(item)
        else:
            errors.append(f"{COMPETITIONS.get(code, code)} : {result['error']}")

    # Évite les doublons éventuels.
    unique = {}
    for match in all_matches:
        match_id = match.get("id")
        if match_id is not None:
            unique[match_id] = match

    return list(unique.values()), errors, successful


# ------------------------------------------------------------
# MODELE DE POISSON
# ------------------------------------------------------------

def poisson_distribution(lam, max_goals=10):
    lam = max(0.05, min(float(lam), 5.0))

    values = [math.exp(-lam)]

    for goals in range(1, max_goals + 1):
        values.append(values[-1] * lam / goals)

    total = sum(values)

    if total > 0:
        values = [value / total for value in values]

    return values


def finished_matches(matches):
    completed = []

    for match in matches:
        status = match.get("status")

        if status not in {"FINISHED", "AWARDED"}:
            continue

        score = match.get("score", {}).get("fullTime", {})
        home_goals = score.get("home")
        away_goals = score.get("away")

        if home_goals is None or away_goals is None:
            continue

        try:
            completed.append({
                "home_id": match.get("homeTeam", {}).get("id"),
                "away_id": match.get("awayTeam", {}).get("id"),
                "home_name": match.get("homeTeam", {}).get("name", "?"),
                "away_name": match.get("awayTeam", {}).get("name", "?"),
                "home_goals": int(home_goals),
                "away_goals": int(away_goals),
                "date": parse_date(match.get("utcDate")),
                "competition": match.get("_competition_name", ""),
                "competition_code": match.get("_competition_code", ""),
            })
        except (TypeError, ValueError):
            continue

    return completed


def team_statistics(history):
    teams = {}

    for match in history:
        home_id = match["home_id"]
        away_id = match["away_id"]

        if home_id is not None:
            teams.setdefault(home_id, []).append({
                "venue": "HOME",
                "scored": match["home_goals"],
                "conceded": match["away_goals"],
            })

        if away_id is not None:
            teams.setdefault(away_id, []).append({
                "venue": "AWAY",
                "scored": match["away_goals"],
                "conceded": match["home_goals"],
            })

    return teams


def average(values, default):
    return sum(values) / len(values) if values else default


def predict_match(match, history):
    home = match.get("homeTeam", {})
    away = match.get("awayTeam", {})

    home_id = home.get("id")
    away_id = away.get("id")

    if home_id is None or away_id is None:
        return None

    competition_code = match.get("_competition_code", "")

    league_history = [
        item for item in history
        if item.get("competition_code") == competition_code
    ]

    if len(league_history) < 8:
        return {
            "match": match,
            "ready": False,
            "reason": "Historique de compétition insuffisant",
        }

    league_home_avg = average(
        [item["home_goals"] for item in league_history],
        1.35,
    )
    league_away_avg = average(
        [item["away_goals"] for item in league_history],
        1.10,
    )

    team_stats = team_statistics(league_history)

    home_games = team_stats.get(home_id, [])
    away_games = team_stats.get(away_id, [])

    home_home = [g for g in home_games if g["venue"] == "HOME"][-10:]
    away_away = [g for g in away_games if g["venue"] == "AWAY"][-10:]

    home_all = home_games[-10:]
    away_all = away_games[-10:]

    if len(home_all) < 3 or len(away_all) < 3:
        return {
            "match": match,
            "ready": False,
            "reason": "Pas assez de matchs récents pour les deux équipes",
        }

    # Statistiques domicile / extérieur, avec repli sur les stats globales.
    home_scored = average(
        [g["scored"] for g in home_home],
        average([g["scored"] for g in home_all], league_home_avg),
    )
    home_conceded = average(
        [g["conceded"] for g in home_home],
        average([g["conceded"] for g in home_all], league_away_avg),
    )

    away_scored = average(
        [g["scored"] for g in away_away],
        average([g["scored"] for g in away_all], league_away_avg),
    )
    away_conceded = average(
        [g["conceded"] for g in away_away],
        average([g["conceded"] for g in away_all], league_home_avg),
    )

    # Attaque et défense relatives à la moyenne de la compétition.
    home_attack = home_scored / max(0.25, league_home_avg)
    home_defence = home_conceded / max(0.25, league_away_avg)

    away_attack = away_scored / max(0.25, league_away_avg)
    away_defence = away_conceded / max(0.25, league_home_avg)

    # Mélange attaque/défense et moyenne du championnat.
    lambda_home = league_home_avg * (
        0.60 * home_attack + 0.40 * away_defence
    )
    lambda_away = league_away_avg * (
        0.60 * away_attack + 0.40 * home_defence
    )

    # Stabilisation pour éviter des prédictions extrêmes.
    lambda_home = max(0.15, min(lambda_home, 4.0))
    lambda_away = max(0.15, min(lambda_away, 4.0))

    home_probs = poisson_distribution(lambda_home, 10)
    away_probs = poisson_distribution(lambda_away, 10)

    p_home = 0.0
    p_draw = 0.0
    p_away = 0.0
    p_over25 = 0.0
    p_over35 = 0.0
    p_btts = 0.0
    score_probs = []

    for hg, ph in enumerate(home_probs):
        for ag, pa in enumerate(away_probs):
            probability = ph * pa
            score_probs.append((hg, ag, probability))

            if hg > ag:
                p_home += probability
            elif hg == ag:
                p_draw += probability
            else:
                p_away += probability

            if hg + ag > 2.5:
                p_over25 += probability

            if hg + ag > 3.5:
                p_over35 += probability

            if hg > 0 and ag > 0:
                p_btts += probability

    p_home = min(1.0, p_home)
    p_draw = min(1.0, p_draw)
    p_away = min(1.0, p_away)
    p_over25 = min(1.0, p_over25)
    p_over35 = min(1.0, p_over35)
    p_btts = min(1.0, p_btts)

    top_scores = sorted(
        score_probs,
        key=lambda item: item[2],
        reverse=True,
    )[:3]

    confidence = "Bonne" if len(home_all) >= 7 and len(away_all) >= 7 else "Moyenne"

    markets = [
        ("1", p_home),
        ("N", p_draw),
        ("2", p_away),
        ("1X", p_home + p_draw),
        ("X2", p_draw + p_away),
        ("12", p_home + p_away),
        ("Plus de 2,5 buts", p_over25),
        ("Moins de 2,5 buts", 1 - p_over25),
        ("Plus de 3,5 buts", p_over35),
        ("Moins de 3,5 buts", 1 - p_over35),
        ("Les deux équipes marquent : oui", p_btts),
        ("Les deux équipes marquent : non", 1 - p_btts),
    ]

    return {
        "match": match,
        "ready": True,
        "home_name": home.get("name", "?"),
        "away_name": away.get("name", "?"),
        "home_crest": home.get("crest"),
        "away_crest": away.get("crest"),
        "competition": match.get("_competition_name", ""),
        "competition_code": competition_code,
        "date": parse_date(match.get("utcDate")),
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "p_home": p_home,
        "p_draw": p_draw,
        "p_away": p_away,
        "p_1x": p_home + p_draw,
        "p_x2": p_draw + p_away,
        "p_12": p_home + p_away,
        "p_over25": p_over25,
        "p_under25": 1 - p_over25,
        "p_over35": p_over35,
        "p_under35": 1 - p_over35,
        "p_btts": p_btts,
        "p_no_btts": 1 - p_btts,
        "top_scores": top_scores,
        "markets": sorted(markets, key=lambda item: item[1], reverse=True),
        "confidence": confidence,
        "games_home": len(home_all),
        "games_away": len(away_all),
    }


# ------------------------------------------------------------
# AFFICHAGE DES MATCHS
# ------------------------------------------------------------

def display_match_card(match, prediction=None):
    date_match = parse_date(match.get("utcDate"))
    date_label = date_match.strftime("%d/%m/%Y à %H:%M") if date_match else "Horaire inconnu"

    home = match.get("homeTeam", {}).get("name", "?")
    away = match.get("awayTeam", {}).get("name", "?")
    competition = match.get("_competition_name", "Compétition")
    status = match.get("status", "")

    score = match.get("score", {}).get("fullTime", {})
    score_home = score.get("home")
    score_away = score.get("away")

    if status == "FINISHED" and score_home is not None and score_away is not None:
        status_text = f"Terminé : {score_home} - {score_away}"
    elif status == "IN_PLAY":
        status_text = "EN DIRECT"
    elif status == "PAUSED":
        status_text = "Mi-temps"
    elif status == "POSTPONED":
        status_text = "Reporté"
    else:
        status_text = date_label

    st.markdown(
        f"""
        <div class="match-card">
            <div class="match-league">{competition}</div>
            <div class="match-teams">{home} <span style="color:#75edb1">VS</span> {away}</div>
            <div class="match-meta">{status_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if prediction and prediction.get("ready"):
        cols = st.columns(3)

        with cols[0]:
            st.markdown(
                f'<div class="probability"><strong>{percent(prediction["p_home"])}</strong><small>Victoire domicile</small></div>',
                unsafe_allow_html=True,
            )

        with cols[1]:
            st.markdown(
                f'<div class="probability"><strong>{percent(prediction["p_draw"])}</strong><small>Match nul</small></div>',
                unsafe_allow_html=True,
            )

        with cols[2]:
            st.markdown(
                f'<div class="probability"><strong>{percent(prediction["p_away"])}</strong><small>Victoire extérieur</small></div>',
                unsafe_allow_html=True,
            )

        best = prediction["markets"][0]
        scores = ", ".join(
            f"{h}-{a} ({percent(p)})"
            for h, a, p in prediction["top_scores"]
        )

        st.caption(
            f"Meilleure probabilité mathématique : {best[0]} — "
            f"{percent(best[1])}. Scores possibles : {scores}. "
            f"Confiance des données : {prediction['confidence']}."
        )


# ------------------------------------------------------------
# STATISTIQUES DES PARIS VIRTUELS
# ------------------------------------------------------------

settled_bets = [bet for bet in bets if is_settled(bet)]
pending_bets = [bet for bet in bets if not is_settled(bet)]
won_bets = [bet for bet in settled_bets if bet_status(bet) == "WON"]
lost_bets = [bet for bet in settled_bets if bet_status(bet) == "LOST"]

total_profit = sum(bet_profit(bet) for bet in settled_bets)
initial_bankroll = number(state.get("initial_bankroll", 20))
current_bankroll = number(state.get("bankroll", initial_bankroll))
win_rate = len(won_bets) / len(settled_bets) if settled_bets else 0.0


def bets_dataframe(items):
    rows = []

    for bet in items:
        dt = bet_date(bet)
        rows.append({
            "Date": dt.strftime("%d/%m/%Y") if dt else "—",
            "Match": match_name(bet),
            "Compétition": competition_name(bet),
            "Marché": bet_market(bet),
            "Cote": bet_odds(bet),
            "Probabilité": percent(bet_probability(bet)),
            "Mise virtuelle": money(bet.get("stake", 0)),
            "Statut": bet_status(bet),
            "Résultat": bet.get("result", "—"),
            "Profit": money(bet_profit(bet)),
        })

    return pd.DataFrame(rows)


# ------------------------------------------------------------
# EN-TÊTE ET NAVIGATION
# ------------------------------------------------------------

st.markdown("""
<div class="hero">
    <div class="hero-title">⚽ FOOT AI PRO</div>
    <div class="hero-sub">
        FOOTBALL LIVE · ANALYSE STATISTIQUE · PRONOSTICS IA
    </div>
    <div class="pill">● MOTEUR POISSON · MODE VIRTUEL</div>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("## ⚽ FOOT AI PRO")
    st.caption("Tableau de bord premium")

    page = st.radio(
        "Navigation",
        [
            "🏠 Accueil",
            "📅 Matchs",
            "🧠 Analyse IA",
            "🎯 Classement",
            "💶 Mes paris",
        ],
        label_visibility="collapsed",
    )

    st.divider()
    st.markdown("### 🏆 Compétitions")

    selected_codes = []

    for code, name in COMPETITIONS.items():
        if st.checkbox(name, value=True, key=f"competition_{code}"):
            selected_codes.append(code)

    st.divider()
    st.markdown("### 📆 Période")

    days_ahead = st.selectbox(
        "Matchs à afficher",
        options=[0, 1, 3, 7],
        index=2,
        format_func=lambda x: {
            0: "Aujourd'hui uniquement",
            1: "Aujourd'hui et demain",
            3: "3 prochains jours",
            7: "7 prochains jours",
        }[x],
    )

    st.caption("Les données de match sont mises en cache pendant 6 heures.")

    if st.button("🔄 Actualiser les données", use_container_width=True):
        fetch_competition_matches.clear()
        st.rerun()


# ------------------------------------------------------------
# CHARGEMENT DES DONNÉES
# ------------------------------------------------------------

need_matches = page != "💶 Mes paris"

all_matches = []
api_errors = []
successful_competitions = 0
predictions = []

if need_matches and selected_codes:
    with st.spinner("Chargement des matchs et analyse statistique..."):
        all_matches, api_errors, successful_competitions = fetch_all_matches(
            selected_codes,
            days_ahead=max(days_ahead, 1),
        )

        history = finished_matches(all_matches)

        today = now_paris().date()
        end_date = today + timedelta(days=days_ahead)

        upcoming_matches = []

        for match in all_matches:
            dt = parse_date(match.get("utcDate"))

            if not dt:
                continue

            if dt.date() < today or dt.date() > end_date:
                continue

            if match.get("status") not in {
                "SCHEDULED", "TIMED", "IN_PLAY", "PAUSED"
            }:
                continue

            upcoming_matches.append(match)

        upcoming_matches.sort(
            key=lambda m: parse_date(m.get("utcDate")) or now_paris()
        )

        for match in upcoming_matches:
            prediction = predict_match(match, history)
            if prediction:
                predictions.append(prediction)

elif need_matches:
    st.warning("Sélectionne au moins une compétition dans le menu de gauche.")


# ------------------------------------------------------------
# ACCUEIL
# ------------------------------------------------------------

if page == "🏠 Accueil":
    st.subheader("Vue d'ensemble")

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        metric_card("Capital virtuel", money(current_bankroll), "Capital enregistré")

    with c2:
        metric_card("Paris en attente", str(len(pending_bets)), "Non encore réglés")

    with c3:
        metric_card("Paris terminés", str(len(settled_bets)), "Historique disponible")

    with c4:
        metric_card("Taux de réussite", percent(win_rate), "Paris terminés uniquement")

    st.markdown("### 📡 Football du jour")
    st.caption(
        f"{len(upcoming_matches)} match(s) à venir dans la période choisie."
    )

    if api_errors:
        with st.expander("Informations sur les données API"):
            for error in api_errors:
                st.warning(error)

    shown = 0

    for match in upcoming_matches[:8]:
        pred = next(
            (
                p for p in predictions
                if p.get("match", {}).get("id") == match.get("id")
            ),
            None,
        )
        display_match_card(match, pred)
        shown += 1

    if shown == 0:
        st.info(
            "Aucun match trouvé pour la période sélectionnée. "
            "Vérifie la clé API, les compétitions choisies et les droits "
            "de ton abonnement football-data.org."
        )

    st.markdown("### 📈 Derniers paris virtuels")

    if bets:
        df = bets_dataframe(bets[:10])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Aucun pari virtuel enregistré pour le moment.")


# ------------------------------------------------------------
# MATCHS
# ------------------------------------------------------------

elif page == "📅 Matchs":
    st.subheader("📅 Calendrier des matchs")

    if api_errors:
        with st.expander("Problèmes de chargement"):
            for error in api_errors:
                st.warning(error)

    if not upcoming_matches:
        st.info("Aucun match à afficher pour cette période.")
    else:
        st.caption(f"{len(upcoming_matches)} match(s) trouvé(s).")

        for match in upcoming_matches:
            pred = next(
                (
                    p for p in predictions
                    if p.get("match", {}).get("id") == match.get("id")
                ),
                None,
            )
            display_match_card(match, pred)


# ------------------------------------------------------------
# ANALYSE IA
# ------------------------------------------------------------

elif page == "🧠 Analyse IA":
    st.subheader("🧠 Analyse IA des matchs")
    st.caption(
        "Estimations statistiques calculées à partir des résultats récents "
        "disponibles. Ce ne sont pas des garanties."
    )

    ready_predictions = [
        p for p in predictions if p.get("ready")
    ]

    insufficient = [
        p for p in predictions if not p.get("ready")
    ]

    if api_errors:
        with st.expander("Informations API"):
            for error in api_errors:
                st.warning(error)

    if insufficient:
        st.info(
            f"{len(insufficient)} match(s) ne disposent pas d'assez "
            "d'historique exploitable pour produire une analyse."
        )

    if not ready_predictions:
        st.warning(
            "Aucune analyse fiable disponible. Cela peut venir du manque "
            "d'historique, des droits API ou d'une clé manquante."
        )
    else:
        ready_predictions.sort(
            key=lambda p: max(
                p["p_home"],
                p["p_draw"],
                p["p_away"],
                p["p_1x"],
                p["p_x2"],
                p["p_over25"],
                p["p_under25"],
                p["p_over35"],
                p["p_under35"],
                p["p_btts"],
                p["p_no_btts"],
            ),
            reverse=True,
        )

        st.markdown("### ⭐ Analyses disponibles")

        for pred in ready_predictions:
            match = pred["match"]
            date_match = pred.get("date")
            date_text = (
                date_match.strftime("%d/%m à %H:%M")
                if date_match else "Horaire inconnu"
            )

            with st.expander(
                f"{pred['home_name']} - {pred['away_name']} · {date_text}",
                expanded=False,
            ):
                st.markdown(
                    f"**Compétition :** {pred['competition']}"
                )

                a, b, c = st.columns(3)

                with a:
                    metric_card("Victoire domicile", percent(pred["p_home"]))

                with b:
                    metric_card("Match nul", percent(pred["p_draw"]))

                with c:
                    metric_card("Victoire extérieur", percent(pred["p_away"]))

                st.markdown("#### Marchés statistiques")

                market_rows = [
                    ("1", pred["p_home"]),
                    ("N", pred["p_draw"]),
                    ("2", pred["p_away"]),
                    ("1X", pred["p_1x"]),
                    ("X2", pred["p_x2"]),
                    ("12", pred["p_12"]),
                    ("Plus de 2,5 buts", pred["p_over25"]),
                    ("Moins de 2,5 buts", pred["p_under25"]),
                    ("Plus de 3,5 buts", pred["p_over35"]),
                    ("Moins de 3,5 buts", pred["p_under35"]),
                    ("Les deux équipes marquent : oui", pred["p_btts"]),
                    ("Les deux équipes marquent : non", pred["p_no_btts"]),
                ]

                market_rows.sort(key=lambda row: row[1], reverse=True)

                market_df = pd.DataFrame([
                    {
                        "Marché": name,
                        "Probabilité estimée": percent(prob),
                    }
                    for name, prob in market_rows
                ])

                st.dataframe(
                    market_df,
                    use_container_width=True,
                    hide_index=True,
                )

                st.markdown("#### 🎯 Scores exacts les plus probables")

                score_cols = st.columns(3)

                for idx, (hg, ag, prob) in enumerate(pred["top_scores"]):
                    with score_cols[idx]:
                        metric_card(
                            f"Score {idx + 1}",
                            f"{hg} - {ag}",
                            percent(prob),
                        )

                st.caption(
                    f"Espérance de buts : {pred['lambda_home']:.2f} "
                    f"pour {pred['home_name']} et "
                    f"{pred['lambda_away']:.2f} pour {pred['away_name']}. "
                    f"Données : confiance {pred['confidence']}."
                )

        st.markdown("### 🏆 Classement des probabilités")

        ranking_rows = []

        for pred in ready_predictions:
            for market, probability in pred["markets"]:
                ranking_rows.append({
                    "Match": f"{pred['home_name']} - {pred['away_name']}",
                    "Compétition": pred["competition"],
                    "Marché": market,
                    "Probabilité": probability,
                    "Confiance données": pred["confidence"],
                })

        ranking_rows.sort(
            key=lambda row: row["Probabilité"],
            reverse=True,
        )

        ranking_df = pd.DataFrame([
            {
                "Match": row["Match"],
                "Compétition": row["Compétition"],
                "Marché": row["Marché"],
                "Probabilité estimée": percent(row["Probabilité"]),
                "Confiance données": row["Confiance données"],
            }
            for row in ranking_rows[:30]
        ])

        st.dataframe(
            ranking_df,
            use_container_width=True,
            hide_index=True,
        )

        st.caption(
            "Les marchés Plus de 0,5 but et Plus de 1,5 but ne sont pas "
            "proposés dans ce classement. Les probabilités ne garantissent "
            "pas le résultat d'un match."
        )


# ------------------------------------------------------------
# CLASSEMENT
# ------------------------------------------------------------

elif page == "🎯 Classement":
    st.subheader("🎯 Classement des pronostics")

    ready_predictions = [
        p for p in predictions if p.get("ready")
    ]

    ranking_rows = []

    for pred in ready_predictions:
        markets = [
            ("1", pred["p_home"]),
            ("N", pred["p_draw"]),
            ("2", pred["p_away"]),
            ("1X", pred["p_1x"]),
            ("X2", pred["p_x2"]),
            ("12", pred["p_12"]),
            ("Moins de 2,5 buts", pred["p_under25"]),
            ("Plus de 2,5 buts", pred["p_over25"]),
            ("Moins de 3,5 buts", pred["p_under35"]),
            ("Plus de 3,5 buts", pred["p_over35"]),
            ("Les deux équipes marquent : oui", pred["p_btts"]),
            ("Les deux équipes marquent : non", pred["p_no_btts"]),
        ]

        for market, prob in markets:
            ranking_rows.append({
                "Match": f"{pred['home_name']} - {pred['away_name']}",
                "Compétition": pred["competition"],
                "Marché": market,
                "Probabilité": prob,
                "Confiance": pred["confidence"],
            })

    ranking_rows.sort(
        key=lambda row: row["Probabilité"],
        reverse=True,
    )

    if not ranking_rows:
        st.info("Aucun pronostic disponible avec les données actuelles.")
    else:
        for idx, row in enumerate(ranking_rows[:20], start=1):
            cols = st.columns([0.6, 3, 2, 1, 1.4])

            with cols[0]:
                st.markdown(f"**#{idx}**")

            with cols[1]:
                st.write(row["Match"])
                st.caption(row["Compétition"])

            with cols[2]:
                st.write(row["Marché"])

            with cols[3]:
                st.markdown(f"**{percent(row['Probabilité'])}**")

            with cols[4]:
                st.caption(row["Confiance"])

            st.divider()

        st.caption(
            "Le classement trie les probabilités mathématiques, pas les "
            "chances de gain garanties. Une probabilité élevée n'élimine "
            "pas le risque."
        )


# ------------------------------------------------------------
# MES PARIS VIRTUELS
# ------------------------------------------------------------

elif page == "💶 Mes paris":
    st.subheader("💶 Mes paris virtuels")

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        metric_card("Capital actuel", money(current_bankroll))

    with c2:
        metric_card("Capital initial", money(initial_bankroll))

    with c3:
        metric_card("Profit enregistré", money(total_profit))

    with c4:
        metric_card("Paris en attente", str(len(pending_bets)))

    st.caption(
        "Cette page lit data/bankroll.json. Elle ne modifie pas le fichier "
        "et ne place aucun pari réel."
    )

    if not state_loaded:
        st.warning(
            "Le fichier data/bankroll.json est absent ou illisible. "
            "Les valeurs affichées peuvent être des valeurs par défaut."
        )

    if not bets:
        st.info("Aucun pari enregistré dans data/bankroll.json.")
    else:
        filter_status = st.selectbox(
            "Filtrer les paris",
            [
                "Tous",
                "En attente",
                "Gagnés",
                "Perdus",
                "Autres réglés",
            ],
        )

        if filter_status == "En attente":
            filtered_bets = [b for b in bets if not is_settled(b)]
        elif filter_status == "Gagnés":
            filtered_bets = [b for b in bets if bet_status(b) == "WON"]
        elif filter_status == "Perdus":
            filtered_bets = [b for b in bets if bet_status(b) == "LOST"]
        elif filter_status == "Autres réglés":
            filtered_bets = [
                b for b in bets
                if is_settled(b)
                and bet_status(b) not in {"WON", "LOST"}
            ]
        else:
            filtered_bets = bets

        df = bets_dataframe(filtered_bets)

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )

        st.download_button(
            "📥 Télécharger l'historique CSV",
            data=df.to_csv(index=False).encode("utf-8-sig"),
            file_name="foot_ai_pro_historique.csv",
            mime="text/csv",
            use_container_width=True,
        )

        st.markdown("### 📊 Résultats")

        r1, r2, r3 = st.columns(3)

        with r1:
            metric_card("Paris gagnés", str(len(won_bets)))

        with r2:
            metric_card("Paris perdus", str(len(lost_bets)))

        with r3:
            metric_card("Taux de réussite", percent(win_rate))


# ------------------------------------------------------------
# PIED DE PAGE
# ------------------------------------------------------------

st.divider()

st.caption(
    "FOOT AI PRO · Analyse statistique à but informatif · "
    "Simulation virtuelle uniquement · Les probabilités ne garantissent "
    "aucun résultat."
)