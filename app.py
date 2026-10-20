import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import pandas as pd
import streamlit as st


# =========================================================
# FOOT AI PRO V7
# Analyse automatique des matchs de football
# =========================================================

st.set_page_config(
    page_title="FOOT AI PRO V7",
    page_icon="⚽",
    layout="wide",
)

API_BASE = "https://v3.football.api-sports.io"
FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"

PARIS = ZoneInfo("Europe/Paris")

# Identifiants des compétitions API-Football.
COMPETITIONS = {
    "Ligue 1 🇫🇷": 61,
    "Premier League 🏴": 39,
    "Liga 🇪🇸": 140,
    "Bundesliga 🇩🇪": 78,
    "Serie A 🇮🇹": 135,
    "Ligue des champions 🏆": 2,
}

# Identifiants football-data.org conservés.
FOOTBALL_DATA_CODES = {
    "Ligue 1 🇫🇷": "FL1",
    "Premier League 🏴": "PL",
    "Liga 🇪🇸": "PD",
    "Bundesliga 🇩🇪": "BL1",
    "Serie A 🇮🇹": "SA",
    "Ligue des champions 🏆": "CL",
}


# =========================================================
# CONFIGURATION DES CLÉS
# =========================================================

def get_secret(name):
    try:
        return str(st.secrets[name]).strip()
    except Exception:
        return ""


API_FOOTBALL_KEY = get_secret("API_FOOTBALL_KEY")
FOOTBALL_API_KEY = get_secret("FOOTBALL_API_KEY")


# =========================================================
# APPELS API ET GESTION DES ERREURS
# =========================================================

def api_request(endpoint, params=None):
    if not API_FOOTBALL_KEY:
        return None, "Clé API_FOOTBALL_KEY introuvable."

    try:
        response = requests.get(
            f"{API_BASE}/{endpoint}",
            headers={
                "x-apisports-key": API_FOOTBALL_KEY,
            },
            params=params or {},
            timeout=20,
        )

        if response.status_code in (401, 403):
            return None, (
                "Accès refusé : vérifie ta clé API "
                "et les droits de ton compte."
            )

        if response.status_code == 429:
            return None, (
                "Limite de requêtes atteinte. "
                "Attends le renouvellement du quota."
            )

        response.raise_for_status()
        data = response.json()

        errors = data.get("errors", {})

        if errors:
            return None, str(errors)

        return data.get("response", []), None

    except requests.exceptions.Timeout:
        return None, "Délai de réponse dépassé."

    except requests.exceptions.RequestException as exc:
        return None, f"Erreur réseau : {exc}"

    except ValueError:
        return None, "Réponse API illisible."


# =========================================================
# RECHERCHE AUTOMATIQUE DES MATCHS
# =========================================================

@st.cache_data(ttl=600, show_spinner=False)
def get_fixtures(competition_id, season, date_from, date_to):
    result, error = api_request(
        "fixtures",
        {
            "league": competition_id,
            "season": season,
            "from": date_from,
            "to": date_to,
            "timezone": "Europe/Paris",
        },
    )

    if error:
        return [], error

    return result or [], None


# =========================================================
# PRÉDICTIONS DE L'API
# =========================================================

@st.cache_data(ttl=1800, show_spinner=False)
def get_api_prediction(fixture_id):
    result, error = api_request(
        "predictions",
        {
            "fixture": fixture_id,
        },
    )

    if error or not result:
        return None

    return result[0]


# =========================================================
# CINQ DERNIERS MATCHS D'UNE ÉQUIPE
# =========================================================

@st.cache_data(ttl=1800, show_spinner=False)
def get_team_last_matches(team_id, season):
    result, error = api_request(
        "fixtures",
        {
            "team": team_id,
            "last": 5,
            "season": season,
            "timezone": "Europe/Paris",
        },
    )

    if error:
        return []

    return result or []


