import math
from datetime import datetime, timedelta
from collections import defaultdict

import pandas as pd
import requests
import streamlit as st


# =========================================================
# FOOT AI PRO V6
# Pronostics automatiques avec football-data.org
# =========================================================

st.set_page_config(
    page_title="FOOT AI PRO V6",
    page_icon="⚽",
    layout="wide",
)

API_URL = "https://api.football-data.org/v4"

COMPETITIONS = {
    "Ligue 1 🇫🇷": "FL1",
    "Premier League 🏴": "PL",
    "Liga 🇪🇸": "PD",
    "Bundesliga 🇩🇪": "BL1",
    "Serie A 🇮🇹": "SA",
    "Ligue des champions 🏆": "CL",
}

HEADERS = {}


# =========================================================
# CONNEXION API
# =========================================================

def get_api_key():
    try:
        return st.secrets["FOOTBALL_API_KEY"]
    except Exception:
        return ""


def api_get(endpoint, params=None):
    """Appelle football-data.org et gère les erreurs courantes."""

    try:
        response = requests.get(
            f"{API_URL}{endpoint}",
            headers=HEADERS,
            params=params,
            timeout=20,
        )

        if response.status_code == 429:
            return None, "Limite de requêtes API atteinte."

        if response.status_code == 403:
            return None, (
                "Accès refusé par football-data.org. "
                "Vérifie les compétitions autorisées par ta clé."
            )

        if response.status_code == 401:
            return None, "Clé API invalide ou non reconnue."

        response.raise_for_status()

        return response.json(), None

    except requests.exceptions.Timeout:
        return None, "Le serveur API met trop de temps à répondre."

    except requests.exceptions.RequestException as exc:
        return None, f"Erreur de connexion API : {exc}"

    except ValueError:
        return None, "La réponse de l'API n'est pas valide."


# =========================================================
# RÉCUPÉRATION DES MATCHS
# =========================================================

@st.cache_data(ttl=300, show_spinner=False)
def get_matches(api_key, competition_codes, days):
    """Recherche automatiquement les matchs à venir."""

    today = datetime.now().date()
    end_date = today + timedelta(days=days)

    headers = {"X-Auth-Token": api_key}
    matches = []
    errors = []

    for competition_code in competition_codes:
        try:
            response = requests.get(
                f"{API_URL}/competitions/"
                f"{competition_code}/matches",
                headers=headers,
                params={
                    "dateFrom": today.isoformat(),
                    "dateTo": end_date.isoformat(),
                },
                timeout=20,
            )

            if response.status_code == 429:
                errors.append(
                    f"{competition_code} : limite API atteinte."
                )
                continue

            if response.status_code in (401, 403):
                errors.append(
                    f"{competition_code} : accès non autorisé."
                )
                continue

            response.raise_for_status()

            data = response.json()

            for match in data.get("matches", []):
                match["competition_code"] = competition_code
                matches.append(match)

        except requests.exceptions.RequestException:
            errors.append(
                f"{competition_code} : erreur de connexion."
            )

    matches.sort(
        key=lambda match: match.get("utcDate", "")
    )

    return matches, errors


# =========================================================
# CINQ DERNIERS MATCHS D'UNE ÉQUIPE
# =========================================================

@st.cache_data(ttl=1800, show_spinner=False)
def get_team_history(api_key, team_id):
    """Récupère les derniers matchs terminés d'une équipe."""

    headers = {"X-Auth-Token": api_key}

    try:
        response = requests.get(
            f"{API_URL}/teams/{team_id}/matches",
            headers=headers,
            params={
                "status": "FINISHED",
                "limit": 5,
            },
            timeout=20,
        )

        if response.status_code != 200:
            return []

        data = response.json()

        matches = data.get("matches", [])

        matches.sort(
            key=lambda match: match.get("utcDate", ""),
            reverse=True,
        )

        return matches[:5]

    except requests.exceptions.RequestException:
        return []


# =========================================================
# STATISTIQUES DES ÉQUIPES
# =========================================================

def calculate_team_stats(history, team_id):
    """Calcule les buts marqués, encaissés et la forme."""

    goals_scored = []
    goals_conceded = []
    results = []

    for match in history:
        home_id = match.get("homeTeam", {}).get("id")
        away_id = match.get("awayTeam", {}).get("id")

        score = match.get("score", {}).get("fullTime", {})

        home_goals = score.get("home")
        away_goals = score.get("away")

        if home_goals is None or away_goals is None:
            continue

        if home_id == team_id:
            scored = home_goals
            conceded = away_goals

        elif away_id == team_id:
            scored = away_goals
            conceded = home_goals

        else:
            continue

        goals_scored.append(scored)
        goals_conceded.append(conceded)

        if scored > conceded:
            results.append("V")
        elif scored == conceded:
            results.append("N")
        else:
            results.append("D")

    count = len(goals_scored)

    if count == 0:
        return {
            "matches": 0,
            "scored": None,
            "conceded": None,
            "form": "-",
            "points": None,
        }

    points = sum(
        3 if result == "V"
        else 1 if result == "N"
        else 0
        for result in results
    )

    return {
        "matches": count,
        "scored": sum(goals_scored) / count,
        "conceded": sum(goals_conceded) / count,
        "form": " ".join(results),
        "points": points,
    }


