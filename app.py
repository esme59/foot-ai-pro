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
    "Ligue des champions": "CL",
}

DEFAULT_DAYS = 7
MAX_HISTORY_MATCHES = 10


# =========================================================
# CLÉ API
# =========================================================

def get_api_key():
    try:
        key = st.secrets.get("FOOTBALL_DATA_API_KEY", "")
        if key:
            return key
    except Exception:
        pass

    return os.getenv("FOOTBALL_DATA_API_KEY", "")


API_KEY = get_api_key()


# =========================================================
# API
# =========================================================

@st.cache_data(ttl=300, show_spinner=False)
def api_get(endpoint, params=None):
    if not API_KEY:
        return None, "Clé API manquante."

    headers = {"X-Auth-Token": API_KEY}

    try:
        response = requests.get(
            f"{API_BASE}{endpoint}",
            headers=headers,
            params=params,
            timeout=20,
        )

        if response.status_code == 200:
            return response.json(), None

        if response.status_code == 401:
            return None, "Clé API invalide ou non autorisée."

        if response.status_code == 403:
            return None, (
                "Accès refusé par football-data.org. "
                "Cette compétition ou cette donnée n'est peut-être "
                "pas incluse dans ton abonnement."
            )

        if response.status_code == 429:
            return None, (
                "Limite de requêtes API atteinte. "
                "Attends un peu avant de réessayer."
            )

        return None, (
            f"Erreur API HTTP {response.status_code} : "
            f"{response.text[:200]}"
        )

    except requests.RequestException as exc:
        return None, f"Erreur de connexion : {exc}"


# =========================================================
# RÉCUPÉRATION DES MATCHS
# =========================================================

@st.cache_data(ttl=300, show_spinner=False)
def get_competition_matches(competition_code, date_from, date_to):
    data, error = api_get(
        f"/competitions/{competition_code}/matches",
        {
            "dateFrom": date_from,
            "dateTo": date_to,
        },
    )

    if error or not data:
        return [], error

    matches = data.get("matches", [])
    matches.sort(key=lambda match: match.get("utcDate", ""))

    return matches, None


@st.cache_data(ttl=600, show_spinner=False)
def get_team_history(team_id, before_date):
    data, error = api_get(
        f"/teams/{team_id}/matches",
        {
            "status": "FINISHED",
            "dateTo": before_date,
            "limit": MAX_HISTORY_MATCHES,
        },
    )

    if error or not data:
        return [], error

    matches = data.get("matches", [])

    matches.sort(
        key=lambda match: match.get("utcDate", ""),
        reverse=True,
    )

    return matches[:MAX_HISTORY_MATCHES], None


# =========================================================
# ANALYSE DE LA FORME
# =========================================================

def get_team_form(team_id, matches):
    goals_for = []
    goals_against = []
    points = []
    opponents = []

    for match in matches:
        home = match.get("homeTeam", {})
        away = match.get("awayTeam", {})
        score = match.get("score", {}).get("fullTime", {})

        home_id = home.get("id")
        away_id = away.get("id")

        home_goals = score.get("home")
        away_goals = score.get("away")

        if home_goals is None or away_goals is None:
            continue

        if home_id == team_id:
            gf = home_goals
            ga = away_goals
            opponent = away.get("name", "Adversaire")
        elif away_id == team_id:
            gf = away_goals
            ga = home_goals
            opponent = home.get("name", "Adversaire")
        else:
            continue

        goals_for.append(gf)
        goals_against.append(ga)
        opponents.append(opponent)

        if gf > ga:
            points.append(3)
        elif gf == ga:
            points.append(1)
        else:
            points.append(0)

    count = len(goals_for)

    if count == 0:
        return {
            "count": 0,
            "avg_for": 1.25,
            "avg_against": 1.25,
            "points": 0,
            "form": "Données insuffisantes",
            "goals_for": 0,
            "goals_against": 0,
        }

    form_letters = []

    for gf, ga in zip(goals_for, goals_against):
        if gf > ga:
            form_letters.append("V")
        elif gf == ga:
            form_letters.append("N")
        else:
            form_letters.append("D")

    return {
        "count": count,
        "avg_for": sum(goals_for) / count,
        "avg_against": sum(goals_against) / count,
        "points": sum(points),
        "form": " ".join(form_letters[:5]),
        "goals_for": sum(goals_for),
        "goals_against": sum(goals_against),
    }


