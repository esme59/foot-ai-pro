import math
import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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
LOCAL_TZ = ZoneInfo("Europe/Paris")

COMPETITIONS = {
    "Ligue 1 🇫🇷": "FL1",
    "Premier League 🏴": "PL",
    "Liga 🇪🇸": "PD",
    "Bundesliga 🇩🇪": "BL1",
    "Serie A 🇮🇹": "SA",
    "Ligue des champions ⭐": "CL",
}

LIVE_STATUSES = {"IN_PLAY", "LIVE", "PAUSED"}
UPCOMING_STATUSES = {"SCHEDULED", "TIMED"}


# =========================================================
# API
# =========================================================

def get_api_key():
    try:
        key = st.secrets.get("FOOTBALL_DATA_API_KEY", "")
        if key:
            return key
    except Exception:
        pass

    return os.getenv("FOOTBALL_DATA_API_KEY", "")


def api_get(endpoint, params=None):
    key = get_api_key()

    if not key:
        raise RuntimeError(
            "Clé API absente. Ajoute "
            "FOOTBALL_DATA_API_KEY dans Streamlit Secrets."
        )

    headers = {"X-Auth-Token": key}

    try:
        response = requests.get(
            f"{API_BASE}{endpoint}",
            headers=headers,
            params=params or {},
            timeout=20,
        )

        if response.status_code == 429:
            raise RuntimeError(
                "Limite de requêtes API atteinte. "
                "Attends une minute avant de réessayer."
            )

        if response.status_code == 403:
            raise RuntimeError(
                "Accès refusé par football-data.org. "
                "Ton offre API ne permet peut-être pas "
                "d'accéder à ces données."
            )

        if response.status_code == 401:
            raise RuntimeError(
                "Clé API invalide. Vérifie Streamlit Secrets."
            )

        response.raise_for_status()
        return response.json()

    except requests.exceptions.Timeout:
        raise RuntimeError("L'API met trop de temps à répondre.")

    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Erreur de connexion API : {exc}")


# =========================================================
# MATCHS DU CALENDRIER
# =========================================================

@st.cache_data(ttl=120, show_spinner=False)
def load_matches(competition_code, date_from, date_to):
    data = api_get(
        f"/competitions/{competition_code}/matches",
        {
            "dateFrom": date_from,
            "dateTo": date_to,
        },
    )

    return data.get("matches", [])


def load_selected_competitions(competition_names, date_from, date_to):
    matches = []
    errors = []

    for competition_name in competition_names:
        code = COMPETITIONS[competition_name]

        try:
            competition_matches = load_matches(
                code,
                date_from,
                date_to,
            )

            for match in competition_matches:
                match["_competition_label"] = competition_name
                matches.append(match)

        except Exception as exc:
            errors.append(f"{competition_name} : {exc}")

    # Évite les doublons
    unique = {}

    for match in matches:
        unique[match.get("id", str(match))] = match

    return list(unique.values()), errors


# =========================================================
# HISTORIQUE DOMICILE / EXTÉRIEUR
# =========================================================

@st.cache_data(ttl=3600, show_spinner=False)
def load_team_history(team_id, before_date, venue):
    """
    Récupère les matchs terminés de l'équipe avant le match étudié.
    venue = HOME ou AWAY.
    """

    params = {
        "status": "FINISHED",
        "dateTo": before_date,
        "venue": venue,
        "limit": 20,
    }

    data = api_get(f"/teams/{team_id}/matches", params)

    matches = data.get("matches", [])

    finished = [
        match for match in matches
        if match.get("status") == "FINISHED"
    ]

    finished.sort(
        key=lambda item: item.get("utcDate", ""),
        reverse=True,
    )

    return finished[:5]


def get_score(match):
    score = match.get("score", {})

    full_time = score.get("fullTime") or {}

    home = full_time.get("home")
    away = full_time.get("away")

    if home is None or away is None:
        regular = score.get("regularTime") or {}
        home = regular.get("home")
        away = regular.get("away")

    if home is None or away is None:
        return None, None

    return int(home), int(away)


