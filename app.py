import math
import os
from datetime import date, timedelta

import pandas as pd
import requests
import streamlit as st


# ==================================================
# FOOT AI PRO V7
# Pronostics + combiné IA de deux matchs
# ==================================================

st.set_page_config(
    page_title="Foot AI PRO",
    page_icon="⚽",
    layout="wide"
)

API_URL = "https://api.football-data.org/v4"

COMPETITIONS = {
    "Ligue 1": "FL1",
    "Premier League": "PL",
    "Liga": "PD",
    "Bundesliga": "BL1",
    "Serie A": "SA",
    "Ligue des champions": "CL",
}

st.title("⚽ FOOT AI PRO")
st.caption("Analyse statistique du football et pronostics")


# ==================================================
# CONNEXION API
# ==================================================

def get_api_key():
    try:
        return st.secrets["FOOTBALL_API_KEY"]
    except Exception:
        return os.environ.get("FOOTBALL_API_KEY", "")


def api_get(endpoint, params=None):
    key = get_api_key()

    if not key:
        return None, "Clé API absente"

    try:
        response = requests.get(
            f"{API_URL}{endpoint}",
            headers={"X-Auth-Token": key},
            params=params,
            timeout=20
        )

        if response.status_code == 200:
            return response.json(), None

        if response.status_code == 429:
            return None, "Limite de requêtes API atteinte"

        return None, f"Erreur API : {response.status_code}"

    except requests.RequestException:
        return None, "Connexion à l'API impossible"


# ==================================================
# CHARGEMENT DES MATCHS
# ==================================================

@st.cache_data(ttl=900)
def load_fixtures():
    fixtures = []
    errors = []

    start = date.today()
    end = start + timedelta(days=7)

    for league, code in COMPETITIONS.items():

        data, error = api_get(
            f"/competitions/{code}/matches",
            {
                "dateFrom": start.isoformat(),
                "dateTo": end.isoformat(),
                "status": "SCHEDULED"
            }
        )

        if error:
            errors.append(f"{league} : {error}")
            continue

        for match in data.get("matches", []):
            home = match.get("homeTeam", {})
            away = match.get("awayTeam", {})

            if not home.get("name") or not away.get("name"):
                continue

            fixtures.append({
                "id": match.get("id"),
                "competition": league,
                "date": match.get("utcDate", ""),
                "home": home["name"],
                "away": away["name"],
                "home_id": home.get("id"),
                "away_id": away.get("id"),
            })

    return fixtures, errors


@st.cache_data(ttl=3600)
def load_results():
    results = []
    errors = []

    for league, code in COMPETITIONS.items():

        data, error = api_get(
            f"/competitions/{code}/matches",
            {"status": "FINISHED"}
        )

        if error:
            errors.append(f"{league} : {error}")
            continue

        for match in data.get("matches", []):

            score = match.get("score", {}).get("fullTime", {})
            home_goals = score.get("home")
            away_goals = score.get("away")

            if home_goals is None or away_goals is None:
                continue

            results.append({
                "competition": league,
                "date": match.get("utcDate", ""),
                "home": match.get("homeTeam", {}).get("name", ""),
                "away": match.get("awayTeam", {}).get("name", ""),
                "home_id": match.get("homeTeam", {}).get("id"),
                "away_id": match.get("awayTeam", {}).get("id"),
                "home_goals": int(home_goals),
                "away_goals": int(away_goals),
            })

    results.sort(key=lambda x: x["date"], reverse=True)

    return results, errors


# ==================================================
# FORME DES ÉQUIPES
# ==================================================

