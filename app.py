import os
import json
import math
from datetime import date, timedelta

import requests
import streamlit as st

# ============================================================
# FOOT AI PRO — ANALYSE IA ET SIMULATION
# API : football-data.org v4
# Compétitions : FL1, PL, PD, BL1, SA, CL
# Capital virtuel de départ : 20 €
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
# CLÉ API
# ============================================================

def get_api_key():
    try:
        key = st.secrets.get("FOOTBALL_DATA_API_KEY", "")
        if key:
            return key
    except Exception:
        pass

    return os.getenv("FOOTBALL_DATA_API_KEY", "")


# ============================================================
# CAPITAL ET HISTORIQUE VIRTUELS
# ============================================================

def load_state():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return {
            "starting_bankroll": 20.0,
            "bankroll": 20.0,
            "day": "",
            "bets": [],
            "history": [],
            "message": "Le bot automatique n'a pas encore été lancé.",
        }


# ============================================================
# RÉCUPÉRATION DES MATCHS
# ============================================================

def get_matches(competition, start_date, end_date, api_key):
    url = f"{API_BASE}/competitions/{competition}/matches"

    headers = {
        "X-Auth-Token": api_key,
    }

    params = {
        "dateFrom": start_date,
        "dateTo": end_date,
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=20,
    )

    if response.status_code == 429:
        raise RuntimeError(
            "Limite de requêtes API atteinte. "
            "Réessaie plus tard."
        )

    if response.status_code == 403:
        raise RuntimeError(
            f"Accès refusé pour la compétition {competition}. "
            "Vérifie les droits de ton abonnement."
        )

    response.raise_for_status()

    return response.json().get("matches", [])


# ============================================================
# MODÈLE DE POISSON
# ============================================================

def poisson(lam, goals):
    if lam <= 0:
        return 1.0 if goals == 0 else 0.0

    return (
        math.exp(-lam)
        * (lam ** goals)
        / math.factorial(goals)
    )


# ============================================================
# ANALYSE D'UN MATCH
# ============================================================

def predict_match(matches, home_team, away_team):

    league_home_goals = []
    league_away_goals = []

    home_scored = []
    home_conceded = []

    away_scored = []
    away_conceded = []

    for match in matches:

        if match.get("status") != "FINISHED":
            continue

        score = match.get("score", {}).get("fullTime", {})

        home_goals = score.get("home")
        away_goals = score.get("away")

        if home_goals is None or away_goals is None:
            continue

        home_name = match.get("homeTeam", {}).get("name", "")
        away_name = match.get("awayTeam", {}).get("name", "")

        league_home_goals.append(home_goals)
        league_away_goals.append(away_goals)

        # Historique de l'équipe qui reçoit
        if home_name == home_team:
            home_scored.append(home_goals)
            home_conceded.append(away_goals)

        elif away_name == home_team:
            home_scored.append(away_goals)
            home_conceded.append(home_goals)

        # Historique de l'équipe qui se déplace
        if home_name == away_team:
            away_scored.append(home_goals)
            away_conceded.append(away_goals)

        elif away_name == away_team:
            away_scored.append(away_goals)
            away_conceded.append(home_goals)

    # Moyennes de la compétition
    avg_home = (
        sum(league_home_goals) / len(league_home_goals)
        if league_home_goals
        else 1.45
    )

    avg_away = (
        sum(league_away_goals) / len(league_away_goals)
        if league_away_goals
        else 1.15
    )

    # Moyennes propres aux équipes
    home_attack = (
        sum(home_scored) / len(home_scored)
        if home_scored
        else avg_home
    )

    home_defence = (
        sum(home_conceded) / len(home_conceded)
        if home_conceded
        else avg_away
    )

    away_attack = (
        sum(away_scored) / len(away_scored)
        if away_scored
        else avg_away
    )

    away_defence = (
        sum(away_conceded) / len(away_conceded)
        if away_conceded
        else avg_home
    )

    # Réduire l'influence des échantillons trop petits
    if len(home_scored) < 3:
        home_attack = (home_attack + avg_home) / 2
        home_defence = (home_defence + avg_away) / 2

    if len(away_scored) < 3:
        away_attack = (away_attack + avg_away) / 2
        away_defence = (away_defence + avg_home) / 2

    # Nombre de buts attendus
    lambda_home = max(
        0.15,
        min(3.5, 0.55 * home_attack + 0.45 * away_defence),
    )

    lambda_away = max(
        0.15,
        min(3.5, 0.55 * away_attack + 0.45 * home_defence),
    )

    # Probabilités des scores
    scores = {}

    for home_goals in range(9):
        for away_goals in range(9):

            probability = (
                poisson(lambda_home, home_goals)
                * poisson(lambda_away, away_goals)
            )

            scores[(home_goals, away_goals)] = probability

    total = sum(scores.values()) or 1

    # Victoire, nul et défaite
    p_home = sum(
        p for (h, a), p in scores.items() if h > a
    ) / total

    p_draw = sum(
        p for (h, a), p in scores.items() if h == a
    ) / total

    p_away = sum(
        p for (h, a), p in scores.items() if h < a
    ) / total

    # Marchés de buts
    over05 = sum(
        p for (h, a), p in scores.items() if h + a >= 1
    ) / total

    over15 = sum(
        p for (h, a), p in scores.items() if h + a >= 2
    ) / total

    over25 = sum(
        p for (h, a), p in scores.items() if h + a >= 3
    ) / total

    over35 = sum(
        p for (h, a), p in scores.items() if h + a >= 4
    ) / total

    under25 = sum(
        p for (h, a), p in scores.items() if h + a <= 2
    ) / total

    under35 = sum(
        p for (h, a), p in scores.items() if h + a <= 3
    ) / total

    btts_yes = sum(
        p for (h, a), p in scores.items() if h > 0 and a > 0
    ) / total

    btts_no = 1 - btts_yes

    # Double chance
    double_home_draw = p_home + p_draw
    double_draw_away = p_draw + p_away

    # Score le plus probable
    best_score = max(scores, key=scores.get)

    # Sélection statistique du marché le plus probable
    markets = {
        "Plus de 0,5 but": over05,
        "Plus de 1,5 but": over15,
        "Plus de 2,5 buts": over25,
        "Plus de 3,5 buts": over35,
        "Moins de 2,5 buts": under25,
        "Moins de 3,5 buts": under35,
        "Les deux équipes marquent : oui": btts_yes,
        "Les deux équipes marquent : non": btts_no,
        "Victoire domicile": p_home,
        "Match nul": p_draw,
        "Victoire extérieur": p_away,
        "Double chance 1X": double_home_draw,
        "Double chance X2": double_draw_away,
    }

    best_market = max(markets, key=markets.get)

    sample = min(
        len(home_scored),
        len(away_scored),
    )

    return {
        "home": home_team,
        "away": away_team,
        "home_win": round(p_home * 100, 1),
        "draw": round(p_draw * 100, 1),
        "away_win": round(p_away * 100, 1),
        "over05": round(over05 * 100, 1),
        "over15": round(over15 * 100, 1),
        "over25": round(over25 * 100, 1),
        "over35": round(over35 * 100, 1),
        "under25": round(under25 * 100, 1),
        "under35": round(under35 * 100, 1),
        "btts_yes": round(btts_yes * 100, 1),
        "btts_no": round(btts_no * 100, 1),
        "double_1x": round(double_home_draw * 100, 1),
        "double_x2": round(double_draw_away * 100, 1),
        "score": f"{best_score[0]}-{best_score[1]}",
        "best_market": best_market,
        "best_probability": round(markets[best_market] * 100, 1),
        "sample": sample,
        "quality": (
            "Données limitées"
            if sample < 3
            else "Échantillon statistique"
        ),
    }