def calculate_team_stats(matches, team_id, venue):
    """
    Statistiques de l'équipe dans le rôle demandé :
    HOME = équipe à domicile
    AWAY = équipe à l'extérieur
    """

    games = []

    for match in matches:
        home_id = (match.get("homeTeam") or {}).get("id")
        away_id = (match.get("awayTeam") or {}).get("id")

        home_goals, away_goals = get_score(match)

        if home_goals is None or away_goals is None:
            continue

        if venue == "HOME" and home_id == team_id:
            scored = home_goals
            conceded = away_goals

        elif venue == "AWAY" and away_id == team_id:
            scored = away_goals
            conceded = home_goals

        else:
            continue

        if scored > conceded:
            points = 3
            result = "V"
        elif scored == conceded:
            points = 1
            result = "N"
        else:
            points = 0
            result = "D"

        games.append({
            "scored": scored,
            "conceded": conceded,
            "points": points,
            "result": result,
        })

    if not games:
        return {
            "count": 0,
            "avg_scored": 1.25,
            "avg_conceded": 1.25,
            "points_avg": 1.0,
            "form": "—",
        }

    return {
        "count": len(games),
        "avg_scored": sum(g["scored"] for g in games) / len(games),
        "avg_conceded": sum(g["conceded"] for g in games) / len(games),
        "points_avg": sum(g["points"] for g in games) / len(games),
        "form": " ".join(g["result"] for g in games),
    }


@st.cache_data(ttl=3600, show_spinner=False)
def load_venue_stats(team_id, before_date, venue):
    history = load_team_history(team_id, before_date, venue)

    stats = calculate_team_stats(history, team_id, venue)

    # Si aucun match n'est disponible pour ce lieu,
    # on essaie de récupérer les derniers matchs toutes positions.
    if stats["count"] == 0:
        fallback_data = api_get(
            f"/teams/{team_id}/matches",
            {
                "status": "FINISHED",
                "dateTo": before_date,
                "limit": 10,
            },
        )

        fallback_matches = [
            match for match in fallback_data.get("matches", [])
            if match.get("status") == "FINISHED"
        ]

        fallback_matches.sort(
            key=lambda item: item.get("utcDate", ""),
            reverse=True,
        )

        stats = calculate_team_stats(
            fallback_matches[:5],
            team_id,
            venue,
        )

        stats["fallback"] = True

    else:
        stats["fallback"] = False

    return stats


# =========================================================
# POISSON : PROBABILITÉS DES SCORES
# =========================================================

def poisson_probability(goals, expected_goals):
    expected_goals = max(0.01, float(expected_goals))

    return (
        math.exp(-expected_goals)
        * expected_goals ** goals
        / math.factorial(goals)
    )


def score_matrix(expected_home, expected_away, max_goals=10):
    matrix = []

    for home_goals in range(max_goals + 1):
        row = []

        for away_goals in range(max_goals + 1):
            probability = (
                poisson_probability(home_goals, expected_home)
                * poisson_probability(away_goals, expected_away)
            )

            row.append(probability)

        matrix.append(row)

    total = sum(sum(row) for row in matrix)

    if total > 0:
        matrix = [
            [value / total for value in row]
            for row in matrix
        ]

    return matrix


def markets_from_matrix(matrix):
    home_win = 0.0
    draw = 0.0
    away_win = 0.0

    over = {0.5: 0.0, 1.5: 0.0, 2.5: 0.0, 3.5: 0.0}
    under = {2.5: 0.0, 3.5: 0.0}

    btts_yes = 0.0
    btts_no = 0.0

    scores = []

    for home_goals, row in enumerate(matrix):
        for away_goals, probability in enumerate(row):
            if home_goals > away_goals:
                home_win += probability
            elif home_goals == away_goals:
                draw += probability
            else:
                away_win += probability

            total_goals = home_goals + away_goals

            for line in over:
                if total_goals > line:
                    over[line] += probability

            for line in under:
                if total_goals < line:
                    under[line] += probability

            if home_goals >= 1 and away_goals >= 1:
                btts_yes += probability
            else:
                btts_no += probability

            scores.append((
                probability,
                home_goals,
                away_goals,
            ))

    scores.sort(reverse=True)

    return {
        "home_win": home_win,
        "draw": draw,
        "away_win": away_win,
        "1X": home_win + draw,
        "X2": away_win + draw,
        "over": over,
        "under": under,
        "btts_yes": btts_yes,
        "btts_no": btts_no,
        "scores": scores[:5],
    }