def team_stats(team_id, results, venue=None):

    matches = []

    for match in results:

        is_home = match["home_id"] == team_id
        is_away = match["away_id"] == team_id

        if not is_home and not is_away:
            continue

        if venue == "home" and not is_home:
            continue

        if venue == "away" and not is_away:
            continue

        if is_home:
            scored = match["home_goals"]
            conceded = match["away_goals"]
        else:
            scored = match["away_goals"]
            conceded = match["home_goals"]

        matches.append({
            "scored": scored,
            "conceded": conceded,
            "date": match["date"],
        })

    matches.sort(key=lambda x: x["date"], reverse=True)
    matches = matches[:5]

    if not matches:
        return None

    return {
        "played": len(matches),
        "scored": sum(m["scored"] for m in matches) / len(matches),
        "conceded": sum(m["conceded"] for m in matches) / len(matches),
        "points": sum(
            3 if m["scored"] > m["conceded"]
            else 1 if m["scored"] == m["conceded"]
            else 0
            for m in matches
        ),
        "matches": matches,
    }


# ==================================================
# MODÈLE DE POISSON
# ==================================================

def poisson_probability(goals, expected):

    if expected < 0:
        return 0

    return (
        math.exp(-expected)
        * expected ** goals
        / math.factorial(goals)
    )


def predict_match(home_id, away_id, results):

    home_home = team_stats(home_id, results, "home")
    away_away = team_stats(away_id, results, "away")

    home_all = team_stats(home_id, results)
    away_all = team_stats(away_id, results)

    if not home_all or not away_all:
        return None

    # Les statistiques domicile/extérieur sont utilisées
    # lorsqu'elles sont disponibles.

    if home_home and away_away:
        expected_home = (
            home_home["scored"] + away_away["conceded"]
        ) / 2

        expected_away = (
            away_away["scored"] + home_home["conceded"]
        ) / 2

    else:
        expected_home = (
            home_all["scored"] + away_all["conceded"]
        ) / 2

        expected_away = (
            away_all["scored"] + home_all["conceded"]
        ) / 2

    # Limitation numérique des moyennes de buts.
    expected_home = max(0.05, min(expected_home, 5))
    expected_away = max(0.05, min(expected_away, 5))

    p_home = 0
    p_draw = 0
    p_away = 0
    p_over15 = 0
    p_over25 = 0
    p_btts = 0

    scores = []

    for h in range(9):
        for a in range(9):

            probability = (
                poisson_probability(h, expected_home)
                * poisson_probability(a, expected_away)
            )

            if h > a:
                p_home += probability
            elif h == a:
                p_draw += probability
            else:
                p_away += probability

            if h + a >= 2:
                p_over15 += probability

            if h + a >= 3:
                p_over25 += probability

            if h >= 1 and a >= 1:
                p_btts += probability

            scores.append({
                "score": f"{h}-{a}",
                "probability": probability
            })

    total = p_home + p_draw + p_away

    if total:
        p_home /= total
        p_draw /= total
        p_away /= total

    # Le modèle utilise la somme des probabilités
    # calculées sur les scores de 0 à 8 buts.

    return {
        "home": expected_home,
        "away": expected_away,
        "p_home": p_home,
        "p_draw": p_draw,
        "p_away": p_away,
        "p_over15": p_over15,
        "p_over25": p_over25,
        "p_btts": p_btts,
        "scores": sorted(
            scores,
            key=lambda x: x["probability"],
            reverse=True
        )[:5]
    }


# ==================================================
# SÉLECTION DES PRONOSTICS
# ==================================================

def get_markets(prediction):

    return [
        {
            "name": "1 - Victoire domicile",
            "probability": prediction["p_home"],
        },
        {
            "name": "N - Match nul",
            "probability": prediction["p_draw"],
        },
        {
            "name": "2 - Victoire extérieur",
            "probability": prediction["p_away"],
        },
        {
            "name": "Plus de 1,5 but",
            "probability": prediction["p_over15"],
        },
        {
            "name": "Plus de 2,5 buts",
            "probability": prediction["p_over25"],
        },
        {
            "name": "Les deux équipes marquent",
            "probability": prediction["p_btts"],
        },
    ]


