import math
import re
from datetime import date, timedelta

import requests
import streamlit as st


# ==========================================================
# FOOT AI PRO V6
# Source : Sportmonks Football API V3
# ==========================================================

st.set_page_config(
    page_title="FOOT AI PRO V6",
    page_icon="⚽",
    layout="wide",
)

API_URL = "https://api.sportmonks.com/v3/football"


# ==========================================================
# CONNEXION API
# ==========================================================

@st.cache_data(ttl=300, show_spinner=False)
def api_get(endpoint, token, params=None):
    params = dict(params or {})
    params["api_token"] = token

    response = requests.get(
        f"{API_URL}/{endpoint.lstrip('/')}",
        params=params,
        timeout=25,
    )

    if response.status_code != 200:
        try:
            detail = response.json().get("message", response.text)
        except ValueError:
            detail = response.text

        raise RuntimeError(
            f"Sportmonks HTTP {response.status_code}: {detail}"
        )

    data = response.json()

    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(str(data["error"]))

    return data


# ==========================================================
# EXTRACTION DES ÉQUIPES ET DES SCORES
# ==========================================================

def participants(fixture):
    teams = fixture.get("participants") or []

    home = next(
        (t for t in teams if t.get("meta", {}).get("location") == "home"),
        None,
    )
    away = next(
        (t for t in teams if t.get("meta", {}).get("location") == "away"),
        None,
    )

    # Certains retours API peuvent ne pas contenir meta.location.
    if home is None and len(teams) >= 2:
        home = teams[0]

    if away is None and len(teams) >= 2:
        away = teams[1]

    return home, away


def team_name(team):
    if not team:
        return "Équipe inconnue"
    return team.get("name", "Équipe inconnue")


def extract_score(fixture):
    scores = fixture.get("scores") or []

    home_score = None
    away_score = None

    for item in scores:
        description = str(item.get("description", "")).upper()

        # On privilégie le score de fin de match.
        if description not in (
            "CURRENT",
            "2ND_HALF",
            "FULLTIME",
            "FT",
        ):
            continue

        score = item.get("score") or {}
        goals = score.get("goals")
        participant = str(item.get("score", {}).get(
            "participant", ""
        )).lower()

        # Selon la réponse API, participant peut être fourni
        # dans score ou dans l'objet racine.
        participant = str(
            score.get("participant")
            or item.get("participant")
            or participant
        ).lower()

        if goals is None:
            continue

        try:
            goals = int(goals)
        except (TypeError, ValueError):
            continue

        if participant == "home":
            home_score = goals
        elif participant == "away":
            away_score = goals

    if home_score is not None and away_score is not None:
        return home_score, away_score

    # Repli sur result_info, quand le format est reconnu.
    result = str(fixture.get("result_info") or "")
    match = re.search(r"(\d+)\s*[-:]\s*(\d+)", result)

    if match:
        return int(match.group(1)), int(match.group(2))

    return None


def is_finished(fixture):
    state = fixture.get("state") or {}
    state_name = str(state.get("name", "")).lower()

    finished_words = (
        "finished",
        "full time",
        "after extra time",
        "after penalties",
    )

    if any(word in state_name for word in finished_words):
        return True

    return extract_score(fixture) is not None


# ==========================================================
# RÉCUPÉRATION DES MATCHS
# ==========================================================

def get_fixtures(token, start_date, end_date):
    all_fixtures = []

    # On utilise l'endpoint de plage de dates.
    # La pagination est limitée pour maîtriser les requêtes.
    for page in range(1, 6):
        result = api_get(
            f"fixtures/between/{start_date}/{end_date}",
            token,
            {
                "include": (
                    "participants;scores;league;state;"
                    "lineups;sidelined;expectedLineups"
                ),
                "per_page": 50,
                "page": page,
            },
        )

        rows = result.get("data", [])

        if not rows:
            break

        all_fixtures.extend(rows)

        pagination = result.get("pagination") or {}

        if not pagination.get("has_more", False):
            break

    # Éliminer les doublons éventuels.
    unique = {}

    for fixture in all_fixtures:
        unique[fixture.get("id")] = fixture

    return list(unique.values())


