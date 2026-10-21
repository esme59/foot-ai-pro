import os
import math
from datetime import datetime, date, timedelta

import requests
import streamlit as st

# =========================================================
# FOOT AI PRO — MOTEUR DE PRONOSTICS POISSON
# API : football-data.org v4
# =========================================================

st.set_page_config(
    page_title="FOOT AI PRO",
    page_icon="⚽",
    layout="wide",
)

API_BASE = "https://api.football-data.org/v4"

COMPETITIONS = {
    "France - Ligue 1": "FL1",
    "Angleterre - Premier League": "PL",
    "Espagne - Liga": "PD",
    "Allemagne - Bundesliga": "BL1",
    "Italie - Serie A": "SA",
    "Ligue des champions": "CL",
}

# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------

st.title("⚽ FOOT AI PRO")
st.caption("Analyse des matchs et probabilités individualisées")

api_key = st.secrets.get(
    "FOOTBALL_DATA_API_KEY",
    os.getenv("FOOTBALL_DATA_API_KEY", "")
)

if not api_key:
    st.error(
        "Clé API introuvable. Ajoute "
        "FOOTBALL_DATA_API_KEY dans les Secrets Streamlit."
    )
    st.stop()

HEADERS = {"X-Auth-Token": api_key}


# ---------------------------------------------------------
# API
# ---------------------------------------------------------

@st.cache_data(ttl=900, show_spinner=False)
def api_get(endpoint, params=None):
    try:
        response = requests.get(
            f"{API_BASE}/{endpoint.lstrip('/')}",
            headers=HEADERS,
            params=params,
            timeout=20,
        )

        if response.status_code == 429:
            st.warning("Limite API atteinte. Réessaie plus tard.")
            return {}

        if response.status_code == 403:
            return {"_error": "Accès refusé par l'API."}

        response.raise_for_status()
        return response.json()

    except requests.RequestException:
        return {}


def parse_date(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).date()
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------
# MATCHS
# ---------------------------------------------------------

@st.cache_data(ttl=900, show_spinner=False)
def get_matches(day_start, day_end, competition_codes):
    all_matches = []
    errors = []

    for code in competition_codes:
        data = api_get(
            f"competitions/{code}/matches",
            {
                "dateFrom": day_start,
                "dateTo": day_end,
            },
        )

        if data.get("_error"):
            errors.append(f"{code}: {data['_error']}")

        all_matches.extend(data.get("matches", []))

    # Élimine les doublons éventuels
    unique = {}

    for match in all_matches:
        unique[match.get("id")] = match

    return list(unique.values()), errors


# ---------------------------------------------------------
# HISTORIQUE DES ÉQUIPES
# ---------------------------------------------------------

@st.cache_data(ttl=1800, show_spinner=False)
def get_team_history(team_id):
    data = api_get(
        f"teams/{team_id}/matches",
        {
            "status": "FINISHED",
            "limit": 10,
        },
    )

    return data.get("matches", [])


def extract_team_stats(matches, team_id):
    """
    Calcule les statistiques récentes d'une équipe.
    Les matchs sont analysés du point de vue de cette équipe.
    """

    games = []

    for match in matches:
        home = match.get("homeTeam", {})
        away = match.get("awayTeam", {})
        score = match.get("score", {}).get("fullTime", {})

        home_id = home.get("id")
        away_id = away.get("id")

        hg = score.get("home")
        ag = score.get("away")

        if hg is None or ag is None:
            continue

        if home_id == team_id:
            gf, ga = hg, ag
            venue = "HOME"
        elif away_id == team_id:
            gf, ga = ag, hg
            venue = "AWAY"
        else:
            continue

        games.append({
            "gf": float(gf),
            "ga": float(ga),
            "venue": venue,
            "date": match.get("utcDate", ""),
        })

    games.sort(key=lambda g: g["date"], reverse=True)

    return games[:10]


def average(values, fallback):
    return sum(values) / len(values) if values else fallback