# =========================================================
# MODÈLE DE POISSON
# =========================================================

def poisson_probability(goals, expected_goals):
    """Probabilité de marquer exactement un nombre de buts."""

    if expected_goals < 0:
        return 0.0

    return (
        math.exp(-expected_goals)
        * expected_goals ** goals
        / math.factorial(goals)
    )


def calculate_probabilities(home_lambda, away_lambda):
    """Calcule les probabilités des principaux marchés."""

    max_goals = 10

    home_probs = [
        poisson_probability(g, home_lambda)
        for g in range(max_goals + 1)
    ]

    away_probs = [
        poisson_probability(g, away_lambda)
        for g in range(max_goals + 1)
    ]

    home_win = 0.0
    draw = 0.0
    away_win = 0.0

    over_15 = 0.0
    over_25 = 0.0
    btts = 0.0

    for home_goals in range(max_goals + 1):
        for away_goals in range(max_goals + 1):

            probability = (
                home_probs[home_goals]
                * away_probs[away_goals]
            )

            if home_goals > away_goals:
                home_win += probability

            elif home_goals == away_goals:
                draw += probability

            else:
                away_win += probability

            total_goals = home_goals + away_goals

            if total_goals >= 2:
                over_15 += probability

            if total_goals >= 3:
                over_25 += probability

            if home_goals >= 1 and away_goals >= 1:
                btts += probability

    total = home_win + draw + away_win

    if total > 0:
        home_win /= total
        draw /= total
        away_win /= total

    return {
        "1": home_win,
        "N": draw,
        "2": away_win,
        "1N": home_win + draw,
        "N2": draw + away_win,
        "12": home_win + away_win,
        "Plus de 1,5 but": over_15,
        "Plus de 2,5 buts": over_25,
        "Les deux équipes marquent": btts,
        "Buts domicile estimés": home_lambda,
        "Buts extérieur estimés": away_lambda,
    }


# =========================================================
# ANALYSE AUTOMATIQUE D'UN MATCH
# =========================================================

def analyze_match(api_key, match):
    """Analyse un match à partir des cinq dernières rencontres."""

    home = match.get("homeTeam", {})
    away = match.get("awayTeam", {})

    home_id = home.get("id")
    away_id = away.get("id")

    if not home_id or not away_id:
        return None

    home_history = get_team_history(api_key, home_id)
    away_history = get_team_history(api_key, away_id)

    home_stats = calculate_team_stats(
        home_history,
        home_id,
    )

    away_stats = calculate_team_stats(
        away_history,
        away_id,
    )

    if (
        home_stats["matches"] < 3
        or away_stats["matches"] < 3
    ):
        return {
            "match": match,
            "home_stats": home_stats,
            "away_stats": away_stats,
            "probabilities": None,
            "reason": (
                "Historique insuffisant : "
                "au moins trois matchs exploitables "
                "par équipe sont nécessaires."
            ),
        }

    # Moyennes offensives et défensives récentes.
    home_attack = home_stats["scored"]
    home_defense = home_stats["conceded"]

    away_attack = away_stats["scored"]
    away_defense = away_stats["conceded"]

    # Modèle simple tenant compte de l'avantage à domicile.
    home_lambda = (
        (home_attack + away_defense) / 2
    ) * 1.10

    away_lambda = (
        (away_attack + home_defense) / 2
    ) * 0.95

    # Limites de sécurité du modèle.
    home_lambda = max(0.10, min(home_lambda, 4.0))
    away_lambda = max(0.10, min(away_lambda, 4.0))

    probabilities = calculate_probabilities(
        home_lambda,
        away_lambda,
    )

    return {
        "match": match,
        "home_stats": home_stats,
        "away_stats": away_stats,
        "probabilities": probabilities,
        "reason": None,
    }


# =========================================================
# SÉLECTION AUTOMATIQUE DES PRONOSTICS
# =========================================================