# ==========================================================
# MODÈLE DE POISSON
# ==========================================================

def poisson_probability(goals, expected_goals):
    if expected_goals <= 0:
        return 1.0 if goals == 0 else 0.0

    return (
        math.exp(-expected_goals)
        * expected_goals ** goals
        / math.factorial(goals)
    )


def analyze_team(team_id, history):
    scored = []
    conceded = []

    for fixture in history:
        if not is_finished(fixture):
            continue

        home, away = participants(fixture)

        if not home or not away:
            continue

        score = extract_score(fixture)

        if score is None:
            continue

        home_goals, away_goals = score

        if home.get("id") == team_id:
            scored.append(home_goals)
            conceded.append(away_goals)

        elif away.get("id") == team_id:
            scored.append(away_goals)
            conceded.append(home_goals)

    # Les résultats récents ne sont pas inventés :
    # sans historique, l'analyse est indisponible.
    if len(scored) < 3:
        return None

    scored = scored[-5:]
    conceded = conceded[-5:]

    return {
        "matches": len(scored),
        "scored": sum(scored) / len(scored),
        "conceded": sum(conceded) / len(conceded),
    }


def predict_match(home_id, away_id, history):
    home_stats = analyze_team(home_id, history)
    away_stats = analyze_team(away_id, history)

    if home_stats is None or away_stats is None:
        return None

    # Estimation simple à partir des buts marqués
    # et encaissés récemment.
    home_xg = (
        home_stats["scored"] + away_stats["conceded"]
    ) / 2 * 1.10

    away_xg = (
        away_stats["scored"] + home_stats["conceded"]
    ) / 2

    home_xg = max(0.05, min(home_xg, 4.5))
    away_xg = max(0.05, min(away_xg, 4.5))

    home_win = 0.0
    draw = 0.0
    away_win = 0.0

    for home_goals in range(9):
        p_home = poisson_probability(home_goals, home_xg)

        for away_goals in range(9):
            p_away = poisson_probability(away_goals, away_xg)
            probability = p_home * p_away

            if home_goals > away_goals:
                home_win += probability
            elif home_goals == away_goals:
                draw += probability
            else:
                away_win += probability

    total = home_win + draw + away_win

    if total <= 0:
        return None

    return {
        "home": home_win / total * 100,
        "draw": draw / total * 100,
        "away": away_win / total * 100,
        "home_xg": home_xg,
        "away_xg": away_xg,
        "home_stats": home_stats,
        "away_stats": away_stats,
    }


# ==========================================================
# INTERFACE
# ==========================================================

st.title("⚽ FOOT AI PRO V6")
st.caption(
    "Analyse automatique des matchs — "
    "probabilités statistiques, sans garantie de résultat."
)

with st.sidebar:
    st.header("⚙️ Configuration")

    token = st.text_input(
        "Sportmonks API Token",
        type="password",
        help="Ta clé reste privée. Ne la publie jamais sur GitHub.",
    )

    selected_date = st.date_input(
        "Date des matchs",
        value=date.today(),
    )

    days_ahead = st.slider(
        "Nombre de jours à analyser",
        min_value=1,
        max_value=7,
        value=3,
    )

    analyze_button = st.button(
        "🔎 Rechercher et analyser",
        type="primary",
        use_container_width=True,
    )

st.info(
    "La version gratuite de Sportmonks couvre notamment "
    "la Superliga danoise et la Premiership écossaise. "
    "Les autres championnats peuvent être inaccessibles."
)