def calculate_team_form(matches, team_id):
    scored = []
    conceded = []
    results = []

    for match in matches:
        fixture = match.get("fixture", {})
        teams = match.get("teams", {})
        goals = match.get("goals", {})

        status = fixture.get("status", {}).get("short")

        if status not in ("FT", "AET", "PEN"):
            continue

        home = teams.get("home", {})
        away = teams.get("away", {})

        home_goals = goals.get("home")
        away_goals = goals.get("away")

        if home_goals is None or away_goals is None:
            continue

        if home.get("id") == team_id:
            team_goals = home_goals
            opponent_goals = away_goals

        elif away.get("id") == team_id:
            team_goals = away_goals
            opponent_goals = home_goals

        else:
            continue

        scored.append(team_goals)
        conceded.append(opponent_goals)

        if team_goals > opponent_goals:
            results.append("V")
        elif team_goals == opponent_goals:
            results.append("N")
        else:
            results.append("D")

    if not scored:
        return {
            "form": "Indisponible",
            "played": 0,
            "scored": None,
            "conceded": None,
            "points": None,
        }

    points = sum(
        3 if result == "V"
        else 1 if result == "N"
        else 0
        for result in results
    )

    return {
        "form": " - ".join(results),
        "played": len(scored),
        "scored": sum(scored) / len(scored),
        "conceded": sum(conceded) / len(conceded),
        "points": points,
    }


# =========================================================
# ESTIMATION STATISTIQUE DE POISSON
# =========================================================

def poisson_probability(goals, expected):
    return (
        math.exp(-expected)
        * expected ** goals
        / math.factorial(goals)
    )


def poisson_markets(home_expected, away_expected):
    max_goals = 10

    home_probs = [
        poisson_probability(g, home_expected)
        for g in range(max_goals + 1)
    ]

    away_probs = [
        poisson_probability(g, away_expected)
        for g in range(max_goals + 1)
    ]

    markets = {
        "1": 0.0,
        "N": 0.0,
        "2": 0.0,
        "1N": 0.0,
        "N2": 0.0,
        "12": 0.0,
        "Over 1.5": 0.0,
        "Over 2.5": 0.0,
        "BTTS": 0.0,
    }

    for hg in range(max_goals + 1):
        for ag in range(max_goals + 1):

            probability = home_probs[hg] * away_probs[ag]
            total_goals = hg + ag

            if hg > ag:
                markets["1"] += probability
            elif hg == ag:
                markets["N"] += probability
            else:
                markets["2"] += probability

            if hg >= ag:
                markets["1N"] += probability

            if ag >= hg:
                markets["N2"] += probability

            if hg != ag:
                markets["12"] += probability

            if total_goals >= 2:
                markets["Over 1.5"] += probability

            if total_goals >= 3:
                markets["Over 2.5"] += probability

            if hg >= 1 and ag >= 1:
                markets["BTTS"] += probability

    return markets


def estimate_goals(home_form, away_form):
    """
    Estimation simplifiée à partir des buts récents.
    Ce calcul ne constitue pas une prédiction garantie.
    """

    if (
        home_form["played"] < 3
        or away_form["played"] < 3
    ):
        return None

    home_attack = home_form["scored"]
    home_defense = home_form["conceded"]

    away_attack = away_form["scored"]
    away_defense = away_form["conceded"]

    home_expected = (
        (home_attack + away_defense) / 2
    ) * 1.10

    away_expected = (
        (away_attack + home_defense) / 2
    ) * 0.95

    home_expected = max(
        0.10,
        min(home_expected, 4.0),
    )

    away_expected = max(
        0.10,
        min(away_expected, 4.0),
    )

    return {
        "home_goals": home_expected,
        "away_goals": away_expected,
        "markets": poisson_markets(
            home_expected,
            away_expected,
        ),
    }


# =========================================================
# BLESSURES ET SUSPENSIONS
# =========================================================

@st.cache_data(ttl=1800, show_spinner=False)
def get_injuries(fixture_id):
    result, error = api_request(
        "injuries",
        {
            "fixture": fixture_id,
        },
    )

    if error:
        return [], error

    return result or [], None


# =========================================================
# COMPOSITIONS
# =========================================================

@st.cache_data(ttl=600, show_spinner=False)
def get_lineups(fixture_id):
    result, error = api_request(
        "fixtures/lineups",
        {
            "fixture": fixture_id,
        },
    )

    if error:
        return [], error

    return result or [], None


# =========================================================
# FORMATAGE DES PROBABILITÉS
# =========================================================

def percentage(value):
    if value is None:
        return None

    try:
        if isinstance(value, str):
            value = value.replace("%", "").strip()

        return float(value)
    except (TypeError, ValueError):
        return None