# =========================================================
# ESTIMATION DES BUTS ATTENDUS
# =========================================================

def estimate_expected_goals(home_stats, away_stats):
    """
    Croise :
    - les buts marqués à domicile par l'équipe qui reçoit ;
    - les buts encaissés à domicile par cette équipe ;
    - les buts marqués à l'extérieur par l'adversaire ;
    - les buts encaissés à l'extérieur par l'adversaire.
    """

    home_attack = home_stats["avg_scored"]
    home_defence = home_stats["avg_conceded"]

    away_attack = away_stats["avg_scored"]
    away_defence = away_stats["avg_conceded"]

    expected_home = (
        0.55 * home_attack
        + 0.45 * away_defence
        + 0.15
    )

    expected_away = (
        0.55 * away_attack
        + 0.45 * home_defence
    )

    # Petit ajustement de forme, sans laisser la forme
    # écraser les statistiques de buts.
    home_form_adjustment = (
        home_stats["points_avg"] - 1.5
    ) * 0.08

    away_form_adjustment = (
        away_stats["points_avg"] - 1.5
    ) * 0.08

    expected_home += home_form_adjustment
    expected_away += away_form_adjustment

    expected_home = max(0.15, min(4.0, expected_home))
    expected_away = max(0.15, min(4.0, expected_away))

    return expected_home, expected_away


# =========================================================
# ANALYSE D'UN MATCH AVANT LE COUP D'ENVOI
# =========================================================

def analyze_match(match):
    home_team = match.get("homeTeam") or {}
    away_team = match.get("awayTeam") or {}

    home_id = home_team.get("id")
    away_id = away_team.get("id")

    if not home_id or not away_id:
        return None

    match_date = match.get("utcDate", "")[:10]

    if not match_date:
        match_date = date.today().isoformat()

    home_stats = load_venue_stats(
        home_id,
        match_date,
        "HOME",
    )

    away_stats = load_venue_stats(
        away_id,
        match_date,
        "AWAY",
    )

    expected_home, expected_away = estimate_expected_goals(
        home_stats,
        away_stats,
    )

    matrix = score_matrix(expected_home, expected_away)
    markets = markets_from_matrix(matrix)

    return {
        "home_stats": home_stats,
        "away_stats": away_stats,
        "expected_home": expected_home,
        "expected_away": expected_away,
        "markets": markets,
    }


# =========================================================
# ANALYSE DES MATCHS EN DIRECT
# =========================================================

def live_score(match):
    score = match.get("score") or {}

    # Pour un match en cours, le score courant est généralement
    # disponible dans regularTime ou fullTime selon le flux.
    regular = score.get("regularTime") or {}
    full_time = score.get("fullTime") or {}
    half_time = score.get("halfTime") or {}

    home = regular.get("home")
    away = regular.get("away")

    if home is None or away is None:
        home = full_time.get("home")
        away = full_time.get("away")

    if home is None or away is None:
        home = half_time.get("home", 0)
        away = half_time.get("away", 0)

    return int(home or 0), int(away or 0)


def live_expected_goals(expected_home, expected_away, minute):
    """
    Estimation simplifiée des buts supplémentaires attendus.
    Elle ne tient pas compte des tirs, xG ou cartons en direct.
    """

    if minute is None:
        minute = 45

    minute = max(0, min(120, int(minute)))

    remaining_fraction = max(0.02, (90 - minute) / 90)

    # En première période, le modèle conserve une estimation prudente
    # du temps restant.
    if minute > 90:
        remaining_fraction = 0.02

    return (
        max(0.01, expected_home * remaining_fraction),
        max(0.01, expected_away * remaining_fraction),
    )