if analyze_button:
    if not token.strip():
        st.error("Entre d'abord ton API Token Sportmonks.")
        st.stop()

    start_history = selected_date - timedelta(days=45)
    end_date = selected_date + timedelta(days=days_ahead - 1)

    with st.spinner("Récupération des matchs et des résultats..."):
        try:
            fixtures = get_fixtures(
                token.strip(),
                start_history.isoformat(),
                end_date.isoformat(),
            )
        except Exception as exc:
            st.error(
                "Impossible de récupérer les données. "
                "Vérifie le token, l'accès à l'API et les "
                "compétitions de ton abonnement."
            )
            st.code(str(exc))
            st.stop()

    if not fixtures:
        st.warning(
            "Aucun match accessible dans cette période. "
            "Essaie une autre date ou vérifie ton abonnement."
        )
        st.stop()

    history = [
        fixture
        for fixture in fixtures
        if fixture.get("starting_at", "")[:10]
        < selected_date.isoformat()
    ]

    upcoming = [
        fixture
        for fixture in fixtures
        if selected_date.isoformat()
        <= fixture.get("starting_at", "")[:10]
        <= end_date.isoformat()
        and not is_finished(fixture)
    ]

    st.success(
        f"{len(fixtures)} rencontres récupérées, "
        f"{len(history)} rencontres antérieures disponibles."
    )

    if not upcoming:
        st.warning(
            "Aucun match à analyser pour cette période. "
            "Essaie une autre date."
        )
        st.stop()

    results = []

    for fixture in upcoming:
        home, away = participants(fixture)

        if not home or not away:
            continue

        prediction = predict_match(
            home.get("id"),
            away.get("id"),
            history,
        )

        league = fixture.get("league") or {}
        league_name = league.get("name", "Championnat inconnu")

        row = {
            "Date": fixture.get("starting_at", "")[:16],
            "Championnat": league_name,
            "Match": (
                f"{team_name(home)} - {team_name(away)}"
            ),
            "Analyse": "Indisponible",
            "Domicile (%)": None,
            "Nul (%)": None,
            "Extérieur (%)": None,
            "Buts estimés": "Indisponibles",
        }

        if prediction:
            row.update({
                "Analyse": "Historique disponible",
                "Domicile (%)": round(prediction["home"], 1),
                "Nul (%)": round(prediction["draw"], 1),
                "Extérieur (%)": round(prediction["away"], 1),
                "Buts estimés": (
                    f'{prediction["home_xg"]:.2f} - '
                    f'{prediction["away_xg"]:.2f}'
                ),
            })

        results.append(row)

    if not results:
        st.warning(
            "Les matchs ont été récupérés, mais les équipes "
            "ne disposent pas de données suffisantes pour "
            "afficher les analyses."
        )
        st.stop()

    st.subheader("📊 Résultats des analyses")

    st.dataframe(
        results,
        use_container_width=True,
        hide_index=True,
    )

    valid = [
        item for item in results
        if item["Analyse"] == "Historique disponible"
    ]

    if valid:
        ranked = sorted(
            valid,
            key=lambda item: max(
                item["Domicile (%)"],
                item["Nul (%)"],
                item["Extérieur (%)"],
            ),
            reverse=True,
        )

        st.subheader("🏆 Classement statistique")

        for index, item in enumerate(ranked[:10], start=1):
            best = max(
                item["Domicile (%)"],
                item["Nul (%)"],
                item["Extérieur (%)"],
            )

            if best == item["Domicile (%)"]:
                outcome = "Victoire domicile"
            elif best == item["Nul (%)"]:
                outcome = "Match nul"
            else:
                outcome = "Victoire extérieur"

            st.write(
                f"**{index}. {item['Match']}** — "
                f"{outcome} : {best:.1f} %"
            )

        st.warning(
            "Ces probabilités proviennent d'un modèle simple "
            "fondé sur les buts récents. Elles ne tiennent pas "
            "encore compte des cotes, des compositions "
            "confirmées, des blessures vérifiées ni de toutes "
            "les variables sportives. Elles ne constituent "
            "pas une garantie de gain."
        )
    else:
        st.warning(
            "Pas assez de résultats historiques pour produire "
            "des probabilités fiables. Aucune prédiction "
            "n'a été inventée."
        )

else:
    st.markdown(
        """
        ### 🚀 Comment utiliser FOOT AI PRO

        1. Entre ton token Sportmonks.
        2. Choisis la date des matchs.
        3. Appuie sur **Rechercher et analyser**.
        4. Consulte les probabilités et le classement.

        Les résultats dépendent des compétitions et des données
        réellement accessibles avec ton abonnement.
        """
    )