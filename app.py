import os
import math
from datetime import datetime, timedelta

import requests
import streamlit as st

# ==========================================================
# FOOT AI PRO — VERSION SCORES EXACTS INTELLIGENTS
# API : football-data.org v4
# ==========================================================

st.set_page_config(
    page_title="FOOT AI PRO",
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

st.markdown("""
<style>
.main {
    background-color: #07111f;
}
h1, h2, h3, p, label {
    color: #f4f7fb;
}
.match-card {
    padding: 18px;
    border-radius: 15px;
    background: #122238;
    border: 1px solid #28405d;
    margin-bottom: 12px;
}
.score {
    font-size: 27px;
    font-weight: bold;
    color: #49e3a2;
}
.small {
    color: #a9bbd0;
    font-size: 13px;
}
</style>
""", unsafe_allow_html=True)

st.title("⚽ FOOT AI PRO")
st.caption("Analyse des matchs • Scores exacts • Statistiques • Pronostics")


# ==========================================================
# CONNEXION API
# ==========================================================

def get_api_key():
    try:
        key = st.secrets.get("FOOTBALL_DATA_TOKEN", "")
        if key:
            return key
    except Exception:
        pass

    return os.getenv("FOOTBALL_DATA_TOKEN", "")


API_KEY = get_api_key()


def api_get(endpoint, params=None):
    if not API_KEY:
        return None, "Clé API absente."

    headers = {"X-Auth-Token": API_KEY}

    try:
        response = requests.get(
            f"{API_BASE}/{endpoint}",
            headers=headers,
            params=params,
            timeout=20,
        )

        if response.status_code == 200:
            return response.json(), None

        if response.status_code == 429:
            return None, "Limite de requêtes API atteinte."

        if response.status_code in (401, 403):
            return None, "Clé API invalide ou accès non autorisé."

        return None, f"Erreur API : HTTP {response.status_code}"

    except requests.RequestException as exc:
        return None, f"Erreur réseau : {exc}"


# ==========================================================
# CHARGEMENT DES MATCHS
# ==========================================================

@st.cache_data(ttl=900, show_spinner=False)
def get_matches(competition, date_from, date_to):
    data, error = api_get(
        f"competitions/{competition}/matches",
        {
            "dateFrom": date_from,
            "dateTo": date_to,
        },
    )

    if error:
        return [], error

    return data.get("matches", []), None


@st.cache_data(ttl=3600, show_spinner=False)
def get_team_matches(team_id):
    data, error = api_get(
        f"teams/{team_id}/matches",
        {
            "status": "FINISHED",
            "limit": 10,
        },
    )

    if error:
        return []

    matches = data.get("matches", [])

    matches.sort(
        key=lambda m: m.get("utcDate", ""),
        reverse=True,
    )

    return matches


# ==========================================================
# STATISTIQUES DES ÉQUIPES
# ==========================================================

def get_team_stats(team_id):
    matches = get_team_matches(team_id)

    goals_for = []
    goals_against = []

    home_for = []
    home_against = []

    away_for = []
    away_against = []

    points = []

    for match in matches:
        score = match.get("score", {}).get("fullTime", {})

        home_goals = score.get("home")
        away_goals = score.get("away")

        if home_goals is None or away_goals is None:
            continue

        home_id = match.get("homeTeam", {}).get("id")
        away_id = match.get("awayTeam", {}).get("id")

        if home_id == team_id:
            gf, ga = home_goals, away_goals
            home_for.append(gf)
            home_against.append(ga)
        elif away_id == team_id:
            gf, ga = away_goals, home_goals
            away_for.append(gf)
            away_against.append(ga)
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

    def avg(values, default):
        return sum(values) / len(values) if values else default

    return {
        "matches": len(goals_for),
        "goals_for": avg(goals_for, 1.2),
        "goals_against": avg(goals_against, 1.2),
        "home_for": avg(home_for, 1.4),
        "home_against": avg(home_against, 1.1),
        "away_for": avg(away_for, 1.1),
        "away_against": avg(away_against, 1.4),
        "points": avg(points, 1.0),
        "form": points,
        "recent_goals": goals_for[:5],
    }


# ==========================================================
# MODÈLE DE POISSON
# ==========================================================

def poisson_probability(goals, expected_goals):
    expected_goals = max(0.05, expected_goals)

    return (
        math.exp(-expected_goals)
        * expected_goals ** goals
        / math.factorial(goals)
    )


def calculate_expected_goals(home_stats, away_stats):
    """
    Estimation des buts attendus.
    Mélange des statistiques de l'équipe et de celles
    de son adversaire, avec avantage du terrain.
    """

    home_attack = home_stats["home_for"]
    home_defense = home_stats["home_against"]

    away_attack = away_stats["away_for"]
    away_defense = away_stats["away_against"]

    # Régression vers une moyenne pour limiter
    # les estimations extrêmes avec peu de matchs.
    home_attack = 0.75 * home_attack + 0.25 * 1.45
    away_defense = 0.75 * away_defense + 0.25 * 1.30

    away_attack = 0.75 * away_attack + 0.25 * 1.10
    home_defense = 0.75 * home_defense + 0.25 * 1.10

    home_xg = (
        0.58 * home_attack
        + 0.42 * away_defense
    )

    away_xg = (
        0.58 * away_attack
        + 0.42 * home_defense
    )

    # Utilisation de la forme récente si disponible.
    if home_stats["form"]:
        home_form = home_stats["points"] / 3
        home_xg *= 0.90 + 0.10 * home_form

    if away_stats["form"]:
        away_form = away_stats["points"] / 3
        away_xg *= 0.90 + 0.10 * away_form

    # Limites de sécurité.
    home_xg = min(3.8, max(0.15, home_xg))
    away_xg = min(3.5, max(0.15, away_xg))

    return home_xg, away_xg


def analyze_match(home_stats, away_stats):
    home_xg, away_xg = calculate_expected_goals(
        home_stats,
        away_stats,
    )

    max_goals = 10

    home_probs = [
        poisson_probability(i, home_xg)
        for i in range(max_goals + 1)
    ]

    away_probs = [
        poisson_probability(i, away_xg)
        for i in range(max_goals + 1)
    ]

    scores = []

    home_win = 0
    draw = 0
    away_win = 0

    over_15 = 0
    over_25 = 0
    over_35 = 0
    btts = 0

    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            probability = home_probs[h] * away_probs[a]

            scores.append({
                "home": h,
                "away": a,
                "prob": probability,
            })

            if h > a:
                home_win += probability
            elif h == a:
                draw += probability
            else:
                away_win += probability

            if h + a >= 2:
                over_15 += probability

            if h + a >= 3:
                over_25 += probability

            if h + a >= 4:
                over_35 += probability

            if h >= 1 and a >= 1:
                btts += probability

    scores.sort(
        key=lambda item: item["prob"],
        reverse=True,
    )

    # Probabilités arrondies uniquement à l'affichage.
    return {
        "home_xg": home_xg,
        "away_xg": away_xg,
        "scores": scores[:10],
        "home_win": home_win * 100,
        "draw": draw * 100,
        "away_win": away_win * 100,
        "over_15": over_15 * 100,
        "over_25": over_25 * 100,
        "over_35": over_35 * 100,
        "btts": btts * 100,
    }


# ==========================================================
# AFFICHAGE
# ==========================================================

def pct(value):
    return f"{value:.1f} %"


def display_match(match):
    home = match.get("homeTeam", {})
    away = match.get("awayTeam", {})

    home_name = home.get("name", "Domicile")
    away_name = away.get("name", "Extérieur")

    home_id = home.get("id")
    away_id = away.get("id")

    if not home_id or not away_id:
        st.warning("Identifiants des équipes indisponibles.")
        return

    match_date = match.get("utcDate", "")
    try:
        dt = datetime.fromisoformat(
            match_date.replace("Z", "+00:00")
        )
        date_label = dt.strftime("%d/%m/%Y à %H:%M UTC")
    except ValueError:
        date_label = match_date

    with st.spinner(f"Analyse de {home_name} - {away_name}..."):
        home_stats = get_team_stats(home_id)
        away_stats = get_team_stats(away_id)

        analysis = analyze_match(home_stats, away_stats)

    st.markdown(
        f"""
        <div class="match-card">
            <div class="small">{date_label}</div>
            <h3>{home_name} — {away_name}</h3>
            <div class="small">
                Buts attendus : {analysis['home_xg']:.2f}
                — {analysis['away_xg']:.2f}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)

    c1.metric(
        f"Victoire {home_name}",
        pct(analysis["home_win"]),
    )

    c2.metric(
        "Match nul",
        pct(analysis["draw"]),
    )

    c3.metric(
        f"Victoire {away_name}",
        pct(analysis["away_win"]),
    )

    st.markdown("#### 🎯 Scores exacts les plus probables")

    score_cols = st.columns(5)

    for i, score in enumerate(analysis["scores"][:5]):
        with score_cols[i]:
            st.metric(
                f"Score {i + 1}",
                f"{score['home']} - {score['away']}",
                pct(score["prob"] * 100),
            )

    with st.expander("Voir les 10 scores les plus probables"):
        for score in analysis["scores"]:
            st.write(
                f"**{score['home']} - {score['away']}** : "
                f"{pct(score['prob'] * 100)}"
            )

    st.markdown("#### 📊 Autres pronostics")

    p1, p2, p3, p4 = st.columns(4)

    p1.metric("+1,5 but", pct(analysis["over_15"]))
    p2.metric("+2,5 buts", pct(analysis["over_25"]))
    p3.metric("+3,5 buts", pct(analysis["over_35"]))
    p4.metric("Les 2 équipes marquent", pct(analysis["btts"]))

    with st.expander("📈 Forme et statistiques récentes"):
        st.write(f"**{home_name}**")
        st.write(
            f"- Matchs analysés : {home_stats['matches']}\n"
            f"- Buts marqués par match : {home_stats['goals_for']:.2f}\n"
            f"- Buts encaissés par match : {home_stats['goals_against']:.2f}\n"
            f"- Buts marqués à domicile : {home_stats['home_for']:.2f}\n"
            f"- Buts encaissés à domicile : {home_stats['home_against']:.2f}"
        )

        st.write(f"**{away_name}**")
        st.write(
            f"- Matchs analysés : {away_stats['matches']}\n"
            f"- Buts marqués par match : {away_stats['goals_for']:.2f}\n"
            f"- Buts encaissés par match : {away_stats['goals_against']:.2f}\n"
            f"- Buts marqués à l'extérieur : {away_stats['away_for']:.2f}\n"
            f"- Buts encaissés à l'extérieur : {away_stats['away_against']:.2f}"
        )

    st.caption(
        "Estimations statistiques, pas des garanties de résultat. "
        "Les scores exacts sont naturellement plus difficiles à prévoir."
    )

    st.divider()


# ==========================================================
# INTERFACE PRINCIPALE
# ==========================================================

if not API_KEY:
    st.error(
        "Clé API manquante. Ajoute FOOTBALL_DATA_TOKEN "
        "dans les Secrets de ton application Streamlit."
    )

    st.code(
        'FOOTBALL_DATA_TOKEN = "TA_CLE_API"',
        language="toml",
    )

    st.stop()

today = datetime.now().date()

with st.sidebar:
    st.header("⚙️ Paramètres")

    selected_competitions = st.multiselect(
        "Championnats",
        options=list(COMPETITIONS.keys()),
        default=["Ligue 1", "Premier League", "Liga"],
    )

    start_date = st.date_input(
        "Du",
        value=today,
    )

    end_date = st.date_input(
        "Au",
        value=today + timedelta(days=3),
        min_value=start_date,
    )

    refresh = st.button(
        "🔄 Actualiser les données",
        use_container_width=True,
    )

if refresh:
    st.cache_data.clear()
    st.rerun()

if end_date < start_date:
    st.error("La date de fin doit être après la date de début.")
    st.stop()

if (end_date - start_date).days > 10:
    st.warning("Pour éviter trop de requêtes API, sélectionne au maximum 10 jours.")
    st.stop()

if not selected_competitions:
    st.info("Choisis au moins un championnat dans le menu.")
    st.stop()

all_matches = []

progress = st.progress(0)

for index, competition_name in enumerate(selected_competitions):
    competition_code = COMPETITIONS[competition_name]

    matches, error = get_matches(
        competition_code,
        start_date.isoformat(),
        end_date.isoformat(),
    )

    if error:
        st.warning(
            f"{competition_name} : {error}"
        )
    else:
        for match in matches:
            match["_competition_name"] = competition_name
            all_matches.append(match)

    progress.progress(
        (index + 1) / len(selected_competitions)
    )

progress.empty()

all_matches.sort(
    key=lambda m: m.get("utcDate", "")
)

st.subheader("📅 Calendrier des rencontres")

if not all_matches:
    st.warning(
        "Aucun match disponible pour cette période. "
        "Essaie d'autres dates ou vérifie les compétitions autorisées "
        "par ton abonnement API."
    )
    st.stop()

st.success(f"{len(all_matches)} rencontre(s) trouvée(s).")

competition_filter = st.selectbox(
    "Filtrer les matchs",
    ["Tous"] + selected_competitions,
)

if competition_filter != "Tous":
    all_matches = [
        m for m in all_matches
        if m.get("_competition_name") == competition_filter
    ]

search = st.text_input(
    "🔎 Rechercher une équipe",
    placeholder="Exemple : PSG, Lille, Arsenal...",
)

if search.strip():
    all_matches = [
        m for m in all_matches
        if search.lower() in (
            m.get("homeTeam", {}).get("name", "")
            + " "
            + m.get("awayTeam", {}).get("name", "")
        ).lower()
    ]

tab1, tab2 = st.tabs([
    "⚽ Tous les matchs",
    "🏆 Classement des pronostics",
])

with tab1:
    for match in all_matches:
        st.caption(
            f"Compétition : {match.get('_competition_name', '')}"
        )
        display_match(match)

with tab2:
    st.write(
        "Ce classement compare les probabilités du modèle. "
        "Une probabilité élevée ne garantit pas le résultat."
    )

    ranking = []

    for match in all_matches:
        home = match.get("homeTeam", {})
        away = match.get("awayTeam", {})

        if not home.get("id") or not away.get("id"):
            continue

        home_stats = get_team_stats(home["id"])
        away_stats = get_team_stats(away["id"])

        analysis = analyze_match(home_stats, away_stats)

        best_score = analysis["scores"][0]

        ranking.append({
            "Match": f"{home.get('name')} - {away.get('name')}",
            "Score probable": (
                f"{best_score['home']} - {best_score['away']}"
            ),
            "Probabilité du score": best_score["prob"] * 100,
            "+1,5 but": analysis["over_15"],
            "+2,5 buts": analysis["over_25"],
            "Deux équipes marquent": analysis["btts"],
            "Confiance résultat": max(
                analysis["home_win"],
                analysis["draw"],
                analysis["away_win"],
            ),
        })

    ranking.sort(
        key=lambda row: row["Confiance résultat"],
        reverse=True,
    )

    if ranking:
        st.dataframe(
            [
                {
                    **row,
                    "Probabilité du score": (
                        f"{row['Probabilité du score']:.1f} %"
                    ),
                    "+1,5 but": f"{row['+1,5 but']:.1f} %",
                    "+2,5 buts": f"{row['+2,5 buts']:.1f} %",
                    "Deux équipes marquent": (
                        f"{row['Deux équipes marquent']:.1f} %"
                    ),
                    "Confiance résultat": (
                        f"{row['Confiance résultat']:.1f} %"
                    ),
                }
                for row in ranking
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Aucun pronostic disponible.")

st.caption(
    "FOOT AI PRO — Les probabilités reposent sur les résultats historiques "
    "disponibles. Elles ne constituent pas des probabilités garanties "
    "ni des conseils de pari."
)