# ============================================================
# INTERFACE
# ============================================================

st.title("⚽ FOOT AI PRO")
st.caption(
    "Analyse statistique des matchs et suivi de paris virtuels."
)

state = load_state()

capital = float(state.get("bankroll", 20.0))
starting_capital = float(state.get("starting_bankroll", 20.0))
bets = state.get("bets", [])

col1, col2, col3 = st.columns(3)

col1.metric(
    "Capital virtuel",
    f"{capital:.2f} €",
)

col2.metric(
    "Paris virtuels enregistrés",
    len(bets),
)

col3.metric(
    "Résultat virtuel",
    f"{capital - starting_capital:+.2f} €",
)

st.info(
    state.get(
        "message",
        "Le bot automatique n'a pas encore été lancé.",
    )
)

# ============================================================
# PARAMÈTRES
# ============================================================

with st.sidebar:

    st.header("⚙️ Paramètres")

    selected_competitions = st.multiselect(
        "Compétitions",
        list(COMPETITIONS.keys()),
        default=list(COMPETITIONS.keys()),
    )

    days_ahead = st.slider(
        "Nombre de jours à analyser",
        min_value=1,
        max_value=7,
        value=3,
    )

    st.caption(
        "Les compétitions disponibles dépendent des droits de ta clé API."
    )

# ============================================================
# ONGLETS
# ============================================================

tab_matches, tab_ai, tab_history = st.tabs(
    [
        "📅 Matchs",
        "🤖 Analyse IA",
        "📊 Historique",
    ]
)

# ============================================================
# MATCHS
# ============================================================