def select_best_predictions(analyses):
    """
    Classe les pronostics selon leurs probabilités.
    Les seuils sont des filtres statistiques, pas une garantie.
    """

    candidates = []

    markets = [
        ("1N", "Domicile ou nul"),
        ("N2", "Extérieur ou nul"),
        ("Plus de 1,5 but", "Plus de 1,5 but"),
        ("Plus de 2,5 buts", "Plus de 2,5 buts"),
        (
            "Les deux équipes marquent",
            "Les deux équipes marquent",
        ),
    ]

    for analysis in analyses:
        probabilities = analysis.get("probabilities")

        if not probabilities:
            continue

        match = analysis["match"]

        for key, label in markets:
            probability = probabilities[key]

            # On écarte les sélections trop incertaines.
            if probability < 0.70:
                continue

            candidates.append({
                "match_id": match.get("id"),
                "match": (
                    f"{match.get('homeTeam', {}).get('name', '?')} "
                    f"– "
                    f"{match.get('awayTeam', {}).get('name', '?')}"
                ),
                "market": label,
                "probability": probability,
                "date": match.get("utcDate", ""),
                "competition": match.get(
                    "competition", {}
                ).get("name", ""),
            })

    candidates.sort(
        key=lambda item: item["probability"],
        reverse=True,
    )

    # Évite de sélectionner deux marchés sur le même match.
    selected = []
    used_matches = set()

    for candidate in candidates:
        match_id = candidate["match_id"]

        if match_id in used_matches:
            continue

        selected.append(candidate)
        used_matches.add(match_id)

        if len(selected) == 2:
            break

    return selected


# =========================================================
# INTERFACE
# =========================================================

st.title("⚽ FOOT AI PRO V6")

st.caption(
    "Analyse automatique des matchs et probabilités statistiques"
)

st.info(
    "Les probabilités sont des estimations statistiques. "
    "Elles ne garantissent aucun résultat sportif."
)

api_key = get_api_key()

if not api_key:
    st.error(
        "Clé API introuvable. Dans Streamlit Cloud, "
        "ouvre Settings > Secrets et vérifie que la clé "
        "FOOTBALL_API_KEY est correctement enregistrée."
    )
    st.stop()

HEADERS = {"X-Auth-Token": api_key}

st.sidebar.header("⚙️ Paramètres")

days = st.sidebar.selectbox(
    "Rechercher les matchs sur",
    [1, 3, 7],
    index=2,
    format_func=lambda value: (
        "Aujourd'hui" if value == 1
        else f"{value} prochains jours"
    ),
)

selected_competitions = st.sidebar.multiselect(
    "Championnats",
    list(COMPETITIONS.keys()),
    default=list(COMPETITIONS.keys()),
)

st.sidebar.caption(
    "Les compétitions visibles dépendent des droits "
    "associés à ta clé football-data.org."
)

if st.button(
    "🔄 Rechercher et analyser les matchs",
    type="primary",
    use_container_width=True,
):

    if not selected_competitions:
        st.warning("Choisis au moins un championnat.")
        st.stop()

    codes = [
        COMPETITIONS[name]
        for name in selected_competitions
    ]

    with st.spinner("Recherche des matchs en cours..."):

        matches, errors = get_matches(
            api_key,
            tuple(codes),
            days,
        )

    if errors:
        with st.expander("Détails des messages API"):
            for error in errors:
                st.warning(error)

    if not matches:
        st.warning(
            "Aucun match disponible pour cette période. "
            "Vérifie les compétitions autorisées et réessaie."
        )
        st.stop()

    st.success(
        f"{len(matches)} match(s) trouvé(s)."
    )

    analyses = []

    progress = st.progress(0)

    for index, match in enumerate(matches):

        analysis = analyze_match(
            api_key,
            match,
        )

        if analysis:
            analyses.append(analysis)

        progress.progress(
            (index + 1) / len(matches)
        )

    progress.empty()

    # Sauvegarde dans la session Streamlit.
    st.session_state["analyses"] = analyses
    st.session_state["last_update"] = datetime.now().strftime(
        "%d/%m/%Y à %H:%M"
    )

    # Sélections automatiques.
    best_predictions = select_best_predictions(
        analyses
    )

    st.session_state["best_predictions"] = best_predictions


# =========================================================
# AFFICHAGE DES RÉSULTATS
# =========================================================