def calculate_live_markets(
    expected_home,
    expected_away,
    current_home,
    current_away,
    minute,
):
    remaining_home, remaining_away = live_expected_goals(
        expected_home,
        expected_away,
        minute,
    )

    remaining_matrix = score_matrix(
        remaining_home,
        remaining_away,
        max_goals=8,
    )

    final_matrix = []

    for additional_home, row in enumerate(remaining_matrix):
        for additional_away, probability in enumerate(row):
            final_home = current_home + additional_home
            final_away = current_away + additional_away

            while len(final_matrix) <= final_home:
                final_matrix.append([])

            # Construit la matrice finale dans un dictionnaire séparé
            # pour gérer les scores déjà inscrits.
    final_scores = {}

    for additional_home, row in enumerate(remaining_matrix):
        for additional_away, probability in enumerate(row):
            score = (
                current_home + additional_home,
                current_away + additional_away,
            )

            final_scores[score] = probability

    home_win = draw = away_win = 0.0
    btts_yes = 0.0
    over = {0.5: 0.0, 1.5: 0.0, 2.5: 0.0, 3.5: 0.0}
    under = {2.5: 0.0, 3.5: 0.0}
    score_list = []

    for (home_goals, away_goals), probability in final_scores.items():
        if home_goals > away_goals:
            home_win += probability
        elif home_goals == away_goals:
            draw += probability
        else:
            away_win += probability

        total = home_goals + away_goals

        for line in over:
            if total > line:
                over[line] += probability

        for line in under:
            if total < line:
                under[line] += probability

        if home_goals > 0 and away_goals > 0:
            btts_yes += probability

        score_list.append((
            probability,
            home_goals,
            away_goals,
        ))

    score_list.sort(reverse=True)

    return {
        "home_win": home_win,
        "draw": draw,
        "away_win": away_win,
        "1X": home_win + draw,
        "X2": away_win + draw,
        "over": over,
        "under": under,
        "btts_yes": btts_yes,
        "btts_no": 1.0 - btts_yes,
        "scores": score_list[:5],
        "remaining_home": remaining_home,
        "remaining_away": remaining_away,
    }


# =========================================================
# AFFICHAGE DES PROBABILITÉS
# =========================================================

def pct(value):
    return f"{value * 100:.1f} %"


def display_markets(markets):
    st.markdown("#### 🏆 Résultat du match")

    col1, col2, col3 = st.columns(3)

    col1.metric("Victoire domicile", pct(markets["home_win"]))
    col2.metric("Match nul", pct(markets["draw"]))
    col3.metric("Victoire extérieur", pct(markets["away_win"]))

    col1, col2 = st.columns(2)
    col1.metric("Double chance 1X", pct(markets["1X"]))
    col2.metric("Double chance X2", pct(markets["X2"]))

    st.markdown("#### ⚽ Probabilité de buts")

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Plus de 0,5", pct(markets["over"][0.5]))
    col2.metric("Plus de 1,5", pct(markets["over"][1.5]))
    col3.metric("Plus de 2,5", pct(markets["over"][2.5]))
    col4.metric("Plus de 3,5", pct(markets["over"][3.5]))

    col1, col2 = st.columns(2)
    col1.metric("Moins de 2,5", pct(markets["under"][2.5]))
    col2.metric("Moins de 3,5", pct(markets["under"][3.5]))

    st.markdown("#### 🎯 Les deux équipes marquent")

    col1, col2 = st.columns(2)
    col1.metric("BTTS — Oui", pct(markets["btts_yes"]))
    col2.metric("BTTS — Non", pct(markets["btts_no"]))

    st.markdown("#### 🔢 Scores exacts les plus probables")

    score_columns = st.columns(5)

    for index, (probability, home_goals, away_goals) in enumerate(
        markets["scores"]
    ):
        score_columns[index].metric(
            f"Score {index + 1}",
            f"{home_goals} - {away_goals}",
            pct(probability),
        )


def show_team_stats(home_team, away_team, analysis):
    home_stats = analysis["home_stats"]
    away_stats = analysis["away_stats"]

    st.markdown("#### 🏠 Analyse domicile / extérieur")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown(f"**{home_team} — à domicile**")
        st.write(f"Matchs utilisés : {home_stats['count']}")
        st.write(f"Forme récente : {home_stats['form']}")
        st.write(
            f"Buts marqués / match : "
            f"{home_stats['avg_scored']:.2f}"
        )
        st.write(
            f"Buts encaissés / match : "
            f"{home_stats['avg_conceded']:.2f}"
        )

        if home_stats.get("fallback"):
            st.caption(
                "Peu de données à domicile : statistiques de remplacement utilisées."
            )

    with col2:
        st.markdown(f"**{away_team} — à l'extérieur**")
        st.write(f"Matchs utilisés : {away_stats['count']}")
        st.write(f"Forme récente : {away_stats['form']}")
        st.write(
            f"Buts marqués / match : "
            f"{away_stats['avg_scored']:.2f}"
        )
        st.write(
            f"Buts encaissés / match : "
            f"{away_stats['avg_conceded']:.2f}"
        )

        if away_stats.get("fallback"):
            st.caption(
                "Peu de données à l'extérieur : statistiques de remplacement utilisées."
            )

    col1, col2 = st.columns(2)

    col1.metric(
        f"Buts attendus — {home_team}",
        f"{analysis['expected_home']:.2f}",
    )

    col2.metric(
        f"Buts attendus — {away_team}",
        f"{analysis['expected_away']:.2f}",
    )