def weighted_average(values):
    """
    Les matchs récents pèsent davantage.
    Le premier élément correspond au match le plus récent.
    """

    if not values:
        return None

    weights = [0.85 ** i for i in range(len(values))]
    denominator = sum(weights)

    return sum(
        value * weight
        for value, weight in zip(values, weights)
    ) / denominator


def summarize_team(games):
    recent = games[:5]

    if not recent:
        return None

    goals_for = [g["gf"] for g in recent]
    goals_against = [g["ga"] for g in recent]

    home_games = [g for g in games if g["venue"] == "HOME"]
    away_games = [g for g in games if g["venue"] == "AWAY"]

    return {
        "played": len(recent),
        "gf": weighted_average(goals_for),
        "ga": weighted_average(goals_against),
        "home_gf": average(
            [g["gf"] for g in home_games], None
        ) if home_games else None,
        "home_ga": average(
            [g["ga"] for g in home_games], None
        ) if home_games else None,
        "away_gf": average(
            [g["gf"] for g in away_games], None
        ) if away_games else None,
        "away_ga": average(
            [g["ga"] for g in away_games], None
        ) if away_games else None,
        "points": sum(
            3 if g["gf"] > g["ga"]
            else 1 if g["gf"] == g["ga"]
            else 0
            for g in recent
        ),
        "form": "".join(
            "V" if g["gf"] > g["ga"]
            else "N" if g["gf"] == g["ga"]
            else "D"
            for g in recent
        ),
    }


# ---------------------------------------------------------
# MODÈLE DE POISSON
# ---------------------------------------------------------

def poisson_probability(goals, expected_goals):
    if expected_goals < 0:
        return 0.0

    return (
        math.exp(-expected_goals)
        * expected_goals ** goals
        / math.factorial(goals)
    )


def estimate_expected_goals(
    home_stats,
    away_stats,
    home_advantage=1.12,
):
    """
    Estimation individuelle des buts attendus.
    Les statistiques domicile/extérieur sont privilégiées
    lorsqu'elles sont disponibles.
    """

    home_attack = (
        0.65 * home_stats["gf"]
        + 0.35 * (
            home_stats["home_gf"]
            if home_stats["home_gf"] is not None
            else home_stats["gf"]
        )
    )

    home_defense = (
        0.65 * away_stats["ga"]
        + 0.35 * (
            away_stats["away_ga"]
            if away_stats["away_ga"] is not None
            else away_stats["ga"]
        )
    )

    away_attack = (
        0.65 * away_stats["gf"]
        + 0.35 * (
            away_stats["away_gf"]
            if away_stats["away_gf"] is not None
            else away_stats["gf"]
        )
    )

    away_defense = (
        0.65 * home_stats["ga"]
        + 0.35 * (
            home_stats["home_ga"]
            if home_stats["home_ga"] is not None
            else home_stats["ga"]
        )
    )

    # Mélange des forces offensives et défensives
    home_xg = (
        0.55 * home_attack
        + 0.45 * home_defense
    ) * home_advantage

    away_xg = (
        0.55 * away_attack
        + 0.45 * away_defense
    ) / home_advantage

    # Limites de sécurité
    home_xg = max(0.15, min(home_xg, 4.5))
    away_xg = max(0.15, min(away_xg, 4.5))

    return home_xg, away_xg


