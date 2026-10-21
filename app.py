import os
import math
from datetime import date, timedelta

import requests
import streamlit as st

# ==========================================================
# FOOT AI PRO V5 - VERSION SIMPLE ET STABLE
# API : football-data.org v4
# ==========================================================

st.set_page_config(
    page_title="FOOT AI PRO V5",
    page_icon="⚽",
    layout="wide",
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

# ==========================================================
# CONNEXION API
# ==========================================================

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
def api_get(endpoint, params=None):
    if not API_KEY:
        return None, "Clé API manquante"

    try:
        response = requests.get(
            f"{API_BASE}/{endpoint}",
            headers={"X-Auth-Token": API_KEY},
            params=params,
            timeout=20,
        )

        if response.status_code == 200:
            return response.json(), None

        if response.status_code == 403:
            return None, (
                "Accès refusé par football-data.org. "
                "Vérifie les compétitions autorisées sur ton compte."
            )

        if response.status_code == 429:
            return None, "Limite de requêtes API atteinte."

        return None, (
            f"Erreur API {response.status_code} : "
            f"{response.text[:250]}"
        )

    except requests.RequestException as exc:
        return None, f"Erreur de connexion : {exc}"


# ==========================================================
# OUTILS DE CALCUL
# ==========================================================

def poisson(lam, k):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0

    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_score(match):
    score = match.get("score", {}).get("fullTime", {})

    home = score.get("home")
    away = score.get("away")

    if home is None or away is None:
        return None

    return int(home), int(away)


def get_team_stats(team_id, before_date):
    start_date = before_date - timedelta(days=45)

    data, error = api_get(
        f"teams/{team_id}/matches",
        {
            "dateFrom": start_date.isoformat(),
            "dateTo": before_date.isoformat(),
            "status": "FINISHED",
            "limit": 10,
        },
    )

    if error or not data:
        return []

    matches = data.get("matches", [])

    matches.sort(
        key=lambda m: m.get("utcDate", ""),
        reverse=True,
    )

    return matches[:5]


def calculate_team_form(team_id, before_date):
    matches = get_team_stats(team_id, before_date)

    goals_for = []
    goals_against = []
    points = []

    for match in matches:
        score = get_score(match)

        if score is None:
            continue

        home_goals, away_goals = score

        home_id = match.get("homeTeam", {}).get("id")
        away_id = match.get("awayTeam", {}).get("id")

        if home_id == team_id:
            gf, ga = home_goals, away_goals
        elif away_id == team_id:
            gf, ga = away_goals, home_goals
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
            "goals_for": 1.2,
            "goals_against": 1.2,
            "points": 0,
            "form": "Données insuffisantes",
        }

    form = "".join(
        "V" if p == 3 else "N" if p == 1 else "D"
        for p in points
    )

    return {
        "matches": len(goals_for),
        "goals_for": sum(goals_for) / len(goals_for),
        "goals_against": sum(goals_against) / len(goals_against),
        "points": sum(points),
        "form": form,
    }


def calculate_predictions(home_stats, away_stats):
    # Estimation des buts attendus à domicile et à l'extérieur.
    home_attack = home_stats["goals_for"]
    home_defence = home_stats["goals_against"]

    away_attack = away_stats["goals_for"]
    away_defence = away_stats["goals_against"]

    home_lambda = (
        0.60 * home_attack
        + 0.40 * away_defence
        + 0.20
    )

    away_lambda = (
        0.60 * away_attack
        + 0.40 * home_defence
    )

    # Limites de sécurité pour les calculs.
    home_lambda = max(0.15, min(home_lambda, 4.5))
    away_lambda = max(0.15, min(away_lambda, 4.5))

    home_win = 0.0
    draw = 0.0
    away_win = 0.0
    over15 = 0.0
    over25 = 0.0
    btts = 0.0

    scores = []

    for h in range(8):
        for a in range(8):
            probability = (
                poisson(home_lambda, h)
                * poisson(away_lambda, a)
            )

            scores.append((h, a, probability))

            if h > a:
                home_win += probability
            elif h == a:
                draw += probability
            else:
                away_win += probability

            if h + a >= 2:
                over15 += probability

            if h + a >= 3:
                over25 += probability

            if h >= 1 and a >= 1:
                btts += probability

    total = home_win + draw + away_win

    if total > 0:
        home_win /= total
        draw /= total
        away_win /= total

    scores.sort(key=lambda item: item[2], reverse=True)

    return {
        "home_lambda": home_lambda,
        "away_lambda": away_lambda,
        "home_win": home_win * 100,
        "draw": draw * 100,
        "away_win": away_win * 100,
        "over15": over15 * 100,
        "over25": over25 * 100,
        "btts": btts * 100,
        "scores": scores[:5],
    }