def extract_api_probabilities(prediction):
    if not prediction:
        return {}

    predictions = prediction.get("predictions", {})
    percent = predictions.get("percent", {})

    home = percentage(percent.get("home"))
    draw = percentage(percent.get("draw"))
    away = percentage(percent.get("away"))

    result = {}

    if home is not None:
        result["Victoire domicile"] = home

    if draw is not None:
        result["Match nul"] = draw

    if away is not None:
        result["Victoire extérieur"] = away

    if home is not None and draw is not None:
        result["Domicile ou nul"] = home + draw

    if away is not None and draw is not None:
        result["Extérieur ou nul"] = away + draw

    if home is not None and away is not None:
        result["Pas de match nul"] = home + away

    return result


# =========================================================
# ANALYSE D'UN MATCH
# =========================================================

def analyze_fixture(match, season, include_details):
    fixture = match.get("fixture", {})
    teams = match.get("teams", {})
    league = match.get("league", {})

    home = teams.get("home", {})
    away = teams.get("away", {})

    fixture_id = fixture.get("id")

    if not fixture_id:
        return None

    home_id = home.get("id")
    away_id = away.get("id")

    home_history = get_team_last_matches(
        home_id,
        season,
    )

    away_history = get_team_last_matches(
        away_id,
        season,
    )

    home_form = calculate_team_form(
        home_history,
        home_id,
    )

    away_form = calculate_team_form(
        away_history,
        away_id,
    )

    estimated = estimate_goals(
        home_form,
        away_form,
    )

    api_prediction = get_api_prediction(
        fixture_id,
    )

    api_probabilities = extract_api_probabilities(
        api_prediction,
    )

    injuries = []
    lineups = []

    injury_error = None
    lineup_error = None

    if include_details:
        injuries, injury_error = get_injuries(
            fixture_id,
        )

        lineups, lineup_error = get_lineups(
            fixture_id,
        )

    return {
        "id": fixture_id,
        "date": fixture.get("date"),
        "timestamp": fixture.get("timestamp"),
        "status": fixture.get("status", {}).get("long"),
        "status_short": fixture.get("status", {}).get("short"),
        "competition": league.get("name", ""),
        "home": home.get("name", "Domicile"),
        "away": away.get("name", "Extérieur"),
        "home_id": home_id,
        "away_id": away_id,
        "home_form": home_form,
        "away_form": away_form,
        "estimated": estimated,
        "api_prediction": api_prediction,
        "api_probabilities": api_probabilities,
        "injuries": injuries,
        "lineups": lineups,
        "injury_error": injury_error,
        "lineup_error": lineup_error,
    }


# =========================================================
# SÉLECTION DES MEILLEURS PRONOSTICS
# =========================================================

def select_best(analyses, threshold):
    candidates = []

    for analysis in analyses:
        estimated = analysis.get("estimated")

        if not estimated:
            continue

        markets = estimated["markets"]

        market_labels = {
            "1N": "Domicile ou nul",
            "N2": "Extérieur ou nul",
            "Over 1.5": "Plus de 1,5 but",
            "Over 2.5": "Plus de 2,5 buts",
            "BTTS": "Les deux équipes marquent",
        }

        for key, label in market_labels.items():
            probability = markets.get(key, 0) * 100

            if probability < threshold:
                continue

            candidates.append({
                "id": analysis["id"],
                "match": (
                    f"{analysis['home']} - "
                    f"{analysis['away']}"
                ),
                "competition": analysis["competition"],
                "market": label,
                "probability": probability,
                "date": analysis["date"],
            })

    candidates.sort(
        key=lambda item: item["probability"],
        reverse=True,
    )

    selected = []
    used_matches = set()

    for candidate in candidates:
        if candidate["id"] in used_matches:
            continue

        selected.append(candidate)
        used_matches.add(candidate["id"])

        if len(selected) >= 2:
            break

    return selected


# =========================================================
# INTERFACE PRINCIPALE
# =========================================================

st.title("⚽ FOOT AI PRO V7")

st.subheader(
    "Analyse automatique des matchs et des probabilités"
)

st.info(
    "Les probabilités sont des estimations statistiques. "
    "Aucun pari n'est garanti."
)