def calculate_probabilities(home_xg, away_xg):
    max_goals = 10

    home_probs = [
        poisson_probability(i, home_xg)
        for i in range(max_goals + 1)
    ]

    away_probs = [
        poisson_probability(i, away_xg)
        for i in range(max_goals + 1)
    ]

    matrix = [
        [
            home_probs[h] * away_probs[a]
            for a in range(max_goals + 1)
        ]
        for h in range(max_goals + 1)
    ]

    home_win = sum(
        matrix[h][a]
        for h in range(max_goals + 1)
        for a in range(max_goals + 1)
        if h > a
    )

    draw = sum(
        matrix[h][a]
        for h in range(max_goals + 1)
        for a in range(max_goals + 1)
        if h == a
    )

    away_win = sum(
        matrix[h][a]
        for h in range(max_goals + 1)
        for a in range(max_goals + 1)
        if h < a
    )

    over_15 = sum(
        matrix[h][a]
        for h in range(max_goals + 1)
        for a in range(max_goals + 1)
        if h + a >= 2
    )

    over_25 = sum(
        matrix[h][a]
        for h in range(max_goals + 1)
        for a in range(max_goals + 1)
        if h + a >= 3
    )

    over_35 = sum(
        matrix[h][a]
        for h in range(max_goals + 1)
        for a in range(max_goals + 1)
        if h + a >= 4
    )

    btts_yes = sum(
        matrix[h][a]
        for h in range(1, max_goals + 1)
        for a in range(1, max_goals + 1)
    )

    scores = []

    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            scores.append((
                h,
                a,
                matrix[h][a],
            ))

    scores.sort(key=lambda item: item[2], reverse=True)

    return {
        "home_win": home_win,
        "draw": draw,
        "away_win": away_win,
        "over_15": over_15,
        "over_25": over_25,
        "over_35": over_35,
        "under_25": 1 - over_25,
        "btts_yes": btts_yes,
        "btts_no": 1 - btts_yes,
        "scores": scores[:3],
        "home_xg": home_xg,
        "away_xg": away_xg,
    }


# ---------------------------------------------------------
# ANALYSE D'UN MATCH
# ---------------------------------------------------------

@st.cache_data(ttl=1800, show_spinner=False)
def analyze_match(home_id, away_id):
    home_history = get_team_history(home_id)
    away_history = get_team_history(away_id)

    home_games = extract_team_stats(home_history, home_id)
    away_games = extract_team_stats(away_history, away_id)

    home_stats = summarize_team(home_games)
    away_stats = summarize_team(away_games)

    if not home_stats or not away_stats:
        return None

    home_xg, away_xg = estimate_expected_goals(
        home_stats,
        away_stats,
    )

    probabilities = calculate_probabilities(
        home_xg,
        away_xg,
    )

    return {
        "home_stats": home_stats,
        "away_stats": away_stats,
        "probabilities": probabilities,
    }


# ---------------------------------------------------------
# AFFICHAGE
# ---------------------------------------------------------

def pct(value):
    return f"{value * 100:.1f} %"


