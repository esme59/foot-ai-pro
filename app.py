import os
import json
import math
import unicodedata
from datetime import date, datetime, timedelta

import requests
import streamlit as st


# ============================================================
# FOOT AI PRO
# Tableau de bord + calendrier + scores réels + comparaison
# API : football-data.org v4
# ============================================================

st.set_page_config(
    page_title="FOOT AI PRO",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_BASE = "https://api.football-data.org/v4"

COMPETITIONS = {
    "Ligue 1": "FL1",
    "Premier League": "PL",
    "Liga": "PD",
    "Bundesliga": "BL1",
    "Serie A": "SA",
    "Ligue des Champions": "CL",
}

DATA_FILE = os.path.join(
    os.path.dirname(__file__),
    "data",
    "bankroll.json",
)


# ============================================================
# STYLE
# ============================================================

st.markdown(
    """
    <style>
    .stApp {
        background-color: #0b1220;
        color: #f1f5f9;
    }
    [data-testid="stSidebar"] {
        background-color: #111b2e;
    }
    div[data-testid="stMetric"] {
        background: #142238;
        padding: 15px;
        border-radius: 12px;
        border: 1px solid #263b57;
    }
    .match-card {
        background: #142238;
        padding: 15px;
        border-radius: 12px;
        border: 1px solid #263b57;
        margin-bottom: 12px;
    }
    .small-text {
        color: #a8b7ca;
        font-size: 0.9rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# FONCTIONS GENERALES
# ============================================================

def normalise_text(value):
    """Nettoie un texte pour faciliter les comparaisons."""
    value = str(value or "").lower().strip()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(
        char for char in value
        if not unicodedata.combining(char)
    )
    return " ".join(value.split())


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def format_percent(value):
    return f"{value:.1f} %"


def get_api_key():
    """Lit la clé API depuis les secrets Streamlit ou l'environnement."""
    try:
        key = st.secrets.get("FOOTBALL_DATA_API_KEY", "")
        if key:
            return str(key).strip()
    except Exception:
        pass

    return os.environ.get("FOOTBALL_DATA_API_KEY", "").strip()


def load_state():
    """Charge les données du tableau de bord sans modifier le fichier."""
    default_state = {
        "starting_bankroll": 20.0,
        "bankroll": 20.0,
        "bets": [],
        "history": [],
        "stats": {},
        "message": "",
    }

    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as file:
                loaded = json.load(file)

            if isinstance(loaded, dict):
                default_state.update(loaded)

    except Exception as exc:
        st.warning(
            f"Impossible de lire le fichier des données : {exc}"
        )

    if not isinstance(default_state.get("bets"), list):
        default_state["bets"] = []

    if not isinstance(default_state.get("history"), list):
        default_state["history"] = []

    if not isinstance(default_state.get("stats"), dict):
        default_state["stats"] = {}

    return default_state


def get_bet_team(bet, side):
    """Récupère le nom d'une équipe malgré les anciens formats."""
    if side == "home":
        return (
            bet.get("home_team")
            or bet.get("home")
            or bet.get("homeTeam")
            or ""
        )

    return (
        bet.get("away_team")
        or bet.get("away")
        or bet.get("awayTeam")
        or ""
    )


def get_bet_pick(bet):
    return (
        bet.get("pick")
        or bet.get("market")
        or bet.get("prediction")
        or ""
    )


def get_bet_date(bet):
    value = bet.get("date") or bet.get("match_date") or ""

    if isinstance(value, str):
        return value[:10]

    return ""


def get_bet_league(bet):
    return (
        bet.get("league")
        or bet.get("competition")
        or ""
    )


def get_bet_probability(bet):
    probability = safe_float(
        bet.get("probability", bet.get("confidence", 0))
    )

    if 0 < probability <= 1:
        probability *= 100

    return probability


def normalise_status(bet):
    status = normalise_text(
        bet.get("status") or bet.get("result") or "en attente"
    )

    if status in ("win", "won", "gagne", "gagnee", "won bet"):
        return "Gagné"

    if status in ("loss", "lost", "perdu", "perdue"):
        return "Perdu"

    if status in ("void", "annule", "annulee"):
        return "Annulé"

    if status in ("pending", "open", "en attente", "non regle"):
        return "En attente"

    return str(bet.get("status") or bet.get("result") or "En attente")


# ============================================================
# API FOOTBALL-DATA.ORG
# ============================================================

@st.cache_data(ttl=900, show_spinner=False)
def get_matches(competition, start_date, end_date, api_key):
    """
    Récupère les matchs d'une compétition sur une période.
    Le cache réduit les appels API répétés.
    """
    if not api_key:
        return {
            "ok": False,
            "matches": [],
            "error": "Clé API manquante.",
        }

    url = f"{API_BASE}/competitions/{competition}/matches"

    headers = {
        "X-Auth-Token": api_key,
    }

    params = {
        "dateFrom": str(start_date),
        "dateTo": str(end_date),
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=20,
        )

        if response.status_code == 200:
            payload = response.json()

            return {
                "ok": True,
                "matches": payload.get("matches", []),
                "error": "",
            }

        if response.status_code == 429:
            return {
                "ok": False,
                "matches": [],
                "error": (
                    "Limite de requêtes API atteinte. "
                    "Attends un peu avant de réessayer."
                ),
            }

        if response.status_code == 403:
            return {
                "ok": False,
                "matches": [],
                "error": (
                    "Accès refusé par l'API. "
                    "Vérifie les compétitions autorisées "
                    "par ton abonnement football-data.org."
                ),
            }

        if response.status_code in (400, 404):
            return {
                "ok": False,
                "matches": [],
                "error": (
                    f"L'API n'a pas accepté la demande "
                    f"(HTTP {response.status_code})."
                ),
            }

        return {
            "ok": False,
            "matches": [],
            "error": (
                f"Erreur API HTTP {response.status_code} : "
                f"{response.text[:250]}"
            ),
        }

    except requests.RequestException as exc:
        return {
            "ok": False,
            "matches": [],
            "error": f"Erreur de connexion à l'API : {exc}",
        }


def match_date(match):
    value = match.get("utcDate", "")

    if not value:
        return ""

    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).date().isoformat()
    except ValueError:
        return str(value)[:10]


def match_score(match):
    score = match.get("score") or {}
    full_time = score.get("fullTime") or {}

    home_goals = full_time.get("home")
    away_goals = full_time.get("away")

    if home_goals is not None and away_goals is not None:
        return int(home_goals), int(away_goals)

    return None, None


def match_status_label(match):
    status = match.get("status", "")

    labels = {
        "SCHEDULED": "À venir",
        "TIMED": "Programmé",
        "IN_PLAY": "En direct",
        "PAUSED": "Mi-temps",
        "FINISHED": "Terminé",
        "POSTPONED": "Reporté",
        "SUSPENDED": "Suspendu",
        "CANCELLED": "Annulé",
        "AWARDED": "Résultat attribué",
    }

    return labels.get(status, status or "Inconnu")


# ============================================================
# MODELE DE PRONOSTIC : POISSON
# ============================================================

def poisson_probability(lam, goals):
    try:
        lam = max(0.05, float(lam))
        return (
            math.exp(-lam)
            * (lam ** goals)
            / math.factorial(goals)
        )
    except (ValueError, OverflowError):
        return 0.0


def predict_match(matches, home_team, away_team):
    """
    Estimation simple à partir des matchs terminés présents
    dans les données récupérées.

    Attention : ce modèle n'est pas une garantie de résultat.
    """
    finished = []

    home_name = normalise_text(home_team)
    away_name = normalise_text(away_team)

    for match in matches:
        if match.get("status") != "FINISHED":
            continue

        hg, ag = match_score(match)

        if hg is None or ag is None:
            continue

        finished.append((match, hg, ag))

    home_scored = []
    home_conceded = []
    away_scored = []
    away_conceded = []
    league_home_goals = []
    league_away_goals = []

    for match, hg, ag in finished:
        h_name = normalise_text(
            (match.get("homeTeam") or {}).get("name", "")
        )
        a_name = normalise_text(
            (match.get("awayTeam") or {}).get("name", "")
        )

        league_home_goals.append(hg)
        league_away_goals.append(ag)

        if h_name == home_name:
            home_scored.append(hg)
            home_conceded.append(ag)

        if a_name == home_name:
            home_scored.append(ag)
            home_conceded.append(hg)

        if h_name == away_name:
            away_scored.append(hg)
            away_conceded.append(ag)

        if a_name == away_name:
            away_scored.append(ag)
            away_conceded.append(hg)

    sample_size = min(len(home_scored), len(away_scored))

    if league_home_goals:
        average_home = sum(league_home_goals) / len(league_home_goals)
        average_away = sum(league_away_goals) / len(league_away_goals)
    else:
        average_home = 1.45
        average_away = 1.15

    if home_scored:
        home_attack = sum(home_scored) / len(home_scored)
        home_defence = sum(home_conceded) / len(home_conceded)
    else:
        home_attack = average_home
        home_defence = average_away

    if away_scored:
        away_attack = sum(away_scored) / len(away_scored)
        away_defence = sum(away_conceded) / len(away_conceded)
    else:
        away_attack = average_away
        away_defence = average_home

    # Mélange des moyennes pour éviter les estimations extrêmes.
    expected_home = (
        0.55 * home_attack
        + 0.25 * away_defence
        + 0.20 * average_home
    )

    expected_away = (
        0.55 * away_attack
        + 0.25 * home_defence
        + 0.20 * average_away
    )

    expected_home = max(0.15, min(expected_home, 4.0))
    expected_away = max(0.15, min(expected_away, 4.0))

    max_goals = 10

    home_probs = [
        poisson_probability(expected_home, i)
        for i in range(max_goals + 1)
    ]

    away_probs = [
        poisson_probability(expected_away, i)
        for i in range(max_goals + 1)
    ]

    p_home = 0.0
    p_draw = 0.0
    p_away = 0.0
    score_probabilities = {}

    for hg in range(max_goals + 1):
        for ag in range(max_goals + 1):
            probability = home_probs[hg] * away_probs[ag]
            score_probabilities[(hg, ag)] = probability

            if hg > ag:
                p_home += probability
            elif hg == ag:
                p_draw += probability
            else:
                p_away += probability

    total_goals_probabilities = {}

    for threshold in (0.5, 1.5, 2.5, 3.5):
        under_probability = 0.0

        for (hg, ag), probability in score_probabilities.items():
            if hg + ag < threshold:
                under_probability += probability

        total_goals_probabilities[threshold] = {
            "over": max(0.0, 1.0 - under_probability),
            "under": under_probability,
        }

    btts_yes = 0.0

    for (hg, ag), probability in score_probabilities.items():
        if hg > 0 and ag > 0:
            btts_yes += probability

    best_score = max(
        score_probabilities,
        key=score_probabilities.get,
    )

    markets = {
        "Victoire domicile": p_home,
        "Match nul": p_draw,
        "Victoire extérieur": p_away,
        "Double chance 1X": p_home + p_draw,
        "Double chance X2": p_draw + p_away,
        "Plus de 0,5 but": total_goals_probabilities[0.5]["over"],
        "Plus de 1,5 but": total_goals_probabilities[1.5]["over"],
        "Plus de 2,5 buts": total_goals_probabilities[2.5]["over"],
        "Plus de 3,5 buts": total_goals_probabilities[3.5]["over"],
        "Moins de 2,5 buts": total_goals_probabilities[2.5]["under"],
        "Moins de 3,5 buts": total_goals_probabilities[3.5]["under"],
        "Les deux équipes marquent : oui": btts_yes,
        "Les deux équipes marquent : non": 1.0 - btts_yes,
    }

    best_market = max(markets, key=markets.get)

    quality = (
        "Bon échantillon"
        if sample_size >= 5
        else "Échantillon limité"
    )

    return {
        "home": p_home,
        "draw": p_draw,
        "away": p_away,
        "over05": total_goals_probabilities[0.5]["over"],
        "over15": total_goals_probabilities[1.5]["over"],
        "over25": total_goals_probabilities[2.5]["over"],
        "over35": total_goals_probabilities[3.5]["over"],
        "under25": total_goals_probabilities[2.5]["under"],
        "under35": total_goals_probabilities[3.5]["under"],
        "btts_yes": btts_yes,
        "btts_no": 1.0 - btts_yes,
        "score": f"{best_score[0]} - {best_score[1]}",
        "best_market": best_market,
        "best_probability": markets[best_market],
        "markets": markets,
        "expected_home": expected_home,
        "expected_away": expected_away,
        "sample_size": sample_size,
        "quality": quality,
    }


# ============================================================
# COMPARAISON DES PRONOSTICS AVEC LES SCORES REELS
# ============================================================

def find_saved_bets(match, bets):
    """Recherche les pronostics enregistrés pour un match."""
    match_id = str(match.get("id", ""))
    home_name = normalise_text(
        (match.get("homeTeam") or {}).get("name", "")
    )
    away_name = normalise_text(
        (match.get("awayTeam") or {}).get("name", "")
    )
    date_value = match_date(match)

    found = []

    for bet in bets:
        bet_match_id = str(bet.get("match_id", ""))

        # Méthode la plus fiable : identifiant du match.
        if match_id and bet_match_id and match_id == bet_match_id:
            found.append(bet)
            continue

        bet_home = normalise_text(get_bet_team(bet, "home"))
        bet_away = normalise_text(get_bet_team(bet, "away"))
        bet_date = get_bet_date(bet)

        teams_match = (
            bet_home == home_name
            and bet_away == away_name
        )

        date_matches = (
            not bet_date
            or not date_value
            or bet_date == date_value
        )

        if teams_match and date_matches:
            found.append(bet)

    return found


def evaluate_market(pick, home_goals, away_goals):
    """
    Évalue un marché courant à partir du score final.
    Renvoie None si le marché n'est pas reconnu.
    """
    if home_goals is None or away_goals is None:
        return None

    text = normalise_text(pick)
    total_goals = home_goals + away_goals

    # Marchés de buts : on teste d'abord les seuils précis.
    over_patterns = [
        ("plus de 0,5", 0.5),
        ("plus de 0.5", 0.5),
        ("over 0.5", 0.5),
        ("plus de 1,5", 1.5),
        ("plus de 1.5", 1.5),
        ("over 1.5", 1.5),
        ("plus de 2,5", 2.5),
        ("plus de 2.5", 2.5),
        ("over 2.5", 2.5),
        ("plus de 3,5", 3.5),
        ("plus de 3.5", 3.5),
        ("over 3.5", 3.5),
    ]

    under_patterns = [
        ("moins de 0,5", 0.5),
        ("moins de 0.5", 0.5),
        ("under 0.5", 0.5),
        ("moins de 1,5", 1.5),
        ("moins de 1.5", 1.5),
        ("under 1.5", 1.5),
        ("moins de 2,5", 2.5),
        ("moins de 2.5", 2.5),
        ("under 2.5", 2.5),
        ("moins de 3,5", 3.5),
        ("moins de 3.5", 3.5),
        ("under 3.5", 3.5),
    ]

    for pattern, threshold in over_patterns:
        if pattern in text:
            return "Gagné" if total_goals > threshold else "Perdu"

    for pattern, threshold in under_patterns:
        if pattern in text:
            return "Gagné" if total_goals < threshold else "Perdu"

    if (
        "deux equipes marquent" in text
        or "les deux equipes marquent" in text
        or "btts" in text
    ):
        both_score = home_goals > 0 and away_goals > 0

        if "non" in text or "no" in text:
            return "Gagné" if not both_score else "Perdu"

        if "oui" in text or "yes" in text or "btts" in text:
            return "Gagné" if both_score else "Perdu"

    if (
        "victoire domicile" in text
        or "victoire a domicile" in text
        or "home win" in text
        or text.strip() in ("1", "1 gagnant")
    ):
        return "Gagné" if home_goals > away_goals else "Perdu"

    if (
        "victoire exterieur" in text
        or "victoire a l'exterieur" in text
        or "away win" in text
        or text.strip() in ("2", "2 gagnant")
    ):
        return "Gagné" if away_goals > home_goals else "Perdu"

    if (
        "match nul" in text
        or text.strip() in ("x", "nul")
        or "draw" in text
    ):
        return "Gagné" if home_goals == away_goals else "Perdu"

    if (
        "double chance 1x" in text
        or "1x" == text.strip()
    ):
        return "Gagné" if home_goals >= away_goals else "Perdu"

    if (
        "double chance x2" in text
        or "x2" == text.strip()
    ):
        return "Gagné" if away_goals >= home_goals else "Perdu"

    return None


# ============================================================
# CHARGEMENT DE L'ETAT
# ============================================================

state = load_state()
bets = state.get("bets", [])

api_key = get_api_key()

starting_bankroll = safe_float(
    state.get("starting_bankroll", 20.0),
    20.0,
)

bankroll = safe_float(
    state.get("bankroll", starting_bankroll),
    starting_bankroll,
)

total_bets = len(bets)
open_bets = [
    bet for bet in bets
    if normalise_status(bet) == "En attente"
]
won_bets = [
    bet for bet in bets
    if normalise_status(bet) == "Gagné"
]
lost_bets = [
    bet for bet in bets
    if normalise_status(bet) == "Perdu"
]

settled_bets = len(won_bets) + len(lost_bets)

win_rate = (
    len(won_bets) / settled_bets * 100
    if settled_bets
    else 0.0
)

open_stakes = sum(
    safe_float(bet.get("stake", 0))
    for bet in open_bets
)


# ============================================================
# EN-TETE
# ============================================================

st.title("⚽ FOOT AI PRO")
st.caption(
    "Analyse des matchs, suivi des pronostics et comparaison "
    "avec les scores réels."
)

if not api_key:
    st.error(
        "Clé API manquante. Dans Streamlit, ouvre "
        "Settings / Secrets et vérifie la présence de "
        "FOOTBALL_DATA_API_KEY."
    )


# ============================================================
# BARRE LATERALE
# ============================================================

with st.sidebar:
    st.header("⚙️ Paramètres")

    selected_leagues = st.multiselect(
        "Compétitions",
        options=list(COMPETITIONS.keys()),
        default=list(COMPETITIONS.keys()),
    )

    st.divider()

    st.subheader("💰 Capital")

    st.metric(
        "Capital actuel",
        f"{bankroll:.2f} €",
    )

    st.metric(
        "Mises en attente",
        f"{open_stakes:.2f} €",
    )

    st.caption(
        "Les mises en attente sont affichées séparément. "
        "Elles ne sont pas automatiquement retirées du capital."
    )

    if st.button("🔄 Actualiser les données"):
        st.cache_data.clear()
        st.rerun()


# ============================================================
# ONGLETS
# ============================================================

tab_dashboard, tab_matches, tab_ai, tab_history = st.tabs(
    [
        "📊 Tableau de bord",
        "📅 Matchs et calendrier",
        "🤖 Analyse IA",
        "📚 Historique",
    ]
)


# ============================================================
# TABLEAU DE BORD
# ============================================================

with tab_dashboard:
    st.subheader("Vue générale")

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Capital",
        f"{bankroll:.2f} €",
    )

    col2.metric(
        "Pronostics enregistrés",
        total_bets,
    )

    col3.metric(
        "Pronostics en attente",
        len(open_bets),
    )

    col4.metric(
        "Réussite des pronostics réglés",
        format_percent(win_rate),
    )

    st.divider()

    col5, col6, col7 = st.columns(3)

    col5.metric("Pronostics gagnés", len(won_bets))
    col6.metric("Pronostics perdus", len(lost_bets))
    col7.metric("Mises en attente", f"{open_stakes:.2f} €")

    st.info(
        "Le taux de réussite ne prend en compte que les pronostics "
        "déjà classés gagnés ou perdus. Les pronostics en attente "
        "ne sont pas inclus."
    )

    if state.get("message"):
        st.write(state.get("message"))

    st.subheader("Derniers pronostics enregistrés")

    if not bets:
        st.info("Aucun pronostic enregistré pour le moment.")
    else:
        rows = []

        for bet in bets[-10:][::-1]:
            rows.append(
                {
                    "Date": get_bet_date(bet) or "—",
                    "Compétition": get_bet_league(bet) or "—",
                    "Match": (
                        f"{get_bet_team(bet, 'home')} - "
                        f"{get_bet_team(bet, 'away')}"
                    ),
                    "Marché": get_bet_pick(bet) or "—",
                    "Probabilité": (
                        f"{get_bet_probability(bet):.1f} %"
                    ),
                    "Mise": (
                        f"{safe_float(bet.get('stake', 0)):.2f} €"
                    ),
                    "Statut": normalise_status(bet),
                }
            )

        st.dataframe(
            rows,
            use_container_width=True,
            hide_index=True,
        )


