import os
import math
from datetime import date, timedelta

import requests
import streamlit as st


# =====================================================
# CONFIGURATION
# =====================================================

st.set_page_config(
    page_title="FOOT AI PRO",
    page_icon="⚽",
    layout="wide",
)

API_BASE = "https://api.football-data.org/v4"

COMPETITIONS = {
    "🇫🇷 Ligue 1": "FL1",
    "🏴 Premier League": "PL",
    "🇪🇸 Liga": "PD",
    "🇩🇪 Bundesliga": "BL1",
    "🇮🇹 Serie A": "SA",
    "🏆 Ligue des Champions": "CL",
}

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 3rem;
    }
    div[data-testid="stMetric"] {
        background-color: rgba(128,128,128,0.08);
        border: 1px solid rgba(128,128,128,0.2);
        padding: 12px;
        border-radius: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# =====================================================
# CLÉ API
# =====================================================

def get_api_key():
    try:
        key = st.secrets.get("FOOTBALL_DATA_API_KEY", "")
        if key:
            return key
    except Exception:
        pass

    return os.environ.get("FOOTBALL_DATA_API_KEY", "")


# =====================================================
# REQUÊTES API
# =====================================================

def api_get(endpoint, params=None):
    key = get_api_key()

    if not key:
        raise RuntimeError(
            "Clé API manquante. Configure "
            "FOOTBALL_DATA_API_KEY dans Streamlit Secrets."
        )

    try:
        response = requests.get(
            API_BASE + endpoint,
            headers={"X-Auth-Token": key},
            params=params,
            timeout=20,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Connexion impossible : {exc}")

    if response.status_code == 429:
        raise RuntimeError(
            "Limite de requêtes atteinte. Réessaie plus tard."
        )

    if response.status_code == 403:
        raise RuntimeError(
            "Cette compétition n'est peut-être pas disponible "
            "avec ton abonnement API."
        )

    if response.status_code != 200:
        raise RuntimeError(
            f"Erreur API {response.status_code} : "
            f"{response.text[:200]}"
        )

    return response.json()


@st.cache_data(ttl=600, show_spinner=False)
def load_matches(competition_code, date_from, date_to):
    data = api_get(
        f"/competitions/{competition_code}/matches",
        {
            "dateFrom": date_from,
            "dateTo": date_to,
        },
    )

    return data.get("matches", [])


@st.cache_data(ttl=3600, show_spinner=False)
def load_team_history(team_id, before_date):
    data = api_get(
        f"/teams/{team_id}/matches",
        {
            "status": "FINISHED",
            "dateTo": before_date,
            "limit": 10,
        },
    )

    return data.get("matches", [])


# =====================================================
# FORME RÉCENTE
# =====================================================

def team_statistics(team_id, before_date):
    try:
        matches = load_team_history(team_id, before_date)
    except Exception:
        matches = []

    valid_matches = []

    for match in matches:
        score = match.get("score", {}).get("fullTime", {})

        if score.get("home") is None or score.get("away") is None:
            continue

        valid_matches.append(match)

    valid_matches.sort(
        key=lambda m: m.get("utcDate", ""),
        reverse=True,
    )

    valid_matches = valid_matches[:5]

    scored_goals = []
    conceded_goals = []
    points = []
    form = []

    for match in valid_matches:
        home_id = match.get("homeTeam", {}).get("id")
        away_id = match.get("awayTeam", {}).get("id")

        score = match["score"]["fullTime"]

        if team_id == home_id:
            scored = score["home"]
            conceded = score["away"]
        elif team_id == away_id:
            scored = score["away"]
            conceded = score["home"]
        else:
            continue

        scored_goals.append(scored)
        conceded_goals.append(conceded)

        if scored > conceded:
            points.append(3)
            form.append("V")
        elif scored == conceded:
            points.append(1)
            form.append("N")
        else:
            points.append(0)
            form.append("D")

    if not scored_goals:
        return {
            "scored": 1.25,
            "conceded": 1.25,
            "points": 1.0,
            "form": "Données indisponibles",
            "count": 0,
        }

    return {
        "scored": sum(scored_goals) / len(scored_goals),
        "conceded": sum(conceded_goals) / len(conceded_goals),
        "points": sum(points) / len(points),
        "form": " – ".join(form),
        "count": len(scored_goals),
    }


# =====================================================
# CALCUL DES PROBABILITÉS DE SCORE
# =====================================================

def poisson(k, expected):
    expected = max(0.01, expected)

    return (
        math.exp(-expected)
        * expected**k
        / math.factorial(k)
    )


def calculate_markets(expected_home, expected_away):
    max_goals = 10

    home_probs = [
        poisson(i, expected_home)
        for i in range(max_goals + 1)
    ]

    away_probs = [
        poisson(i, expected_away)
        for i in range(max_goals + 1)
    ]

    scores = []
    total_mass = 0.0

    home_win = 0.0
    draw = 0.0
    away_win = 0.0

    over05 = 0.0
    over15 = 0.0
    over25 = 0.0
    over35 = 0.0

    btts_yes = 0.0
    home_scores = {}
    away_scores = {}

    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = home_probs[h] * away_probs[a]

            total_mass += p
            scores.append((h, a, p))

            if h > a:
                home_win += p
            elif h == a:
                draw += p
            else:
                away_win += p

            if h + a >= 1:
                over05 += p
            if h + a >= 2:
                over15 += p
            if h + a >= 3:
                over25 += p
            if h + a >= 4:
                over35 += p

            if h >= 1 and a >= 1:
                btts_yes += p

    if total_mass <= 0:
        total_mass = 1.0

    def norm(value):
        return value / total_mass

    markets = {
        "Victoire domicile": norm(home_win),
        "Match nul": norm(draw),
        "Victoire extérieur": norm(away_win),
        "Double chance 1X": norm(home_win + draw),
        "Double chance X2": norm(away_win + draw),
        "Plus de 0,5 but": norm(over05),
        "Plus de 1,5 but": norm(over15),
        "Plus de 2,5 buts": norm(over25),
        "Plus de 3,5 buts": norm(over35),
        "Les deux équipes marquent — Oui": norm(btts_yes),
        "Les deux équipes marquent — Non": norm(total_mass - btts_yes),
        "Moins de 2,5 buts": norm(total_mass - over25),
        "Moins de 3,5 buts": norm(total_mass - over35),
    }

    top_scores = sorted(
        scores,
        key=lambda item: item[2],
        reverse=True,
    )[:5]

    top_scores = [
        {
            "score": f"{h} - {a}",
            "probability": norm(p),
        }
        for h, a, p in top_scores
    ]

    return markets, top_scores


# =====================================================
# ANALYSE COMPLÈTE D'UN MATCH
# =====================================================

def analyze_match(match):
    home = match.get("homeTeam", {})
    away = match.get("awayTeam", {})

    home_id = home.get("id")
    away_id = away.get("id")

    if not home_id or not away_id:
        return None

    home_name = home.get("name", "Domicile")
    away_name = away.get("name", "Extérieur")

    kickoff = match.get("utcDate", "")
    before_date = kickoff[:10] if kickoff else date.today().isoformat()

    home_stats = team_statistics(home_id, before_date)
    away_stats = team_statistics(away_id, before_date)

    # Estimation des buts attendus.
    # La méthode est volontairement simple : ce n'est pas un modèle
    # entraîné sur plusieurs saisons et ses probabilités peuvent être
    # mal calibrées.
    expected_home = (
        0.55 * home_stats["scored"]
        + 0.45 * away_stats["conceded"]
        + 0.20
    )

    expected_away = (
        0.55 * away_stats["scored"]
        + 0.45 * home_stats["conceded"]
    )

    expected_home *= 0.90 + home_stats["points"] * 0.07
    expected_away *= 0.90 + away_stats["points"] * 0.07

    expected_home = max(0.10, min(expected_home, 4.0))
    expected_away = max(0.10, min(expected_away, 4.0))

    markets, top_scores = calculate_markets(
        expected_home,
        expected_away,
    )

    return {
        "id": match.get("id"),
        "home": home_name,
        "away": away_name,
        "kickoff": kickoff,
        "competition": match.get("competition", {}).get("name", ""),
        "home_stats": home_stats,
        "away_stats": away_stats,
        "expected_home": expected_home,
        "expected_away": expected_away,
        "markets": markets,
        "top_scores": top_scores,
    }


# =====================================================
# AFFICHAGE DES MATCHS
# =====================================================

def probability_color(probability):
    if probability >= 0.75:
        return "🟢"
    if probability >= 0.60:
        return "🟡"
    if probability >= 0.45:
        return "🟠"
    return "⚪"


def show_match(analysis):
    kickoff = analysis["kickoff"]

    if kickoff:
        time_text = kickoff[11:16] + " UTC"
    else:
        time_text = "Horaire inconnu"

    st.markdown(
        f"### ⚽ {analysis['home']} — {analysis['away']}"
    )

    st.caption(
        f"{analysis['competition']} · {time_text}"
    )

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Buts attendus domicile",
        f"{analysis['expected_home']:.2f}",
    )

    col2.metric(
        "Buts attendus extérieur",
        f"{analysis['expected_away']:.2f}",
    )

    col3.metric(
        "Matchs récents utilisés",
        f"{analysis['home_stats']['count']} / "
        f"{analysis['away_stats']['count']}",
    )

    st.markdown("#### 📊 Probabilités de chaque marché")

    # Afficher les marchés par ordre de probabilité décroissante.
    sorted_markets = sorted(
        analysis["markets"].items(),
        key=lambda item: item[1],
        reverse=True,
    )

    for start in range(0, len(sorted_markets), 2):
        cols = st.columns(2)

        for offset, col in enumerate(cols):
            index = start + offset

            if index >= len(sorted_markets):
                continue

            label, probability = sorted_markets[index]

            with col:
                st.markdown(
                    f"**{probability_color(probability)} {label}**"
                )

                st.progress(
                    max(0.0, min(1.0, probability))
                )

                st.caption(
                    f"{probability * 100:.1f} % estimés"
                )

    with st.expander("📈 Forme récente des équipes"):
        left, right = st.columns(2)

        with left:
            st.markdown(f"**{analysis['home']}**")
            st.write(
                f"Forme : {analysis['home_stats']['form']}"
            )
            st.write(
                f"Buts marqués par match : "
                f"{analysis['home_stats']['scored']:.2f}"
            )
            st.write(
                f"Buts encaissés par match : "
                f"{analysis['home_stats']['conceded']:.2f}"
            )

        with right:
            st.markdown(f"**{analysis['away']}**")
            st.write(
                f"Forme : {analysis['away_stats']['form']}"
            )
            st.write(
                f"Buts marqués par match : "
                f"{analysis['away_stats']['scored']:.2f}"
            )
            st.write(
                f"Buts encaissés par match : "
                f"{analysis['away_stats']['conceded']:.2f}"
            )

    with st.expander("🎯 Scores exacts théoriques"):
        for item in analysis["top_scores"]:
            st.write(
                f"**{item['score']}** : "
                f"{item['probability'] * 100:.1f} %"
            )

    st.divider()


# =====================================================
# APPLICATION
# =====================================================

st.title("⚽ FOOT AI PRO")
st.markdown(
    "### Tous les matchs, toutes les probabilités, une analyse à la fois."
)

st.info(
    "Les pourcentages sont des estimations d'un modèle de Poisson "
    "simple, et non des garanties. Les probabilités doivent être "
    "évaluées sur des résultats historiques avant de pouvoir être "
    "considérées comme fiables."
)

if not get_api_key():
    st.error("La clé API football-data.org n'a pas été trouvée.")
    st.code(
        'FOOTBALL_DATA_API_KEY = "TA_CLE_API"',
        language="toml",
    )
    st.stop()


# =====================================================
# FILTRES
# =====================================================

with st.sidebar:
    st.header("🔎 Rechercher les matchs")

    selected_date = st.date_input(
        "Date des matchs",
        value=date.today(),
    )

    selected_competitions = st.multiselect(
        "Championnats",
        options=list(COMPETITIONS.keys()),
        default=list(COMPETITIONS.keys()),
    )

    show_button = st.button(
        "Afficher les matchs",
        use_container_width=True,
    )

    st.caption(
        "La première ouverture récupère les matchs du jour. "
        "Tu peux ensuite choisir une autre date."
    )


# Charge automatiquement les matchs du jour au premier lancement.
if "loaded_date" not in st.session_state:
    st.session_state["loaded_date"] = date.today().isoformat()
    st.session_state["loaded_competitions"] = list(COMPETITIONS.keys())
    st.session_state["analyses"] = []
    st.session_state["load_requested"] = True

if show_button:
    st.session_state["loaded_date"] = selected_date.isoformat()
    st.session_state["loaded_competitions"] = selected_competitions
    st.session_state["load_requested"] = True

if st.session_state.get("load_requested"):
    target_date = st.session_state["loaded_date"]
    target_competitions = st.session_state["loaded_competitions"]

    all_matches = []
    errors = []

    if not target_competitions:
        st.warning("Choisis au moins un championnat.")
        st.session_state["load_requested"] = False
        st.stop()

    with st.spinner("Récupération des matchs..."):
        for competition_name in target_competitions:
            code = COMPETITIONS[competition_name]

            try:
                matches = load_matches(
                    code,
                    target_date,
                    target_date,
                )

                for match in matches:
                    match["_competition_label"] = competition_name

                all_matches.extend(matches)

            except Exception as exc:
                errors.append(f"{competition_name} : {exc}")

    # Supprimer les doublons éventuels.
    unique_matches = {
        match.get("id"): match
        for match in all_matches
        if match.get("id") is not None
    }

    all_matches = list(unique_matches.values())

    all_matches.sort(
        key=lambda match: match.get("utcDate", "")
    )

    analyses = []

    with st.spinner(
        f"Analyse de {len(all_matches)} match(s)..."
    ):
        for match in all_matches:
            status = match.get("status", "")

            # Ne pas analyser comme prochains matchs les rencontres
            # déjà terminées ou annulées.
            if status not in ("SCHEDULED", "TIMED"):
                continue

            try:
                analysis = analyze_match(match)

                if analysis:
                    analysis["competition"] = (
                        match.get("_competition_label")
                        or analysis["competition"]
                    )

                    analyses.append(analysis)

            except Exception as exc:
                errors.append(
                    f"{match.get('homeTeam', {}).get('name', '?')} "
                    f"– {match.get('awayTeam', {}).get('name', '?')} : "
                    f"{exc}"
                )

    st.session_state["analyses"] = analyses
    st.session_state["errors"] = errors
    st.session_state["load_requested"] = False


# =====================================================
# RÉSULTATS
# =====================================================

analyses = st.session_state.get("analyses", [])

for error in st.session_state.get("errors", []):
    st.warning(error)

target_date = st.session_state.get(
    "loaded_date",
    date.today().isoformat(),
)

st.markdown(f"## 📅 Matchs du {target_date}")

if not analyses:
    st.warning(
        "Aucun match à venir trouvé pour cette date et ces compétitions. "
        "Essaie une autre date ou vérifie l'accès de ta clé API."
    )
else:
    st.success(f"{len(analyses)} match(s) à analyser.")

    # Filtre rapide par équipe.
    team_search = st.text_input(
        "🔍 Rechercher une équipe",
        placeholder="Exemple : PSG, Lille, Arsenal...",
    )

    filtered = analyses

    if team_search.strip():
        query = team_search.strip().lower()

        filtered = [
            item for item in analyses
            if query in item["home"].lower()
            or query in item["away"].lower()
        ]

    st.caption(
        "Ouvre chaque rencontre pour retrouver toutes les "
        "probabilités calculées pour ce match."
    )

    for analysis in filtered:
        with st.container(border=True):
            show_match(analysis)

st.caption(
    "FOOT AI PRO — Analyse statistique. "
    "Les données de blessures, les compositions officielles "
    "et les nouvelles de dernière minute ne sont pas incluses "
    "dans cette version."
)