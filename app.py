import math
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st


# =====================================================
# FOOT AI PRO - VERSION CHAMPIONNATS ÉLARGIS
# Matchs du jour + analyses + combiné SAFE IA
# =====================================================

st.set_page_config(
    page_title="Foot AI PRO",
    page_icon="⚽",
    layout="wide"
)

API_URL = "https://api.football-data.org/v4"
PARIS_TZ = ZoneInfo("Europe/Paris")

# =====================================================
# CHAMPIONNATS
# =====================================================

COMPETITIONS = {
    # FRANCE
    "Ligue 1": "FL1",
    "Ligue 2": "FL2",

    # ANGLETERRE
    "Premier League": "PL",
    "Championship": "ELC",
    "League One": "EL1",
    "League Two": "EL2",

    # ESPAGNE
    "Liga": "PD",
    "Segunda Division": "SD",

    # ALLEMAGNE
    "Bundesliga": "BL1",
    "2. Bundesliga": "BL2",

    # ITALIE
    "Serie A": "SA",
    "Serie B": "SB",

    # PORTUGAL
    "Primeira Liga": "PPL",

    # PAYS-BAS
    "Eredivisie": "DED",

    # BELGIQUE
    "Jupiler Pro League": "BJL",

    # TURQUIE
    "Süper Lig": "TSL",

    # EUROPE
    "Ligue des champions": "CL",
    "Ligue Europa": "EL",
}


# =====================================================
# INTERFACE
# =====================================================

st.title("⚽ FOOT AI PRO")
st.caption(
    "Pronostics du jour • Championnats internationaux • IA statistique"
)


# =====================================================
# DATE ET HEURE FRANÇAISES
# =====================================================

def paris_now():
    return datetime.now(PARIS_TZ)


def paris_today():
    return paris_now().date()


def format_date(utc_date):
    try:
        dt = datetime.fromisoformat(
            utc_date.replace("Z", "+00:00")
        )
        return dt.astimezone(PARIS_TZ).strftime(
            "%d/%m/%Y à %H:%M"
        )
    except (ValueError, AttributeError):
        return utc_date


# =====================================================
# CONNEXION API
# =====================================================

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

        if response.status_code == 403:
            return None, "Compétition non accessible avec cette clé API"

        if response.status_code == 429:
            return None, "Limite de requêtes API atteinte"

        return None, f"Erreur API : {response.status_code}"

    except requests.RequestException:
        return None, "Erreur de connexion à l'API"


# =====================================================
# MATCHS DU JOUR
# =====================================================