def display_match(match):
    home = match.get("homeTeam", {})
    away = match.get("awayTeam", {})

    home_name = home.get("name", "Domicile")
    away_name = away.get("name", "Extérieur")

    match_date = match.get("utcDate", "")
    status = match.get("status", "")

    st.divider()

    st.subheader(f"⚽ {home_name} — {away_name}")

    st.caption(
        f"Date : {match_date.replace('T', ' ')[:16]} UTC"
        f"  |  Statut : {status}"
    )

    if not home.get("id") or not away.get("id"):
        st.warning("Identifiants des équipes indisponibles.")
        return

    with st.spinner("Analyse des statistiques des deux équipes..."):
        result = analyze_match(
            home["id"],
            away["id"],
        )

    if not result:
        st.warning(
            "Pas assez d'historique disponible pour calculer "
            "des probabilités fiables sur cette rencontre."
        )
        return

    p = result["probabilities"]
    hs = result["home_stats"]
    aws = result["away_stats"]

    col1, col2, col3 = st.columns(3)

    col1.metric("Victoire domicile", pct(p["home_win"]))
    col2.metric("Match nul", pct(p["draw"]))
    col3.metric("Victoire extérieur", pct(p["away_win"]))

    col1, col2, col3 = st.columns(3)

    col1.metric("+ 1,5 but", pct(p["over_15"]))
    col2.metric("+ 2,5 buts", pct(p["over_25"]))
    col3.metric("+ 3,5 buts", pct(p["over_35"]))

    col1, col2 = st.columns(2)

    col1.metric(
        "Les deux équipes marquent : OUI",
        pct(p["btts_yes"]),
    )

    col2.metric(
        "Les deux équipes marquent : NON",
        pct(p["btts_no"]),
    )

    st.markdown("### 🎯 Scores exacts les plus probables")

    score_cols = st.columns(3)

    for index, (hg, ag, probability) in enumerate(p["scores"]):
        score_cols[index].metric(
            f"Score {index + 1}",
            f"{hg} - {ag}",
            pct(probability),
        )

    st.markdown("### 📈 Statistiques récentes")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown(f"**{home_name}**")
        st.write(f"Forme récente : {hs['form']}")
        st.write(f"Buts moyens marqués : {hs['gf']:.2f}")
        st.write(f"Buts moyens encaissés : {hs['ga']:.2f}")
        st.write(f"Points sur les 5 derniers matchs : {hs['points']}/15")

    with col2:
        st.markdown(f"**{away_name}**")
        st.write(f"Forme récente : {aws['form']}")
        st.write(f"Buts moyens marqués : {aws['gf']:.2f}")
        st.write(f"Buts moyens encaissés : {aws['ga']:.2f}")
        st.write(f"Points sur les 5 derniers matchs : {aws['points']}/15")

    st.markdown("### 🔬 Buts attendus par le modèle")

    col1, col2 = st.columns(2)

    col1.metric(
        f"{home_name} — buts attendus",
        f"{p['home_xg']:.2f}",
    )

    col2.metric(
        f"{away_name} — buts attendus",
        f"{p['away_xg']:.2f}",
    )

    best_market = max(
        [
            ("Plus de 1,5 but", p["over_15"]),
            ("Plus de 2,5 buts", p["over_25"]),
            ("Plus de 3,5 buts", p["over_35"]),
            ("Les deux équipes marquent : oui", p["btts_yes"]),
            ("Victoire domicile", p["home_win"]),
            ("Match nul", p["draw"]),
            ("Victoire extérieur", p["away_win"]),
        ],
        key=lambda item: item[1],
    )

    st.info(
        f"Pronostic le plus probable selon ce modèle : "
        f"**{best_market[0]} — {pct(best_market[1])}**"
    )

    st.caption(
        "Probabilités théoriques calculées avec un modèle de "
        "Poisson et les résultats récents disponibles. "
        "Ce ne sont pas des garanties de résultat. "
        "Les statistiques des championnats et la qualité "
        "des historiques peuvent varier."
    )


# ---------------------------------------------------------
# INTERFACE
# ---------------------------------------------------------

today = date.today()

with st.sidebar:
    st.header("⚙️ Paramètres")

    selected_competitions = st.multiselect(
        "Championnats",
        list(COMPETITIONS.keys()),
        default=list(COMPETITIONS.keys()),
    )

    start_date = st.date_input(
        "Date de début",
        value=today,
    )

    end_date = st.date_input(
        "Date de fin",
        value=today,
    )

    show_finished = st.checkbox(
        "Afficher aussi les matchs terminés",
        value=False,
    )

    refresh = st.button(
        "🔄 Actualiser les données",
        use_container_width=True,
    )

if refresh:
    st.cache_data.clear()
    st.rerun()

if start_date > end_date:
    st.error("La date de début doit être antérieure à la date de fin.")
    st.stop()

codes = [
    COMPETITIONS[name]
    for name in selected_competitions
]

if not codes:
    st.warning("Sélectionne au moins un championnat.")
    st.stop()

with st.spinner("Récupération du calendrier des matchs..."):
    matches, errors = get_matches(
        start_date.isoformat(),
        end_date.isoformat(),
        tuple(codes),
    )

if errors:
    for error in errors:
        st.warning(error)

if not matches:
    st.warning(
        "Aucun match récupéré pour cette période. "
        "Vérifie les dates, les championnats et les accès "
        "autorisés par ton abonnement API."
    )
    st.stop()

if not show_finished:
    matches = [
        m for m in matches
        if m.get("status") not in (
            "FINISHED",
            "AWARDED",
            "CANCELLED",
        )
    ]

matches.sort(key=lambda m: m.get("utcDate", ""))

st.subheader(f"📅 {len(matches)} match(s) à analyser")

if st.button("🚀 Analyser tous les matchs"):
    st.session_state["analyze_all"] = True

if st.session_state.get("analyze_all", False):
    st.info(
        "L'analyse de nombreux matchs peut prendre du temps "
        "et consommer les requêtes autorisées par ton API."
    )

for match in matches:
    display_match(match)