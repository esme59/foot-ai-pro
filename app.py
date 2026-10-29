import os
import json
import math
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import pandas as pd
import streamlit as st

# ==========================================================
# IA CATBOOST — ACTIVATION SÉCURISÉE
# ==========================================================
try:
    from catboost import CatBoostClassifier
    CATBOOST_AVAILABLE = True
except ImportError:
    CATBOOST_AVAILABLE = False
    
# ==========================================================
# FOOT AI PRO ULTIMATE
# Interface + analyses statistiques + combinés virtuels
# API : football-data.org v4
# Ne modifie jamais bot.py ni bankroll.json
# ==========================================================

st.set_page_config(
    page_title="FOOT AI PRO ULTIMATE",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_BASE = "https://api.football-data.org/v4"
DATA_FILE = Path("data/bankroll.json")
TZ = ZoneInfo("Europe/Paris")

COMPETITIONS = {
    "FL1": "Ligue 1",
    "PL": "Premier League",
    "PD": "Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "CL": "Ligue des Champions",
}

# ----------------------------------------------------------
# DESIGN
# Seule modification : ajout de l'image de fond du stade.
# ----------------------------------------------------------

st.markdown("""
<style>

/* IMAGE DE FOND DU STADE */
.stApp {
    background:
        linear-gradient(
            rgba(5, 13, 22, 0.88),
            rgba(5, 13, 22, 0.91)
        ),
        url("https://images.unsplash.com/photo-1522778119026-d647f0596c20?auto=format&fit=crop&w=2400&q=85");

    background-size: cover;
    background-position: center center;
    background-repeat: no-repeat;
    background-attachment: fixed;

    color: #f0f5f8;
}

/* BARRE LATERALE */
[data-testid="stSidebar"] {
    background: rgba(7, 17, 27, 0.96);
    border-right: 1px solid #263c49;
}

[data-testid="stHeader"] {
    background: transparent;
}

/* TITRES */
h1, h2, h3 {
    color: #f5f8fa !important;
}

/* BANNIERE PRINCIPALE */
.hero {
    padding: 25px;
    border-radius: 22px;
    border: 1px solid #2a514b;
    background: linear-gradient(
        120deg,
        rgba(16, 46, 43, 0.94),
        rgba(17, 35, 51, 0.94) 65%,
        rgba(23, 43, 38, 0.94)
    );
    margin-bottom: 20px;
}

.hero-title {
    font-size: 31px;
    font-weight: 900;
    letter-spacing: 1px;
}

.hero-sub {
    color: #b4c9d1;
    margin-top: 6px;
    font-size: 13px;
}

.badge {
    display: inline-block;
    padding: 6px 11px;
    margin-top: 12px;
    border-radius: 20px;
    color: #83f2b9;
    background: #173b32;
    border: 1px solid #28624b;
    font-size: 11px;
    font-weight: 800;
}

/* CARTES */
.card {
    padding: 16px;
    border: 1px solid #273f4d;
    border-radius: 17px;
    background: linear-gradient(
        145deg,
        rgba(20, 38, 55, 0.94),
        rgba(13, 26, 39, 0.94)
    );
    margin-bottom: 12px;
}

.card-label {
    color: #9db4c1;
    font-size: 12px;
}

.card-value {
    font-size: 25px;
    font-weight: 900;
    margin-top: 7px;
}

.card-note {
    color: #7fe7ae;
    font-size: 11px;
    margin-top: 5px;
}

.match-title {
    font-size: 18px;
    font-weight: 800;
    margin: 7px 0;
}

.league {
    color: #7fe7ae;
    font-size: 12px;
    font-weight: 800;
}

.muted {
    color: #a3b7c2;
    font-size: 12px;
}

.green {
    color: #7fe7ae;
    font-weight: 800;
}

/* BOUTONS */
div.stButton > button {
    border-radius: 10px;
    border: 1px solid #315b67;
    background: rgba(21, 52, 64, 0.96);
    color: white;
    font-weight: 700;
}

div.stButton > button:hover {
    border-color: #7fe7ae;
    color: #7fe7ae;
}

/* ONGLETS */
div[data-testid="stTabs"] button {
    border-radius: 9px;
}

hr {
    border-color: #243946;
}

/* TABLEAUX */
[data-testid="stDataFrame"] {
    border-radius: 12px;
    overflow: hidden;
}

/* MOBILE */
@media (max-width: 700px) {
    .hero {
        padding: 18px;
    }

    .hero-title {
        font-size: 24px;
    }

    .card-value {
        font-size: 21px;
    }

    .stApp {
        background-attachment: scroll;
    }
}

</style>
""", unsafe_allow_html=True)


# ----------------------------------------------------------
# UTILITAIRES
# ----------------------------------------------------------

def now_local():
    return datetime.now(TZ)


def parse_datetime(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ)
    except (ValueError, TypeError):
        return None


def num(value, default=0.0):
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def euro(value):
    return f"{num(value):.2f} €".replace(".", ",")


def pct(value):
    return f"{num(value) * 100:.1f} %".replace(".", ",")


def card(label, value, note=""):
    st.markdown(
        f"""
        <div class="card">
            <div class="card-label">{label}</div>
            <div class="card-value">{value}</div>
            <div class="card-note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def status_of(bet):
    return str(bet.get("status", "PENDING")).upper()


def settled(bet):
    return status_of(bet) in {
        "WON", "LOST", "VOID", "CANCELLED",
        "CANCELED", "REMBOURSE"
    }


def bet_match_name(bet):
    home = bet.get("home_team", bet.get("homeTeam", "?"))
    away = bet.get("away_team", bet.get("awayTeam", "?"))
    return f"{home} - {away}"


def bet_market(bet):
    return str(bet.get("market", bet.get("type", "Pronostic")))


def bet_odds(bet):
    return num(bet.get("odds", bet.get("virtual_odds", 0)))


def bet_probability(bet):
    value = num(bet.get("probability", 0))
    return value / 100 if value > 1 else value


def bet_profit(bet):
    if bet.get("profit") is not None:
        return num(bet.get("profit"))

    stake = num(bet.get("stake", 0))
    odds = bet_odds(bet)

    if status_of(bet) == "WON":
        return stake * (odds - 1)
    if status_of(bet) == "LOST":
        return -stake
    return 0.0


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
            raw = json.load(f)

        if not isinstance(raw, dict):
            return default, False

        initial = raw.get(
            "initial_bankroll",
            raw.get("starting_bankroll", raw.get("bankroll_initiale", 20)),
        )

        current = raw.get(
            "bankroll",
            raw.get("bankroll_actuelle", raw.get("capital", initial)),
        )

        bets = raw.get("bets", raw.get("paris", []))
        history = raw.get("history", raw.get("historique", []))

        raw["initial_bankroll"] = num(initial, 20)
        raw["bankroll"] = num(current, num(initial, 20))
        raw["bets"] = bets if isinstance(bets, list) else []
        raw["history"] = history if isinstance(history, list) else []

        return raw, True

    except (OSError, ValueError, TypeError):
        return default, False


state, state_loaded = load_state()
bets = state["bets"]


# ----------------------------------------------------------
# API
# ----------------------------------------------------------

def api_key():
    try:
        key = st.secrets.get("FOOTBALL_DATA_API_KEY", "")
        if key:
            return str(key).strip()
    except Exception:
        pass

    return os.getenv("FOOTBALL_DATA_API_KEY", "").strip()


@st.cache_data(ttl=21600, show_spinner=False)
def get_competition_matches(code, date_from, date_to, token):
    if not token:
        return {
            "ok": False,
            "error": "Clé API manquante.",
            "matches": [],
        }

    try:
        response = requests.get(
            f"{API_BASE}/competitions/{code}/matches",
            headers={"X-Auth-Token": token},
            params={
                "dateFrom": date_from,
                "dateTo": date_to,
            },
            timeout=20,
        )

        if response.status_code == 429:
            return {
                "ok": False,
                "error": "Limite API atteinte. Attends avant de réessayer.",
                "matches": [],
            }

        if response.status_code == 403:
            return {
                "ok": False,
                "error": "Compétition ou période non autorisée par ton abonnement.",
                "matches": [],
            }

        if response.status_code == 401:
            return {
                "ok": False,
                "error": "Clé API invalide.",
                "matches": [],
            }

        response.raise_for_status()
        data = response.json()

        return {
            "ok": True,
            "error": "",
            "matches": data.get("matches", []),
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
            "error": "Réponse API illisible.",
            "matches": [],
        }


def load_matches(codes, days_ahead):
    token = api_key()

    if not token:
        return [], [
            "Clé API manquante : vérifie FOOTBALL_DATA_API_KEY."
        ], 0

    today = now_local().date()

    date_from = (today - timedelta(days=180)).isoformat()
    date_to = (
        today + timedelta(days=max(1, days_ahead))
    ).isoformat()

    matches = []
    errors = []
    successful = 0

    for code in codes:
        result = get_competition_matches(
            code,
            date_from,
            date_to,
            token,
        )

        if result["ok"]:
            successful += 1

            for match in result["matches"]:
                item = dict(match)
                item["_code"] = code
                item["_league"] = COMPETITIONS.get(code, code)
                matches.append(item)

        else:
            errors.append(
                f"{COMPETITIONS.get(code, code)} : {result['error']}"
            )

    unique = {}

    for match in matches:
        if match.get("id") is not None:
            unique[match["id"]] = match

    return list(unique.values()), errors, successful


# ----------------------------------------------------------
# HISTORIQUE ET MODELE POISSON
# ----------------------------------------------------------

def build_history(matches):
    history = []

    for match in matches:
        if match.get("status") not in {"FINISHED", "AWARDED"}:
            continue

        score = match.get("score", {}).get("fullTime", {})

        hg = score.get("home")
        ag = score.get("away")

        if hg is None or ag is None:
            continue

        home = match.get("homeTeam", {})
        away = match.get("awayTeam", {})

        history.append({
            "home_id": home.get("id"),
            "away_id": away.get("id"),
            "home_name": home.get("name", "?"),
            "away_name": away.get("name", "?"),
            "hg": int(hg),
            "ag": int(ag),
            "code": match.get("_code"),
            "date": parse_datetime(match.get("utcDate")),
        })

    return history


def poisson(lam, maximum=10):
    lam = max(0.05, min(float(lam), 5.0))

    probs = [math.exp(-lam)]

    for goals in range(1, maximum + 1):
        probs.append(probs[-1] * lam / goals)

    total = sum(probs)

    return [p / total for p in probs] if total else probs


def average(values, default):
    return sum(values) / len(values) if values else default


def team_records(history, team_id):
    records = []

    for match in history:
        if match["home_id"] == team_id:
            records.append({
                "venue": "HOME",
                "scored": match["hg"],
                "conceded": match["ag"],
                "date": match["date"],
            })

        elif match["away_id"] == team_id:
            records.append({
                "venue": "AWAY",
                "scored": match["ag"],
                "conceded": match["hg"],
                "date": match["date"],
            })

    records.sort(
        key=lambda x: x["date"] or datetime.min.replace(tzinfo=TZ)
    )

    return records[-10:]


def analyze_match(match, history):
    home = match.get("homeTeam", {})
    away = match.get("awayTeam", {})

    home_id = home.get("id")
    away_id = away.get("id")
    code = match.get("_code")

    if home_id is None or away_id is None:
        return {
            "ready": False,
            "reason": "Identifiant équipe manquant.",
        }

    # Historique limité à la compétition du match.
    league_history = [
        m for m in history
        if m.get("code") == code
        and m.get("hg") is not None
        and m.get("ag") is not None
    ]

    if len(league_history) < 8:
        return {
            "ready": False,
            "reason": "Historique insuffisant pour cette compétition.",
        }

    # Moyennes de buts du championnat.
    league_home = average(
        [m["hg"] for m in league_history],
        1.45,
    )
    league_away = average(
        [m["ag"] for m in league_history],
        1.15,
    )

    # Derniers matchs des deux équipes.
    home_records = team_records(league_history, home_id)
    away_records = team_records(league_history, away_id)

    if len(home_records) < 3 or len(away_records) < 3:
        return {
            "ready": False,
            "reason": (
                "Historique insuffisant pour l'une des équipes "
                "(minimum 3 matchs connus par équipe)."
            ),
        }

    # Les 5 derniers matchs, tous terrains confondus.
    home_recent = home_records[-5:]
    away_recent = away_records[-5:]

    # Performances au stade concerné.
    home_at_home = [
        r for r in home_records
        if r["venue"] == "HOME"
    ]
    away_away = [
        r for r in away_records
        if r["venue"] == "AWAY"
    ]

    # Moyennes récentes de buts marqués et encaissés.
    home_recent_scored = average(
        [r["scored"] for r in home_recent],
        league_home,
    )
    home_recent_conceded = average(
        [r["conceded"] for r in home_recent],
        league_away,
    )

    away_recent_scored = average(
        [r["scored"] for r in away_recent],
        league_away,
    )
    away_recent_conceded = average(
        [r["conceded"] for r in away_recent],
        league_home,
    )

    # Statistiques spécifiques domicile et extérieur.
    home_scored = average(
        [r["scored"] for r in home_at_home],
        home_recent_scored,
    )
    home_conceded = average(
        [r["conceded"] for r in home_at_home],
        home_recent_conceded,
    )

    away_scored = average(
        [r["scored"] for r in away_away],
        away_recent_scored,
    )
    away_conceded = average(
        [r["conceded"] for r in away_away],
        away_recent_conceded,
    )

    # Mélange entre forme récente et performances selon le terrain.
    # Les coefficients évitent de dépendre excessivement d'un seul match.
    home_attack_goals = (
        0.60 * home_scored
        + 0.40 * home_recent_scored
    )
    home_defence_goals = (
        0.60 * home_conceded
        + 0.40 * home_recent_conceded
    )

    away_attack_goals = (
        0.60 * away_scored
        + 0.40 * away_recent_scored
    )
    away_defence_goals = (
        0.60 * away_conceded
        + 0.40 * away_recent_conceded
    )

    # Ratios offensifs et défensifs.
    home_attack = (
        home_attack_goals / max(0.25, league_home)
    )
    home_defence = (
        home_defence_goals / max(0.25, league_away)
    )

    away_attack = (
        away_attack_goals / max(0.25, league_away)
    )
    away_defence = (
        away_defence_goals / max(0.25, league_home)
    )

    # Buts attendus : attaque d'une équipe contre défense adverse.
    lambda_home = league_home * (
        0.60 * home_attack
        + 0.40 * away_defence
    )

    lambda_away = league_away * (
        0.60 * away_attack
        + 0.40 * home_defence
    )

    # Limites de sécurité pour éviter des valeurs extrêmes.
    lambda_home = max(0.15, min(4.0, lambda_home))
    lambda_away = max(0.15, min(4.0, lambda_away))

    # Distribution de Poisson.
    prob_home = poisson(lambda_home)
    prob_away = poisson(lambda_away)

    p1 = 0.0
    px = 0.0
    p2 = 0.0
    over25 = 0.0
    over35 = 0.0
    btts = 0.0
    scores = []

    for hg, p_home in enumerate(prob_home):
        for ag, p_away in enumerate(prob_away):
            probability = p_home * p_away

            scores.append((hg, ag, probability))

            if hg > ag:
                p1 += probability
            elif hg == ag:
                px += probability
            else:
                p2 += probability

            if hg + ag >= 3:
                over25 += probability

            if hg + ag >= 4:
                over35 += probability

            if hg > 0 and ag > 0:
                btts += probability

    # Marchés autorisés pour les analyses.
    markets = [
        ("1", p1),
        ("N", px),
        ("2", p2),
        ("1X", p1 + px),
        ("X2", px + p2),
        ("12", p1 + p2),
        ("Plus de 2,5 buts", over25),
        ("Moins de 2,5 buts", 1 - over25),
        ("Plus de 3,5 buts", over35),
        ("Moins de 3,5 buts", 1 - over35),
        ("Les deux équipes marquent : oui", btts),
        ("Les deux équipes marquent : non", 1 - btts),
    ]

    scores.sort(
        key=lambda item: item[2],
        reverse=True,
    )

    # Niveau de données disponible.
    sample_size = min(
        len(home_records),
        len(away_records),
    )

    if sample_size >= 7:
        confidence = "Bonne"
    elif sample_size >= 5:
        confidence = "Moyenne"
    else:
        confidence = "Limitée"

    return {
        "ready": True,
        "match": match,
        "home": home.get("name", "?"),
        "away": away.get("name", "?"),
        "league": match.get("_league", ""),
        "code": code,
        "date": parse_datetime(match.get("utcDate")),
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "p1": p1,
        "px": px,
        "p2": p2,
        "p1x": p1 + px,
        "px2": px + p2,
        "p12": p1 + p2,
        "over25": over25,
        "under25": 1 - over25,
        "over35": over35,
        "under35": 1 - over35,
        "btts": btts,
        "no_btts": 1 - btts,
        "scores": scores[:3],
        "markets": sorted(
            markets,
            key=lambda item: item[1],
            reverse=True,
        ),
        "confidence": confidence,
        "home_games": len(home_records),
        "away_games": len(away_records),
    }


# ----------------------------------------------------------
# MATCHS ET PRÉDICTIONS
# ----------------------------------------------------------

def upcoming_for_period(matches, days_ahead):
    today = now_local().date()
    last_day = today + timedelta(days=days_ahead)

    result = []

    for match in matches:
        dt = parse_datetime(match.get("utcDate"))

        if not dt:
            continue

        if not today <= dt.date() <= last_day:
            continue

        if match.get("status") not in {
            "SCHEDULED",
            "TIMED",
            "IN_PLAY",
            "PAUSED",
        }:
            continue

        result.append(match)

    return sorted(
        result,
        key=lambda m: parse_datetime(m.get("utcDate")) or now_local(),
    )


def display_match(match, prediction=None):
    home = match.get("homeTeam", {}).get("name", "?")
    away = match.get("awayTeam", {}).get("name", "?")
    league = match.get("_league", "Compétition")

    dt = parse_datetime(match.get("utcDate"))
    status = match.get("status", "")

    if status == "IN_PLAY":
        time_label = "🔴 EN DIRECT"

    elif status == "PAUSED":
        time_label = "⏸️ Mi-temps"

    else:
        time_label = (
            dt.strftime("%d/%m/%Y · %H:%M")
            if dt else "Horaire inconnu"
        )

    home_crest = match.get("homeTeam", {}).get("crest", "")
    away_crest = match.get("awayTeam", {}).get("crest", "")

    home_logo = (
        f'<img src="{home_crest}" '
        'style="width:48px;height:48px;object-fit:contain;">'
        if home_crest else "⚽"
    )

    away_logo = (
        f'<img src="{away_crest}" '
        'style="width:48px;height:48px;object-fit:contain;">'
        if away_crest else "⚽"
    )

    st.markdown(
        f"""
        <div class="card">
            <div class="league">{league}</div>
            <div style="display:flex;align-items:center;
                        justify-content:space-around;gap:12px;
                        text-align:center;">
                <div style="flex:1;">
                    {home_logo}
                    <div class="match-title">{home}</div>
                </div>
                <span class="green">VS</span>
                <div style="flex:1;">
                    {away_logo}
                    <div class="match-title">{away}</div>
                </div>
            </div>
            <div class="muted">{time_label}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if prediction and prediction.get("ready"):
        cols = st.columns(3)

        values = [
            ("1 · Domicile", prediction["p1"]),
            ("N · Nul", prediction["px"]),
            ("2 · Extérieur", prediction["p2"]),
        ]

        for col, (label, value) in zip(cols, values):
            with col:
                card(label, pct(value))

        scores = " · ".join(
            f"{h}-{a} ({pct(p)})"
            for h, a, p in prediction["scores"]
        )

        st.caption(
            f"Scores les plus probables : {scores}. "
            f"Fiabilité des données : {prediction['confidence']}."
        )


def predictions_for_matches(matches, history):
    result = []

    for match in matches:
        analysis = analyze_match(match, history)
        analysis["match"] = match

        if analysis.get("ready"):
            result.append(analysis)

    return result

return result

# ----------------------------------------------------------

# IA CATBOOST — BASE DE PRÉPARATION

# ----------------------------------------------------------

def catboost_status():
"""Indique si CatBoost est disponible."""
if not CATBOOST_AVAILABLE:
return {
"available": False,
"message": "CatBoost n’est pas installé. Vérifie requirements.txt."
}

return {
    "available": True,
    "message": "CatBoost est installé. Le modèle doit encore être entraîné sur des données historiques."
}

# ----------------------------------------------------------

# BUTEURS DU JOUR — API-FOOTBALL

# ----------------------------------------------------------

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"


def api_football_key():
    try:
        key = st.secrets.get("API_FOOTBALL_KEY", "")
        if key:
            return str(key).strip()
    except Exception:
        pass

    return os.getenv("API_FOOTBALL_KEY", "").strip()


@st.cache_data(ttl=1800, show_spinner=False)
def get_api_football(endpoint, params_json, token):
    if not token:
        return {
            "ok": False,
            "error": "Clé API_FOOTBALL_KEY manquante.",
            "data": [],
        }

    try:
        params = json.loads(params_json)

        response = requests.get(
            f"{API_FOOTBALL_BASE}/{endpoint}",
            headers={"x-apisports-key": token},
            params=params,
            timeout=20,
        )

        if response.status_code in (401, 403):
            return {
                "ok": False,
                "error": "Clé invalide ou accès API non autorisé.",
                "data": [],
            }

        if response.status_code == 429:
            return {
                "ok": False,
                "error": "Limite de requêtes API atteinte.",
                "data": [],
            }

        response.raise_for_status()
        payload = response.json()

        return {
            "ok": True,
            "error": "",
            "data": payload.get("response", []),
        }

    except requests.RequestException:
        return {
            "ok": False,
            "error": "Impossible de contacter l'API-Football.",
            "data": [],
        }
    except (ValueError, TypeError):
        return {
            "ok": False,
            "error": "Réponse API-Football illisible.",
            "data": [],
        }


def calculer_probabilite_buteur(statistiques):
    games = statistiques.get("games", {})
    goals = statistiques.get("goals", {})

    appearances = num(games.get("appearences", 0))
    minutes = num(games.get("minutes", 0))
    total_goals = num(goals.get("total", 0))

    if appearances <= 0 or minutes <= 0:
        return 0.0

    # Estimation du taux de buts par 90 minutes.
    minutes_per_game = minutes / appearances
    goals_per_90 = total_goals / (minutes / 90)

    # Estimation prudente du temps de jeu attendu.
    expected_minutes = min(90.0, max(20.0, minutes_per_game))

    expected_goals = goals_per_90 * expected_minutes / 90

    # Probabilité indicative d'au moins un but.
    probability = 1 - math.exp(-max(0.0, expected_goals))

    return max(0.0, min(0.95, probability))


def charger_classement_buteurs(matches):
    token = api_football_key()

    if not token:
        return [], "Ajoute API_FOOTBALL_KEY dans les secrets."

    today = now_local().date().isoformat()

    # Les matchs du jour proviennent de l'API déjà utilisée par l'application.
    todays_matches = []

    for match in matches:
        dt = parse_datetime(match.get("utcDate"))

        if dt and dt.date().isoformat() == today:
            if match.get("status") in {"SCHEDULED", "TIMED"}:
                todays_matches.append(match)

    if not todays_matches:
        return [], (
            "Aucun match programmé aujourd'hui dans les compétitions "
            "sélectionnées. Vérifie aussi la période choisie."
        )

    fixtures_result = get_api_football(
        "fixtures",
        json.dumps({"date": today}),
        token,
    )

    if not fixtures_result["ok"]:
        return [], fixtures_result["error"]

    fixtures = fixtures_result["data"]
    classement = []
    seen_players = set()

    for match in todays_matches:
        home_name = match.get("homeTeam", {}).get("name", "")
        away_name = match.get("awayTeam", {}).get("name", "")

        fixture = None

        for item in fixtures:
            teams = item.get("teams", {})
            api_home = teams.get("home", {}).get("name", "")
            api_away = teams.get("away", {}).get("name", "")

            if (
                home_name.lower() in api_home.lower()
                or api_home.lower() in home_name.lower()
            ) and (
                away_name.lower() in api_away.lower()
                or api_away.lower() in away_name.lower()
            ):
                fixture = item
                break

        if not fixture:
            continue

        fixture_info = fixture.get("fixture", {})
        league_info = fixture.get("league", {})
        league_id = league_info.get("id")
        season = league_info.get("season")
        fixture_id = fixture_info.get("id")

        if not league_id or not season or not fixture_id:
            continue

        for side in ("home", "away"):
            team = fixture.get("teams", {}).get(side, {})
            team_id = team.get("id")
            team_name = team.get("name", "")

            if not team_id:
                continue

            players_result = get_api_football(
                "players",
                json.dumps({
                    "team": team_id,
                    "league": league_id,
                    "season": season,
                    "page": 1,
                }),
                token,
            )

            if not players_result["ok"]:
                continue

            for player_item in players_result["data"]:
                player = player_item.get("player", {})
                stats_list = player_item.get("statistics", [])

                if not stats_list:
                    continue

                stats = stats_list[0]
                probability = calculer_probabilite_buteur(stats)

                player_id = player.get("id")

                if not player_id or player_id in seen_players:
                    continue

                seen_players.add(player_id)

                games_info = stats.get("games", {})
                goals_info = stats.get("goals", {})

                classement.append({
                    "Joueur": player.get("name", "Inconnu"),
                    "Équipe": team_name,
                    "Match": f"{home_name} - {away_name}",
                    "Buts saison": int(num(goals_info.get("total", 0))),
                    "Titularisations": int(num(games_info.get("lineups", 0))),
                    "Minutes": int(num(games_info.get("minutes", 0))),
                    "Probabilité estimée": probability,
                })

    classement.sort(
        key=lambda item: item["Probabilité estimée"],
        reverse=True,
    )

    return classement, ""
    
# ----------------------------------------------------------
# 🎾 TENNIS IA — ATP + WTA
# Source de données publique ESPN
# Modèle Elo indicatif
# ----------------------------------------------------------

TENNIS_API_BASE = (
    "https://site.api.espn.com/apis/site/v2/sports/tennis"
)


@st.cache_data(ttl=1800, show_spinner=False)
def get_tennis_scoreboard(tour, date_range=None):
    """Récupère et extrait les matchs ATP et WTA depuis ESPN."""

    url = (
        "https://site.api.espn.com/apis/site/v2/"
        f"sports/tennis/{tour.lower()}/scoreboard"
    )

    try:
        today = now_local().date()
        events_by_id = {}

        # Recherche sur 15 jours, sauf si une période est fournie
        if date_range:
            dates_to_check = [date_range]
        else:
            dates_to_check = [
                (today + timedelta(days=offset)).strftime("%Y%m%d")
                for offset in range(-7, 8)
            ]

        for date_query in dates_to_check:
            response = requests.get(
                url,
                params={"dates": date_query},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()

            for tournament in data.get("events", []):
                tournament_name = (
                    tournament.get("name")
                    or tournament.get("shortName")
                    or "Tournoi de tennis"
                )

                # Format ESPN : les matchs sont parfois imbriqués
                # dans tournament -> groupings -> competitions.
                for grouping in tournament.get("groupings", []):
                    grouping_name = (
                        grouping.get("grouping", {}).get("displayName")
                        or ""
                    )

                    for competition in grouping.get("competitions", []):
                        if len(competition.get("competitors", [])) < 2:
                            continue

                        match_id = str(
                            competition.get("id")
                            or competition.get("uid")
                            or ""
                        )

                        if not match_id:
                            continue

                        # On conserve le format attendu par les
                        # fonctions déjà présentes dans l'application.
                        match = dict(competition)
                        match["id"] = match_id
                        match["name"] = tournament_name
                        match["shortName"] = (
                            f"{tournament_name} - {grouping_name}"
                            if grouping_name
                            else tournament_name
                        )
                        match["competitions"] = [
                            {
                                "competitors": competition.get(
                                    "competitors", []
                                )
                            }
                        ]

                        events_by_id[match_id] = match

                # Compatibilité avec les événements ESPN non imbriqués
                if tournament.get("competitions"):
                    for competition in tournament["competitions"]:
                        if len(competition.get("competitors", [])) < 2:
                            continue

                        match_id = str(competition.get("id") or "")
                        if not match_id:
                            continue

                        match = dict(competition)
                        match["id"] = match_id
                        match["name"] = tournament_name
                        match["competitions"] = [
                            {
                                "competitors": competition.get(
                                    "competitors", []
                                )
                            }
                        ]

                        events_by_id[match_id] = match

        return {
            "ok": True,
            "events": list(events_by_id.values()),
            "error": "",
        }

    except Exception as exc:
        return {
            "ok": False,
            "events": [],
            "error": f"Erreur ESPN {tour.upper()} : {exc}",
        }

def tennis_get_players(event):
    """Récupère les deux joueurs d'un événement ESPN."""

    competitions = event.get("competitions", [])

    if not competitions:
        return []

    competitors = competitions[0].get("competitors", [])
    players = []

    for competitor in competitors:
        athlete = competitor.get("athlete", {})

        if not isinstance(athlete, dict):
            athlete = {}

        name = (
            athlete.get("displayName")
            or athlete.get("fullName")
            or competitor.get("displayName")
            or competitor.get("name")
            or "Joueur inconnu"
        )

        player_id = (
            athlete.get("id")
            or competitor.get("id")
        )

        players.append({
            "id": str(player_id) if player_id else name,
            "name": name,
            "winner": competitor.get("winner", False),
        })

    return players


def tennis_event_status(event):
    """Renvoie l'état normalisé d'un match."""

    status = event.get("status", {})
    status_type = status.get("type", {})

    state = str(status_type.get("state", "")).lower()
    name = str(status_type.get("name", "")).upper()
    completed = bool(status_type.get("completed", False))

    if completed or state == "post" or "FINAL" in name:
        return "FINISHED"

    if state == "in" or "PROGRESS" in name:
        return "LIVE"

    return "UPCOMING"


def tennis_event_date(event):
    """Convertit la date en heure française."""

    return parse_datetime(event.get("date"))


def tennis_event_name(event):
    return (
        event.get("name")
        or event.get("shortName")
        or "Match de tennis"
    )


def tennis_collect_matches(events, tour):
    """Transforme les événements ESPN en matchs exploitables."""

    matches = []

    for event in events:
        players = tennis_get_players(event)

        if len(players) < 2:
            continue

        date = tennis_event_date(event)

        matches.append({
            "tour": tour.upper(),
            "event_id": str(event.get("id", "")),
            "tournament": tennis_event_name(event),
            "date": date,
            "status": tennis_event_status(event),
            "player1": players[0],
            "player2": players[1],
        })

    return matches


def tennis_update_elo(events, ratings, forms):
    """
    Met à jour les classements Elo à partir des matchs terminés.
    Les matchs sans vainqueur identifiable sont ignorés.
    """

    completed = []

    for event in events:
        if tennis_event_status(event) != "FINISHED":
            continue

        players = tennis_get_players(event)

        if len(players) < 2:
            continue

        winner_indices = [
            index
            for index, player in enumerate(players[:2])
            if player.get("winner") is True
        ]

        if len(winner_indices) != 1:
            continue

        date = tennis_event_date(event)

        completed.append({
            "date": date,
            "players": players[:2],
            "winner_index": winner_indices[0],
        })

    completed.sort(
        key=lambda item: (
            item["date"] or datetime.min.replace(tzinfo=TZ)
        )
    )

    for match in completed:
        player1 = match["players"][0]
        player2 = match["players"][1]

        id1 = player1["id"]
        id2 = player2["id"]

        rating1 = ratings.get(id1, 1500.0)
        rating2 = ratings.get(id2, 1500.0)

        expected1 = 1 / (
            1 + 10 ** ((rating2 - rating1) / 400)
        )

        expected2 = 1 - expected1

        if match["winner_index"] == 0:
            result1 = 1.0
            result2 = 0.0
        else:
            result1 = 0.0
            result2 = 1.0

        k_factor = 32

        ratings[id1] = (
            rating1 + k_factor * (result1 - expected1)
        )

        ratings[id2] = (
            rating2 + k_factor * (result2 - expected2)
        )

        forms.setdefault(id1, []).append(result1)
        forms.setdefault(id2, []).append(result2)

    return ratings, forms


def tennis_probability(rating1, rating2):
    """Probabilité Elo théorique de victoire du premier joueur."""

    difference = max(
        -1000,
        min(1000, rating2 - rating1),
    )

    return 1 / (1 + 10 ** (difference / 400))


def tennis_form_text(results):
    """Affiche les résultats récents disponibles."""

    recent = results[-5:]

    if not recent:
        return "Historique insuffisant"

    return " ".join(
        "V" if result == 1 else "D"
        for result in recent
    )


def tennis_prepare_analysis(matches, ratings, forms):
    """Prépare les probabilités des matchs à venir."""

    results = []

    for match in matches:
        if match["status"] not in {"UPCOMING", "LIVE"}:
            continue

        player1 = match["player1"]
        player2 = match["player2"]

        id1 = player1["id"]
        id2 = player2["id"]

        has_history1 = id1 in ratings and bool(forms.get(id1))
        has_history2 = id2 in ratings and bool(forms.get(id2))

        rating1 = ratings.get(id1, 1500.0)
        rating2 = ratings.get(id2, 1500.0)

        probability1 = tennis_probability(rating1, rating2)
        probability2 = 1 - probability1

        if has_history1 and has_history2:
            quality = "Historique disponible"
        elif has_history1 or has_history2:
            quality = "Historique partiel"
        else:
            quality = "Données insuffisantes"

        results.append({
            **match,
            "rating1": rating1,
            "rating2": rating2,
            "probability1": probability1,
            "probability2": probability2,
            "form1": tennis_form_text(forms.get(id1, [])),
            "form2": tennis_form_text(forms.get(id2, [])),
            "quality": quality,
            "has_history": has_history1 and has_history2,
        })

    return sorted(
        results,
        key=lambda item: (
            item["date"] or datetime.max.replace(tzinfo=TZ)
        ),
    )


def tennis_load_data():
    """Charge les matchs ATP et WTA et calcule les probabilités."""

    all_matches = []
    errors = []

    # Récupérer les matchs ATP et WTA
    for tour in ("atp", "wta"):
        response = get_tennis_scoreboard(tour)

        if not response.get("ok"):
            errors.append(
                response.get("error", f"Erreur {tour.upper()}")
            )
            continue

        events = response.get("events", [])

        all_matches.extend(
            tennis_collect_matches(events, tour)
        )

    analyses = []

    # Calculer les analyses pour chaque circuit
    for tour in ("ATP", "WTA"):
        tour_matches = [
            match for match in all_matches
            if match.get("tour") == tour
        ]

        # Initialisation des classements
        ratings_tour = {}
        forms_tour = {}

        # Récupérer les résultats terminés pour mettre à jour les Elo
        response = get_tennis_scoreboard(tour.lower())

        if response.get("ok"):
            ratings_tour, forms_tour = tennis_update_elo(
                response.get("events", []),
                ratings_tour,
                forms_tour,
            )

        # Calculer les probabilités des matchs
        analyses.extend(
            tennis_prepare_analysis(
                tour_matches,
                ratings_tour,
                forms_tour,
            )
        )

    if not all_matches:
        errors.append("Aucun match reçu depuis ESPN.")

    if all_matches and not analyses:
        errors.append(
            "Des matchs ont été reçus, mais aucun n'est actuellement "
            "considéré comme à venir ou en cours."
        )

    return analyses, errors
    
    
# ----------------------------------------------------------
# STATISTIQUES DES PARIS
# ----------------------------------------------------------

settled_bets = [b for b in bets if settled(b)]
pending_bets = [b for b in bets if not settled(b)]
won_bets = [b for b in bets if status_of(b) == "WON"]
lost_bets = [b for b in bets if status_of(b) == "LOST"]

initial_bankroll = num(state.get("initial_bankroll", 20))
current_bankroll = num(state.get("bankroll", initial_bankroll))

profit_total = sum(
    bet_profit(b) for b in settled_bets
)

win_rate = (
    len(won_bets) / len(settled_bets)
    if settled_bets else 0.0
)


# ----------------------------------------------------------
# NAVIGATION
# ----------------------------------------------------------

with st.sidebar:
    st.markdown("## ⚽ FOOT AI PRO")
    st.caption("ULTIMATE · Tableau de bord")

    page = st.radio(
        "Menu",
[
"🏠 Accueil",
"🔴 Football Live",
"🧠 Analyse IA",
"⚽ Buteurs du jour",
"🏆 Classement IA",
"🧾 Combinés IA",
"🎾 Tennis IA",
"💶 Mes paris",
],
        label_visibility="collapsed",
    )

    st.divider()
    st.markdown("### Compétitions")

    selected_codes = []

    for code, name in COMPETITIONS.items():
        if st.checkbox(
            name,
            value=True,
            key=f"league_{code}",
        ):
            selected_codes.append(code)

    st.divider()

    days_ahead = st.selectbox(
        "Période des matchs",
        [0, 1, 3, 7],
        index=2,
        format_func=lambda n: {
            0: "Aujourd'hui",
            1: "Aujourd'hui + demain",
            3: "3 prochains jours",
            7: "7 prochains jours",
        }[n],
    )

    if st.button(
        "🔄 Actualiser l'API",
        use_container_width=True,
    ):
        get_competition_matches.clear()
        st.rerun()

    st.caption("Cache API : 6 heures.")
    st.caption("Mode simulation : aucun pari réel.")


st.markdown("""
<div class="hero">
    <div class="hero-title">⚽ FOOT AI PRO ULTIMATE</div>
    <div class="hero-sub">
        FOOTBALL LIVE · ANALYSE IA · STATISTIQUES · COMBINÉS VIRTUELS
    </div>
    <div class="badge">● MOTEUR STATISTIQUE ACTIF</div>
</div>
""", unsafe_allow_html=True)


# ----------------------------------------------------------
# CHARGEMENT DES MATCHS
# ----------------------------------------------------------

matches = []
api_errors = []
upcoming = []
history = []
analyses = []

if page not in {"💶 Mes paris", "🎾 Tennis IA"}:
    if not selected_codes:
        st.warning("Sélectionne au moins une compétition.")

    else:
        with st.spinner(
            "Chargement des matchs et calcul des analyses..."
        ):
            matches, api_errors, _ = load_matches(
                selected_codes,
                max(days_ahead, 1),
            )

            history = build_history(matches)
            upcoming = upcoming_for_period(matches, days_ahead)

            analyses = predictions_for_matches(
                upcoming,
                history,
            )

    if api_errors:
        with st.expander("⚠️ Informations sur les données"):
            for error in api_errors:
                st.warning(error)


# ----------------------------------------------------------
# ACCUEIL
# ----------------------------------------------------------

if page == "🏠 Accueil":
    st.subheader("Vue d'ensemble")

    cols = st.columns(4)

    with cols[0]:
        card(
            "Capital virtuel",
            euro(current_bankroll),
            "Capital enregistré",
        )

    with cols[1]:
        card(
            "Matchs à venir",
            str(len(upcoming)),
            "Période sélectionnée",
        )

    with cols[2]:
        card(
            "Paris en attente",
            str(len(pending_bets)),
            "Simulation",
        )

    with cols[3]:
        card(
            "Réussite historique",
            pct(win_rate),
            "Paris terminés",
        )

    st.markdown("### ⭐ Analyses disponibles")

    if analyses:
        best = sorted(
            analyses,
            key=lambda p: max(
                prob for _, prob in p["markets"]
            ),
            reverse=True,
        )

        for prediction in best[:5]:
            display_match(
                prediction["match"],
                prediction,
            )

    elif upcoming:
        st.info(
            "Les matchs sont disponibles, mais l'historique ne permet "
            "pas encore de produire suffisamment d'analyses."
        )

    else:
        st.info("Aucun match trouvé pour la période choisie.")

    st.markdown("### 📈 Derniers paris virtuels")

    if bets:
        rows = []

        for bet in bets[:10]:
            rows.append({
                "Match": bet_match_name(bet),
                "Marché": bet_market(bet),
                "Cote": bet_odds(bet),
                "Statut": status_of(bet),
                "Profit": euro(bet_profit(bet)),
            })

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
        )

    else:
        st.info("Aucun pari enregistré dans l'historique.")


# ----------------------------------------------------------
# FOOTBALL LIVE
# ----------------------------------------------------------

elif page == "🔴 Football Live":
    st.subheader("🔴 Football Live")

    st.caption(
        "Les scores dépendent des informations fournies par l'API."
    )

    live_matches = [
        m for m in matches
        if m.get("status") in {"IN_PLAY", "PAUSED"}
    ]

    if live_matches:
        st.markdown("### En cours")

        for match in live_matches:
            score = match.get("score", {}).get("fullTime", {})

            home_score = score.get("home")
            away_score = score.get("away")

            st.markdown(
                f"""
                <div class="card">
                    <div class="league">
                        {match.get('_league', '')}
                    </div>
                    <div class="match-title">
                        {match.get('homeTeam', {}).get('name', '?')}
                        <span class="green">
                            {home_score} - {away_score}
                        </span>
                        {match.get('awayTeam', {}).get('name', '?')}
                    </div>
                    <div class="muted">🔴 Match en cours</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    else:
        st.info(
            "Aucun match en direct dans les compétitions sélectionnées."
        )

    st.markdown("### 📅 Prochains matchs")

    for match in upcoming:
        pred = next(
            (
                p for p in analyses
                if p["match"].get("id") == match.get("id")
            ),
            None,
        )

        display_match(match, pred)


# ----------------------------------------------------------
# ANALYSE IA
# ----------------------------------------------------------

elif page == "🧠 Analyse IA":
    st.subheader("🧠 Analyse IA")

    st.caption(
        "Probabilités calculées à partir des résultats historiques "
        "disponibles. Ce modèle n'est pas une garantie de résultat."
    )

    if not analyses:
        st.warning(
            "Aucune analyse disponible. Vérifie la clé API, les "
            "compétitions sélectionnées et la quantité d'historique accessible."
        )

    for prediction in analyses:
        with st.expander(
            f"{prediction['home']} - {prediction['away']}",
            expanded=False,
        ):
            st.write(f"**Compétition :** {prediction['league']}")

            c1, c2, c3 = st.columns(3)

            with c1:
                card("Victoire domicile", pct(prediction["p1"]))

            with c2:
                card("Match nul", pct(prediction["px"]))

            with c3:
                card("Victoire extérieur", pct(prediction["p2"]))

            st.markdown("#### Marchés statistiques")

            market_rows = [
                {
                    "Marché": name,
                    "Probabilité estimée": pct(prob),
                }
                for name, prob in prediction["markets"]
            ]

            st.dataframe(
                pd.DataFrame(market_rows),
                use_container_width=True,
                hide_index=True,
            )

            st.markdown("#### Scores exacts les plus probables")

            score_cols = st.columns(3)

            for index, (hg, ag, probability) in enumerate(
                prediction["scores"][:3]
            ):
                with score_cols[index]:
                    card(
                        f"Score {index + 1}",
                        f"{hg} - {ag}",
                        pct(probability),
                    )

            st.markdown("#### Indicateurs des équipes")

            left, right = st.columns(2)

            with left:
                card(
                    f"Buts attendus · {prediction['home']}",
                    f"{prediction['lambda_home']:.2f}",
                    f"{prediction['home_games']} matchs historiques",
                )

            with right:
                card(
                    f"Buts attendus · {prediction['away']}",
                    f"{prediction['lambda_away']:.2f}",
                    f"{prediction['away_games']} matchs historiques",
                )

            st.caption(
                f"Qualité indicative de l'historique : "
                f"{prediction['confidence']}. "
                "Les blessures, compositions et cotes ne sont pas intégrées "
                "si elles ne sont pas disponibles via la source de données."
            )


# ----------------------------------------------------------
# BUTEURS DU JOUR
# ----------------------------------------------------------

elif page == "⚽ Buteurs du jour":
    st.subheader("⚽ Buteurs du jour")

    st.caption(
        "Estimations statistiques des chances de marquer. "
        "Les compositions officielles ne sont pas garanties."
    )

    if st.button("🔄 Actualiser les buteurs"):
        get_api_football.clear()
        st.rerun()

    with st.spinner("Analyse des statistiques des joueurs..."):
        classement_buteurs, erreur_buteurs = charger_classement_buteurs(
            matches
        )

    if erreur_buteurs:
        st.info(erreur_buteurs)

    elif not classement_buteurs:
        st.info(
            "Aucun joueur trouvé pour les matchs du jour. "
            "Vérifie les matchs disponibles et la clé API."
        )

    else:
        df = pd.DataFrame([
            {
                "Joueur": item["Joueur"],
                "Équipe": item["Équipe"],
                "Match": item["Match"],
                "Buts saison": item["Buts saison"],
                "Titularisations": item["Titularisations"],
                "Minutes": item["Minutes"],
                "Probabilité estimée": pct(
                    item["Probabilité estimée"]
                ),
            }
            for item in classement_buteurs[:30]
        ])

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )

        st.warning(
            "Ces pourcentages sont des estimations, pas des garanties. "
            "Ils ne prennent pas nécessairement en compte les blessures "
            "ou les compositions officielles."
        )


# ----------------------------------------------------------
# CLASSEMENT IA
# ----------------------------------------------------------

elif page == "🏆 Classement IA":
    st.subheader("🏆 Classement des pronostics")

    rows = []

    for prediction in analyses:
        for market, probability in prediction["markets"]:
            rows.append({
                "Match": (
                    f"{prediction['home']} - {prediction['away']}"
                ),
                "Compétition": prediction["league"],
                "Marché": market,
                "Probabilité": probability,
                "Confiance": prediction["confidence"],
            })

    rows.sort(
        key=lambda x: x["Probabilité"],
        reverse=True,
    )

    if not rows:
        st.info("Aucun classement disponible.")

    else:
        minimum = st.slider(
            "Probabilité minimale affichée",
            min_value=40,
            max_value=95,
            value=60,
            step=5,
        )

        filtered = [
            r for r in rows
            if r["Probabilité"] >= minimum / 100
        ]

        if not filtered:
            st.info("Aucun marché ne correspond à ce seuil.")

        else:
            df = pd.DataFrame([
                {
                    "Match": r["Match"],
                    "Compétition": r["Compétition"],
                    "Marché": r["Marché"],
                    "Probabilité": pct(r["Probabilité"]),
                    "Confiance des données": r["Confiance"],
                }
                for r in filtered[:50]
            ])

            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
            )

    st.caption(
        "Un pourcentage élevé n'implique pas un pari rentable : les cotes "
        "et les marges des bookmakers ne sont pas prises en compte."
    )


# ----------------------------------------------------------
# COMBINÉS IA
# ----------------------------------------------------------

elif page == "🧾 Combinés IA":
    st.subheader("🧾 Combinés IA")

    st.caption(
        "Suggestions théoriques : aucune cote de bookmaker n'est inventée."
    )

    if not analyses:
        st.warning(
            "Il faut disposer d'analyses de matchs pour créer des combinés."
        )

    else:
        count = st.selectbox(
            "Nombre de sélections",
            [2, 3, 4],
            index=0,
        )

        target_low, target_high = st.slider(
            "Cote théorique totale",
            min_value=1.2,
            max_value=8.0,
            value=(1.5, 2.0),
            step=0.1,
        )

        min_probability = st.slider(
            "Probabilité minimale par sélection",
            min_value=45,
            max_value=90,
            value=60,
            step=5,
        ) / 100

        # Logique des combinés conservée.
        candidates = []

        allowed_markets = {
            "1", "N", "2", "1X", "X2", "12",
            "Plus de 2,5 buts",
            "Moins de 2,5 buts",
            "Plus de 3,5 buts",
            "Moins de 3,5 buts",
            "Les deux équipes marquent : oui",
            "Les deux équipes marquent : non",
        }

        for prediction in analyses:
            for market, probability in prediction["markets"]:
                if market not in allowed_markets:
                    continue

                if probability < min_probability:
                    continue

                # Cote équitable indicative, pas une cote réelle.
                fair_odds = (
                    1 / probability if probability > 0 else 99
                )

                candidates.append({
                    "match_id": prediction["match"].get("id"),
                    "match": (
                        f"{prediction['home']} - {prediction['away']}"
                    ),
                    "league": prediction["league"],
                    "market": market,
                    "probability": probability,
                    "fair_odds": fair_odds,
                })

        candidates.sort(
            key=lambda x: x["probability"],
            reverse=True,
        )

        combinations = []
        seen = set()

        def build_combos(start, chosen):
            if len(combinations) >= 30:
                return

            if len(chosen) == count:
                odds = math.prod(
                    item["fair_odds"] for item in chosen
                )

                if target_low <= odds <= target_high:
                    key = tuple(
                        (item["match_id"], item["market"])
                        for item in chosen
                    )

                    if key not in seen:
                        seen.add(key)

                        combinations.append({
                            "items": list(chosen),
                            "odds": odds,
                            "probability": math.prod(
                                item["probability"]
                                for item in chosen
                            ),
                        })

                return

            for index in range(start, len(candidates)):
                item = candidates[index]

                if any(
                    chosen_item["match_id"] == item["match_id"]
                    for chosen_item in chosen
                ):
                    continue

                build_combos(
                    index + 1,
                    chosen + [item],
                )

                if len(combinations) >= 30:
                    return

        # Limiter la recherche pour ne pas surcharger Streamlit.
        build_combos(0, candidates[:18])

        if not combinations:
            st.info(
                "Aucun combiné ne correspond à ces paramètres. Essaie de "
                "réduire le nombre de sélections, le seuil de probabilité "
                "ou d'élargir la fourchette de cote théorique."
            )

        else:
            combinations.sort(
                key=lambda c: c["probability"],
                reverse=True,
            )

            st.warning(
                "Les cotes affichées sont des cotes équitables théoriques "
                "(1 / probabilité), pas des cotes réelles de bookmaker. "
                "Les probabilités combinées supposent l'indépendance des "
                "sélections ; les résultats de matchs différents ne sont "
                "pas toujours indépendants."
            )

            for index, combo in enumerate(
                combinations[:10],
                start=1,
            ):
                with st.expander(
                    f"Combiné {index} · "
                    f"Cote théorique {combo['odds']:.2f} · "
                    f"Probabilité indicative "
                    f"{pct(combo['probability'])}",
                    expanded=index == 1,
                ):
                    for item in combo["items"]:
                        st.write(
                            f"• **{item['match']}** — "
                            f"{item['market']} "
                            f"({pct(item['probability'])})"
                        )

                    st.caption(
                        "Simulation uniquement. Cette estimation ne tient "
                        "pas compte de la marge d'un bookmaker."
                    )


# ----------------------------------------------------------
# MES PARIS VIRTUELS
# ----------------------------------------------------------

elif page == "💶 Mes paris":
    st.subheader("💶 Mes paris virtuels")

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        card(
            "Capital actuel",
            euro(current_bankroll),
        )

    with c2:
        card(
            "Capital initial",
            euro(initial_bankroll),
        )

    with c3:
        card(
            "Profit enregistré",
            euro(profit_total),
        )

    with c4:
        card(
            "Paris en attente",
            str(len(pending_bets)),
        )

    st.caption(
        "Cette rubrique lit data/bankroll.json sans le modifier."
    )

    if not state_loaded:
        st.warning(
            "Le fichier data/bankroll.json est absent ou illisible. "
            "Les valeurs affichées peuvent être des valeurs par défaut."
        )

    if not bets:
        st.info("Aucun pari enregistré.")

    else:
        filter_status = st.selectbox(
            "Filtrer l'historique",
            [
                "Tous",
                "En attente",
                "Gagnés",
                "Perdus",
                "Autres réglés",
            ],
        )

        if filter_status == "En attente":
            filtered = [
                b for b in bets
                if not settled(b)
            ]

        elif filter_status == "Gagnés":
            filtered = [
                b for b in bets
                if status_of(b) == "WON"
            ]

        elif filter_status == "Perdus":
            filtered = [
                b for b in bets
                if status_of(b) == "LOST"
            ]

        elif filter_status == "Autres réglés":
            filtered = [
                b for b in bets
                if settled(b)
                and status_of(b) not in {"WON", "LOST"}
            ]

        else:
            filtered = bets

        rows = []

        for bet in filtered:
            rows.append({
                "Match": bet_match_name(bet),
                "Compétition": bet.get("competition_name", ""),
                "Marché": bet_market(bet),
                "Cote": bet_odds(bet),
                "Probabilité": pct(bet_probability(bet)),
                "Mise virtuelle": euro(bet.get("stake", 0)),
                "Statut": status_of(bet),
                "Résultat": bet.get("result", "—"),
                "Profit": euro(bet_profit(bet)),
            })

        df = pd.DataFrame(rows)

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

        r1, r2, r3 = st.columns(3)

        with r1:
            card(
                "Paris gagnés",
                str(len(won_bets)),
            )

        with r2:
            card(
                "Paris perdus",
                str(len(lost_bets)),
            )

        with r3:
            card(
                "Taux de réussite",
                pct(win_rate),
            )


# ----------------------------------------------------------
# 🎾 PAGE TENNIS IA
# ----------------------------------------------------------

elif page == "🎾 Tennis IA":
    st.subheader("🎾 Tennis IA — ATP & WTA")

    st.caption(
        "Analyses indicatives fondées sur un modèle Elo et les "
        "résultats disponibles. Les probabilités ne garantissent "
        "pas l'issue d'un match."
    )

    if st.button("🔄 Actualiser le tennis"):
        get_tennis_scoreboard.clear()
        st.rerun()

    with st.spinner(
        "Chargement des matchs ATP et WTA et calcul des estimations..."
    ):
        tennis_analyses, tennis_errors = tennis_load_data()

    for error in tennis_errors:
        st.warning(error)

    if not tennis_analyses:
        st.info(
            "Aucun match tennis exploitable n'a été trouvé. "
            "Le calendrier peut être vide ou la source indisponible."
        )

    else:
        tour_filter = st.radio(
            "Circuit",
            ["ATP + WTA", "ATP", "WTA"],
            horizontal=True,
        )

        filtered_tennis = [
            match for match in tennis_analyses
            if tour_filter == "ATP + WTA"
            or match["tour"] == tour_filter
        ]

        upcoming_tennis = [
            match for match in filtered_tennis
            if match["status"] == "UPCOMING"
        ]

        live_tennis = [
            match for match in filtered_tennis
            if match["status"] == "LIVE"
        ]

        col1, col2, col3 = st.columns(3)

        with col1:
            card(
                "Matchs à venir",
                str(len(upcoming_tennis)),
                "ATP et WTA",
            )

        with col2:
            card(
                "Matchs en direct",
                str(len(live_tennis)),
                "Selon les données disponibles",
            )

        with col3:
            card(
                "Circuits",
                "ATP + WTA",
                "Classements Elo séparés",
            )

        st.markdown("### 🔴 Matchs en direct")

        if not live_tennis:
            st.info("Aucun match en direct trouvé.")

        for match in live_tennis:
            with st.container(border=True):
                st.markdown(
                    f"**{match['tour']} · {match['tournament']}**"
                )

                st.markdown(
                    f"### {match['player1']['name']} — "
                    f"{match['player2']['name']}"
                )

                st.write(
                    f"Probabilité Elo indicative : "
                    f"{pct(match['probability1'])} / "
                    f"{pct(match['probability2'])}"
                )

                st.caption(
                    "Match en cours : ces pourcentages ne tiennent "
                    "pas compte du score en direct."
                )

        st.markdown("### 📅 Prochains matchs")

        if not upcoming_tennis:
            st.info("Aucun match à venir trouvé dans les données.")

        for match in upcoming_tennis:
            date_label = (
                match["date"].strftime("%d/%m/%Y · %H:%M")
                if match["date"]
                else "Horaire inconnu"
            )

            with st.container(border=True):
                st.markdown(
                    f"**{match['tour']} · {match['tournament']}**"
                )

                st.caption(date_label)

                c1, c2 = st.columns(2)

                with c1:
                    st.markdown(
                        f"### {match['player1']['name']}"
                    )

                    st.metric(
                        "Probabilité Elo",
                        pct(match["probability1"]),
                    )

                    st.write(
                        f"Classement Elo indicatif : "
                        f"{match['rating1']:.0f}"
                    )

                    st.caption(
                        f"Forme récente : {match['form1']}"
                    )

                with c2:
                    st.markdown(
                        f"### {match['player2']['name']}"
                    )

                    st.metric(
                        "Probabilité Elo",
                        pct(match["probability2"]),
                    )

                    st.write(
                        f"Classement Elo indicatif : "
                        f"{match['rating2']:.0f}"
                    )

                    st.caption(
                        f"Forme récente : {match['form2']}"
                    )

                if not match["has_history"]:
                    st.warning(
                        "Historique incomplet : les probabilités "
                        "sont trop fragiles pour être considérées "
                        "comme une analyse fiable."
                    )

                else:
                    favorite = (
                        match["player1"]["name"]
                        if match["probability1"] >= match["probability2"]
                        else match["player2"]["name"]
                    )

                    st.success(
                        f"Favori statistique indicatif : {favorite}"
                    )

        st.warning(
            "Limites : les données proviennent d'un scoreboard public "
            "qui peut changer ou manquer des matchs. Le modèle ne tient "
            "pas compte de la surface, des blessures, de la fatigue, "
            "du classement officiel ni du score en direct. "
            "Les probabilités sont des estimations, pas des garanties."
        )
        
# ----------------------------------------------------------
# PIED DE PAGE
# ----------------------------------------------------------

st.divider()

st.caption(
    "FOOT AI PRO ULTIMATE · Analyse statistique informative · "
    "Simulation virtuelle uniquement · Aucun résultat garanti."
)