@st.cache_data(ttl=300)
def load_fixtures(day_string):

    fixtures = []
    errors = []

    day = datetime.strptime(
        day_string, "%Y-%m-%d"
    ).date()

    # On récupère une plage UTC élargie pour ne pas
    # manquer les matchs autour de minuit en France.

    date_from = (day - timedelta(days=1)).isoformat()
    date_to = (day + timedelta(days=1)).isoformat()

    for league, code in COMPETITIONS.items():

        data, error = api_get(
            f"/competitions/{code}/matches",
            {
                "dateFrom": date_from,
                "dateTo": date_to,
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

            utc_date = match.get("utcDate", "")

            try:
                kickoff = datetime.fromisoformat(
                    utc_date.replace("Z", "+00:00")
                )

                if kickoff.tzinfo is None:
                    kickoff = kickoff.replace(
                        tzinfo=timezone.utc
                    )

                local_kickoff = kickoff.astimezone(PARIS_TZ)

            except (ValueError, AttributeError):
                continue

            # Uniquement les matchs de la journée française.
            if local_kickoff.date() != day:
                continue

            # Exclure les matchs déjà commencés ou indisponibles.
            if local_kickoff <= paris_now():
                continue

            status = match.get("status", "")

            if status not in ("SCHEDULED", "TIMED"):
                continue

            fixtures.append({
                "id": match.get("id"),
                "competition": league,
                "date": utc_date,
                "home": home["name"],
                "away": away["name"],
                "home_id": home.get("id"),
                "away_id": away.get("id"),
            })

    # Éviter les doublons éventuels.
    unique = {}

    for match in fixtures:
        unique[match["id"]] = match

    fixtures = list(unique.values())

    fixtures.sort(key=lambda x: x["date"])

    return fixtures, errors


# =====================================================
# RÉSULTATS DES MATCHS TERMINÉS
# =====================================================

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

            home = match.get("homeTeam", {})
            away = match.get("awayTeam", {})

            if home_goals is None or away_goals is None:
                continue

            if not home.get("id") or not away.get("id"):
                continue

            results.append({
                "competition": league,
                "date": match.get("utcDate", ""),
                "home": home.get("name", ""),
                "away": away.get("name", ""),
                "home_id": home.get("id"),
                "away_id": away.get("id"),
                "home_goals": int(home_goals),
                "away_goals": int(away_goals),
            })

    results.sort(
        key=lambda x: x["date"],
        reverse=True
    )

    return results, errors


# =====================================================
# STATISTIQUES DES ÉQUIPES
# =====================================================

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

    matches.sort(
        key=lambda x: x["date"],
        reverse=True
    )

    matches = matches[:5]

    if not matches:
        return None

    points = sum(
        3 if m["scored"] > m["conceded"]
        else 1 if m["scored"] == m["conceded"]
        else 0
        for m in matches
    )

    return {
        "played": len(matches),
        "scored": sum(
            m["scored"] for m in matches
        ) / len(matches),
        "conceded": sum(
            m["conceded"] for m in matches
        ) / len(matches),
        "points": points,
        "matches": matches,
    }


# =====================================================
# MODÈLE DE POISSON
# =====================================================

def poisson_probability(goals, expected):

    return (
        math.exp(-expected)
        * expected ** goals
        / math.factorial(goals)
    )


def predict_match(home_id, away_id, results):

    home_home = team_stats(
        home_id, results, "home"
    )

    away_away = team_stats(
        away_id, results, "away"
    )

    home_all = team_stats(home_id, results)
    away_all = team_stats(away_id, results)

    if not home_all or not away_all:
        return None

    if home_home and away_away:

        expected_home = (
            home_home["scored"]
            + away_away["conceded"]
        ) / 2

        expected_away = (
            away_away["scored"]
            + home_home["conceded"]
        ) / 2

    else:

        expected_home = (
            home_all["scored"]
            + away_all["conceded"]
        ) / 2

        expected_away = (
            away_all["scored"]
            + home_all["conceded"]
        ) / 2

    expected_home = max(
        0.05, min(expected_home, 5)
    )

    expected_away = max(
        0.05, min(expected_away, 5)
    )

    p_home = 0.0
    p_draw = 0.0
    p_away = 0.0

    p_over15 = 0.0
    p_over25 = 0.0
    p_btts = 0.0

    scores = []
    total_probability = 0.0

    for h in range(11):
        for a in range(11):

            probability = (
                poisson_probability(h, expected_home)
                * poisson_probability(a, expected_away)
            )

            total_probability += probability

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
                "Score": f"{h}-{a}",
                "Probabilité": probability,
            })

    # Corriger la légère perte de probabilité due
    # à la limitation des scores à 10 buts.

    if total_probability > 0:

        p_home /= total_probability
        p_draw /= total_probability
        p_away /= total_probability
        p_over15 /= total_probability
        p_over25 /= total_probability
        p_btts /= total_probability

    scores.sort(
        key=lambda x: x["Probabilité"],
        reverse=True
    )

    return {
        "home": expected_home,
        "away": expected_away,
        "p_home": p_home,
        "p_draw": p_draw,
        "p_away": p_away,
        "p_over15": p_over15,
        "p_over25": p_over25,
        "p_btts": p_btts,
        "scores": scores[:5],
    }


# =====================================================
# MARCHÉS ANALYSÉS
# =====================================================