if not API_FOOTBALL_KEY:
    st.error(
        "Clé API-Football manquante. "
        "Dans Streamlit Cloud, ouvre Settings > Secrets "
        "et vérifie API_FOOTBALL_KEY."
    )
    st.stop()

if not FOOTBALL_API_KEY:
    st.warning(
        "La clé football-data.org n'a pas été détectée. "
        "La V7 utilise API-Football pour ses analyses avancées."
    )

st.sidebar.header("⚙️ Configuration")

selected_competitions = st.sidebar.multiselect(
    "Championnats",
    list(COMPETITIONS.keys()),
    default=list(COMPETITIONS.keys()),
)

days = st.sidebar.selectbox(
    "Période",
    [1, 3, 7],
    index=2,
    format_func=lambda value: (
        "Aujourd'hui"
        if value == 1
        else f"{value} prochains jours"
    ),
)

threshold = st.sidebar.slider(
    "Seuil de sélection statistique",
    min_value=55,
    max_value=90,
    value=70,
    step=5,
)

max_matches = st.sidebar.slider(
    "Nombre maximal de matchs à analyser en détail",
    min_value=2,
    max_value=10,
    value=6,
)

include_details = st.sidebar.checkbox(
    "Rechercher blessures et compositions",
    value=True,
)

st.sidebar.caption(
    "Les appels API sont limités pour préserver "
    "le quota de ton forfait."
)

if st.button(
    "🔎 RECHERCHER ET ANALYSER",
    type="primary",
    use_container_width=True,
):

    if not selected_competitions:
        st.warning(
            "Sélectionne au moins un championnat."
        )
        st.stop()

    now = datetime.now(PARIS)

    season = now.year if now.month >= 7 else now.year - 1

    date_from = now.date()
    date_to = date_from + timedelta(days=days)

    matches = []
    api_errors = []

    progress = st.progress(0)

    with st.spinner(
        "Recherche des matchs des six championnats..."
    ):

        for index, name in enumerate(
            selected_competitions
        ):

            competition_id = COMPETITIONS[name]

            fixtures, error = get_fixtures(
                competition_id,
                season,
                date_from.isoformat(),
                date_to.isoformat(),
            )

            if error:
                api_errors.append(
                    f"{name} : {error}"
                )

            for fixture in fixtures:
                fixture["competition_label"] = name
                matches.append(fixture)

            progress.progress(
                (index + 1) / len(selected_competitions)
            )

    progress.empty()

    # Ne conserve que les matchs pas encore terminés.
    upcoming = []

    for match in matches:
        fixture = match.get("fixture", {})
        status = fixture.get(
            "status", {}
        ).get("short", "")

        if status in ("NS", "TBD"):
            upcoming.append(match)

    upcoming.sort(
        key=lambda match: match.get(
            "fixture", {}
        ).get("timestamp", 0)
    )

    st.session_state["upcoming"] = upcoming
    st.session_state["api_errors"] = api_errors
    st.session_state["season"] = season
    st.session_state["threshold"] = threshold
    st.session_state["max_matches"] = max_matches
    st.session_state["include_details"] = include_details

    if upcoming:
        selected = upcoming[:max_matches]
        analyses = []

        progress = st.progress(0)

        with st.spinner(
            "Analyse des équipes et des probabilités..."
        ):

            for index, match in enumerate(selected):

                analysis = analyze_fixture(
                    match,
                    season,
                    include_details,
                )

                if analysis:
                    analyses.append(analysis)

                progress.progress(
                    (index + 1) / len(selected)
                )

        progress.empty()

        st.session_state["analyses"] = analyses

        st.session_state["best"] = select_best(
            analyses,
            threshold,
        )

        st.session_state["analysis_date"] = now.strftime(
            "%d/%m/%Y %H:%M"
        )

    else:
        st.session_state["analyses"] = []
        st.session_state["best"] = []


# =========================================================
# AFFICHAGE DES MATCHS
# =========================================================

if "api_errors" in st.session_state:

    for error in st.session_state["api_errors"]:
        st.warning(error)