def build_candidates(fixtures, results):

    candidates = []

    for match in fixtures:

        prediction = predict_match(
            match["home_id"],
            match["away_id"],
            results
        )

        if not prediction:
            continue

        markets = get_markets(prediction)

        # On conserve les marchés ayant une probabilité
        # estimée d'au moins 70 % pour la présélection.
        eligible = [
            market for market in markets
            if market["probability"] >= 0.70
        ]

        if not eligible:
            continue

        best_market = max(
            eligible,
            key=lambda x: x["probability"]
        )

        candidates.append({
            **match,
            "prediction": prediction,
            "market": best_market["name"],
            "probability": best_market["probability"],
        })

    candidates.sort(
        key=lambda x: x["probability"],
        reverse=True
    )

    return candidates


# ==================================================
# ONGLETS
# ==================================================

tab1, tab2, tab3, tab4 = st.tabs([
    "🏠 Accueil",
    "⚽ Matchs",
    "🔥 Combiné SAFE IA",
    "📊 Statistiques"
])


with st.spinner("Chargement des matchs et résultats..."):
    fixtures, fixture_errors = load_fixtures()
    results, result_errors = load_results()


with tab1:

    st.subheader("Bienvenue sur Foot AI PRO")

    col1, col2, col3 = st.columns(3)

    col1.metric("Matchs à venir", len(fixtures))
    col2.metric("Résultats récupérés", len(results))
    col3.metric("Championnats", len(COMPETITIONS))

    st.info(
        "L'application analyse les données disponibles "
        "et estime les probabilités à l'aide d'un modèle "
        "statistique de Poisson."
    )

    st.caption(
        "Une estimation statistique n'est pas une garantie "
        "de résultat. Les données incomplètes peuvent réduire "
        "la fiabilité des prévisions."
    )

    if not fixtures:
        st.warning(
            "Aucun match à venir n'a été récupéré. "
            "Vérifie la connexion API et les compétitions accessibles."
        )


with tab2:

    st.subheader("⚽ Analyse des matchs")

    if fixtures:

        selected_league = st.selectbox(
            "Choisir un championnat",
            ["Tous"] + list(COMPETITIONS.keys())
        )

        filtered = fixtures

        if selected_league != "Tous":
            filtered = [
                m for m in fixtures
                if m["competition"] == selected_league
            ]

        if not filtered:
            st.info("Aucun match dans cette sélection.")

        for match in filtered:

            with st.expander(
                f'{match["home"]} - {match["away"]}'
            ):

                st.write("Championnat :", match["competition"])
                st.write("Date UTC :", match["date"])

                prediction = predict_match(
                    match["home_id"],
                    match["away_id"],
                    results
                )

                if not prediction:
                    st.warning(
                        "Pas assez de résultats disponibles "
                        "pour analyser les deux équipes."
                    )
                    continue

                st.write(
                    f'Buts attendus : {prediction["home"]:.2f} - '
                    f'{prediction["away"]:.2f}'
                )

                col1, col2, col3 = st.columns(3)

                col1.metric(
                    "Victoire domicile",
                    f'{prediction["p_home"] * 100:.1f} %'
                )

                col2.metric(
                    "Match nul",
                    f'{prediction["p_draw"] * 100:.1f} %'
                )

                col3.metric(
                    "Victoire extérieur",
                    f'{prediction["p_away"] * 100:.1f} %'
                )

                st.write(
                    "Plus de 1,5 but : "
                    f'{prediction["p_over15"] * 100:.1f} %'
                )

                st.write(
                    "Plus de 2,5 buts : "
                    f'{prediction["p_over25"] * 100:.1f} %'
                )

                st.write(
                    "Les deux équipes marquent : "
                    f'{prediction["p_btts"] * 100:.1f} %'
                )

                st.write("Scores les plus probables :")

                st.dataframe(
                    pd.DataFrame(prediction["scores"]),
                    hide_index=True,
                    use_container_width=True
                )

    else:
        st.info("Aucun match disponible pour le moment.")


