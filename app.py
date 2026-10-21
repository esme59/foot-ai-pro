import os
import math
import itertools
from datetime import date, timedelta

import requests
import streamlit as st


# =========================================================
# CONFIGURATION
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
    "Espagne - La Liga": "PD",
    "Allemagne - Bundesliga": "BL1",
    "Italie - Serie A": "SA",
    "Ligue des Champions": "CL",
}

MARKET_NAMES = {
    "home_win": "Victoire domicile",
    "draw": "Match nul",
    "away_win": "Victoire extérieur",
    "1X": "Double chance 1X",
    "X2": "Double chance X2",
    "over15": "Plus de 1,5 but",
    "over25": "Plus de 2,5 buts",
    "btts": "Les deux équipes marquent",
}

MARKET_GROUPS = {
    "home_win": "Résultat",
    "draw": "Résultat",
    "away_win": "Résultat",
    "1X": "Double chance",
    "X2": "Double chance",
    "over15": "Buts",
    "over25": "Buts",
    "btts": "Les deux équipes marquent",
}


# =========================================================
# API FOOTBALL-DATA
# =========================================================

def get_api_key():
    try:
        key = st.secrets.get("FOOTBALL_DATA_API_KEY", "")
        if key:
            return key
    except Exception:
        pass

    return os.environ.get("FOOTBALL_DATA_API_KEY", "")