# ==========================================================
# INTERFACE
# ==========================================================

st.title("⚽ FOOT AI PRO V5")
st.caption(
    "Pronostics football basés sur les résultats récents "
    "et un modèle probabiliste de Poisson."
)

with st.sidebar:
    st.header("⚙️ Paramètres")

    selected_competitions = st.multiselect(
        "Championnats",
        options=list(COMPETITIONS.keys()),
        default=list(COMPETITIONS.keys()),
    )

    selected_date = st.date_input(
        "Date des matchs",
        value=date.today(),
    )

    if st.button("🔄 Actualiser les données"):
        st.cache_data.clear()
        st.rerun()

if not API_KEY:
    st.error(
        "Clé API manquante. Ajoute FOOTBALL_DATA_API_KEY "
        "dans les Secrets de ton application Streamlit."
    )
    st.stop()

# ==========================================================
# RÉCUPÉRATION DES MATCHS
# ==========================================================

st.subheader(f"📅 Matchs du {selected_date.strftime('%d/%m/%Y')}")

all_matches = []
errors = []

if not selected_competitions:
    st.warning("Sélectionne au moins une compétition.")
    st.stop()

with st.spinner("Récupération des matchs..."):
    for competition_name in selected_competitions:
        competition_code = COMPETITIONS[competition_name]

        data, error = api_get(
            f"competitions/{competition_code}/matches",
            {
                "dateFrom": selected_date.isoformat(),
                "dateTo": selected_date.isoformat(),
            },
        )

        if error:
            errors.append(f"{competition_name} : {error}")
            continue

        if data:
            for match in data.get("matches", []):
                match["_competition_name"] = competition_name
                all_matches.append(match)

if errors:
    with st.expander("⚠️ Informations sur les compétitions"):
        for error in errors:
            st.warning(error)

if not all_matches:
    st.info(
        "Aucun match trouvé pour cette date dans les "
        "compétitions accessibles avec ta clé API."
    )
    st.stop()

all_matches.sort(key=lambda m: m.get("utcDate", ""))

st.success(f"{len(all_matches)} match(s) trouvé(s).")

# ==========================================================
# ANALYSE DES MATCHS
# ==========================================================

rankings = []