with tab_matches:

    key = get_api_key()

    if not key:

        st.error(
            "Clé API manquante. Dans les Secrets Streamlit, ajoute :"
        )

        st.code(
            'FOOTBALL_DATA_API_KEY = "TA_CLE_API"'
        )

    elif st.button(
        "🔎 Analyser les matchs",
        type="primary",
    ):

        start_date = date.today()
        end_date = start_date + timedelta(days=days_ahead)

        all_predictions = []
        errors = []

        with st.spinner("Analyse des rencontres en cours..."):

            for league in selected_competitions:

                competition_code = COMPETITIONS[league]

                try:

                    matches = get_matches(
                        competition_code,
                        start_date.isoformat(),
                        end_date.isoformat(),
                        key,
                    )

                    for match in matches:

                        if match.get("status") not in (
                            "SCHEDULED",
                            "TIMED",
                            "IN_PLAY",
                            "PAUSED",
                        ):
                            continue

                        home = match.get(
                            "homeTeam", {}
                        ).get("name", "Domicile")

                        away = match.get(
                            "awayTeam", {}
                        ).get("name", "Extérieur")

                        prediction = predict_match(
                            matches,
                            home,
                            away,
                        )

                        prediction["league"] = league

                        prediction["date"] = (
                            match.get("utcDate", "")
                            .replace("T", " ")[:16]
                            + " UTC"
                        )

                        all_predictions.append(prediction)

                except Exception as error:
                    errors.append(
                        f"{league} : {error}"
                    )

        for error in errors:
            st.warning(error)

        if not all_predictions:

            st.info(
                "Aucun match disponible pour cette période. "
                "Vérifie aussi les droits de ta clé API."
            )

        else:

            all_predictions.sort(
                key=lambda item: item["best_probability"],
                reverse=True,
            )

            st.success(
                f"{len(all_predictions)} rencontre(s) analysée(s)."
            )

            for prediction in all_predictions:

                with st.container(border=True):

                    st.subheader(
                        f'{prediction["home"]} - {prediction["away"]}'
                    )

                    st.caption(
                        f'{prediction["league"]} · '
                        f'{prediction["date"]}'
                    )

                    c1, c2, c3 = st.columns(3)

                    c1.metric(
                        "Victoire domicile",
                        f'{prediction["home_win"]} %',
                    )

                    c2.metric(
                        "Match nul",
                        f'{prediction["draw"]} %',
                    )

                    c3.metric(
                        "Victoire extérieur",
                        f'{prediction["away_win"]} %',
                    )

                    st.markdown("#### ⚽ Marchés de buts")

                    a, b, c = st.columns(3)

                    a.metric(
                        "+ 1,5 but",
                        f'{prediction["over15"]} %',
                    )

                    b.metric(
                        "+ 2,5 buts",
                        f'{prediction["over25"]} %',
                    )

                    c.metric(
                        "+ 3,5 buts",
                        f'{prediction["over35"]} %',
                    )

                    a, b, c = st.columns(3)

                    a.metric(
                        "BTTS oui",
                        f'{prediction["btts_yes"]} %',
                    )

                    b.metric(
                        "BTTS non",
                        f'{prediction["btts_no"]} %',
                    )

                    c.metric(
                        "Double chance 1X",
                        f'{prediction["double_1x"]} %',
                    )

                    st.markdown("#### 🤖 Sélection statistique")

                    st.write(
                        f'**Marché :** {prediction["best_market"]}'
                    )

                    st.write(
                        f'**Probabilité estimée :** '
                        f'{prediction["best_probability"]} %'
                    )

                    st.write(
                        f'**Score indicatif :** {prediction["score"]}'
                    )

                    st.caption(
                        f'{prediction["quality"]} · '
                        f'{prediction["sample"]} match(s) '
                        f'dans l’échantillon minimum'
                    )

# ============================================================
# ANALYSE IA ET SIMULATION
# ============================================================

with tab_ai:

    st.subheader("🤖 Gestion de la simulation")

    st.write(
        "Capital de départ : 20 € virtuels."
    )

    st.write(
        "Le bot automatique sera lancé par GitHub Actions "
        "après installation des fichiers complémentaires."
    )

    st.write(
        f'Dernière exécution enregistrée : '
        f'{state.get("day") or "Aucune"}'
    )

    st.warning(
        "Cette version n'effectue aucun pari réel. "
        "Les vraies cotes Unibet ne sont pas encore intégrées. "
        "Les probabilités sont des estimations, pas des garanties."
    )

    st.markdown("#### Principes de gestion")

    st.write("- Mises virtuelles limitées.")
    st.write("- Maximum de deux nouvelles sélections virtuelles par jour.")
    st.write("- Pas de martingale.")
    st.write("- Historique des résultats.")
    st.write("- Capital fictif suivi au fil du temps.")

# ============================================================
# HISTORIQUE
# ============================================================

with tab_history:

    st.subheader("📊 Historique des simulations")

    if bets:

        st.dataframe(
            bets,
            use_container_width=True,
            hide_index=True,
        )

    else:

        st.info(
            "Aucun pari virtuel enregistré pour le moment."
        )

    history = state.get("history", [])

    if history:

        st.subheader("Évolution du capital virtuel")

        st.dataframe(
            history,
            use_container_width=True,
            hide_index=True,
        )

# ============================================================
# AVERTISSEMENT
# ============================================================

st.divider()

st.caption(
    "FOOT AI PRO est un outil expérimental. "
    "Il ne garantit aucun gain. Les blessures, compositions officielles, "
    "suspensions et cotes réelles ne sont pas intégrées."
)