if "upcoming" in st.session_state:

    upcoming = st.session_state["upcoming"]

    st.subheader(
        f"📅 Matchs à venir : {len(upcoming)}"
    )

    if not upcoming:
        st.info(
            "Aucun match à venir trouvé pour cette période. "
            "Vérifie la couverture des compétitions et la saison."
        )

    else:
        fixture_rows = []

        for match in upcoming:
            fixture = match.get("fixture", {})
            teams = match.get("teams", {})

            fixture_rows.append({
                "Date": fixture.get("date", ""),
                "Compétition": match.get(
                    "competition_label", ""
                ),
                "Domicile": teams.get(
                    "home", {}
                ).get("name", ""),
                "Extérieur": teams.get(
                    "away", {}
                ).get("name", ""),
            })

        st.dataframe(
            pd.DataFrame(fixture_rows),
            hide_index=True,
            use_container_width=True,
        )


# =========================================================
# MEILLEURES SÉLECTIONS
# =========================================================

if "analyses" in st.session_state:

    analyses = st.session_state["analyses"]
    best = st.session_state.get("best", [])

    st.divider()
    st.subheader("🎯 Les meilleures sélections")

    st.caption(
        "Dernière analyse : "
        + st.session_state.get("analysis_date", "")
    )

    if len(best) < 2:
        st.warning(
            "Moins de deux sélections atteignent le seuil "
            "choisi. Ne force pas un combiné."
        )

    if best:
        for index, item in enumerate(best, start=1):

            st.markdown(
                f"### Sélection {index} : {item['match']}"
            )

            st.write(
                f"**Pronostic :** {item['market']}"
            )

            st.write(
                f"**Probabilité estimée :** "
                f"{item['probability']:.1f} %"
            )

            st.caption(
                f"{item['competition']} — {item['date']}"
            )

            st.progress(
                min(1.0, item["probability"] / 100)
            )


# =========================================================
# ANALYSE DÉTAILLÉE
# =========================================================