# =========================================================
# POISSON
# =========================================================

def poisson_probability(lam, goals):
    if lam < 0:
        lam = 0

    return (math.exp(-lam) * lam**goals) / math.factorial(goals)


def calculate_probabilities(lambda_home, lambda_away):
    max_goals = 8

    home_win = 0.0
    draw = 0.0
    away_win = 0.0
    over_15 = 0.0
    over_25 = 0.0
    btts = 0.0
    score_probs = []

    for home_goals in range(max_goals + 1):
        p_home = poisson_probability(lambda_home, home_goals)

        for away_goals in range(max_goals + 1):
            p_away = poisson_probability(lambda_away, away_goals)
            probability = p_home * p_away

            score_probs.append(
                (home_goals, away_goals, probability)
            )

            if home_goals > away_goals:
                home_win += probability
            elif home_goals == away_goals:
                draw += probability
            else:
                away_win += probability

            if home_goals + away_goals >= 2:
                over_15 += probability

            if home_goals + away_goals >= 3:
                over_25 += probability

            if home_goals >= 1 and away_goals >= 1:
                btts += probability

    total = home_win + draw + away_win

    if total > 0:
        home_win /= total
        draw /= total
        away_win /= total

    return {
        "home_win": home_win,
        "draw": draw,
        "away_win": away_win,
        "over_15": over_15,
        "over_25": over_25,
        "btts": btts,
        "score_probs": sorted(
            score_probs,
            key=lambda item: item[2],
            reverse=True,
        ),
    }


# =========================================================
# ANALYSE D'UN MATCH
# =========================================================

def analyze_match(match):
    home = match.get("homeTeam", {})
    away = match.get("awayTeam", {})

    home_id = home.get("id")
    away_id = away.get("id")

    home_name = home.get("name", "Équipe domicile")
    away_name = away.get("name", "Équipe extérieure")

    if not home_id or not away_id:
        return None

    match_date = match.get("utcDate", "")
    before_date = match_date[:10] if match_date else date.today().isoformat()

    home_history, home_error = get_team_history(
        home_id,
        before_date,
    )
    away_history, away_error = get_team_history(
        away_id,
        before_date,
    )

    home_form = get_team_form(home_id, home_history)
    away_form = get_team_form(away_id, away_history)

    # Valeurs de secours si l'historique n'est pas disponible.
    # Elles permettent d'afficher une estimation, mais pas une
    # analyse aussi fiable qu'avec des données récentes.
    home_attack = home_form["avg_for"]
    away_defence = away_form["avg_against"]
    away_attack = away_form["avg_for"]
    home_defence = home_form["avg_against"]

    lambda_home = (home_attack + away_defence) / 2 + 0.20
    lambda_away = (away_attack + home_defence) / 2

    # Ajustement modéré selon les résultats récents.
    if home_form["count"] >= 3:
        home_points_per_match = home_form["points"] / home_form["count"]
        lambda_home *= 0.90 + (home_points_per_match / 3) * 0.20

    if away_form["count"] >= 3:
        away_points_per_match = away_form["points"] / away_form["count"]
        lambda_away *= 0.90 + (away_points_per_match / 3) * 0.20

    lambda_home = max(0.15, min(lambda_home, 3.5))
    lambda_away = max(0.15, min(lambda_away, 3.5))

    probabilities = calculate_probabilities(
        lambda_home,
        lambda_away,
    )

    home_win = probabilities["home_win"]
    draw = probabilities["draw"]
    away_win = probabilities["away_win"]

    selections = [
        {
            "name": "1X - Domicile ou nul",
            "probability": home_win + draw,
        },
        {
            "name": "X2 - Extérieur ou nul",
            "probability": away_win + draw,
        },
        {
            "name": "Plus de 1,5 but",
            "probability": probabilities["over_15"],
        },
        {
            "name": "Victoire domicile",
            "probability": home_win,
        },
        {
            "name": "Match nul",
            "probability": draw,
        },
        {
            "name": "Victoire extérieur",
            "probability": away_win,
        },
        {
            "name": "Plus de 2,5 buts",
            "probability": probabilities["over_25"],
        },
        {
            "name": "Les deux équipes marquent",
            "probability": probabilities["btts"],
        },
    ]

    selections.sort(
        key=lambda item: item["probability"],
        reverse=True,
    )

    best_score = probabilities["score_probs"][0]

    return {
        "id": match.get("id"),
        "date": match_date,
        "competition": match.get("competition", {}).get(
            "name",
            "Compétition",
        ),
        "home_name": home_name,
        "away_name": away_name,
        "home_form": home_form,
        "away_form": away_form,
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "probabilities": probabilities,
        "selections": selections,
        "best_score": f"{best_score[0]} - {best_score[1]}",
        "history_error": bool(home_error or away_error),
    }