with tab3:

    st.subheader("🔥 COMBINÉ SAFE IA — 2 MATCHS")

    st.write(
        "L'IA compare les matchs accessibles et recherche "
        "deux sélections statistiquement favorables."
    )

    st.warning(
        "Les cotes des bookmakers ne sont pas fournies "
        "par cette source de données. Les cotes doivent "
        "être vérifiées puis renseignées manuellement."
    )

    candidates = build_candidates(fixtures, results)

    if len(candidates) < 2:

        st.warning(
            "Moins de deux sélections répondent aux critères "
            "actuels. Aucune combinaison ne peut être proposée "
            "avec ces critères."
        )

    else:

        # Deux matchs différents sont obligatoires.
        chosen = []

        for candidate in candidates:

            if all(
                candidate["id"] != item["id"]
                for item in chosen
            ):
                chosen.append(candidate)

            if len(chosen) == 2:
                break

        if len(chosen) < 2:

            st.warning("Deux matchs distincts sont nécessaires.")

        else:

            st.success("Les deux sélections les mieux classées")

            for index, match in enumerate(chosen, start=1):

                st.markdown(f"### Match {index}")

                st.write(
                    f'**{match["home"]} - {match["away"]}**'
                )

                st.write(
                    f'Championnat : {match["competition"]}'
                )

                st.write(
                    f'Pronostic IA : **{match["market"]}**'
                )

                st.write(
                    "Probabilité estimée du pronostic : "
                    f'**{match["probability"] * 100:.1f} %**'
                )

                st.caption(
                    "Cette probabilité provient du modèle "
                    "statistique, pas d'une garantie réelle."
                )

                st.number_input(
                    f"Cote réelle du match {index}",
                    min_value=1.01,
                    max_value=100.0,
                    value=1.50,
                    step=0.05,
                    key=f"odds_{index}"
                )

            odds1 = st.session_state.get("odds_1", 1.50)
            odds2 = st.session_state.get("odds_2", 1.50)

            combined_odds = odds1 * odds2

            st.divider()

            st.metric(
                "Cote combinée",
                f"{combined_odds:.2f}"
            )

            # Probabilité du combiné calculée sous hypothèse
            # d'indépendance des deux événements.
            probability1 = chosen[0]["probability"]
            probability2 = chosen[1]["probability"]

            combined_probability = probability1 * probability2

            st.metric(
                "Probabilité théorique du combiné",
                f"{combined_probability * 100:.1f} %"
            )

            if 1.50 <= combined_odds <= 2.00:

                st.success(
                    "La cote combinée se situe dans la plage "
                    "demandée : 1,50 à 2,00."
                )

            else:

                st.warning(
                    "La cote combinée est en dehors de la plage "
                    "demandée. Modifie les cotes renseignées "
                    "pour comparer une autre combinaison."
                )

            if combined_probability >= 0.80:

                st.success(
                    "Le modèle estime une probabilité théorique "
                    "d'au moins 80 %. Cela ne garantit pas "
                    "la réussite du combiné."
                )

            else:

                st.info(
                    "Le modèle n'atteint pas 80 % de probabilité "
                    "théorique sur ce combiné. Ne considère pas "
                    "cette sélection comme sûre."
                )

            st.caption(
                "Important : le calcul multiplie les probabilités "
                "des deux sélections et suppose leur indépendance. "
                "Les probabilités du modèle ne sont pas calibrées "
                "et peuvent être imprécises. La cote saisie "
                "manuellement n'est pas vérifiée par l'application."
            )


with tab4:

    st.subheader("📊 État des données")

    st.write("Championnats configurés :")

    for league in COMPETITIONS:
        st.write(f"• {league}")

    st.write(f"Matchs à venir chargés : {len(fixtures)}")
    st.write(f"Résultats chargés : {len(results)}")

    if fixture_errors or result_errors:

        st.warning("Certaines données n'ont pas pu être chargées.")

        for error in fixture_errors + result_errors:
            st.write(f"• {error}")

    if results:

        st.write("Derniers résultats récupérés :")

        st.dataframe(
            pd.DataFrame(results).head(20),
            hide_index=True,
            use_container_width=True
        )

    if st.button("🔄 Actualiser les données"):

        st.cache_data.clear()
        st.rerun()