if "analyses" in st.session_state:

    st.divider()
    st.subheader("📊 Analyses détaillées")

    for analysis in st.session_state["analyses"]:

        with st.expander(
            f"{analysis['home']} - {analysis['away']}"
        ):

            st.write(
                f"**Compétition :** {analysis['competition']}"
            )

            st.write(
                f"**Date :** {analysis['date']}"
            )

            col1, col2 = st.columns(2)

            with col1:
                st.markdown(
                    f"#### 🏠 {analysis['home']}"
                )

                form = analysis["home_form"]

                st.write(
                    f"Forme : {form['form']}"
                )

                if form["scored"] is not None:
                    st.write(
                        f"Buts marqués par match : "
                        f"{form['scored']:.2f}"
                    )

                    st.write(
                        f"Buts encaissés par match : "
                        f"{form['conceded']:.2f}"
                    )

            with col2:
                st.markdown(
                    f"#### ✈️ {analysis['away']}"
                )

                form = analysis["away_form"]

                st.write(
                    f"Forme : {form['form']}"
                )

                if form["scored"] is not None:
                    st.write(
                        f"Buts marqués par match : "
                        f"{form['scored']:.2f}"
                    )

                    st.write(
                        f"Buts encaissés par match : "
                        f"{form['conceded']:.2f}"
                    )

            estimated = analysis["estimated"]

            if estimated:
                st.markdown(
                    "#### 🧮 Estimation statistique"
                )

                st.write(
                    f"Buts attendus à domicile : "
                    f"{estimated['home_goals']:.2f}"
                )

                st.write(
                    f"Buts attendus à l'extérieur : "
                    f"{estimated['away_goals']:.2f}"
                )

                market_names = {
                    "1": "Victoire domicile",
                    "N": "Match nul",
                    "2": "Victoire extérieur",
                    "1N": "Domicile ou nul",
                    "N2": "Extérieur ou nul",
                    "12": "Pas de match nul",
                    "Over 1.5": "Plus de 1,5 but",
                    "Over 2.5": "Plus de 2,5 buts",
                    "BTTS": "Les deux équipes marquent",
                }

                rows = []

                for key, label in market_names.items():
                    rows.append({
                        "Marché": label,
                        "Probabilité": round(
                            estimated["markets"][key] * 100,
                            1,
                        ),
                    })

                st.dataframe(
                    pd.DataFrame(rows),
                    hide_index=True,
                    use_container_width=True,
                )

            else:
                st.warning(
                    "Historique insuffisant pour estimer "
                    "les buts avec le modèle Poisson."
                )

            api_prediction = analysis["api_prediction"]

            st.markdown(
                "#### 🤖 Prédiction API-Football"
            )

            if api_prediction:

                predictions = api_prediction.get(
                    "predictions", {}
                )

                winner = predictions.get("winner", {})

                if winner.get("name"):
                    st.write(
                        f"Équipe favorite selon l'API : "
                        f"{winner['name']}"
                    )

                if predictions.get("advice"):
                    st.write(
                        f"Conseil de l'API : "
                        f"{predictions['advice']}"
                    )

                api_probs = analysis["api_probabilities"]

                if api_probs:
                    st.dataframe(
                        pd.DataFrame([
                            {
                                "Marché": key,
                                "Probabilité API (%)": value,
                            }
                            for key, value in api_probs.items()
                        ]),
                        hide_index=True,
                        use_container_width=True,
                    )

            else:
                st.info(
                    "Prédiction API indisponible pour ce match."
                )

            # Blessures
            st.markdown("#### 🩺 Blessures et suspensions")

            injuries = analysis["injuries"]

            if injuries:
                injury_rows = []

                for item in injuries:
                    player = item.get("player", {})
                    team = item.get("team", {})

                    injury_rows.append({
                        "Équipe": team.get("name", ""),
                        "Joueur": player.get("name", ""),
                        "Type": player.get("type", ""),
                        "Motif": player.get("reason", ""),
                    })

                st.dataframe(
                    pd.DataFrame(injury_rows),
                    hide_index=True,
                    use_container_width=True,
                )

            elif analysis["injury_error"]:
                st.warning(
                    "Données de blessures non récupérées : "
                    + analysis["injury_error"]
                )

            else:
                st.info(
                    "Aucune blessure retournée par l'API. "
                    "Cela ne prouve pas qu'il n'y a aucune absence."
                )

            # Compositions
            st.markdown("#### 📋 Compositions")

            lineups = analysis["lineups"]

            if lineups:

                for lineup in lineups:

                    team_name = lineup.get(
                        "team", {}
                    ).get("name", "Équipe")

                    st.markdown(
                        f"**{team_name}**"
                    )

                    st.write(
                        "Formation : "
                        + str(lineup.get("formation", "Non précisée"))
                    )

                    players = lineup.get(
                        "startXI", []
                    )

                    if players:
                        names = [
                            player.get(
                                "player", {}
                            ).get("name", "")
                            for player in players
                        ]

                        st.write(
                            ", ".join(
                                name for name in names if name
                            )
                        )

            elif analysis["lineup_error"]:
                st.info(
                    "Compositions indisponibles : "
                    + analysis["lineup_error"]
                )

            else:
                st.info(
                    "Aucune composition publiée par l'API "
                    "pour le moment. Les compositions probables "
                    "ne sont pas inventées."
                )


# =========================================================
# EXPORT CSV
# =========================================================

if "analyses" in st.session_state:

    st.divider()
    st.subheader("📥 Exporter les analyses")

    export_rows = []

    for analysis in st.session_state["analyses"]:

        row = {
            "Date": analysis["date"],
            "Compétition": analysis["competition"],
            "Domicile": analysis["home"],
            "Extérieur": analysis["away"],
            "Forme domicile": analysis["home_form"]["form"],
            "Forme extérieur": analysis["away_form"]["form"],
        }

        if analysis["estimated"]:
            for key, value in (
                analysis["estimated"]["markets"].items()
            ):
                row[key] = round(value * 100, 1)

        for key, value in (
            analysis["api_probabilities"].items()
        ):
            row[f"API - {key}"] = value

        export_rows.append(row)

    st.download_button(
        "Télécharger les analyses CSV",
        data=pd.DataFrame(
            export_rows
        ).to_csv(
            index=False
        ).encode("utf-8-sig"),
        file_name="foot_ai_pro_v7.csv",
        mime="text/csv",
        use_container_width=True,
    )

else:
    st.markdown(
        """
        ### Bienvenue sur FOOT AI PRO V7

        1. Sélectionne les championnats.
        2. Choisis la période.
        3. Appuie sur **RECHERCHER ET ANALYSER**.
        4. Consulte les probabilités, les blessures et les
           compositions disponibles.

        Les données indisponibles sont signalées.
        Les probabilités ne garantissent aucun résultat.
        """
    )