def api_get(endpoint, params=None):
    api_key = get_api_key()

    if not api_key:
        raise RuntimeError(
            "Clé API absente. Ajoute FOOTBALL_DATA_API_KEY "
            "dans les Secrets de Streamlit."
        )

    headers = {"X-Auth-Token": api_key}

    try:
        response = requests.get(
            f"{API_BASE}{endpoint}",
            headers=headers,
            params=params,
            timeout=20,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Erreur de connexion à l'API : {exc}")

    if response.status_code == 429:
        raise RuntimeError(
            "Limite de requêtes API atteinte. "
            "Attends quelques minutes avant de réessayer."
        )

    if response.status_code == 403:
        raise RuntimeError(
            "Accès refusé par l'API. Vérifie les compétitions "
            "disponibles avec ton abonnement."
        )

    if response.status_code == 404:
        return {}

    if response.status_code != 200:
        message = response.text[:250]
        raise RuntimeError(
            f"Erreur API {response.status_code} : {message}"
        )

    return response.json()


# =========================================================
# MATCHS DES COMPÉTITIONS
# =========================================================

@st.cache_data(ttl=900, show_spinner=False)
def get_competition_matches(code, date_from, date_to):
    data = api_get(
        f"/competitions/{code}/matches",
        {
            "dateFrom": date_from,
            "dateTo": date_to,
        },
    )

    return data.get("matches", [])


@st.cache_data(ttl=3600, show_spinner=False)
def get_team_history(team_id, before_date):
    data = api_get(
        f"/teams/{team_id}/matches",
        {
            "status": "FINISHED",
            "dateTo": before_date,
            "limit": 10,
        },
    )

    return data.get("matches", [])


# =========================================================
# FORME RÉCENTE DES ÉQUIPES
# =========================================================

def get_team_form(team_id, before_date):
    try:
        matches = get_team_history(team_id, before_date)
    except Exception:
        matches = []

    matches = [
        match for match in matches
        if match.get("score", {}).get("fullTime", {}).get("home")
        is not None
        and match.get("score", {}).get("fullTime", {}).get("away")
        is not None
    ]

    matches = sorted(
        matches,
        key=lambda match: match.get("utcDate", ""),
        reverse=True,
    )[:5]

    goals_for = []
    goals_against = []
    points = []
    form = []

    for match in matches:
        home_id = match.get("homeTeam", {}).get("id")
        away_id = match.get("awayTeam", {}).get("id")

        score = match["score"]["fullTime"]
        home_goals = score["home"]
        away_goals = score["away"]

        if team_id == home_id:
            scored = home_goals
            conceded = away_goals
        elif team_id == away_id:
            scored = away_goals
            conceded = home_goals
        else:
            continue

        goals_for.append(scored)
        goals_against.append(conceded)

        if scored > conceded:
            points.append(3)
            form.append("V")
        elif scored == conceded:
            points.append(1)
            form.append("N")
        else:
            points.append(0)
            form.append("D")

    if not goals_for:
        return {
            "avg_for": 1.25,
            "avg_against": 1.25,
            "points": 1.0,
            "form": "Indisponible",
            "matches": 0,
        }

    return {
        "avg_for": sum(goals_for) / len(goals_for),
        "avg_against": sum(goals_against) / len(goals_against),
        "points": sum(points) / len(points),
        "form": " ".join(form),
        "matches": len(goals_for),
    }


# =========================================================
# POISSON : PROBABILITÉS DES SCORES
# =========================================================

def poisson_probability(goals, expected_goals):
    expected_goals = max(0.05, expected_goals)

    return (
        math.exp(-expected_goals)
        * expected_goals ** goals
        / math.factorial(goals)
    )


def calculate_probabilities(lambda_home, lambda_away):
    max_goals = 10

    home_probs = [
        poisson_probability(i, lambda_home)
        for i in range(max_goals + 1)
    ]

    away_probs = [
        poisson_probability(i, lambda_away)
        for i in range(max_goals + 1)
    ]

    total_mass = 0.0
    home_win = 0.0
    draw = 0.0
    away_win = 0.0
    over15 = 0.0
    over25 = 0.0
    btts = 0.0
    score_probs = []

    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            probability = home_probs[h] * away_probs[a]
            total_mass += probability

            if h > a:
                home_win += probability
            elif h == a:
                draw += probability
            else:
                away_win += probability

            if h + a >= 2:
                over15 += probability

            if h + a >= 3:
                over25 += probability

            if h >= 1 and a >= 1:
                btts += probability

            score_probs.append(
                {
                    "score": f"{h}-{a}",
                    "probability": probability,
                }
            )

    if total_mass <= 0:
        total_mass = 1.0

    # Normalisation de toutes les probabilités calculées
    probabilities = {
        "home_win": home_win / total_mass,
        "draw": draw / total_mass,
        "away_win": away_win / total_mass,
        "1X": (home_win + draw) / total_mass,
        "X2": (away_win + draw) / total_mass,
        "over15": over15 / total_mass,
        "over25": over25 / total_mass,
        "btts": btts / total_mass,
    }

    best_scores = sorted(
        score_probs,
        key=lambda item: item["probability"],
        reverse=True,
    )[:3]

    return probabilities, best_scores


# =========================================================
# ANALYSE D'UN MATCH
# =========================================================

def analyze_match(match):
    home_team = match.get("homeTeam", {})
    away_team = match.get("awayTeam", {})

    home_id = home_team.get("id")
    away_id = away_team.get("id")

    home_name = home_team.get("name", "Équipe domicile")
    away_name = away_team.get("name", "Équipe extérieure")

    match_date = match.get("utcDate", "")
    before_date = match_date[:10] if match_date else date.today().isoformat()

    if not home_id or not away_id:
        return None

    home_form = get_team_form(home_id, before_date)
    away_form = get_team_form(away_id, before_date)

    # Estimation simple des buts attendus
    lambda_home = (
        0.55 * home_form["avg_for"]
        + 0.45 * away_form["avg_against"]
        + 0.20
    )

    lambda_away = (
        0.55 * away_form["avg_for"]
        + 0.45 * home_form["avg_against"]
    )

    # Ajustement léger selon la forme récente
    lambda_home *= 0.90 + home_form["points"] * 0.07
    lambda_away *= 0.90 + away_form["points"] * 0.07

    lambda_home = max(0.15, min(lambda_home, 3.5))
    lambda_away = max(0.15, min(lambda_away, 3.5))

    probabilities, best_scores = calculate_probabilities(
        lambda_home,
        lambda_away,
    )

    candidates = []

    for market, probability in probabilities.items():
        candidates.append(
            {
                "market": market,
                "label": MARKET_NAMES[market],
                "probability": probability,
                "group": MARKET_GROUPS[market],
                "home": home_name,
                "away": away_name,
                "match_id": match.get("id"),
                "date": match_date,
                "lambda_home": lambda_home,
                "lambda_away": lambda_away,
            }
        )

    candidates.sort(
        key=lambda item: item["probability"],
        reverse=True,
    )

    return {
        "match_id": match.get("id"),
        "home": home_name,
        "away": away_name,
        "date": match_date,
        "competition": match.get("competition", {}).get("name", ""),
        "home_form": home_form,
        "away_form": away_form,
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "probabilities": probabilities,
        "best_scores": best_scores,
        "candidates": candidates,
    }


# =========================================================
# CRÉATION DES COMBINÉS
# =========================================================

def get_match_candidates(analysis, category):
    candidates = analysis["candidates"]

    # Retire les choix trop faibles pour les combinés fiables
    if category == "Fiable":
        candidates = [
            item for item in candidates
            if item["probability"] >= 0.65
        ]

    elif category == "Équilibré":
        candidates = [
            item for item in candidates
            if item["probability"] >= 0.45
        ]

    else:
        candidates = [
            item for item in candidates
            if item["probability"] >= 0.25
        ]

    if not candidates:
        return []

    if category == "Fiable":
        candidates.sort(
            key=lambda item: item["probability"],
            reverse=True,
        )

    elif category == "Équilibré":
        # Favorise un compromis entre probabilité et diversité
        candidates.sort(
            key=lambda item: (
                item["probability"]
                + (0.04 if item["group"] != "Buts" else 0)
            ),
            reverse=True,
        )

    else:
        # Les marchés plus difficiles peuvent être plus présents
        candidates.sort(
            key=lambda item: (
                (1 - abs(item["probability"] - 0.50))
                + (0.08 if item["market"] in (
                    "home_win", "draw", "away_win", "over25", "btts"
                ) else 0)
            ),
            reverse=True,
        )

    # Garder plusieurs marchés possibles par match
    return candidates[:5]


def combo_score(combo, category):
    probabilities = [
        item["probability"]
        for item in combo
    ]

    product = math.prod(probabilities)

    unique_groups = len(set(
        item["group"] for item in combo
    ))

    unique_markets = len(set(
        item["market"] for item in combo
    ))

    if category == "Fiable":
        return product

    if category == "Équilibré":
        return product * (
            1 + 0.04 * (unique_groups - 1)
            + 0.02 * (unique_markets - 1)
        )

    # Pour la catégorie risquée, on privilégie des choix plus audacieux,
    # mais on conserve l'affichage de la probabilité estimée réelle.
    risk_factor = sum(
        1 - item["probability"]
        for item in combo
    ) / len(combo)

    return product * (1 + 0.15 * risk_factor)


def generate_combinations(analyses, size, category, max_matches=18):
    usable = []

    for analysis in analyses:
        candidates = get_match_candidates(analysis, category)

        if candidates:
            usable.append((analysis, candidates))

    if len(usable) < size:
        return []

    # Limite les matchs examinés pour éviter un calcul excessif
    usable = usable[:max_matches]

    combinations_found = []

    for selected_matches in itertools.combinations(usable, size):
        candidate_lists = [
            item[1] for item in selected_matches
        ]

        for combo in itertools.product(*candidate_lists):
            # Évite de répéter le même marché sur chaque match
            # lorsque des alternatives de probabilité proche existent.
            score = combo_score(combo, category)

            actual_probability = math.prod(
                item["probability"] for item in combo
            )

            signature = tuple(
                sorted(
                    (
                        str(item["match_id"]),
                        item["market"],
                    )
                    for item in combo
                )
            )

            combinations_found.append(
                {
                    "selections": list(combo),
                    "score": score,
                    "probability": actual_probability,
                    "signature": signature,
                }
            )

    combinations_found.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    # Conserver des propositions distinctes
    results = []
    signatures = set()

    for combo in combinations_found:
        signature = combo["signature"]

        if signature in signatures:
            continue

        signatures.add(signature)
        results.append(combo)

        if len(results) >= 5:
            break

    return results


# =========================================================
# AFFICHAGE
# =========================================================

def format_percent(value):
    return f"{value * 100:.1f} %"


def format_datetime(value):
    if not value:
        return "Date inconnue"

    return value.replace("T", " ")[:16] + " UTC"


def display_selection(selection):
    st.markdown(
        f"**{selection['home']} – {selection['away']}**"
    )

    st.write(
        f"Pronostic : **{selection['label']}**"
    )

    st.write(
        f"Probabilité estimée : "
        f"**{format_percent(selection['probability'])}**"
    )


def display_combinations(analyses, category):
    for size in (2, 3, 4):
        st.subheader(f"🔗 Combiné de {size} matchs")

        combos = generate_combinations(
            analyses,
            size,
            category,
        )

        if not combos:
            st.info(
                "Pas assez de matchs ou de sélections "
                "disponibles dans cette catégorie. "
                "Essaie une autre catégorie ou une autre date."
            )
            continue

        for index, combo in enumerate(combos, start=1):
            with st.container(border=True):
                st.markdown(f"### Proposition {index}")

                for selection in combo["selections"]:
                    display_selection(selection)

                st.divider()

                st.write(
                    "**Probabilité théorique combinée :** "
                    f"{format_percent(combo['probability'])}"
                )

                st.caption(
                    "Calcul par multiplication des probabilités "
                    "estimées. Ce chiffre n'est pas une garantie "
                    "et peut surestimer la fiabilité réelle."
                )


def display_single_predictions(analyses):
    st.subheader("🎯 Meilleurs pronostics simples")

    candidates = []

    for analysis in analyses:
        candidates.extend(analysis["candidates"])

    candidates.sort(
        key=lambda item: item["probability"],
        reverse=True,
    )

    # Éviter d'afficher trop de fois le même match
    used_matches = set()
    displayed = 0

    for selection in candidates:
        match_id = selection["match_id"]

        if match_id in used_matches:
            continue

        used_matches.add(match_id)

        with st.container(border=True):
            display_selection(selection)

        displayed += 1

        if displayed >= 10:
            break

    if displayed == 0:
        st.info("Aucun pronostic simple disponible.")


def display_match_analysis(analysis):
    with st.expander(
        f"{analysis['home']} – {analysis['away']}"
    ):
        st.write(
            f"Compétition : {analysis['competition']}"
        )

        st.write(
            f"Date : {format_datetime(analysis['date'])}"
        )

        st.write(
            f"Forme domicile : "
            f"{analysis['home_form']['form']}"
        )

        st.write(
            f"Forme extérieur : "
            f"{analysis['away_form']['form']}"
        )

        st.write(
            f"Buts attendus : "
            f"{analysis['lambda_home']:.2f} – "
            f"{analysis['lambda_away']:.2f}"
        )

        st.markdown("**Probabilités calculées**")

        for selection in analysis["candidates"]:
            st.write(
                f"- {selection['label']} : "
                f"{format_percent(selection['probability'])}"
            )

        st.markdown("**Scores théoriques les plus probables**")

        for score in analysis["best_scores"]:
            st.write(
                f"- {score['score']} : "
                f"{format_percent(score['probability'])}"
            )


# =========================================================
# INTERFACE PRINCIPALE
# =========================================================

st.title("⚽ FOOT AI PRO")
st.caption(
    "Analyse statistique des matchs et génération de pronostics "
    "simples et combinés."
)

st.warning(
    "Les probabilités sont des estimations issues d'un modèle "
    "statistique simple. L'application ne garantit aucun résultat. "
    "Elle ne dispose pas automatiquement des compositions officielles, "
    "des blessures ou des dernières informations d'équipe."
)

with st.sidebar:
    st.header("⚙️ Paramètres")

    today = date.today()

    date_from = st.date_input(
        "Date de début",
        value=today,
    )

    date_to = st.date_input(
        "Date de fin",
        value=today + timedelta(days=3),
    )

    selected_competitions = st.multiselect(
        "Championnats",
        options=list(COMPETITIONS.keys()),
        default=list(COMPETITIONS.keys()),
    )

    category = st.selectbox(
        "Type de combiné",
        ["Fiable", "Équilibré", "Risqué"],
        index=0,
    )

    st.caption(
        "Fiable : sélectionne les probabilités estimées élevées. "
        "Équilibré : favorise aussi la diversité des marchés. "
        "Risqué : accepte davantage de choix incertains."
    )

    launch = st.button(
        "🔎 Analyser les matchs",
        use_container_width=True,
    )

if date_from > date_to:
    st.error(
        "La date de début doit être antérieure ou égale "
        "à la date de fin."
    )
    st.stop()

if not get_api_key():
    st.error(
        "Clé API manquante. Dans les paramètres de ton application "
        "Streamlit, ouvre Secrets et ajoute :"
    )

    st.code(
        'FOOTBALL_DATA_API_KEY = "TA_CLE_API"',
        language="toml",
    )

    st.stop()

if launch:
    if not selected_competitions:
        st.warning("Choisis au moins un championnat.")
        st.stop()

    all_matches = []
    errors = []

    start_date = date_from.isoformat()
    end_date = date_to.isoformat()

    progress = st.progress(0)

    for index, competition_name in enumerate(
        selected_competitions,
        start=1,
    ):
        code = COMPETITIONS[competition_name]

        try:
            matches = get_competition_matches(
                code,
                start_date,
                end_date,
            )

            for match in matches:
                match["_selected_competition"] = competition_name

            all_matches.extend(matches)

        except Exception as exc:
            errors.append(
                f"{competition_name} : {exc}"
            )

        progress.progress(
            index / len(selected_competitions)
        )

    progress.empty()

    # Éliminer les doublons éventuels
    unique_matches = {}

    for match in all_matches:
        match_id = match.get("id")

        if match_id is not None:
            unique_matches[match_id] = match

    all_matches = list(unique_matches.values())

    all_matches.sort(
        key=lambda match: match.get("utcDate", "")
    )

    st.session_state["foot_ai_matches"] = all_matches
    st.session_state["foot_ai_errors"] = errors
    st.session_state["foot_ai_analyses"] = []

    if not all_matches:
        st.warning(
            "Aucun match trouvé pour ces dates et ces compétitions."
        )

    else:
        st.success(
            f"{len(all_matches)} match(s) trouvé(s). "
            "Calcul des analyses..."
        )

        analyses = []
        analysis_errors = []

        for index, match in enumerate(all_matches, start=1):
            status = match.get("status", "")

            if status not in ("SCHEDULED", "TIMED"):
                continue

            try:
                analysis = analyze_match(match)

                if analysis:
                    analysis["competition"] = (
                        match.get("_selected_competition")
                        or match.get("competition", {}).get("name", "")
                    )

                    analyses.append(analysis)

            except Exception as exc:
                analysis_errors.append(
                    f"{match.get('homeTeam', {}).get('name', '?')} "
                    f"– {match.get('awayTeam', {}).get('name', '?')} : "
                    f"{exc}"
                )

        st.session_state["foot_ai_analyses"] = analyses
        st.session_state["foot_ai_analysis_errors"] = analysis_errors

        st.rerun()


# =========================================================
# RÉSULTATS ENREGISTRÉS DANS LA SESSION
# =========================================================

for error in st.session_state.get("foot_ai_errors", []):
    st.warning(error)

for error in st.session_state.get("foot_ai_analysis_errors", [])[:5]:
    st.warning(error)

analyses = st.session_state.get("foot_ai_analyses", [])

if analyses:
    st.success(
        f"{len(analyses)} match(s) analysé(s)."
    )

    tab1, tab2, tab3 = st.tabs(
        [
            "🎯 Pronostics simples",
            "🔗 Combinés IA",
            "📊 Analyses des matchs",
        ]
    )

    with tab1:
        display_single_predictions(analyses)

    with tab2:
        st.markdown(
            f"### Type sélectionné : {category}"
        )

        display_combinations(
            analyses,
            category,
        )

    with tab3:
        for analysis in analyses:
            display_match_analysis(analysis)

elif st.session_state.get("foot_ai_matches"):
    st.info(
        "Les matchs sont récupérés, mais aucune analyse n'est "
        "disponible. Vérifie les erreurs affichées ci-dessus."
    )

else:
    st.info(
        "Choisis tes dates et tes championnats dans le menu de gauche, "
        "puis appuie sur « Analyser les matchs »."
    )

st.divider()

st.caption(
    "FOOT AI PRO — outil d'aide à l'analyse statistique. "
    "Les résultats sportifs restent incertains."
)