if "analyses" in st.session_state:

    analyses = st.session_state["analyses"]

    st.caption(
        "Dernière analyse : "
        + st.session_state.get("last_update", "")
    )

    st.subheader("🎯 Les meilleures sélections")

    best_predictions = st.session_state.get(
        "best_predictions",
        [],
    )

    if len(best_predictions) < 2:

        st.warning(
            "Moins de deux sélections atteignent le seuil "
            "de 70 %. Mieux vaut ne pas forcer un combiné."
        )

    if best_predictions:

        for index, prediction in enumerate(
            best_predictions,
            start=1,
        ):

            probability = prediction["probability"] * 100

            st.markdown(
                f"**Sélection {index} : "
                f"{prediction['match']}**"
            )

            st.write(
                f"Pronostic : {prediction['market']}"
            )

            st.write(
                f"Probabilité estimée : {probability:.1f} %"
            )

            st.caption(
                f"Compétition : {prediction['competition']}"
            )

            st.progress(
                min(
                    1.0,
                    max(0.0, prediction["probability"]),
                )
            )

    st.divider()

    st.subheader("📊 Toutes les analyses")

    for analysis in analyses:

        match = analysis["match"]

        home_name = match.get(
            "homeTeam", {}
        ).get("name", "Domicile")

        away_name = match.get(
            "awayTeam", {}
        ).get("name", "Extérieur")

        competition_name = match.get(
            "competition", {}
        ).get("name", "Compétition inconnue")

        with st.expander(
            f"{home_name} – {away_name}"
        ):

            st.write(
                f"**Compétition :** {competition_name}"
            )

            st.write(
                f"**Date :** {match.get('utcDate', 'Inconnue')}"
            )

            col1, col2 = st.columns(2)

            with col1:
                st.markdown(f"### {home_name}")

                st.write(
                    f"Derniers résultats : "
                    f"{analysis['home_stats']['form']}"
                )

                st.write(
                    f"Buts marqués par match : "
                    f"{analysis['home_stats']['scored']}"
                )

                st.write(
                    f"Buts encaissés par match : "
                    f"{analysis['home_stats']['conceded']}"
                )

            with col2:
                st.markdown(f"### {away_name}")

                st.write(
                    f"Derniers résultats : "
                    f"{analysis['away_stats']['form']}"
                )

                st.write(
                    f"Buts marqués par match : "
                    f"{analysis['away_stats']['scored']}"
                )

                st.write(
                    f"Buts encaissés par match : "
                    f"{analysis['away_stats']['conceded']}"
                )

            probabilities = analysis["probabilities"]

            if not probabilities:
                st.warning(analysis["reason"])
                continue

            st.markdown("#### Probabilités estimées")

            probability_rows = [
                ("Victoire domicile", probabilities["1"]),
                ("Match nul", probabilities["N"]),
                ("Victoire extérieur", probabilities["2"]),
                ("Domicile ou nul", probabilities["1N"]),
                ("Extérieur ou nul", probabilities["N2"]),
                ("Plus de 1,5 but", probabilities["Plus de 1,5 but"]),
                ("Plus de 2,5 buts", probabilities["Plus de 2,5 buts"]),
                (
                    "Les deux équipes marquent",
                    probabilities["Les deux équipes marquent"],
                ),
            ]

            probability_df = pd.DataFrame(
                probability_rows,
                columns=["Pronostic", "Probabilité"],
            )

            probability_df["Probabilité"] = (
                probability_df["Probabilité"] * 100
            ).round(1).astype(str) + " %"

            st.dataframe(
                probability_df,
                hide_index=True,
                use_container_width=True,
            )

            st.caption(
                "Modèle Poisson simplifié basé sur les "
                "derniers résultats disponibles. "
                "Il ne prend pas encore en compte "
                "les blessures, les compositions officielles, "
                "les suspensions ou les cotes des bookmakers."
            )

    st.divider()

    st.subheader("📥 Exporter les analyses")

    export_rows = []

    for analysis in analyses:

        match = analysis["match"]
        probabilities = analysis["probabilities"]

        row = {
            "Domicile": match.get(
                "homeTeam", {}
            ).get("name", ""),
            "Extérieur": match.get(
                "awayTeam", {}
            ).get("name", ""),
            "Compétition": match.get(
                "competition", {}
            ).get("name", ""),
            "Date": match.get("utcDate", ""),
        }

        if probabilities:
            for key, value in probabilities.items():
                row[key] = round(value * 100, 1)

        else:
            row["Analyse"] = analysis["reason"]

        export_rows.append(row)

    export_df = pd.DataFrame(export_rows)

    st.download_button(
        "📄 Télécharger les analyses en CSV",
        data=export_df.to_csv(
            index=False
        ).encode("utf-8-sig"),
        file_name="foot_ai_pro_analyses.csv",
        mime="text/csv",
        use_container_width=True,
    )

else:

    st.markdown(
        """
        ### 🤖 Ton assistant de pronostics

        1. Choisis les championnats dans le menu.
        2. Sélectionne la période à analyser.
        3. Appuie sur **Rechercher et analyser les matchs**.
        4. Consulte les probabilités et les meilleures sélections.

        L'application recherche les rencontres et calcule
        automatiquement les probabilités à partir des
        résultats disponibles.
        """
    )