# ============================================================
# MATCHS ET CALENDRIER
# ============================================================

with tab_matches:
    st.subheader("📅 Choisir une date")

    st.write(
        "Choisis une date passée, actuelle ou future pour consulter "
        "les matchs disponibles et comparer les résultats avec "
        "les pronostics enregistrés."
    )

    today = date.today()

    selected_date = st.date_input(
        "Date à analyser",
        value=today,
        min_value=date(2000, 1, 1),
        max_value=today + timedelta(days=365),
        format="DD/MM/YYYY",
        key="calendar_selected_date",
    )

    search_button = st.button(
        "🔎 Rechercher les matchs de cette date",
        type="primary",
        use_container_width=True,
    )

    if search_button:
        if not api_key:
            st.error(
                "Impossible de rechercher les matchs : "
                "la clé API est manquante."
            )
        elif not selected_leagues:
            st.warning("Sélectionne au moins une compétition.")
        else:
            all_matches = []
            errors = []

            start_string = selected_date.isoformat()
            end_string = selected_date.isoformat()

            progress = st.progress(0)
            status_text = st.empty()

            total_competitions = len(selected_leagues)

            for index, league_name in enumerate(selected_leagues):
                competition_code = COMPETITIONS[league_name]

                status_text.write(
                    f"Recherche : {league_name}..."
                )

                result = get_matches(
                    competition_code,
                    start_string,
                    end_string,
                    api_key,
                )

                if result["ok"]:
                    for match in result["matches"]:
                        match["_league_name"] = league_name
                        all_matches.append(match)
                else:
                    errors.append(
                        f"{league_name} : {result['error']}"
                    )

                progress.progress(
                    (index + 1) / total_competitions
                )

            progress.empty()
            status_text.empty()

            st.session_state["calendar_matches"] = all_matches
            st.session_state["calendar_date"] = start_string
            st.session_state["calendar_errors"] = errors

    stored_date = st.session_state.get("calendar_date")
    stored_matches = st.session_state.get("calendar_matches", [])
    stored_errors = st.session_state.get("calendar_errors", [])

    if stored_date == selected_date.isoformat():
        if stored_errors:
            for error in stored_errors:
                st.warning(error)

        if not stored_matches:
            st.info(
                "Aucun match disponible pour cette date dans les "
                "compétitions sélectionnées. Vérifie aussi les "
                "compétitions accessibles avec ton abonnement API."
            )
        else:
            st.success(
                f"{len(stored_matches)} match(s) trouvé(s) "
                f"le {selected_date.strftime('%d/%m/%Y')}."
            )

            for match in sorted(
                stored_matches,
                key=lambda item: (
                    item.get("utcDate", ""),
                    item.get("_league_name", ""),
                ),
            ):
                home_team = (
                    match.get("homeTeam") or {}
                ).get("name", "Équipe domicile")

                away_team = (
                    match.get("awayTeam") or {}
                ).get("name", "Équipe extérieur")

                league_name = match.get(
                    "_league_name",
                    match.get("competition", {}).get("name", ""),
                )

                status = match.get("status", "")
                status_label = match_status_label(match)

                home_goals, away_goals = match_score(match)

                st.markdown(
                    f'<div class="match-card">'
                    f'<div class="small-text">'
                    f'{league_name} · {status_label}'
                    f'</div>'
                    f'<h4>{home_team} — {away_team}</h4>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                if status == "FINISHED" and home_goals is not None:
                    st.markdown(
                        f"### ⚽ Score final : "
                        f"**{home_goals} - {away_goals}**"
                    )
                elif status in ("IN_PLAY", "PAUSED"):
                    st.info(
                        f"Match en cours : {home_team} "
                        f"{home_goals if home_goals is not None else '—'}"
                        f" - "
                        f"{away_goals if away_goals is not None else '—'} "
                        f"{away_team}"
                    )
                else:
                    st.caption(
                        f"Statut : {status_label}"
                    )

                saved_bets = find_saved_bets(match, bets)

                if saved_bets:
                    st.markdown("**🎯 Pronostics enregistrés**")

                    for bet in saved_bets:
                        pick = get_bet_pick(bet)
                        probability = get_bet_probability(bet)
                        stake = safe_float(bet.get("stake", 0))

                        st.write(
                            f"- **{pick or 'Marché non renseigné'}** "
                            f"· Probabilité : {probability:.1f} % "
                            f"· Mise : {stake:.2f} €"
                        )

                        if (
                            status == "FINISHED"
                            and home_goals is not None
                            and away_goals is not None
                        ):
                            evaluation = evaluate_market(
                                pick,
                                home_goals,
                                away_goals,
                            )

                            if evaluation == "Gagné":
                                st.success(
                                    "Résultat du marché : GAGNÉ"
                                )
                            elif evaluation == "Perdu":
                                st.error(
                                    "Résultat du marché : PERDU"
                                )
                            else:
                                st.warning(
                                    "Marché non reconnu automatiquement. "
                                    "Vérifie le pronostic manuellement."
                                )
                        elif status in (
                            "POSTPONED",
                            "CANCELLED",
                            "SUSPENDED",
                        ):
                            st.warning(
                                "Le match est reporté, annulé ou suspendu. "
                                "Aucune évaluation automatique."
                            )
                        else:
                            st.info(
                                "Pronostic en attente du score final."
                            )

                else:
                    st.caption(
                        "Aucun pronostic enregistré correspondant "
                        "à ce match dans le fichier bankroll.json."
                    )

                st.divider()

    elif stored_date:
        st.info(
            "Appuie sur « Rechercher les matchs » pour charger "
            "la nouvelle date sélectionnée."
        )
    else:
        st.info(
            "Sélectionne une date, puis appuie sur le bouton "
            "de recherche. Les requêtes API ne sont pas lancées "
            "automatiquement à chaque changement de date."
        )


# ============================================================
# ANALYSE IA
# ============================================================

with tab_ai:
    st.subheader("🤖 Analyse des matchs")

    st.write(
        "Cette analyse utilise les matchs terminés disponibles "
        "dans les données chargées pour calculer des probabilités "
        "indicatives avec un modèle de Poisson."
    )

    st.warning(
        "Pour obtenir des moyennes fiables, il faut disposer "
        "d'un historique suffisant. Les matchs d'une seule journée "
        "ne constituent généralement pas un historique complet. "
        "Les probabilités ne garantissent jamais un résultat."
    )

    if not stored_matches:
        st.info(
            "Commence par rechercher une date dans l'onglet "
            "« Matchs et calendrier »."
        )
    else:
        upcoming_matches = [
            match for match in stored_matches
            if match.get("status") in (
                "SCHEDULED",
                "TIMED",
                "IN_PLAY",
                "PAUSED",
            )
        ]

        if not upcoming_matches:
            st.info(
                "Aucun match à venir ou en cours sur la date chargée. "
                "Les matchs terminés sont visibles dans le calendrier."
            )
        else:
            for match in upcoming_matches:
                home_team = (
                    match.get("homeTeam") or {}
                ).get("name", "")

                away_team = (
                    match.get("awayTeam") or {}
                ).get("name", "")

                league_name = match.get(
                    "_league_name",
                    match.get("competition", {}).get("name", ""),
                )

                prediction = predict_match(
                    stored_matches,
                    home_team,
                    away_team,
                )

                st.markdown(
                    f"### {home_team} — {away_team}"
                )
                st.caption(league_name)

                col1, col2, col3 = st.columns(3)

                col1.metric(
                    "Victoire domicile",
                    format_percent(prediction["home"] * 100),
                )

                col2.metric(
                    "Match nul",
                    format_percent(prediction["draw"] * 100),
                )

                col3.metric(
                    "Victoire extérieur",
                    format_percent(prediction["away"] * 100),
                )

                st.markdown("**Marchés de buts**")

                market_columns = st.columns(3)

                market_columns[0].write(
                    f"Plus de 1,5 but : "
                    f"**{prediction['over15'] * 100:.1f} %**"
                )

                market_columns[1].write(
                    f"Plus de 2,5 buts : "
                    f"**{prediction['over25'] * 100:.1f} %**"
                )

                market_columns[2].write(
                    f"Moins de 3,5 buts : "
                    f"**{prediction['under35'] * 100:.1f} %**"
                )

                st.write(
                    f"Les deux équipes marquent : oui — "
                    f"**{prediction['btts_yes'] * 100:.1f} %**"
                )

                st.write(
                    f"Score exact le plus probable selon le modèle : "
                    f"**{prediction['score']}**"
                )

                st.write(
                    f"Marché le plus probable selon le modèle : "
                    f"**{prediction['best_market']}** "
                    f"({prediction['best_probability'] * 100:.1f} %)"
                )

                st.caption(
                    f"{prediction['quality']} — "
                    f"{prediction['sample_size']} match(s) récent(s) "
                    f"identifié(s) pour chacune des deux équipes "
                    f"dans les données chargées."
                )

                st.divider()


# ============================================================
# HISTORIQUE
# ============================================================

with tab_history:
    st.subheader("📚 Historique des pronostics")

    if not bets:
        st.info(
            "Aucun pronostic trouvé dans data/bankroll.json."
        )
    else:
        filter_status = st.selectbox(
            "Filtrer par statut",
            [
                "Tous",
                "En attente",
                "Gagné",
                "Perdu",
                "Annulé",
            ],
        )

        filtered_bets = []

        for bet in bets:
            status = normalise_status(bet)

            if filter_status == "Tous" or status == filter_status:
                filtered_bets.append(bet)

        history_rows = []

        for bet in filtered_bets[::-1]:
            history_rows.append(
                {
                    "Date du match": get_bet_date(bet) or "—",
                    "Compétition": get_bet_league(bet) or "—",
                    "Match": (
                        f"{get_bet_team(bet, 'home')} - "
                        f"{get_bet_team(bet, 'away')}"
                    ),
                    "Pronostic": get_bet_pick(bet) or "—",
                    "Probabilité (%)": round(
                        get_bet_probability(bet),
                        1,
                    ),
                    "Score prédit": bet.get("score", "—"),
                    "Mise (€)": round(
                        safe_float(bet.get("stake", 0)),
                        2,
                    ),
                    "Statut enregistré": normalise_status(bet),
                }
            )

        st.dataframe(
            history_rows,
            use_container_width=True,
            hide_index=True,
        )

        st.caption(
            "Le statut enregistré est affiché tel qu'il apparaît "
            "dans le fichier de données. La comparaison dans "
            "l'onglet calendrier évalue séparément le marché "
            "avec le score réel, sans modifier le fichier."
        )

    st.divider()

    st.subheader("📈 Évolution du capital")

    history = state.get("history", [])

    if history:
        chart_rows = []

        for row in history:
            chart_date = row.get("date", "")
            chart_bankroll = safe_float(
                row.get("bankroll", 0)
            )

            if chart_date:
                chart_rows.append(
                    {
                        "Date": chart_date,
                        "Capital (€)": chart_bankroll,
                    }
                )

        if chart_rows:
            st.line_chart(
                chart_rows,
                x="Date",
                y="Capital (€)",
            )
        else:
            st.info(
                "Les données disponibles ne permettent pas "
                "d'afficher la courbe."
            )
    else:
        st.info(
            "Aucun historique de capital enregistré pour le moment."
        )


# ============================================================
# PIED DE PAGE
# ============================================================

st.divider()

st.caption(
    "FOOT AI PRO — Outil d'analyse statistique. "
    "Les probabilités sont des estimations et ne garantissent "
    "pas le résultat d'un match. Parie de manière responsable."
)