# =========================================================
# COMBINÉS AUTOMATIQUES
# =========================================================

def best_combo_selection(result):
    selections = result.get("selections", [])

    if not selections:
        return None

    # On choisit le marché le mieux évalué pour chaque match.
    # Cette probabilité reste une estimation statistique.
    valid = [
        selection
        for selection in selections
        if selection.get("probability") is not None
    ]

    if not valid:
        return None

    return max(
        valid,
        key=lambda selection: selection["probability"],
    )


def build_combo_candidates(results):
    candidates = []
    seen = set()

    for result in results:
        selection = best_combo_selection(result)

        if selection is None:
            continue

        match_id = result.get("id")

        if match_id is None:
            match_id = (
                result.get("home_name"),
                result.get("away_name"),
                result.get("date"),
            )

        if match_id in seen:
            continue

        seen.add(match_id)

        probability = float(selection["probability"])

        if not 0 < probability <= 1:
            continue

        history_count = min(
            result["home_form"]["count"],
            result["away_form"]["count"],
        )

        candidates.append({
            "match": (
                f'{result["home_name"]} - '
                f'{result["away_name"]}'
            ),
            "date": result.get("date", ""),
            "market": selection["name"],
            "probability": probability,
            "history_count": history_count,
            "result": result,
        })

    candidates.sort(
        key=lambda candidate: candidate["probability"],
        reverse=True,
    )

    return candidates


def generate_combinations(candidates, size, limit=5):
    if len(candidates) < size:
        return []

    # On prend les meilleurs candidats pour éviter de parcourir
    # un nombre excessif de combinaisons.
    pool = candidates[:20]
    combinations = []

    for combo in itertools.combinations(pool, size):
        # Évite de proposer plusieurs sélections du même match.
        match_names = [item["match"] for item in combo]

        if len(match_names) != len(set(match_names)):
            continue

        probability = 1.0

        for item in combo:
            probability *= item["probability"]

        combinations.append({
            "selections": combo,
            "probability": probability,
        })

    combinations.sort(
        key=lambda item: item["probability"],
        reverse=True,
    )

    return combinations[:limit]