for match in all_matches:
    home_team = match.get("homeTeam", {})
    away_team = match.get("awayTeam", {})

    home_name = home_team.get("name", "Équipe domicile")
    away_name = away_team.get("name", "Équipe extérieur")

    home_id = home_team.get("id")
    away_id = away_team.get("id")

    competition = match.get("_competition_name", "")
    status = match.get("status", "")

    utc_date = match.get("utcDate", "")
    kickoff = utc_date[11:16] if len(utc_date) >= 16 else "--:--"

    with st.expander(
        f"⚽ {home_name} - {away_name} | {competition}",
        expanded=False,
    ):
        st.write(f"**Horaire UTC :** {kickoff}")
        st.write(f"**Statut :** {status}")

        if status in ("FINISHED", "AWARDED"):
            score = get_score(match)

            if score:
                st.write(
                    f"**Score final :** {score[0]} - {score[1]}"
                )

            st.info("Ce match est terminé.")
            continue

        if not home_id or not away_id:
            st.warning("Identifiants des équipes indisponibles.")
            continue

        with st.spinner("Analyse des cinq derniers matchs..."):
            home_stats = calculate_team_form(
                home_id,
                selected_date,
            )

            away_stats = calculate_team_form(
                away_id,
                selected_date,
            )

        predictions = calculate_predictions(
            home_stats,
            away_stats,
        )

        col1, col2 = st.columns(2)

        with col1:
            st.markdown(f"### 🏠 {home_name}")
            st.metric(
                "Buts marqués en moyenne",
                f"{home_stats['goals_for']:.2f}",
            )
            st.metric(
                "Buts encaissés en moyenne",
                f"{home_stats['goals_against']:.2f}",
            )
            st.write(f"**Forme récente :** {home_stats['form']}")
            st.write(
                f"**Matchs analysés :** {home_stats['matches']}"
            )

        with col2:
            st.markdown(f"### ✈️ {away_name}")
            st.metric(
                "Buts marqués en moyenne",
                f"{away_stats['goals_for']:.2f}",
            )
            st.metric(
                "Buts encaissés en moyenne",
                f"{away_stats['goals_against']:.2f}",
            )
            st.write(f"**Forme récente :** {away_stats['form']}")
            st.write(
                f"**Matchs analysés :** {away_stats['matches']}"
            )

        st.divider()
        st.markdown("### 📊 Probabilités estimées")

        c1, c2, c3 = st.columns(3)

        c1.metric(
            f"Victoire {home_name}",
            f"{predictions['home_win']:.1f} %",
        )

        c2.metric(
            "Match nul",
            f"{predictions['draw']:.1f} %",
        )

        c3.metric(
            f"Victoire {away_name}",
            f"{predictions['away_win']:.1f} %",
        )

        c4, c5, c6 = st.columns(3)

        c4.metric(
            "Plus de 1,5 but",
            f"{predictions['over15']:.1f} %",
        )

        c5.metric(
            "Plus de 2,5 buts",
            f"{predictions['over25']:.1f} %",
        )

        c6.metric(
            "Les deux équipes marquent",
            f"{predictions['btts']:.1f} %",
        )

        st.markdown("### 🎯 Scores exacts théoriques")

        for h, a, probability in predictions["scores"]:
            st.write(
                f"**{h} - {a}** : {probability * 100:.1f} %"
            )

        markets = {
            f"Victoire {home_name}": predictions["home_win"],
            "Match nul": predictions["draw"],
            f"Victoire {away_name}": predictions["away_win"],
            "Plus de 1,5 but": predictions["over15"],
            "Plus de 2,5 buts": predictions["over25"],
            "Les deux équipes marquent": predictions["btts"],
        }

        best_market = max(markets, key=markets.get)
        best_probability = markets[best_market]

        st.markdown("### ⭐ Pronostic principal")
        st.write(f"**{best_market} : {best_probability:.1f} %**")

        rankings.append({
            "Match": f"{home_name} - {away_name}",
            "Compétition": competition,
            "Pronostic": best_market,
            "Probabilité": best_probability,
        })

# ==========================================================
# CLASSEMENT DES PRONOSTICS
# ==========================================================

st.divider()
st.subheader("🏆 Classement des pronostics")

if rankings:
    rankings.sort(
        key=lambda item: item["Probabilité"],
        reverse=True,
    )

    st.caption(
        "Classement indicatif selon le marché ayant la "
        "probabilité estimée la plus élevée pour chaque match."
    )

    for index, item in enumerate(rankings, start=1):
        st.write(
            f"**{index}. {item['Match']}** — "
            f"{item['Pronostic']} : "
            f"{item['Probabilité']:.1f} %"
        )

st.caption(
    "Important : ces pourcentages sont des estimations "
    "mathématiques, pas des garanties. Le modèle utilise "
    "les cinq derniers matchs disponibles et ne prend pas "
    "en compte toutes les blessures, compositions ou "
    "informations en direct."
)