def show_prematch(match):
    home_team = (match.get("homeTeam") or {}).get("name", "Domicile")
    away_team = (match.get("awayTeam") or {}).get("name", "Extérieur")

    competition = match.get("_competition_label", "Championnat")
    utc_date = match.get("utcDate")

    st.markdown("---")
    st.subheader(f"⚽ {home_team} - {away_team}")
    st.caption(f"{competition} · Coup d'envoi : {format_local_time(utc_date)}")

    with st.spinner(f"Analyse de {home_team} - {away_team}..."):
        try:
            analysis = analyze_match(match)

            if not analysis:
                st.warning("Impossible de récupérer les identifiants des équipes.")
                return

            show_team_stats(home_team, away_team, analysis)
            display_markets(analysis["markets"])

        except Exception as exc:
            st.error(
                "Impossible d'analyser ce match. "
                f"Détail : {exc}"
            )


def format_local_time(utc_date):
    if not utc_date:
        return "Horaire indisponible"

    try:
        parsed = datetime.fromisoformat(
            utc_date.replace("Z", "+00:00")
        )

        return parsed.astimezone(LOCAL_TZ).strftime("%d/%m/%Y à %H:%M")

    except Exception:
        return utc_date


def show_live_match(match):
    home_team = (match.get("homeTeam") or {}).get("name", "Domicile")
    away_team = (match.get("awayTeam") or {}).get("name", "Extérieur")

    competition = match.get("_competition_label", "Championnat")
    status = match.get("status", "LIVE")
    minute = match.get("minute")

    home_score, away_score = live_score(match)

    if minute is not None:
        minute_text = f"{minute}'"
    elif status == "PAUSED":
        minute_text = "Mi-temps / pause"
    else:
        minute_text = status.replace("_", " ")

    st.markdown("---")
    st.subheader(f"🔴 {home_team} {home_score} - {away_score} {away_team}")
    st.caption(f"{competition} · {minute_text}")

    if status == "PAUSED":
        st.info("Le match est en pause. La minute exacte peut ne pas être fournie.")

    with st.spinner("Calcul de l'estimation en direct..."):
        try:
            analysis = analyze_match(match)

            if not analysis:
                st.warning("Données insuffisantes pour ce match.")
                return

            if minute is None:
                minute = 45

            markets = calculate_live_markets(
                analysis["expected_home"],
                analysis["expected_away"],
                home_score,
                away_score,
                minute,
            )

            st.info(
                "Estimation statistique de la fin du match. "
                "Elle utilise le score actuel, la minute et les statistiques "
                "pré-match ; elle ne dispose pas nécessairement des tirs, "
                "des xG ou des cartons en temps réel."
            )

            st.markdown("#### 📈 Probabilités estimées à la fin du match")
            display_markets(markets)

            st.caption(
                f"Buts supplémentaires attendus selon le modèle : "
                f"{markets['remaining_home']:.2f} pour {home_team}, "
                f"{markets['remaining_away']:.2f} pour {away_team}."
            )

        except Exception as exc:
            st.error(f"Analyse en direct indisponible : {exc}")


# =========================================================
# INTERFACE
# =========================================================

st.title("⚽ FOOT AI PRO")
st.subheader("Pronostics statistiques domicile / extérieur et matchs en direct")

st.write(
    "L'application analyse les statistiques récentes des équipes, "
    "calcule plusieurs marchés et estime les scores possibles."
)

if not get_api_key():
    st.error(
        "Clé API manquante. Dans les paramètres Streamlit, "
        "ajoute le secret FOOTBALL_DATA_API_KEY."
    )
    st.code('FOOTBALL_DATA_API_KEY = "TA_CLE_API"')
    st.stop()


# Sélection des dates
today = date.today()

