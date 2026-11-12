import os
import json
import math
import html
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import pandas as pd
import streamlit as st

# ============================================================
# FOOT AI PRO ULTIMATE — VERSION AGRESSIVE NIVEAU 2
# Analyse statistique football : Poisson + forme + domicile/extérieur
# API : football-data.org v4
#
# IMPORTANT :
# - Ce fichier app.py ne modifie JAMAIS bot.py.
# - data/bankroll.json est consulté en LECTURE SEULE.
# - Les probabilités sont des estimations, jamais des garanties.
# - Aucun pari réel n'est placé par cette application.
# ============================================================

st.set_page_config(
    page_title="FOOT AI PRO ULTIMATE",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_BASE = "https://api.football-data.org/v4"
DATA_FILE = Path("data/bankroll.json")
TZ = ZoneInfo("Europe/Paris")

# Les six compétitions demandées sont conservées.
COMPETITIONS = {
    "FL1": "Ligue 1",
    "PL": "Premier League",
    "PD": "Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "CL": "Ligue des Champions",
    # Code standard utilisé pour la Ligue des Nations UEFA.
    # La disponibilité réelle dépend du catalogue et de l'abonnement API.
    "UNL": "Ligue des Nations",
}

# Niveau 2 : plus de sélections, sans gonfler artificiellement les probabilités.
RISK_MODE = "AGRESSIF — NIVEAU 2"
MIN_TEAM_MATCHES = 3
MIN_LEAGUE_MATCHES = 8
MAX_TEAM_HISTORY = 10
POISSON_MAX_GOALS = 10
COMBO_DEFAULT_MIN_PROB = 0.50
COMBO_MAX_ODDS = 3.00

try:
    from catboost import CatBoostClassifier
    CATBOOST_AVAILABLE = True
except Exception:
    CatBoostClassifier = None
    CATBOOST_AVAILABLE = False


# ----------------------------- DESIGN -----------------------------

st.markdown(
    """
    <style>
    .stApp {
        background:
        linear-gradient(rgba(3,12,20,.94),rgba(3,12,20,.96)),
        url("https://images.unsplash.com/photo-1522778119026-d647f0596c20?auto=format&fit=crop&w=2400&q=85");
        background-size:cover;
        background-position:center;
        background-attachment:fixed;
        color:#f2f7fa;
    }
    [data-testid="stSidebar"] {
        background:rgba(5,17,27,.98);
        border-right:1px solid #294c55;
    }
    h1,h2,h3 {color:#f4f8fa!important;}
    .hero {
        background:linear-gradient(120deg,rgba(12,48,54,.96),rgba(13,28,43,.96));
        border:1px solid #35666a;border-radius:18px;
        padding:20px;margin-bottom:18px;
    }
    .card {
        background:rgba(15,34,48,.96);
        border:1px solid #294653;border-radius:15px;
        padding:15px;margin:9px 0;
    }
    .muted {color:#a9bfca;font-size:12px;}
    .tag {
        display:inline-block;padding:4px 9px;border-radius:20px;
        background:#173e3d;color:#a5f0c6;font-size:12px;
        margin:2px 3px 2px 0;
    }
    div.stButton>button {
        border-radius:10px;border:1px solid #35605f;
        background:#153b3a;color:white;
    }
    @media(max-width:700px) {
        .stApp {background-attachment:scroll;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ----------------------------- OUTILS -----------------------------

def now_local():
    return datetime.now(TZ)


def parse_dt(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TZ)
        return parsed.astimezone(TZ)
    except (ValueError, TypeError):
        return None


def safe_float(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (ValueError, TypeError):
        return default


def pct(value):
    return f"{100 * safe_float(value):.1f} %".replace(".", ",")


def api_token():
    try:
        token = st.secrets.get("FOOTBALL_DATA_API_KEY", "")
        if token:
            return str(token).strip()
    except Exception:
        pass
    return os.getenv("FOOTBALL_DATA_API_KEY", "").strip()


def safe_name(value):
    return html.escape(str(value or "?"))


# ----------------------------- API FOOTBALL -----------------------------

@st.cache_data(ttl=1800, show_spinner=False)
def get_competition_matches(code, date_from, date_to, token):
    if not token:
        return [], "Clé FOOTBALL_DATA_API_KEY manquante."
    try:
        response = requests.get(
            f"{API_BASE}/competitions/{code}/matches",
            headers={"X-Auth-Token": token},
            params={"dateFrom": date_from, "dateTo": date_to},
            timeout=20,
        )
        if response.status_code == 401:
            return [], "Clé API invalide (401)."
        if response.status_code == 403:
            return [], "Accès refusé à cette compétition/période (403)."
        if response.status_code == 429:
            return [], "Limite API atteinte (429). Attends avant de réactualiser."
        response.raise_for_status()
        data = response.json()
        return data.get("matches", []), ""
    except requests.RequestException as exc:
        return [], f"Erreur réseau/API : {exc}"
    except (ValueError, TypeError):
        return [], "Réponse API illisible."


@st.cache_data(ttl=1800, show_spinner=False)
def load_all_matches(days_back, days_ahead, token):
    today = now_local().date()
    date_from = (today - timedelta(days=days_back)).isoformat()
    date_to = (today + timedelta(days=days_ahead)).isoformat()
    all_matches, errors = [], []

    for code, league_name in COMPETITIONS.items():
        rows, error = get_competition_matches(
            code, date_from, date_to, token
        )
        if error:
            errors.append(f"{league_name} : {error}")
        for row in rows:
            row["_code"] = code
            row["_league"] = league_name
            all_matches.append(row)

    unique = {}
    for match in all_matches:
        match_id = match.get("id")
        if match_id is not None:
            unique[match_id] = match
    return list(unique.values()), errors


# ----------------------------- HISTORIQUE -----------------------------

def build_history(matches):
    history = []
    for match in matches:
        if match.get("status") not in {"FINISHED", "AWARDED"}:
            continue
        score = (match.get("score") or {}).get("fullTime") or {}
        home_goals, away_goals = score.get("home"), score.get("away")
        if home_goals is None or away_goals is None:
            continue

        history.append({
            "home_id": (match.get("homeTeam") or {}).get("id"),
            "away_id": (match.get("awayTeam") or {}).get("id"),
            "home_name": (match.get("homeTeam") or {}).get("name", "?"),
            "away_name": (match.get("awayTeam") or {}).get("name", "?"),
            "hg": int(home_goals),
            "ag": int(away_goals),
            "code": match.get("_code"),
            "date": parse_dt(match.get("utcDate")),
        })

    history.sort(
        key=lambda item: item["date"] or datetime.min.replace(tzinfo=TZ)
    )
    return history


def team_records(history, team_id):
    rows = []
    for match in history:
        if match["home_id"] == team_id:
            rows.append({
                "scored": match["hg"],
                "conceded": match["ag"],
                "venue": "H",
                "date": match["date"],
            })
        elif match["away_id"] == team_id:
            rows.append({
                "scored": match["ag"],
                "conceded": match["hg"],
                "venue": "A",
                "date": match["date"],
            })
    return rows[-MAX_TEAM_HISTORY:]


def average(values, default):
    return sum(values) / len(values) if values else default


def weighted_recent(records, key, default):
    """Donne plus de poids aux derniers matchs, sans oublier l'échantillon."""
    if not records:
        return default
    values = [safe_float(row.get(key), default) for row in records[-5:]]
    weights = list(range(1, len(values) + 1))
    return sum(v * w for v, w in zip(values, weights)) / sum(weights)


def poisson_distribution(lam, maximum=POISSON_MAX_GOALS):
    lam = max(0.08, min(safe_float(lam, 1.2), 4.8))
    probabilities = [math.exp(-lam)]
    for goals in range(1, maximum + 1):
        probabilities.append(probabilities[-1] * lam / goals)
    total = sum(probabilities)
    return [p / total for p in probabilities] if total else probabilities


def features_for_match(home_id, away_id, history, code, fixture_date=None):
    # Point essentiel : seules les rencontres antérieures au match sont utilisées.
    prior = []
    for row in history:
        if row["code"] != code:
            continue
        if fixture_date and row["date"] and row["date"] >= fixture_date:
            continue
        prior.append(row)

    home_rows = team_records(prior, home_id)
    away_rows = team_records(prior, away_id)

    if (
        len(home_rows) < MIN_TEAM_MATCHES
        or len(away_rows) < MIN_TEAM_MATCHES
        or len(prior) < MIN_LEAGUE_MATCHES
    ):
        return None

    league_home = average([m["hg"] for m in prior], 1.45)
    league_away = average([m["ag"] for m in prior], 1.15)

    home_recent = home_rows[-5:]
    away_recent = away_rows[-5:]
    home_at_home = [r for r in home_rows if r["venue"] == "H"]
    away_away = [r for r in away_rows if r["venue"] == "A"]

    # Mélange forme récente, performance domicile/extérieur et moyenne de ligue.
    h_scored_recent = weighted_recent(home_recent, "scored", league_home)
    h_conceded_recent = weighted_recent(home_recent, "conceded", league_away)
    a_scored_recent = weighted_recent(away_recent, "scored", league_away)
    a_conceded_recent = weighted_recent(away_recent, "conceded", league_home)

    h_scored_home = average(
        [r["scored"] for r in home_at_home], h_scored_recent
    )
    h_conceded_home = average(
        [r["conceded"] for r in home_at_home], h_conceded_recent
    )
    a_scored_away = average(
        [r["scored"] for r in away_away], a_scored_recent
    )
    a_conceded_away = average(
        [r["conceded"] for r in away_away], a_conceded_recent
    )

    # Rétrécissement vers la moyenne de ligue pour limiter les extrêmes.
    home_sample = len(home_at_home)
    away_sample = len(away_away)
    home_weight = min(0.65, home_sample / (home_sample + 5))
    away_weight = min(0.65, away_sample / (away_sample + 5))

    home_attack = (
        home_weight * h_scored_home
        + (1 - home_weight) * (0.65 * h_scored_recent + 0.35 * league_home)
    )
    home_defence = (
        home_weight * h_conceded_home
        + (1 - home_weight) * (0.65 * h_conceded_recent + 0.35 * league_away)
    )
    away_attack = (
        away_weight * a_scored_away
        + (1 - away_weight) * (0.65 * a_scored_recent + 0.35 * league_away)
    )
    away_defence = (
        away_weight * a_conceded_away
        + (1 - away_weight) * (0.65 * a_conceded_recent + 0.35 * league_home)
    )

    home_lambda = league_home * (
        0.58 * home_attack / max(0.25, league_home)
        + 0.42 * away_defence / max(0.25, league_home)
    )
    away_lambda = league_away * (
        0.58 * away_attack / max(0.25, league_away)
        + 0.42 * home_defence / max(0.25, league_away)
    )

    # Léger avantage domicile, plafonné pour ne pas gonfler les favoris.
    home_lambda *= 1.04
    home_lambda = max(0.20, min(home_lambda, 3.8))
    away_lambda = max(0.20, min(away_lambda, 3.5))

    confidence = min(
        1.0,
        0.45
        + 0.035 * min(len(home_rows), 10)
        + 0.035 * min(len(away_rows), 10)
        + 0.002 * min(len(prior), 40),
    )

    return {
        "home_lambda": home_lambda,
        "away_lambda": away_lambda,
        "home_records": len(home_rows),
        "away_records": len(away_rows),
        "league_records": len(prior),
        "confidence": confidence,
    }


# ----------------------------- ANALYSE MATCH -----------------------------

def analyze_match(match, history):
    home = match.get("homeTeam") or {}
    away = match.get("awayTeam") or {}
    fixture_date = parse_dt(match.get("utcDate"))
    code = match.get("_code")

    features = features_for_match(
        home.get("id"), away.get("id"), history, code, fixture_date
    )
    if features is None:
        return {
            "ready": False,
            "reason": (
                "Historique insuffisant avant le match "
                "(minimum 3 matchs par équipe et 8 dans la compétition)."
            ),
        }

    ph = poisson_distribution(features["home_lambda"])
    pa = poisson_distribution(features["away_lambda"])

    p1 = px = p2 = 0.0
    over15 = over25 = over35 = btts = 0.0
    score_probabilities = []

    for home_goals, prob_home in enumerate(ph):
        for away_goals, prob_away in enumerate(pa):
            probability = prob_home * prob_away
            score_probabilities.append((home_goals, away_goals, probability))

            if home_goals > away_goals:
                p1 += probability
            elif home_goals == away_goals:
                px += probability
            else:
                p2 += probability

            if home_goals + away_goals >= 2:
                over15 += probability
            if home_goals + away_goals >= 3:
                over25 += probability
            if home_goals + away_goals >= 4:
                over35 += probability
            if home_goals > 0 and away_goals > 0:
                btts += probability

    # Normalisation de 1/N/2 pour éviter les écarts d'arrondi.
    total_outcomes = p1 + px + p2
    p1, px, p2 = (
        p1 / total_outcomes,
        px / total_outcomes,
        p2 / total_outcomes,
    )

    markets = [
        ("1", p1, "Résultat"),
        ("N", px, "Résultat"),
        ("2", p2, "Résultat"),
        ("Plus de 1,5 buts", over15, "Buts"),
        ("Moins de 1,5 buts", 1 - over15, "Buts"),
        ("Plus de 2,5 buts", over25, "Buts"),
        ("Moins de 2,5 buts", 1 - over25, "Buts"),
        ("Plus de 3,5 buts", over35, "Buts"),
        ("Moins de 3,5 buts", 1 - over35, "Buts"),
        ("Les deux équipes marquent : oui", btts, "BTTS"),
        ("Les deux équipes marquent : non", 1 - btts, "BTTS"),
    ]

    score_probabilities.sort(key=lambda item: item[2], reverse=True)
    best_outcome = max(
        [("1", p1), ("N", px), ("2", p2)],
        key=lambda item: item[1],
    )

    return {
        "ready": True,
        "home": home.get("name", "?"),
        "away": away.get("name", "?"),
        "league": match.get("_league", code),
        "date": fixture_date,
        "status": match.get("status", ""),
        "p1": p1,
        "px": px,
        "p2": p2,
        "markets": sorted(markets, key=lambda item: item[1], reverse=True),
        "scores": score_probabilities[:3],
        "lambda_home": features["home_lambda"],
        "lambda_away": features["away_lambda"],
        "confidence": features["confidence"],
        "home_records": features["home_records"],
        "away_records": features["away_records"],
        "league_records": features["league_records"],
        "best_outcome": best_outcome[0],
        "best_outcome_probability": best_outcome[1],
    }


# ----------------------------- BANKROLL EN LECTURE SEULE -----------------------------

def read_bankroll_read_only():
    if not DATA_FILE.exists():
        return {
            "initial_bankroll": 20.0,
            "bankroll": 20.0,
            "bets": [],
            "history": [],
            "_missing": True,
        }

    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Format JSON inattendu")

        initial = raw.get(
            "initial_bankroll",
            raw.get("starting_bankroll", raw.get("bankroll_initiale", 20.0)),
        )
        current = raw.get(
            "bankroll",
            raw.get("bankroll_actuelle", raw.get("capital_actuel", initial)),
        )
        raw["initial_bankroll"] = safe_float(initial, 20.0)
        raw["bankroll"] = safe_float(current, raw["initial_bankroll"])
        raw.setdefault("bets", raw.get("paris", []))
        raw.setdefault("history", raw.get("historique", []))
        raw["_missing"] = False
        return raw
    except Exception as exc:
        st.warning(
            "Impossible de lire data/bankroll.json. "
            "Aucune donnée n'a été modifiée."
        )
        return {
            "initial_bankroll": 20.0,
            "bankroll": 20.0,
            "bets": [],
            "history": [],
            "_error": str(exc),
        }


# ----------------------------- AFFICHAGE -----------------------------

def show_match_card(match, analysis):
    kickoff = parse_dt(match.get("utcDate"))
    status = match.get("status", "")
    if status == "IN_PLAY":
        time_label = "🔴 EN DIRECT"
    elif status == "PAUSED":
        time_label = "⏸️ MI-TEMPS"
    else:
        time_label = kickoff.strftime("%d/%m/%Y · %H:%M") if kickoff else "Horaire inconnu"

    home_name = safe_name((match.get("homeTeam") or {}).get("name"))
    away_name = safe_name((match.get("awayTeam") or {}).get("name"))
    league_name = safe_name(match.get("_league", ""))

    st.markdown(
        f"""
        <div class="card">
            <div class="muted">{league_name} · {time_label}</div>
            <h3>{home_name} — {away_name}</h3>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not analysis.get("ready"):
        st.warning(analysis.get("reason", "Analyse indisponible."))
        return

    col1, col2, col3 = st.columns(3)
    col1.metric("1 · Domicile", pct(analysis["p1"]))
    col2.metric("N · Nul", pct(analysis["px"]))
    col3.metric("2 · Extérieur", pct(analysis["p2"]))

    st.markdown(
        f'<span class="tag">Mode agressif niveau 2</span>'
        f'<span class="tag">Confiance données : {pct(analysis["confidence"])}</span>',
        unsafe_allow_html=True,
    )

    st.write(
        f"**Pronostic résultat : {analysis['best_outcome']}** "
        f"({pct(analysis['best_outcome_probability'])})"
    )
    st.write(
        f"**Buts estimés :** domicile {analysis['lambda_home']:.2f} "
        f"— extérieur {analysis['lambda_away']:.2f}"
    )
    st.write("**Autres marchés estimés :**")
    for market, probability, category in analysis["markets"]:
        if market in {"1", "N", "2"}:
            continue
        st.write(f"• {market} : **{pct(probability)}**")

    st.write(
        "**Scores exacts indicatifs :** "
        + " · ".join(
            f"{hg}-{ag} ({pct(prob)})"
            for hg, ag, prob in analysis["scores"]
        )
    )
    st.caption(
        f"Échantillon : {analysis['home_records']} matchs équipe domicile, "
        f"{analysis['away_records']} équipe extérieure, "
        f"{analysis['league_records']} matchs de compétition."
    )


# ----------------------------- EN-TÊTE / MENU -----------------------------

st.markdown(
    """
    <div class="hero">
        <h1>⚽ FOOT AI PRO ULTIMATE</h1>
        <div class="muted">
            Intelligence statistique football · Mode agressif niveau 2 ·
            Poisson avancé · Historique · Simulation virtuelle
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.title("⚽ FOOT AI PRO")
    st.markdown(f'<span class="tag">{RISK_MODE}</span>', unsafe_allow_html=True)

    page = st.radio(
        "Navigation",
        [
            "🏠 Accueil",
            "🔴 Football Live",
            "🧠 Analyse IA",
            "🏆 Classement IA",
            "🧾 Combinés IA",
            "⚽ Buteurs",
            "🎾 Tennis IA",
            "💶 Mes paris",
        ],
        label_visibility="collapsed",
    )

    days_ahead = st.selectbox(
        "Période des matchs",
        [1, 3, 7, 14],
        index=2,
    )

    if st.button("🔄 Actualiser les matchs", use_container_width=True):
        load_all_matches.clear()
        get_competition_matches.clear()
        st.rerun()

    st.caption("Compétitions suivies : 6")
    for league in COMPETITIONS.values():
        st.caption(f"• {league}")


# ----------------------------- CHARGEMENT CENTRAL -----------------------------

token = api_token()
if not token:
    st.error(
        "Clé API manquante. Dans Streamlit → Settings → Secrets, "
        "ajoute FOOTBALL_DATA_API_KEY."
    )

with st.spinner("Chargement des matchs et des résultats historiques…"):
    all_matches, api_errors = load_all_matches(180, days_ahead, token)

history = build_history(all_matches)
today = now_local().date()

upcoming = []
for match in all_matches:
    match_date = parse_dt(match.get("utcDate"))
    if (
        match.get("status") in {"SCHEDULED", "TIMED", "IN_PLAY", "PAUSED"}
        and match_date
        and today <= match_date.date() <= today + timedelta(days=days_ahead)
    ):
        upcoming.append(match)

upcoming.sort(
    key=lambda match: parse_dt(match.get("utcDate")) or now_local()
)

analyses = [(match, analyze_match(match, history)) for match in upcoming]
ready_analyses = [
    (match, analysis)
    for match, analysis in analyses
    if analysis.get("ready")
]


with st.expander("📡 État des données et du modèle", expanded=False):
    st.write(f"Matchs reçus : **{len(all_matches)}**")
    st.write(f"Matchs à venir/en direct : **{len(upcoming)}**")
    st.write(f"Résultats historiques reçus : **{len(history)}**")
    st.write(f"Matchs analysables : **{len(ready_analyses)}**")
    st.write("Mode de risque : **Agressif niveau 2**")
    st.write(
        "CatBoost : installé, mais non utilisé dans les probabilités "
        "de cette version afin d'éviter d'afficher un modèle non validé."
        if CATBOOST_AVAILABLE
        else "CatBoost non installé. Le moteur Poisson reste actif."
    )
    if api_errors:
        for error in api_errors:
            st.warning(error)


# ----------------------------- PAGES -----------------------------

if page == "🏠 Accueil":
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Matchs à venir", len(upcoming))
    c2.metric("Matchs analysables", len(ready_analyses))
    c3.metric("Historique chargé", len(history))
    c4.metric("Compétitions", len(COMPETITIONS))

    st.subheader("Prochains matchs")
    if not analyses:
        st.info(
            "Aucun match disponible sur la période. "
            "Vérifie la clé API ou augmente la période."
        )
    for match, analysis in analyses[:12]:
        show_match_card(match, analysis)


elif page == "🔴 Football Live":
    st.subheader("Football en direct")
    live = [
        (match, analysis)
        for match, analysis in analyses
        if match.get("status") in {"IN_PLAY", "PAUSED"}
    ]
    if not live:
        st.info("Aucun match en direct pour le moment.")
    for match, analysis in live:
        show_match_card(match, analysis)

    st.subheader("Calendrier à venir")
    scheduled = [
        (match, analysis)
        for match, analysis in analyses
        if match.get("status") in {"SCHEDULED", "TIMED"}
    ]
    for match, analysis in scheduled:
        show_match_card(match, analysis)


elif page == "🧠 Analyse IA":
    st.subheader("Analyse détaillée des rencontres")
    selected_league = st.selectbox(
        "Filtrer par compétition",
        ["Toutes"] + list(COMPETITIONS.values()),
    )
    filtered = [
        (match, analysis)
        for match, analysis in analyses
        if selected_league == "Toutes"
        or match.get("_league") == selected_league
    ]

    if not filtered:
        st.info("Aucun match ne correspond à ce filtre.")
    for match, analysis in filtered:
        show_match_card(match, analysis)


elif page == "🏆 Classement IA":
    st.subheader("Classement des pronostics")
    st.caption(
        "Le classement affiche les probabilités calculées. "
        "Le mode agressif assouplit la sélection, il ne gonfle pas les probabilités."
    )

    min_probability = st.slider(
        "Probabilité minimale à afficher",
        min_value=0.30,
        max_value=0.85,
        value=0.45,
        step=0.01,
    )
    ranking = []

    for match, analysis in ready_analyses:
        for market, probability, category in analysis["markets"]:
            if probability >= min_probability:
                # Pas de double chance : seuls 1/N/2 et les marchés buts/BTTS.
                ranking.append({
                    "Date": (
                        analysis["date"].strftime("%d/%m %H:%M")
                        if analysis["date"] else ""
                    ),
                    "Compétition": analysis["league"],
                    "Match": f'{analysis["home"]} - {analysis["away"]}',
                    "Marché": market,
                    "Probabilité": probability,
                    "Confiance données": analysis["confidence"],
                    "Catégorie": category,
                })

    ranking.sort(
        key=lambda row: (
            row["Probabilité"] * (0.75 + 0.25 * row["Confiance données"])
        ),
        reverse=True,
    )

    if ranking:
        table = pd.DataFrame(ranking)
        table["Probabilité"] = table["Probabilité"].map(pct)
        table["Confiance données"] = table["Confiance données"].map(pct)
        st.dataframe(table, use_container_width=True, hide_index=True)
    else:
        st.info("Aucun pronostic ne dépasse le seuil choisi.")


elif page == "🧾 Combinés IA":
    st.subheader("Combinés statistiques — mode agressif niveau 2")
    st.warning(
        "Les combinés sont des simulations. Les probabilités multipliées "
        "supposent une indépendance approximative entre les sélections."
    )

    min_probability = st.slider(
        "Probabilité minimale par sélection",
        min_value=0.30,
        max_value=0.85,
        value=COMBO_DEFAULT_MIN_PROB,
        step=0.01,
    )
    number_of_legs = st.selectbox(
        "Nombre de matchs",
        [2, 3, 4],
        index=1,
    )
    target_min_odds = st.number_input(
        "Cote théorique minimale",
        min_value=1.20,
        max_value=5.00,
        value=1.50,
        step=0.10,
    )
    target_max_odds = st.number_input(
        "Cote théorique maximale",
        min_value=1.50,
        max_value=8.00,
        value=COMBO_MAX_ODDS,
        step=0.10,
    )

    candidates = []
    for match, analysis in ready_analyses:
        # Un seul choix par rencontre : évite de combiner deux marchés du même match.
        options = [
            (market, probability, category)
            for market, probability, category in analysis["markets"]
            if probability >= min_probability
        ]
        if not options:
            continue

        # Pour favoriser un profil moins conservateur, on conserve aussi les choix
        # 1/N/2 dès qu'ils passent le seuil ; aucun double chance n'existe ici.
        market, probability, category = max(
            options,
            key=lambda item: item[1],
        )
        candidates.append({
            "match": f'{analysis["home"]} - {analysis["away"]}',
            "league": analysis["league"],
            "market": market,
            "probability": probability,
            "date": analysis["date"],
            "category": category,
        })

    candidates.sort(
        key=lambda item: item["probability"],
        reverse=True,
    )

    # Recherche de combinaisons distinctes dont la cote théorique est dans la plage.
    # On examine un nombre limité de combinaisons pour garder l'app rapide.
    best_combo = None
    best_score = -1.0
    pool = candidates[:18]

    if len(pool) >= number_of_legs:
        import itertools

        examined = 0
        for combo in itertools.combinations(pool, number_of_legs):
            examined += 1
            if examined > 2500:
                break
            match_names = [item["match"] for item in combo]
            if len(set(match_names)) != len(match_names):
                continue

            combined_probability = math.prod(
                item["probability"] for item in combo
            )
            theoretical_odds = (
                1 / combined_probability if combined_probability > 0 else 99
            )

            if target_min_odds <= theoretical_odds <= target_max_odds:
                # Priorité à la combinaison la plus probable dans la plage visée.
                if combined_probability > best_score:
                    best_score = combined_probability
                    best_combo = combo

    if best_combo:
        combined_probability = math.prod(
            item["probability"] for item in best_combo
        )
        theoretical_odds = 1 / combined_probability

        st.success("Combinaison trouvée dans la plage de cote théorique.")
        for item in best_combo:
            kickoff_text = (
                item["date"].strftime("%d/%m %H:%M")
                if item["date"] else "Date inconnue"
            )
            st.markdown(
                f"""
                <div class="card">
                    <div class="muted">{safe_name(item["league"])} · {kickoff_text}</div>
                    <b>{safe_name(item["match"])}</b><br>
                    {safe_name(item["market"])} — <b>{pct(item["probability"])}</b>
                </div>
                """,
                unsafe_allow_html=True,
            )

        col1, col2 = st.columns(2)
        col1.metric("Probabilité combinée estimée", pct(combined_probability))
        col2.metric("Cote théorique", f"{theoretical_odds:.2f}")
        st.caption(
            "Cote calculée à partir des probabilités du modèle (1 / probabilité). "
            "Ce n'est pas une cote de bookmaker."
        )
    else:
        st.info(
            "Aucune combinaison ne correspond à la plage choisie. "
            "Essaie de baisser légèrement le seuil ou d'élargir la cote maximale."
        )

    with st.expander("Voir les sélections candidates"):
        if candidates:
            candidate_table = pd.DataFrame([
                {
                    "Match": item["match"],
                    "Compétition": item["league"],
                    "Marché": item["market"],
                    "Probabilité": pct(item["probability"]),
                }
                for item in candidates
            ])
            st.dataframe(
                candidate_table,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Aucune sélection candidate disponible.")


elif page == "⚽ Buteurs":
    st.subheader("Analyse des buteurs")
    st.info(
        "La source football-data.org ne fournit pas systématiquement les "
        "compositions, les titularisations et les statistiques individuelles "
        "nécessaires pour calculer une probabilité de buteur."
    )
    st.write(
        "Je préfère ne pas inventer de joueurs ni afficher de faux pourcentages. "
        "Ce module pourra être activé avec une source joueurs/compositions autorisée."
    )


elif page == "🎾 Tennis IA":
    st.subheader("Tennis IA — ATP / WTA")
    st.info(
        "Le module tennis est volontairement laissé sans pronostics automatiques "
        "dans cette version : il faut une source fiable de calendrier et de "
        "résultats historiques ATP/WTA pour calculer un Elo sérieux."
    )
    st.write(
        "Un Elo initial fixé arbitrairement à 1500 ou calculé sur quelques jours "
        "de résultats ne serait pas assez fiable pour afficher des probabilités."
    )


elif page == "💶 Mes paris":
    st.subheader("Mes paris virtuels enregistrés")
    st.caption(
        "Lecture seule : cette page ne modifie jamais data/bankroll.json."
    )
    state = read_bankroll_read_only()
    bets = state.get("bets", [])

    c1, c2, c3 = st.columns(3)
    c1.metric(
        "Capital initial",
        f'{safe_float(state.get("initial_bankroll"), 20):.2f} €',
    )
    c2.metric(
        "Capital actuel enregistré",
        f'{safe_float(state.get("bankroll"), 20):.2f} €',
    )
    c3.metric("Paris enregistrés", len(bets))

    if state.get("_missing"):
        st.info(
            "Le fichier data/bankroll.json n'a pas été trouvé. "
            "Le capital affiché est une valeur indicative par défaut."
        )

    if bets:
        rows = []
        for bet in bets:
            home = bet.get(
                "home_team",
                bet.get("homeTeam", bet.get("equipe_domicile", "?")),
            )
            away = bet.get(
                "away_team",
                bet.get("awayTeam", bet.get("equipe_exterieure", "?")),
            )
            rows.append({
                "Date": str(
                    bet.get("date_match", bet.get("date", ""))
                )[:16],
                "Match": f"{home} - {away}",
                "Marché": bet.get(
                    "market",
                    bet.get("type", bet.get("marche", "Pronostic")),
                ),
                "Cote": safe_float(
                    bet.get("odds", bet.get("virtual_odds", bet.get("cote_virtuelle", 0)))
                ),
                "Mise": safe_float(bet.get("stake", bet.get("mise", 0))),
                "Statut": bet.get("status", bet.get("statut", "EN COURS")),
            })

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Aucun pari enregistré dans data/bankroll.json.")


# ----------------------------- PIED DE PAGE -----------------------------

st.divider()
st.caption(
    "FOOT AI PRO ULTIMATE — Mode agressif niveau 2. "
    "Les seuils sont plus souples afin de proposer davantage de pistes, "
    "mais les probabilités ne sont jamais artificiellement augmentées. "
    "Les estimations peuvent être inexactes et ne garantissent aucun résultat. "
    "Joue de manière responsable."
)