def get_markets(prediction):

    return [
        {
            "name": "Victoire domicile",
            "probability": prediction["p_home"],
        },
        {
            "name": "Match nul",
            "probability": prediction["p_draw"],
        },
        {
            "name": "Victoire extérieur",
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


# =====================================================
# CONSTRUCTION DU COMBINÉ SAFE
# =====================================================

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


# =====================================================
# CHARGEMENT DES DONNÉES
# =====================================================

today = paris_today()

with st.spinner("Chargement des données football..."):

    fixtures, fixture_errors = load_fixtures(
        today.isoformat()
    )

    results, result_errors = load_results()


# =====================================================
# ONGLETS
# =====================================================

tab1, tab2, tab3, tab4 = st.tabs([
    "🏠 Accueil",
    "⚽ Matchs du jour",
    "🔥 Combiné SAFE IA",
    "📊 Statistiques",
])


# =====================================================
# ACCUEIL
# =====================================================

with tab1:

    st.subheader("Bienvenue sur Foot AI PRO")

    st.write(
        f"📅 Date française : "
        f"**{today.strftime('%d/%m/%Y')}**"
    )

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Matchs restants aujourd'hui",
        len(fixtures)
    )

    col2.metric(
        "Résultats chargés",
        len(results)
    )

    col3.metric(
        "Championnats configurés",
        len(COMPETITIONS)
    )

    st.info(
        "L'application analyse les matchs prévus aujourd'hui, "
        "les résultats récents et les probabilités de buts."
    )

    st.caption(
        "Les estimations statistiques ne garantissent "
        "pas les résultats sportifs."
    )

    if not fixtures:

        st.warning(
            "Aucun match restant aujourd'hui n'a été récupéré. "
            "Vérifie les compétitions accessibles et les "
            "éventuelles erreurs API dans l'onglet Statistiques."
        )


# =====================================================
# MATCHS DU JOUR
# =====================================================

with tab2:

    st.subheader("⚽ Tous les matchs du jour")

    if fixtures:

        selected_league = st.selectbox(
            "Filtrer par championnat",
            ["Tous"] + list(COMPETITIONS.keys())
        )

        filtered = fixtures

        if selected_league != "Tous":

            filtered = [
                match for match in fixtures
                if match["competition"] == selected_league
            ]

        if not filtered:

            st.info(
                "Aucun match restant aujourd'hui "
                "dans cette compétition."
            )

        for match in filtered:

            with st.expander(
                f'{match["home"]} - {match["away"]}'
            ):

                st.write(
                    "Championnat :",
                    match["competition"]
                )

                st.write(
                    "Heure française :",
                    format_date(match["date"])
                )

                prediction = predict_match(
                    match["home_id"],
                    match["away_id"],
                    results
                )

                if not prediction:

                    st.warning(
                        "Pas assez de résultats disponibles "
                        "pour analyser ce match."
                    )

                    continue

                st.write(
                    f'Buts attendus : '
                    f'{prediction["home"]:.2f} - '
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
                    f'Plus de 1,5 but : '
                    f'{prediction["p_over15"] * 100:.1f} %'
                )

                st.write(
                    f'Plus de 2,5 buts : '
                    f'{prediction["p_over25"] * 100:.1f} %'
                )

                st.write(
                    f'Les deux équipes marquent : '
                    f'{prediction["p_btts"] * 100:.1f} %'
                )

                st.write("Scores les plus probables")

                st.dataframe(
                    pd.DataFrame(prediction["scores"]),
                    hide_index=True,
                    use_container_width=True
                )

    else:

        st.info(
            "Aucun match restant aujourd'hui "
            "dans les compétitions accessibles."
        )


# =====================================================
# COMBINÉ SAFE IA
# =====================================================

with tab3:

    st.subheader("🔥 COMBINÉ SAFE IA — 2 MATCHS")

    st.write(
        "Recherche des deux sélections présentant "
        "les probabilités estimées les plus élevées "
        "parmi les matchs du jour."
    )

    st.warning(
        "Les cotes ne sont pas récupérées automatiquement. "
        "Renseigne les cotes réelles de ton bookmaker."
    )

    candidates = build_candidates(
        fixtures,
        results
    )

    if len(candidates) < 2:

        st.warning(
            "Moins de deux sélections répondent aux critères "
            "statistiques. Aucun combiné ne sera proposé."
        )

    else:

        chosen = []
        used_ids = set()

        for candidate in candidates:

            if candidate["id"] in used_ids:
                continue

            chosen.append(candidate)
            used_ids.add(candidate["id"])

            if len(chosen) == 2:
                break

        if len(chosen) < 2:

            st.warning(
                "Deux matchs distincts sont nécessaires."
            )

        else:

            st.success(
                "Deux sélections retenues selon le classement "
                "statistique du modèle."
            )

            for index, match in enumerate(
                chosen,
                start=1
            ):

                st.markdown(f"### Match {index}")

                st.write(
                    f'**{match["home"]} - {match["away"]}**'
                )

                st.write(
                    "Championnat :",
                    match["competition"]
                )

                st.write(
                    "Heure française :",
                    format_date(match["date"])
                )

                st.write(
                    f'Pronostic IA : **{match["market"]}**'
                )

                st.write(
                    "Probabilité estimée : "
                    f'**{match["probability"] * 100:.1f} %**'
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

            probability1 = chosen[0]["probability"]
            probability2 = chosen[1]["probability"]

            # Hypothèse simplificatrice d'indépendance.
            combined_probability = probability1 * probability2

            st.divider()

            st.metric(
                "Cote combinée",
                f"{combined_odds:.2f}"
            )

            st.metric(
                "Probabilité théorique du combiné",
                f"{combined_probability * 100:.1f} %"
            )

            if 1.50 <= combined_odds <= 2.00:

                st.success(
                    "La cote combinée se situe entre 1,50 et 2,00."
                )

            else:

                st.warning(
                    "La cote combinée est hors de la plage "
                    "souhaitée. Vérifie les cotes ou les sélections."
                )

            if combined_probability >= 0.80:

                st.success(
                    "Le modèle estime une probabilité théorique "
                    "d'au moins 80 %. Ce résultat n'est pas garanti."
                )

            else:

                st.warning(
                    "La probabilité théorique du combiné "
                    "est inférieure à 80 %."
                )

            st.caption(
                "Le produit des probabilités suppose leur "
                "indépendance. Le modèle n'a pas été calibré "
                "sur un échantillon indépendant de résultats : "
                "sa probabilité estimée peut être imprécise."
            )


# =====================================================
# STATISTIQUES ET ERREURS API
# =====================================================

with tab4:

    st.subheader("📊 Statistiques")

    st.write(
        "Date française :",
        today.strftime("%d/%m/%Y")
    )

    st.write(
        "Matchs restants aujourd'hui :",
        len(fixtures)
    )

    st.write(
        "Résultats disponibles :",
        len(results)
    )

    st.write(
        "Championnats configurés :",
        len(COMPETITIONS)
    )

    st.write("Liste des championnats :")

    for league in COMPETITIONS:
        st.write(f"• {league}")

    all_errors = fixture_errors + result_errors

    if all_errors:

        st.warning(
            "Certaines compétitions n'ont pas pu être chargées."
        )

        for error in all_errors:
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