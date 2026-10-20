import os
import math
import itertools
from datetime import date, timedelta

import pandas as pd
import requests
import streamlit as st


# =========================================================
# FOOT AI PRO
# Application complète de pronostics football
# API : football-data.org
# =========================================================

st.set_page_config(
    page_title="FOOT AI PRO",
    page_icon="⚽",
    layout="wide"
)

API_URL = "https://api.football-data.org/v4"

COMPETITIONS = {
    "France - Ligue 1": "FL1",
    "Angleterre - Premier League": "PL",
    "Espagne - Liga": "PD",
    "Allemagne - Bundesliga": "BL1",
    "Italie - Serie A": "SA",
    "Ligue des champions": "CL",
    "Pays-Bas - Eredivisie": "DED",
    "Portugal - Liga Portugal": "PPL",
    "Belgique - Pro League": "BJL",
    "France - Ligue 2": "FL2",
}


# =========================================================
# STYLE
# =========================================================

st.markdown(
    """
    <style>
    .main-title {
        text-align: center;
        font-size: 38px;
        font-weight: 900;
        color: #00c878;
    }
    .subtitle {
        text-align: center;
        color: #aaaaaa;
        margin-bottom: 25px;
    }
    .match-card {
        padding: 15px;
        border-radius: 12px;
        border: 1px solid #444444;
        margin-bottom: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown(
    '<div class="main-title">⚽ FOOT AI PRO</div>',
    unsafe_allow_html=True
)

st.markdown(
    '<div class="subtitle">'
    'Analyse statistique automatique des matchs de football'
    '</div>',
    unsafe_allow_html=True
)


# =========================================================
# CONFIGURATION API
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


@st.cache_data(ttl=300, show_spinner=False)
def api_get(endpoint, api_key):
    if not api_key:
        return None, "Clé API manquante."

    headers = {"X-Auth-Token": api_key}

    try:
        response = requests.get(
            f"{API_URL}{endpoint}",
            headers=headers,
            timeout=20
        )

        if response.status_code == 200:
            return response.json(), None

        if response.status_code == 401:
            return None, "Clé API invalide."

        if response.status_code == 403:
            return None, (
                "Accès refusé : cette compétition ou cette donnée "
                "n'est peut-être pas comprise dans ton abonnement."
            )

        if response.status_code == 429:
            return None, (
                "Limite de requêtes API atteinte. "
                "Attends avant de réessayer."
            )

        return None, (
            f"Erreur API {response.status_code} : "
            f"{response.text[:200]}"
        )

    except requests.RequestException as exc:
        return None, f"Erreur de connexion : {exc}"


# =========================================================
# RÉCUPÉRATION DES MATCHS
# =========================================================

@st.cache_data(ttl=300, show_spinner=False)
def get_matches(api_key, competition_code, start_date, end_date):
    endpoint = (
        f"/competitions/{competition_code}/matches"
        f"?dateFrom={start_date}&dateTo={end_date}"
    )

    data, error = api_get(endpoint, api_key)

    if error or not data:
        return [], error

    matches = data.get("matches", [])

    matches.sort(key=lambda match: match.get("utcDate", ""))

    return matches, None


# =========================================================
# HISTORIQUE DES ÉQUIPES
# =========================================================

@st.cache_data(ttl=900, show_spinner=False)
def get_team_history(api_key, team_id, before_date):
    endpoint = (
        f"/teams/{team_id}/matches"
        f"?status=FINISHED&dateTo={before_date}&limit=10"
    )

    data, error = api_get(endpoint, api_key)

    if error or not data:
        return []

    matches = data.get("matches", [])

    matches.sort(
        key=lambda match: match.get("utcDate", ""),
        reverse=True
    )

    return matches[:10]


# =========================================================
# ANALYSE DES DERNIERS MATCHS
# =========================================================

def analyze_team(team_id, api_key, before_date):
    matches = get_team_history(api_key, team_id, before_date)

    goals_for = []
    goals_against = []
    points = []
    home_goals = []
    away_goals = []

    for match in matches:
        home = match.get("homeTeam") or {}
        away = match.get("awayTeam") or {}
        score = match.get("score", {}).get("fullTime") or {}

        hg = score.get("home")
        ag = score.get("away")

        if hg is None or ag is None:
            continue

        if home.get("id") == team_id:
            gf, ga = hg, ag
            home_goals.append(hg)
        elif away.get("id") == team_id:
            gf, ga = ag, hg
            away_goals.append(ag)
        else:
            continue

        goals_for.append(gf)
        goals_against.append(ga)

        if gf > ga:
            points.append(3)
        elif gf == ga:
            points.append(1)
        else:
            points.append(0)

    if not goals_for:
        return {
            "matches": 0,
            "goals_for": 1.25,
            "goals_against": 1.25,
            "points": 0,
            "form": "Inconnue",
            "reliability": 0.20,
            "home_goals": [],
            "away_goals": [],
        }

    form_letters = []

    for match in matches:
        if len(form_letters) >= 5:
            break

        home = match.get("homeTeam") or {}
        away = match.get("awayTeam") or {}
        score = match.get("score", {}).get("fullTime") or {}

        hg = score.get("home")
        ag = score.get("away")

        if hg is None or ag is None:
            continue

        if home.get("id") == team_id:
            gf, ga = hg, ag
        elif away.get("id") == team_id:
            gf, ga = ag, hg
        else:
            continue

        if gf > ga:
            form_letters.append("V")
        elif gf == ga:
            form_letters.append("N")
        else:
            form_letters.append("D")

    count = len(goals_for)

    return {
        "matches": count,
        "goals_for": sum(goals_for) / count,
        "goals_against": sum(goals_against) / count,
        "points": sum(points) / count,
        "form": " - ".join(form_letters) if form_letters else "Inconnue",
        "reliability": min(count / 5, 1.0),
        "home_goals": home_goals,
        "away_goals": away_goals,
    }


# =========================================================
# MODÈLE DE POISSON
# =========================================================

def poisson_probability(lam, goals):
    if lam < 0:
        return 0.0

    if lam == 0:
        return 1.0 if goals == 0 else 0.0

    return (math.exp(-lam) * lam ** goals) / math.factorial(goals)


def estimate_match(home_stats, away_stats):
    # Estimation simplifiée : elle n'utilise pas de véritable
    # base de données complète des forces offensives/défensives.
    home_reliability = home_stats["reliability"]
    away_reliability = away_stats["reliability"]

    home_attack = home_stats["goals_for"]
    away_defense = away_stats["goals_against"]

    away_attack = away_stats["goals_for"]
    home_defense = home_stats["goals_against"]

    home_lambda = (
        0.55 * home_attack
        + 0.45 * away_defense
        + 0.25
    )

    away_lambda = (
        0.55 * away_attack
        + 0.45 * home_defense
    )

    # Réglage des valeurs extrêmes.
    home_lambda = max(0.15, min(home_lambda, 3.5))
    away_lambda = max(0.15, min(away_lambda, 3.5))

    home_win = 0.0
    draw = 0.0
    away_win = 0.0

    max_goals = 8

    for hg in range(max_goals + 1):
        for ag in range(max_goals + 1):
            probability = (
                poisson_probability(home_lambda, hg)
                * poisson_probability(away_lambda, ag)
            )

            if hg > ag:
                home_win += probability
            elif hg == ag:
                draw += probability
            else:
                away_win += probability

    total = home_win + draw + away_win

    if total > 0:
        home_win /= total
        draw /= total
        away_win /= total

    over_15 = 1 - sum(
        poisson_probability(home_lambda, hg)
        * poisson_probability(away_lambda, ag)
        for hg in range(9)
        for ag in range(9)
        if hg + ag <= 1
    )

    over_25 = 1 - sum(
        poisson_probability(home_lambda, hg)
        * poisson_probability(away_lambda, ag)
        for hg in range(9)
        for ag in range(9)
        if hg + ag <= 2
    )

    btts = 1 - math.exp(-home_lambda) - math.exp(-away_lambda) + (
        math.exp(-home_lambda - away_lambda)
    )

    reliability = (
        home_reliability + away_reliability
    ) / 2

    return {
        "home_win": home_win,
        "draw": draw,
        "away_win": away_win,
        "over_15": max(0.0, min(over_15, 1.0)),
        "over_25": max(0.0, min(over_25, 1.0)),
        "btts": max(0.0, min(btts, 1.0)),
        "home_lambda": home_lambda,
        "away_lambda": away_lambda,
        "reliability": reliability,
    }


# =========================================================
# PRONOSTIC PRINCIPAL
# =========================================================

def best_pick(probabilities):
    candidates = [
        ("Victoire domicile", probabilities["home_win"]),
        ("Match nul", probabilities["draw"]),
        ("Victoire extérieur", probabilities["away_win"]),
        ("Plus de 1,5 but", probabilities["over_15"]),
        ("Plus de 2,5 buts", probabilities["over_25"]),
        ("Les deux équipes marquent", probabilities["btts"]),
    ]

    candidates.sort(key=lambda item: item[1], reverse=True)

    return candidates[0]


def analyze_fixture(match, api_key):
    home = match.get("homeTeam") or {}
    away = match.get("awayTeam") or {}

    home_id = home.get("id")
    away_id = away.get("id")

    if not home_id or not away_id:
        return None

    kickoff = match.get("utcDate", "")[:10]

    home_stats = analyze_team(home_id, api_key, kickoff)
    away_stats = analyze_team(away_id, api_key, kickoff)

    probabilities = estimate_match(home_stats, away_stats)

    pick, pick_probability = best_pick(probabilities)

    sample_count = min(
        home_stats["matches"],
        away_stats["matches"]
    )

    if sample_count < 3:
        confidence = "Données insuffisantes"
    elif sample_count < 5:
        confidence = "Fiabilité limitée"
    else:
        confidence = "Historique disponible"

    return {
        "date": match.get("utcDate", ""),
        "competition": (
            (match.get("competition") or {}).get("name", "Compétition")
        ),
        "home": home.get("name", "Domicile"),
        "away": away.get("name", "Extérieur"),
        "home_form": home_stats["form"],
        "away_form": away_stats["form"],
        "home_matches": home_stats["matches"],
        "away_matches": away_stats["matches"],
        "home_lambda": probabilities["home_lambda"],
        "away_lambda": probabilities["away_lambda"],
        "home_win": probabilities["home_win"],
        "draw": probabilities["draw"],
        "away_win": probabilities["away_win"],
        "over_15": probabilities["over_15"],
        "over_25": probabilities["over_25"],
        "btts": probabilities["btts"],
        "pick": pick,
        "pick_probability": pick_probability,
        "reliability": probabilities["reliability"],
        "confidence": confidence,
    }


# =========================================================
# INTERFACE
# =========================================================

if not API_KEY:
    st.error(
        "Clé API absente. Configure FOOTBALL_DATA_API_KEY "
        "dans les Secrets de Streamlit."
    )
    st.info(
        "Dans les paramètres de ton application Streamlit, "
        "ajoute ta clé API sous ce nom : "
        "FOOTBALL_DATA_API_KEY"
    )
    st.stop()


st.sidebar.header("⚙️ Paramètres")

today = date.today()

start_date = st.sidebar.date_input(
    "Date de début",
    value=today
)

end_date = st.sidebar.date_input(
    "Date de fin",
    value=today + timedelta(days=3),
    min_value=start_date
)

selected_competitions = st.sidebar.multiselect(
    "Championnats",
    options=list(COMPETITIONS.keys()),
    default=[
        "France - Ligue 1",
        "Angleterre - Premier League",
        "Espagne - Liga",
        "Allemagne - Bundesliga",
        "Italie - Serie A",
        "Ligue des champions",
    ]
)

max_matches = st.sidebar.slider(
    "Nombre maximum de matchs analysés",
    min_value=5,
    max_value=100,
    value=30,
    step=5
)

minimum_probability = st.sidebar.slider(
    "Probabilité minimale affichée (%)",
    min_value=40,
    max_value=90,
    value=55,
    step=5
)

if st.sidebar.button("🔄 Actualiser les données"):
    st.cache_data.clear()
    st.rerun()


# =========================================================
# RÉCUPÉRATION AUTOMATIQUE DES MATCHS
# =========================================================

if start_date > end_date:
    st.error("La date de début doit précéder la date de fin.")
    st.stop()

if not selected_competitions:
    st.warning("Sélectionne au moins un championnat.")
    st.stop()

all_matches = []
api_errors = []

with st.spinner("Recherche automatique des matchs..."):
    for competition_name in selected_competitions:
        competition_code = COMPETITIONS[competition_name]

        matches, error = get_matches(
            API_KEY,
            competition_code,
            start_date.isoformat(),
            end_date.isoformat()
        )

        if error:
            api_errors.append(f"{competition_name} : {error}")
            continue

        for match in matches:
            match["competition"] = {
                "name": competition_name
            }
            all_matches.append(match)

# Éviter les doublons.
unique_matches = {}

for match in all_matches:
    unique_matches[match.get("id")] = match

all_matches = list(unique_matches.values())

all_matches.sort(key=lambda item: item.get("utcDate", ""))

if api_errors:
    with st.expander("⚠️ Problèmes de récupération des données"):
        for error in api_errors:
            st.warning(error)

if not all_matches:
    st.warning(
        "Aucun match trouvé pour cette période. "
        "Essaie d'autres dates ou vérifie les compétitions accessibles "
        "avec ta clé API."
    )
    st.stop()

st.success(f"{len(all_matches)} matchs trouvés.")


# =========================================================
# ANALYSE AUTOMATIQUE
# =========================================================

fixtures_to_analyze = all_matches[:max_matches]

results = []

with st.spinner(
    f"Analyse statistique de {len(fixtures_to_analyze)} matchs..."
):
    progress = st.progress(0)

    for index, match in enumerate(fixtures_to_analyze):
        result = analyze_fixture(match, API_KEY)

        if result:
            results.append(result)

        progress.progress(
            int((index + 1) / len(fixtures_to_analyze) * 100)
        )

    progress.empty()

if not results:
    st.warning(
        "Impossible de produire des analyses avec les données reçues."
    )
    st.stop()


# =========================================================
# CLASSEMENT DES PRONOSTICS
# =========================================================

results.sort(
    key=lambda item: (
        item["reliability"] * item["pick_probability"]
    ),
    reverse=True
)

st.header("🏆 Classement des meilleurs pronostics")

st.caption(
    "Classement statistique indicatif. "
    "Une probabilité élevée ne garantit pas le résultat."
)

ranked_rows = []

for index, result in enumerate(results, start=1):
    ranked_rows.append({
        "Rang": index,
        "Match": f'{result["home"]} - {result["away"]}',
        "Compétition": result["competition"],
        "Pronostic principal": result["pick"],
        "Probabilité estimée": (
            f'{result["pick_probability"] * 100:.1f} %'
        ),
        "Données": result["confidence"],
    })

st.dataframe(
    pd.DataFrame(ranked_rows),
    use_container_width=True,
    hide_index=True
)


# =========================================================
# DÉTAIL DES MATCHS
# =========================================================

st.header("🔍 Analyses détaillées")

for result in results:
    with st.expander(
        f'{result["home"]} vs {result["away"]} '
        f'— {result["pick_probability"] * 100:.1f} %'
    ):
        st.write(f'**Compétition :** {result["competition"]}')
        st.write(f'**Date :** {result["date"]}')
        st.write(
            f'**Forme récente domicile :** {result["home_form"]}'
        )
        st.write(
            f'**Forme récente extérieur :** {result["away_form"]}'
        )

        if result["confidence"] == "Données insuffisantes":
            st.warning(
                "Historique trop limité pour établir un pronostic "
                "suffisamment documenté."
            )
        elif result["confidence"] == "Fiabilité limitée":
            st.info(
                "L'historique est limité : prudence dans l'interprétation."
            )

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "Victoire domicile",
            f'{result["home_win"] * 100:.1f} %'
        )

        col2.metric(
            "Match nul",
            f'{result["draw"] * 100:.1f} %'
        )

        col3.metric(
            "Victoire extérieur",
            f'{result["away_win"] * 100:.1f} %'
        )

        col4, col5, col6 = st.columns(3)

        col4.metric(
            "Plus de 1,5 but",
            f'{result["over_15"] * 100:.1f} %'
        )

        col5.metric(
            "Plus de 2,5 buts",
            f'{result["over_25"] * 100:.1f} %'
        )

        col6.metric(
            "Les deux marquent",
            f'{result["btts"] * 100:.1f} %'
        )

        st.write(
            "**Score moyen théorique :** "
            f'{result["home_lambda"]:.2f} - '
            f'{result["away_lambda"]:.2f}'
        )

        st.write(
            f'**Pronostic principal :** {result["pick"]} '
            f'({result["pick_probability"] * 100:.1f} %)'
        )


# =========================================================
# SÉLECTION DES CHOIX POUR COMBINÉS
# =========================================================

def get_candidate(result):
    candidates = [
        ("Victoire domicile", result["home_win"]),
        ("Match nul", result["draw"]),
        ("Victoire extérieur", result["away_win"]),
        ("Plus de 1,5 but", result["over_15"]),
        ("Plus de 2,5 buts", result["over_25"]),
        ("Les deux équipes marquent", result["btts"]),
    ]

    candidates.sort(key=lambda item: item[1], reverse=True)

    # Choix le plus probable au-dessus du seuil demandé.
    for name, probability in candidates:
        if probability * 100 >= minimum_probability:
            return name, probability

    return None


# =========================================================
# COMBINÉS AUTOMATIQUES
# =========================================================

st.header("🎯 Combinés automatiques")

st.warning(
    "Les combinés sont risqués. Le produit des probabilités "
    "suppose notamment l'indépendance des événements, ce qui "
    "n'est pas toujours exact. Aucun gain n'est garanti."
)

candidates = []

for result in results:
    candidate = get_candidate(result)

    if candidate is None:
        continue

    pick_name, probability = candidate

    # Écarter les matchs avec peu de données.
    if result["confidence"] == "Données insuffisantes":
        continue

    candidates.append({
        "match": f'{result["home"]} - {result["away"]}',
        "competition": result["competition"],
        "pick": pick_name,
        "probability": probability,
        "date": result["date"],
    })

# Retirer les doublons éventuels.
seen = set()
clean_candidates = []

for candidate in candidates:
    key = candidate["match"]

    if key not in seen:
        seen.add(key)
        clean_candidates.append(candidate)

candidates = clean_candidates

if len(candidates) < 2:
    st.info(
        "Pas assez de choix répondant aux critères pour générer "
        "des combinés. Diminue le seuil de probabilité ou élargis "
        "la période des matchs."
    )
else:
    for size in [2, 3, 4]:
        st.subheader(f"Combinés de {size} matchs")

        if len(candidates) < size:
            st.info(
                f"Il faut au moins {size} matchs admissibles."
            )
            continue

        combos = []

        # Limiter le nombre de combinaisons pour préserver
        # les performances de l'application.
        for combination in itertools.islice(
            itertools.combinations(candidates, size),
            5000
        ):
            probability = math.prod(
                item["probability"] for item in combination
            )

            combos.append({
                "matches": combination,
                "probability": probability,
            })

        combos.sort(
            key=lambda item: item["probability"],
            reverse=True
        )

        for index, combo in enumerate(combos[:5], start=1):
            with st.expander(
                f"Combiné {index} — "
                f'{combo["probability"] * 100:.2f} % théorique'
            ):
                for item in combo["matches"]:
                    st.write(
                        f'⚽ **{item["match"]}** — {item["pick"]} '
                        f'({item["probability"] * 100:.1f} %)'
                    )
                    st.caption(
                        f'{item["competition"]} · {item["date"]}'
                    )

                st.metric(
                    "Probabilité théorique du combiné",
                    f'{combo["probability"] * 100:.2f} %'
                )


# =========================================================
# INFORMATIONS ET LIMITES
# =========================================================

st.divider()

st.header("ℹ️ Informations importantes")

st.write(
    """
    - Les données proviennent de football-data.org.
    - Les compétitions disponibles dépendent de ton abonnement API.
    - Le modèle utilise les résultats historiques accessibles.
    - Les compositions probables, les blessures, les suspensions
      et les informations de dernière minute ne sont pas intégrées
      automatiquement par cette version.
    - Les probabilités sont des estimations statistiques, et non
      des probabilités certifiées ou des garanties de résultat.
    - Les combinés peuvent être perdants même si chaque sélection
      semble individuellement probable.
    """
)

st.caption("FOOT AI PRO — version statistique automatique")