def display_combinations(results):
    st.header("🔗 Combinés automatiques")

    candidates = build_combo_candidates(results)

    st.write(
        f"**Matchs utilisables pour les combinés : "
        f"{len(candidates)}**"
    )

    if len(candidates) < 2:
        st.warning(
            "Il faut au moins 2 matchs analysables pour créer "
            "un combiné. Essaie une période plus large ou vérifie "
            "que l'API renvoie des matchs."
        )
        return

    st.caption(
        "Les pourcentages sont des estimations statistiques, "
        "pas des garanties. Le produit des probabilités suppose "
        "notamment que les sélections sont indépendantes."
    )

    tabs = st.tabs([
        "Combinés de 2",
        "Combinés de 3",
        "Combinés de 4",
    ])

    for tab, size in zip(tabs, [2, 3, 4]):
        with tab:
            combos = generate_combinations(
                candidates,
                size,
                limit=5,
            )

            if not combos:
                st.info(
                    f"Pas assez de matchs pour un combiné de {size}."
                )
                continue

            for index, combo in enumerate(combos, start=1):
                percentage = combo["probability"] * 100

                st.subheader(
                    f"Combiné {index} — probabilité théorique "
                    f"{percentage:.1f} %"
                )

                for item in combo["selections"]:
                    st.write(
                        f"• **{item['match']}** — "
                        f"{item['market']} "
                        f"({item['probability'] * 100:.1f} %)"
                    )

                    if item["history_count"] < 3:
                        st.caption(
                            "⚠️ Historique limité pour au moins "
                            "une des deux équipes."
                        )

                st.divider()


# =========================================================
# AFFICHAGE D'UNE ANALYSE
# =========================================================

def display_match_analysis(result):
    home = result["home_name"]
    away = result["away_name"]
    probs = result["probabilities"]

    st.subheader(f"⚽ {home} - {away}")

    if result["date"]:
        st.caption(
            f"Date : {result['date']} | "
            f"Compétition : {result['competition']}"
        )

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Victoire domicile",
        f"{probs['home_win'] * 100:.1f} %",
    )
    col2.metric(
        "Match nul",
        f"{probs['draw'] * 100:.1f} %",
    )
    col3.metric(
        "Victoire extérieur",
        f"{probs['away_win'] * 100:.1f} %",
    )

    st.write(
        f"**Forme récente domicile :** "
        f"{result['home_form']['form']} "
        f"({result['home_form']['count']} matchs)"
    )

    st.write(
        f"**Forme récente extérieur :** "
        f"{result['away_form']['form']} "
        f"({result['away_form']['count']} matchs)"
    )

    st.write(
        f"**Buts attendus estimés :** "
        f"{home} {result['lambda_home']:.2f} — "
        f"{result['lambda_away']:.2f} {away}"
    )

    st.write(
        f"**Score exact le plus probable selon le modèle :** "
        f"{result['best_score']}"
    )

    st.markdown("**Meilleurs marchés estimés :**")

    for selection in result["selections"][:5]:
        st.write(
            f"• {selection['name']} : "
            f"**{selection['probability'] * 100:.1f} %**"
        )

    if (
        result["home_form"]["count"] < 3
        or result["away_form"]["count"] < 3
    ):
        st.warning(
            "Historique récent incomplet : "
            "la précision de cette analyse peut être réduite."
        )

    st.divider()


# =========================================================
# INTERFACE
# =========================================================

st.title("⚽ FOOT AI PRO")
st.write(
    "Analyse automatique des matchs et estimation des probabilités "
    "à partir des résultats disponibles."
)

if not API_KEY:
    st.error(
        "Clé API introuvable. Dans Streamlit, ouvre les paramètres "
        "Secrets et ajoute :\n\n"
        'FOOTBALL_DATA_API_KEY = "TA_CLE_API"'
    )
    st.stop()


today = date.today()

col1, col2 = st.columns(2)

with col1:
    date_from = st.date_input(
        "Date de début",
        value=today,
        key="date_from",
    )

with col2:
    date_to = st.date_input(
        "Date de fin",
        value=today + timedelta(days=DEFAULT_DAYS),
        key="date_to",
    )

selected_competitions = st.multiselect(
    "Championnats à analyser",
    options=list(COMPETITIONS.keys()),
    default=list(COMPETITIONS.keys()),
)

if date_to < date_from:
    st.error(
        "La date de fin doit être égale ou postérieure "
        "à la date de début."
    )
    st.stop()

if not selected_competitions:
    st.warning("Sélectionne au moins un championnat.")
    st.stop()


analyze_button = st.button(
    "🔎 Rechercher les matchs et lancer les pronostics",
    type="primary",
    use_container_width=True,
)