col1, col2 = st.columns(2)

with col1:
    date_from = st.date_input(
        "Date de début",
        value=today,
    )

with col2:
    date_to = st.date_input(
        "Date de fin",
        value=today,
    )

if date_to < date_from:
    st.error("La date de fin doit être égale ou postérieure à la date de début.")
    st.stop()

competition_names = st.multiselect(
    "Championnats à analyser",
    options=list(COMPETITIONS.keys()),
    default=list(COMPETITIONS.keys()),
)

col1, col2 = st.columns(2)

with col1:
    load_button = st.button(
        "🔎 Charger les matchs",
        use_container_width=True,
    )

with col2:
    refresh_live_button = st.button(
        "🔄 Actualiser les matchs en direct",
        use_container_width=True,
    )

if refresh_live_button:
    load_matches.clear()
    load_team_history.clear()
    load_venue_stats.clear()
    st.rerun()


if "loaded_matches" not in st.session_state:
    st.session_state.loaded_matches = []
    st.session_state.load_errors = []
    st.session_state.last_loaded_range = None


if load_button or st.session_state.last_loaded_range != (
    str(date_from),
    str(date_to),
    tuple(competition_names),
):
    if not competition_names:
        st.warning("Sélectionne au moins un championnat.")
    else:
        with st.spinner("Récupération des matchs..."):
            matches, errors = load_selected_competitions(
                competition_names,
                date_from.isoformat(),
                date_to.isoformat(),
            )

            st.session_state.loaded_matches = matches
            st.session_state.load_errors = errors
            st.session_state.last_loaded_range = (
                str(date_from),
                str(date_to),
                tuple(competition_names),
            )


for error in st.session_state.load_errors:
    st.warning(error)


matches = st.session_state.loaded_matches

live_matches = [
    match for match in matches
    if match.get("status") in LIVE_STATUSES
]

upcoming_matches = [
    match for match in matches
    if match.get("status") in UPCOMING_STATUSES
]

other_matches = [
    match for match in matches
    if match.get("status") not in LIVE_STATUSES | UPCOMING_STATUSES
]


# =========================================================
# SECTION EN DIRECT
# =========================================================

st.markdown("---")
st.header("🔴 Matchs en direct")

if live_matches:
    st.success(f"{len(live_matches)} match(s) en direct trouvé(s).")

    for match in live_matches:
        show_live_match(match)

else:
    st.info(
        "Aucun match en direct n'a été trouvé dans les championnats "
        "et la période sélectionnés. Vérifie les dates ou actualise."
    )


# =========================================================
# SECTION AVANT-MATCH
# =========================================================

st.markdown("---")
st.header("📅 Pronostics des matchs à venir")

if upcoming_matches:
    st.write(f"{len(upcoming_matches)} match(s) à analyser.")

    sort_matches = sorted(
        upcoming_matches,
        key=lambda item: item.get("utcDate", ""),
    )

    for match in sort_matches:
        show_prematch(match)

else:
    st.info(
        "Aucun match programmé trouvé pour la période et les championnats "
        "sélectionnés."
    )


# =========================================================
# AUTRES STATUTS
# =========================================================

if other_matches:
    with st.expander("📋 Matchs terminés ou autres statuts"):
        for match in sorted(
            other_matches,
            key=lambda item: item.get("utcDate", ""),
        ):
            home = (match.get("homeTeam") or {}).get("name", "?")
            away = (match.get("awayTeam") or {}).get("name", "?")
            status = match.get("status", "INCONNU")
            home_score, away_score = live_score(match)

            if status == "FINISHED":
                st.write(
                    f"✅ {home} {home_score} - {away_score} {away} "
                    f"({match.get('_competition_label', '')})"
                )
            else:
                st.write(
                    f"ℹ️ {home} - {away} : {status} "
                    f"({match.get('_competition_label', '')})"
                )


# =========================================================
# AVERTISSEMENT
# =========================================================

st.markdown("---")
st.caption(
    "FOOT AI PRO fournit des estimations statistiques et non des garanties. "
    "Les probabilités ne sont pas des cotes de bookmaker. "
    "Les compositions, blessures, suspensions, statistiques détaillées en direct "
    "et informations de dernière minute ne sont pas automatiquement disponibles "
    "avec toutes les offres de l'API."
)