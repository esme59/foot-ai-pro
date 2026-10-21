import os
import math
from datetime import date, timedelta

import requests
import streamlit as st


# ============================================================
# FOOT AI PRO - VERSION COMPLETE
# API : football-data.org v4
# Ligue des Champions : CL
# ============================================================

st.set_page_config(
    page_title="FOOT AI PRO",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_BASE = "https://api.football-data.org/v4"
TIMEOUT = 20

COMPETITIONS = {
    "🇫🇷 Ligue 1": "FL1",
    "🏴 Premier League": "PL",
    "🇪🇸 Liga": "PD",
    "🇩🇪 Bundesliga": "BL1",
    "🇮🇹 Serie A": "SA",
    "🏆 Ligue des Champions": "CL",
}


# ============================================================
# CONFIGURATION API
# ============================================================

def get_api_key():
    # Noms possibles pour conserver les anciens Secrets.
    for name in (
        "FOOTBALL_DATA_API_KEY",
        "FOOTBALL_API_KEY",
        "FOOTBALL_DATA_TOKEN",
    ):
        try:
            value = st.secrets.get(name, "")
            if value:
                return str(value).strip()
        except Exception:
            pass

    return os.getenv("FOOTBALL_DATA_API_KEY", "").strip()


API_KEY = get_api_key()


def api_get(endpoint, params=None):
    if not API_KEY:
        return None, (
            "Clé API manquante. Vérifie les Secrets "
            "de Streamlit."
        )

    url = f"{API_BASE}/{endpoint.lstrip('/')}"

    try:
        response = requests.get(
            url,
            headers={"X-Auth-Token": API_KEY},
            params=params or {},
            timeout=TIMEOUT,
        )

        if response.status_code == 401:
            return None, "Clé API invalide ou non reconnue."

        if response.status_code == 403:
            return None, (
                "Accès refusé par football-data.org. "
                "Vérifie si ton abonnement autorise "
                "cette compétition."
            )

        if response.status_code == 429:
            return None, (
                "Limite de requêtes API atteinte. "
                "Réessaie un peu plus tard."
            )

        if not response.ok:
            return None, (
                f"Erreur API HTTP {response.status_code}."
            )

        return response.json(), None

    except requests.RequestException:
        return None, (
            "Impossible de contacter football-data.org. "
            "Vérifie ta connexion."
        )

    except ValueError:
        return None, "Réponse API illisible."


# ============================================================
# STYLE
# ============================================================

st.markdown(
    """
    <style>
    .stApp {
        background-color: #0b1220;
        color: #ffffff;
    }

    h1, h2, h3 {
        color: #ffffff !important;
    }

    div[data-testid="stMetric"] {
        background: #172235;
        border: 1px solid #293952;
        padding: 14px;
        border-radius: 12px;
    }

    div[data-testid="stMetricLabel"] {
        color: #aabbd1;
    }

    .match-card {
        background: #172235;
        border: 1px solid #293952;
        padding: 16px;
        border-radius: 14px;
        margin-bottom: 12px;
    }

    .badge {
        display: inline-block;
        padding: 5px 9px;
        border-radius: 7px;
        background: #173b32;
        color: #8cf5c6;
        font-weight: bold;
    }

    .small-text {
        color: #aabbd1;
        font-size: 13px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# OUTILS
# ============================================================

def parse_date(value):
    if not value:
        return None

    try:
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def safe_name(team):
    return (team or {}).get("name", "Équipe inconnue")


def get_matches(competition, start_date, end_date):
    """
    Récupère les rencontres d'une compétition
    sur la période demandée.
    """

    data, error = api_get(
        f"competitions/{competition}/matches",
        {
            "dateFrom": start_date.isoformat(),
            "dateTo": end_date.isoformat(),
        },
    )

    if error:
        return [], error

    return data.get("matches", []), None


def get_team_history(team_id, match_date):
    """
    Récupère les derniers matchs terminés
    avant la date du match à analyser.
    """

    end_date = match_date - timedelta(days=1)
    start_date = end_date - timedelta(days=180)

    data, error = api_get(
        f"teams/{team_id}/matches",
        {
            "dateFrom": start_date.isoformat(),
            "dateTo": end_date.isoformat(),
            "status": "FINISHED",
            "limit": 10,
        },
    )

    if error:
        return [], error

    matches = data.get("matches", [])

    matches.sort(
        key=lambda match: match.get("utcDate", ""),
        reverse=True,
    )

    return matches[:10], None


# ============================================================
# STATISTIQUES DES EQUIPES
# ============================================================

def team_statistics(matches, team_id):
    """
    Calcule les buts marqués et encaissés.
    Distingue les matchs à domicile et à l'extérieur.
    """

    all_games = []
    home_games = []
    away_games = []

    for match in matches:
        home_id = (
            match.get("homeTeam", {}).get("id")
        )
        away_id = (
            match.get("awayTeam", {}).get("id")
        )

        score = match.get("score", {}).get("fullTime", {})
        hg = score.get("home")
        ag = score.get("away")

        if hg is None or ag is None:
            continue

        if home_id == team_id:
            record = {
                "gf": hg,
                "ga": ag,
                "venue": "home",
                "date": match.get("utcDate", ""),
            }

        elif away_id == team_id:
            record = {
                "gf": ag,
                "ga": hg,
                "venue": "away",
                "date": match.get("utcDate", ""),
            }

        else:
            continue

        all_games.append(record)

        if record["venue"] == "home":
            home_games.append(record)
        else:
            away_games.append(record)

    def averages(games):
        if not games:
            return None

        return {
            "gf": sum(g["gf"] for g in games) / len(games),
            "ga": sum(g["ga"] for g in games) / len(games),
            "n": len(games),
        }

    return {
        "all": averages(all_games),
        "home": averages(home_games),
        "away": averages(away_games),
        "count": len(all_games),
        "recent": all_games[:5],
    }


# ============================================================
# MODELE DE POISSON
# ============================================================

def poisson_probability(lam, goals):
    if lam <= 0:
        return 1.0 if goals == 0 else 0.0

    return (
        math.exp(-lam)
        * (lam ** goals)
        / math.factorial(goals)
    )


def get_expected_goals(home_stats, away_stats):
    """
    Estimation des buts attendus.

    Priorité aux performances à domicile et à l'extérieur,
    avec repli sur les statistiques générales.
    """

    home_attack = (
        home_stats["home"]
        or home_stats["all"]
    )

    home_defence = (
        home_stats["home"]
        or home_stats["all"]
    )

    away_attack = (
        away_stats["away"]
        or away_stats["all"]
    )

    away_defence = (
        away_stats["away"]
        or away_stats["all"]
    )

    if not all(
        [home_attack, home_defence, away_attack, away_defence]
    ):
        return None

    # Moyennes pondérées : attaque propre et défense adverse.
    home_xg = (
        0.55 * home_attack["gf"]
        + 0.45 * away_defence["ga"]
    ) * 1.08

    away_xg = (
        0.55 * away_attack["gf"]
        + 0.45 * home_defence["ga"]
    ) * 0.94

    # Évite des valeurs extrêmes.
    home_xg = max(0.15, min(home_xg, 4.5))
    away_xg = max(0.15, min(away_xg, 4.5))

    return home_xg, away_xg


def calculate_predictions(home_xg, away_xg):
    """
    Probabilités théoriques calculées à partir
    d'une distribution de Poisson.
    """

    max_goals = 10

    home_probs = [
        poisson_probability(home_xg, i)
        for i in range(max_goals + 1)
    ]

    away_probs = [
        poisson_probability(away_xg, i)
        for i in range(max_goals + 1)
    ]

    matrix = []

    for h in range(max_goals + 1):
        row = []

        for a in range(max_goals + 1):
            row.append(home_probs[h] * away_probs[a])

        matrix.append(row)

    p_home = 0.0
    p_draw = 0.0
    p_away = 0.0

    p_over15 = 0.0
    p_over25 = 0.0
    p_over35 = 0.0
    p_btts = 0.0

    scores = []

    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            probability = matrix[h][a]
            total = h + a

            if h > a:
                p_home += probability
            elif h == a:
                p_draw += probability
            else:
                p_away += probability

            if total >= 2:
                p_over15 += probability

            if total >= 3:
                p_over25 += probability

            if total >= 4:
                p_over35 += probability

            if h >= 1 and a >= 1:
                p_btts += probability

            scores.append((h, a, probability))

    total_probability = p_home + p_draw + p_away

    if total_probability > 0:
        p_home /= total_probability
        p_draw /= total_probability
        p_away /= total_probability

    scores.sort(key=lambda item: item[2], reverse=True)

    return {
        "home": p_home,
        "draw": p_draw,
        "away": p_away,
        "over15": p_over15,
        "over25": p_over25,
        "over35": p_over35,
        "btts": p_btts,
        "scores": scores[:5],
        "home_xg": home_xg,
        "away_xg": away_xg,
    }


def pct(value):
    return f"{value * 100:.1f} %"


# ============================================================
# ANALYSE D'UN MATCH
# ============================================================

@st.cache_data(ttl=600, show_spinner=False)
def analyze_match(match_id, home_id, away_id, match_date):
    """
    Les données historiques sont récupérées séparément
    pour les deux équipes.
    """

    home_matches, home_error = get_team_history(
        home_id, match_date
    )

    away_matches, away_error = get_team_history(
        away_id, match_date
    )

    if home_error or away_error:
        return {
            "error": home_error or away_error
        }

    home_stats = team_statistics(home_matches, home_id)
    away_stats = team_statistics(away_matches, away_id)

    if (
        home_stats["count"] < 3
        or away_stats["count"] < 3
    ):
        return {
            "error": (
                "Pas assez de matchs récents pour produire "
                "une analyse fiable."
            )
        }

    expected = get_expected_goals(
        home_stats,
        away_stats,
    )

    if not expected:
        return {
            "error": "Statistiques insuffisantes."
        }

    predictions = calculate_predictions(
        expected[0],
        expected[1],
    )

    predictions["home_stats"] = home_stats
    predictions["away_stats"] = away_stats

    return predictions


# ============================================================
# CHARGEMENT PRINCIPAL
# ============================================================

st.title("⚽ FOOT AI PRO")
st.caption(
    "Analyse des matchs • Statistiques • Pronostics • Combinés"
)

if not API_KEY:
    st.error(
        "Clé API manquante. Ouvre Settings > Secrets "
        "dans Streamlit Cloud et vérifie le nom "
        "FOOTBALL_DATA_API_KEY."
    )
    st.stop()


with st.sidebar:
    st.header("⚙️ Configuration")

    selected_competitions = st.multiselect(
        "Championnats",
        options=list(COMPETITIONS.keys()),
        default=list(COMPETITIONS.keys()),
    )

    selected_day = st.date_input(
        "Date des rencontres",
        value=date.today(),
    )

    days_forward = st.selectbox(
        "Période",
        options=[0, 1, 3, 7],
        format_func=lambda x: (
            "Aujourd'hui"
            if x == 0
            else f"Aujourd'hui + {x} jour(s)"
        ),
        index=0,
    )

    refresh = st.button(
        "🔄 Actualiser les données",
        use_container_width=True,
    )

if refresh:
    st.cache_data.clear()


# ============================================================
# RECUPERATION DES RENCONTRES
# ============================================================

all_matches = []
competition_errors = {}

if not selected_competitions:
    st.warning("Sélectionne au moins une compétition.")
    st.stop()

with st.spinner("Récupération des rencontres..."):
    for competition_name in selected_competitions:
        competition_code = COMPETITIONS[competition_name]

        matches, error = get_matches(
            competition_code,
            selected_day,
            selected_day + timedelta(days=days_forward),
        )

        if error:
            competition_errors[competition_name] = error
            continue

        for match in matches:
            match["_competition_name"] = competition_name
            match["_competition_code"] = competition_code
            all_matches.append(match)


if competition_errors:
    with st.expander("⚠️ Problèmes d'accès aux compétitions"):
        for name, error in competition_errors.items():
            st.warning(f"{name} : {error}")


# ============================================================
# FILTRES ET ONGLETS
# ============================================================

tab_matches, tab_analysis, tab_ranking, tab_combinations = st.tabs(
    [
        "📅 Matchs du jour",
        "🧠 Analyse IA",
        "🏆 Classement des pronostics",
        "🎯 Combinés",
    ]
)


def match_status(match):
    status = match.get("status", "")

    if status == "IN_PLAY":
        return "🔴 EN DIRECT"

    if status == "PAUSED":
        return "⏸️ MI-TEMPS"

    if status == "FINISHED":
        return "✅ TERMINÉ"

    if status == "POSTPONED":
        return "⏳ REPORTÉ"

    return "🕒 À VENIR"


def match_label(match):
    home = safe_name(match.get("homeTeam"))
    away = safe_name(match.get("awayTeam"))

    return (
        f"{home} - {away} "
        f"({match.get('_competition_name', '')})"
    )


def format_kickoff(match):
    value = match.get("utcDate", "")

    if not value:
        return "Horaire inconnu"

    try:
        from datetime import datetime, timezone

        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        return dt.astimezone().strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return value


# ============================================================
# ONGLET MATCHS
# ============================================================

with tab_matches:
    st.subheader("📅 Calendrier des rencontres")

    if not all_matches:
        st.info(
            "Aucun match récupéré pour cette période. "
            "Vérifie la date, les compétitions sélectionnées "
            "et les droits de ton abonnement API."
        )
    else:
        all_matches.sort(
            key=lambda m: m.get("utcDate", "")
        )

        for match in all_matches:
            home = safe_name(match.get("homeTeam"))
            away = safe_name(match.get("awayTeam"))

            score = match.get("score", {}).get("fullTime", {})
            home_score = score.get("home")
            away_score = score.get("away")

            score_text = ""

            if home_score is not None and away_score is not None:
                score_text = f" | Score : {home_score} - {away_score}"

            st.markdown(
                f"""
                <div class="match-card">
                    <span class="badge">
                        {match_status(match)}
                    </span>
                    <h3>{home} - {away}</h3>
                    <p class="small-text">
                        {match.get('_competition_name', '')}
                        · {format_kickoff(match)}
                        {score_text}
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )


# ============================================================
# ANALYSES DES MATCHS
# ============================================================

analyzed_matches = []

with tab_analysis:
    st.subheader("🧠 Analyse individuelle")

    if not all_matches:
        st.info("Aucune rencontre disponible à analyser.")
    else:
        match_options = {
            match_label(match): match
            for match in all_matches
        }

        selected_label = st.selectbox(
            "Choisis une rencontre",
            list(match_options.keys()),
        )

        selected_match = match_options[selected_label]

        home_team = selected_match.get("homeTeam", {})
        away_team = selected_match.get("awayTeam", {})

        home_id = home_team.get("id")
        away_id = away_team.get("id")

        match_day = parse_date(
            selected_match.get("utcDate")
        )

        if not match_day:
            match_day = selected_day

        if not home_id or not away_id:
            st.error("Impossible d'identifier les équipes.")
        else:
            with st.spinner(
                "Analyse des dernières performances..."
            ):
                result = analyze_match(
                    selected_match.get("id"),
                    home_id,
                    away_id,
                    match_day,
                )

            if result.get("error"):
                st.warning(result["error"])
            else:
                home = safe_name(home_team)
                away = safe_name(away_team)

                st.markdown(f"## {home} - {away}")

                c1, c2, c3 = st.columns(3)

                c1.metric(
                    f"Victoire {home}",
                    pct(result["home"]),
                )

                c2.metric(
                    "Match nul",
                    pct(result["draw"]),
                )

                c3.metric(
                    f"Victoire {away}",
                    pct(result["away"]),
                )

                st.markdown("### ⚽ Probabilités de buts")

                g1, g2, g3, g4 = st.columns(4)

                g1.metric(
                    "Plus de 1,5 but",
                    pct(result["over15"]),
                )

                g2.metric(
                    "Plus de 2,5 buts",
                    pct(result["over25"]),
                )

                g3.metric(
                    "Plus de 3,5 buts",
                    pct(result["over35"]),
                )

                g4.metric(
                    "Les deux marquent",
                    pct(result["btts"]),
                )

                st.markdown("### 📊 Buts attendus")

                st.write(
                    f"{home} : "
                    f"**{result['home_xg']:.2f} but(s) attendu(s)**"
                )

                st.write(
                    f"{away} : "
                    f"**{result['away_xg']:.2f} but(s) attendu(s)**"
                )

                st.markdown("### 🔢 Scores exacts théoriques")

                for h, a, probability in result["scores"]:
                    st.write(
                        f"**{h} - {a}** : {pct(probability)}"
                    )

                st.markdown("### 🏠 Forme à domicile / extérieur")

                hs = result["home_stats"]
                aws = result["away_stats"]

                col1, col2 = st.columns(2)

                with col1:
                    st.write(f"**{home}**")

                    if hs["home"]:
                        st.write(
                            "À domicile : "
                            f"{hs['home']['gf']:.2f} but(s) marqué(s) "
                            "par match, "
                            f"{hs['home']['ga']:.2f} encaissé(s)."
                        )

                    if hs["all"]:
                        st.write(
                            f"Derniers matchs disponibles : "
                            f"{hs['count']}"
                        )

                with col2:
                    st.write(f"**{away}**")

                    if aws["away"]:
                        st.write(
                            "À l'extérieur : "
                            f"{aws['away']['gf']:.2f} but(s) marqué(s) "
                            "par match, "
                            f"{aws['away']['ga']:.2f} encaissé(s)."
                        )

                    if aws["all"]:
                        st.write(
                            f"Derniers matchs disponibles : "
                            f"{aws['count']}"
                        )

                st.caption(
                    "Ces pourcentages sont des estimations "
                    "statistiques, pas des garanties de résultat."
                )


# ============================================================
# CLASSEMENT AUTOMATIQUE
# ============================================================

with tab_ranking:
    st.subheader("🏆 Classement des pronostics")

    candidates = [
        match for match in all_matches
        if match.get("status") == "TIMED"
        and match.get("homeTeam", {}).get("id")
        and match.get("awayTeam", {}).get("id")
    ]

    if not candidates:
        st.info(
            "Aucun match à venir disponible pour établir "
            "le classement."
        )
    else:
        ranking = []

        progress = st.progress(0)

        for index, match in enumerate(candidates):
            match_day = parse_date(
                match.get("utcDate")
            ) or selected_day

            result = analyze_match(
                match.get("id"),
                match["homeTeam"]["id"],
                match["awayTeam"]["id"],
                match_day,
            )

            if not result.get("error"):
                home = safe_name(match.get("homeTeam"))
                away = safe_name(match.get("awayTeam"))

                markets = [
                    (
                        f"Plus de 1,5 but",
                        result["over15"],
                    ),
                    (
                        "Plus de 2,5 buts",
                        result["over25"],
                    ),
                    (
                        "Les deux équipes marquent",
                        result["btts"],
                    ),
                    (
                        f"Victoire {home}",
                        result["home"],
                    ),
                    (
                        "Match nul",
                        result["draw"],
                    ),
                    (
                        f"Victoire {away}",
                        result["away"],
                    ),
                ]

                best_market = max(
                    markets,
                    key=lambda item: item[1],
                )

                ranking.append({
                    "match": f"{home} - {away}",
                    "competition": match.get(
                        "_competition_name", ""
                    ),
                    "pronostic": best_market[0],
                    "probability": best_market[1],
                    "over25": result["over25"],
                    "btts": result["btts"],
                    "over15": result["over15"],
                    "home": result["home"],
                    "draw": result["draw"],
                    "away": result["away"],
                })

            progress.progress(
                (index + 1) / len(candidates)
            )

        progress.empty()

        ranking.sort(
            key=lambda item: item["probability"],
            reverse=True,
        )

        if not ranking:
            st.warning(
                "Aucune analyse complète. "
                "Vérifie la disponibilité des statistiques."
            )
        else:
            for i, item in enumerate(ranking, 1):
                st.markdown(
                    f"""
                    <div class="match-card">
                        <span class="badge">
                            #{i} · {pct(item['probability'])}
                        </span>
                        <h3>{item['match']}</h3>
                        <p>{item['competition']}</p>
                        <p>
                            Pronostic principal :
                            <b>{item['pronostic']}</b>
                        </p>
                        <p class="small-text">
                            +2,5 buts : {pct(item['over25'])}
                            · BTTS : {pct(item['btts'])}
                            · +1,5 but : {pct(item['over15'])}
                        </p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


# ============================================================
# COMBINES AUTOMATIQUES
# ============================================================

with tab_combinations:
    st.subheader("🎯 Générateur de combinés")

    st.info(
        "Les combinés sont construits à partir des "
        "probabilités calculées pour les matchs disponibles."
    )

    candidates = [
        match for match in all_matches
        if match.get("status") == "TIMED"
        and match.get("homeTeam", {}).get("id")
        and match.get("awayTeam", {}).get("id")
    ]

    if not candidates:
        st.warning(
            "Aucun match à venir disponible pour créer "
            "un combiné."
        )
    else:
        mode = st.selectbox(
            "Type de combiné",
            [
                "Prudent",
                "Équilibré",
                "Audacieux",
            ],
        )

        max_selections = st.slider(
            "Nombre maximum de sélections",
            min_value=2,
            max_value=5,
            value=3,
        )

        if st.button(
            "🚀 Générer mes combinés",
            use_container_width=True,
        ):
            selections = []

            progress = st.progress(0)

            for index, match in enumerate(candidates):
                match_day = parse_date(
                    match.get("utcDate")
                ) or selected_day

                result = analyze_match(
                    match.get("id"),
                    match["homeTeam"]["id"],
                    match["awayTeam"]["id"],
                    match_day,
                )

                if not result.get("error"):
                    home = safe_name(match.get("homeTeam"))
                    away = safe_name(match.get("awayTeam"))

                    markets = [
                        (
                            "Plus de 1,5 but",
                            result["over15"],
                        ),
                        (
                            "Plus de 2,5 buts",
                            result["over25"],
                        ),
                        (
                            "Les deux équipes marquent : OUI",
                            result["btts"],
                        ),
                        (
                            f"{home} ou nul",
                            result["home"] + result["draw"],
                        ),
                        (
                            f"{away} ou nul",
                            result["away"] + result["draw"],
                        ),
                        (
                            f"Victoire {home}",
                            result["home"],
                        ),
                        (
                            f"Victoire {away}",
                            result["away"],
                        ),
                    ]

                    if mode == "Prudent":
                        min_probability = 0.75
                    elif mode == "Équilibré":
                        min_probability = 0.60
                    else:
                        min_probability = 0.45

                    eligible = [
                        market for market in markets
                        if market[1] >= min_probability
                    ]

                    if eligible:
                        best = max(
                            eligible,
                            key=lambda item: item[1],
                        )

                        selections.append({
                            "match": f"{home} - {away}",
                            "market": best[0],
                            "probability": best[1],
                        })

                progress.progress(
                    (index + 1) / len(candidates)
                )

            progress.empty()

            # Évite plusieurs sélections sur le même match.
            selections.sort(
                key=lambda item: item["probability"],
                reverse=True,
            )

            selections = selections[:max_selections]

            if len(selections) < 2:
                st.warning(
                    "Pas assez de sélections répondent "
                    "aux critères de ce mode. Essaie "
                    "Équilibré ou Audacieux, ou sélectionne "
                    "une période avec davantage de matchs."
                )
            else:
                st.success(
                    f"Combiné {mode.lower()} généré."
                )

                combined_probability = 1.0

                for index, selection in enumerate(
                    selections,
                    1,
                ):
                    combined_probability *= (
                        selection["probability"]
                    )

                    st.markdown(
                        f"""
                        <div class="match-card">
                            <b>Sélection {index}</b>
                            <h3>{selection['match']}</h3>
                            <p>{selection['market']}</p>
                            <span class="badge">
                                {pct(selection['probability'])}
                            </span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                st.metric(
                    "Probabilité théorique combinée",
                    pct(combined_probability),
                )

                st.caption(
                    "Attention : le produit des probabilités "
                    "suppose l'indépendance des sélections. "
                    "Les probabilités du modèle peuvent être "
                    "imprécises et ne garantissent aucun gain."
                )


# ============================================================
# PIED DE PAGE
# ============================================================

st.divider()

st.caption(
    "FOOT AI PRO · Statistiques et probabilités théoriques. "
    "Les résultats dépendent des données accessibles "
    "avec ton abonnement football-data.org."
)