if analyze_button:
    all_matches = []
    api_errors = []

    date_from_string = date_from.isoformat()
    date_to_string = date_to.isoformat()

    progress = st.progress(0)
    status = st.empty()

    total_competitions = len(selected_competitions)

    for index, competition_name in enumerate(
        selected_competitions,
        start=1,
    ):
        code = COMPETITIONS[competition_name]

        status.write(
            f"Recherche : {competition_name} "
            f"({index}/{total_competitions})..."
        )

        matches, error = get_competition_matches(
            code,
            date_from_string,
            date_to_string,
        )

        if error:
            api_errors.append(
                f"{competition_name} : {error}"
            )
        else:
            for match in matches:
                match["competition"]["name"] = competition_name

            all_matches.extend(matches)

        progress.progress(
            index / total_competitions
        )

    progress.empty()
    status.empty()

    # Supprime les éventuels doublons.
    unique_matches = {}

    for match in all_matches:
        unique_matches[match.get("id", str(match))] = match

    all_matches = list(unique_matches.values())
    all_matches.sort(
        key=lambda match: match.get("utcDate", "")
    )

    if api_errors:
        with st.expander("Voir les problèmes de connexion API"):
            for error in api_errors:
                st.warning(error)

    if not all_matches:
        st.warning(
            "Aucun match disponible pour cette période "
            "avec les compétitions et les accès API sélectionnés."
        )
        st.info(
            "Essaie d'élargir les dates, de sélectionner d'autres "
            "championnats ou de vérifier les autorisations de ta clé."
        )
        st.stop()

    st.success(
        f"{len(all_matches)} match(s) récupéré(s). "
        "Lancement des analyses..."
    )

    results = []
    analysis_progress = st.progress(0)

    for index, match in enumerate(all_matches, start=1):
        result = analyze_match(match)

        if result is not None:
            results.append(result)

        analysis_progress.progress(
            index / len(all_matches)
        )

    analysis_progress.empty()

    if not results:
        st.error(
            "Impossible de produire des analyses avec les données "
            "reçues. Vérifie les identifiants des équipes et les "
            "réponses de l'API."
        )
        st.stop()

    st.success(
        f"{len(results)} match(s) analysé(s)."
    )

    # Sauvegarde dans la session Streamlit pour que les onglets
    # restent accessibles lors des interactions suivantes.
    st.session_state["foot_ai_results"] = results


# =========================================================
# RÉSULTATS
# =========================================================

results = st.session_state.get("foot_ai_results", [])

if results:
    tab_matches, tab_ranking, tab_combos = st.tabs([
        "📋 Analyses des matchs",
        "🏆 Classement des pronostics",
        "🔗 Combinés",
    ])

    with tab_matches:
        for result in results:
            display_match_analysis(result)

    with tab_ranking:
        st.subheader("Pronostics les mieux évalués")

        ranking = []

        for result in results:
            selection = best_combo_selection(result)

            if selection:
                ranking.append({
                    "Match": (
                        f'{result["home_name"]} - '
                        f'{result["away_name"]}'
                    ),
                    "Pronostic": selection["name"],
                    "Probabilité estimée": (
                        f'{selection["probability"] * 100:.1f} %'
                    ),
                    "Historique domicile": (
                        result["home_form"]["count"]
                    ),
                    "Historique extérieur": (
                        result["away_form"]["count"]
                    ),
                })

        ranking.sort(
            key=lambda row: float(
                row["Probabilité estimée"].replace("%", "")
            ),
            reverse=True,
        )

        st.dataframe(
            ranking,
            use_container_width=True,
            hide_index=True,
        )

    with tab_combos:
        display_combinations(results)

else:
    st.info(
        "Choisis les dates et les championnats, puis appuie sur "
        "« Rechercher les matchs et lancer les pronostics »."
    )


st.caption(
    "FOOT AI PRO fournit des estimations statistiques et non "
    "des certitudes. Les probabilités ne garantissent pas le résultat "
    "d'un match. Vérifie les compositions, les blessures et les "
    "informations récentes auprès de sources fiables."
)