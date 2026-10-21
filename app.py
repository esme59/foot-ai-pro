import os
import math
import time
from datetime import date, timedelta, datetime

import requests
import streamlit as st


# ============================================================
# FOOT AI PRO - VERSION OPTIMISEE
# API : football-data.org v4
# Cache, limitation des requêtes et gestion HTTP 429
# ============================================================

st.set_page_config(
    page_title="FOOT AI PRO",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_BASE = "https://api.football-data.org/v4"
TIMEOUT = 15
CACHE_TTL = 900  # 15 minutes

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


# ============================================================
# SESSION HTTP
# ============================================================

@st.cache_resource
def get_session():
    session = requests.Session()
    session.headers.update({
        "X-Auth-Token": API_KEY,
        "User-Agent": "FOOT-AI-PRO/2.0",
    })
    return session


# ============================================================
# CACHE CENTRAL DES REQUETES API
# ============================================================

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def api_get_cached(endpoint, params_tuple, api_key_fingerprint):
    """
    Une même requête est conservée pendant 15 minutes.
    api_key_fingerprint évite de mélanger les caches
    si la clé API est changée.
    """

    if not API_KEY:
        return None, "Clé API manquante."

    params = dict(params_tuple)

    try:
        response = get_session().get(
            f"{API_BASE}/{endpoint.lstrip('/')}",
            params=params,
            timeout=TIMEOUT,
        )

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            message = (
                "Limite API atteinte (HTTP 429). "
                "Attends le renouvellement du quota "
                "avant de relancer les analyses."
            )
            if retry_after:
                message += f" Réessaie après {retry_after} seconde(s)."
            return None, message

        if response.status_code == 401:
            return None, "Clé API invalide. Vérifie les Secrets Streamlit."

        if response.status_code == 403:
            return None, (
                "Accès refusé pour cette compétition ou cet endpoint. "
                "Vérifie les droits de ton abonnement."
            )

        if response.status_code == 404:
            return None, "Données introuvables pour cette requête."

        if not response.ok:
            return None, f"Erreur API HTTP {response.status_code}."

        return response.json(), None

    except requests.RequestException:
        return None, "Impossible de contacter football-data.org."

    except ValueError:
        return None, "La réponse de l'API est illisible."


def api_get(endpoint, params=None):
    if not API_KEY:
        return None, "Clé API manquante dans les Secrets Streamlit."

    params = params or {}

    # Paramètres triés pour que les mêmes requêtes utilisent
    # exactement la même entrée de cache.
    params_tuple = tuple(sorted(
        (str(key), str(value))
        for key, value in params.items()
    ))

    # Empreinte non secrète : ne pas afficher la clé dans l'interface.
    fingerprint = str(hash(API_KEY))

    return api_get_cached(
        endpoint,
        params_tuple,
        fingerprint,
    )


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
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def safe_name(team):
    return (team or {}).get("name", "Équipe inconnue")


def get_matches(competition, start_date, end_date):
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


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_team_history_cached(team_id, match_date_string):
    """
    Historique de l'équipe mis en cache séparément.
    Une équipe affrontant plusieurs adversaires ne nécessite
    pas de télécharger son historique à chaque fois.
    """

    match_day = date.fromisoformat(match_date_string)
    end_date = match_day - timedelta(days=1)
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


def get_team_history(team_id, match_date):
    return get_team_history_cached(
        int(team_id),
        match_date.isoformat(),
    )


# ============================================================
# STATISTIQUES DES EQUIPES
# ============================================================

def team_statistics(matches, team_id):
    all_games = []
    home_games = []
    away_games = []

    for match in matches:
        home_id = match.get("homeTeam", {}).get("id")
        away_id = match.get("awayTeam", {}).get("id")

        score = match.get("score", {}).get("fullTime", {})
        hg = score.get("home")
        ag = score.get("away")

        if hg is None or ag is None:
            continue

        if home_id == team_id:
            record = {"gf": hg, "ga": ag, "venue": "home"}
        elif away_id == team_id:
            record = {"gf": ag, "ga": hg, "venue": "away"}
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
    }


# ============================================================
# MODELE DE POISSON
# ============================================================

def poisson_probability(lam, goals):
    if lam <= 0:
        return 1.0 if goals == 0 else 0.0

    return math.exp(-lam) * (lam ** goals) / math.factorial(goals)


def get_expected_goals(home_stats, away_stats):
    home_attack = home_stats["home"] or home_stats["all"]
    home_defence = home_stats["home"] or home_stats["all"]
    away_attack = away_stats["away"] or away_stats["all"]
    away_defence = away_stats["away"] or away_stats["all"]

    if not all([home_attack, home_defence, away_attack, away_defence]):
        return None

    home_xg = (
        0.55 * home_attack["gf"] +
        0.45 * away_defence["ga"]
    ) * 1.08

    away_xg = (
        0.55 * away_attack["gf"] +
        0.45 * home_defence["ga"]
    ) * 0.94

    return (
        max(0.15, min(home_xg, 4.5)),
        max(0.15, min(away_xg, 4.5)),
    )


def calculate_predictions(home_xg, away_xg):
    max_goals = 10

    home_probs = [
        poisson_probability(home_xg, i)
        for i in range(max_goals + 1)
    ]
    away_probs = [
        poisson_probability(away_xg, i)
        for i in range(max_goals + 1)
    ]

    p_home = p_draw = p_away = 0.0
    p_over15 = p_over25 = p_over35 = p_btts = 0.0
    scores = []

    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            probability = home_probs[h] * away_probs[a]
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

    if total_probability:
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

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def analyze_match(match_id, home_id, away_id, match_date):
    home_matches, home_error = get_team_history(
        home_id, match_date
    )
    away_matches, away_error = get_team_history(
        away_id, match_date
    )

    if home_error or away_error:
        return {"error": home_error or away_error}

    home_stats = team_statistics(home_matches, home_id)
    away_stats = team_statistics(away_matches, away_id)

    if home_stats["count"] < 3 or away_stats["count"] < 3:
        return {
            "error": "Pas assez de matchs récents pour produire une analyse."
        }

    expected = get_expected_goals(home_stats, away_stats)

    if not expected:
        return {"error": "Statistiques insuffisantes."}

    predictions = calculate_predictions(*expected)
    predictions["home_stats"] = home_stats
    predictions["away_stats"] = away_stats

    return predictions


# ============================================================
# APPLICATION
# ============================================================

st.title("⚽ FOOT AI PRO")
st.caption("Matchs • Statistiques • Pronostics • Combinés")

if not API_KEY:
    st.error(
        "Clé API manquante. Vérifie Settings > Secrets "
        "dans Streamlit Cloud."
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
            "Aujourd'hui" if x == 0
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
# RENCONTRES
# ============================================================

all_matches = []
competition_errors = {}

if not selected_competitions:
    st.warning("Sélectionne au moins une compétition.")
    st.stop()

with st.spinner("Chargement des rencontres..."):
    for competition_name in selected_competitions:
        code = COMPETITIONS[competition_name]

        matches, error = get_matches(
            code,
            selected_day,
            selected_day + timedelta(days=days_forward),
        )

        if error:
            competition_errors[competition_name] = error
            continue

        for match in matches:
            match["_competition_name"] = competition_name
            match["_competition_code"] = code
            all_matches.append(match)


if competition_errors:
    with st.expander("⚠️ Informations API"):
        for name, error in competition_errors.items():
            st.warning(f"{name} : {error}")


tab_matches, tab_analysis, tab_ranking, tab_combinations = st.tabs(
    [
        "📅 Matchs",
        "🧠 Analyse IA",
        "🏆 Classement",
        "🎯 Combinés",
    ]
)


def match_status(match):
    status = match.get("status", "")

    return {
        "IN_PLAY": "🔴 EN DIRECT",
        "PAUSED": "⏸️ MI-TEMPS",
        "FINISHED": "✅ TERMINÉ",
        "POSTPONED": "⏳ REPORTÉ",
        "SCHEDULED": "🕒 À VENIR",
        "TIMED": "🕒 À VENIR",
    }.get(status, "🕒 " + status)


def match_label(match):
    return (
        f"{safe_name(match.get('homeTeam'))} - "
        f"{safe_name(match.get('awayTeam'))} "
        f"({match.get('_competition_name', '')})"
    )


def format_kickoff(match):
    value = match.get("utcDate", "")

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError, AttributeError):
        return value or "Horaire inconnu"


# ============================================================
# ONGLET MATCHS
# ============================================================

with tab_matches:
    st.subheader("📅 Calendrier")

    if not all_matches:
        st.info(
            "Aucun match disponible. Vérifie la date, les droits "
            "de ton abonnement et les erreurs API ci-dessus."
        )

    for match in sorted(
        all_matches,
        key=lambda m: m.get("utcDate", ""),
    ):
        home = safe_name(match.get("homeTeam"))
        away = safe_name(match.get("awayTeam"))

        score = match.get("score", {}).get("fullTime", {})
        hs = score.get("home")
        aws = score.get("away")

        score_text = (
            f" | Score : {hs} - {aws}"
            if hs is not None and aws is not None
            else ""
        )

        st.markdown(
            f"""
            <div class="match-card">
                <span class="badge">{match_status(match)}</span>
                <h3>{home} - {away}</h3>
                <p class="small-text">
                    {match.get('_competition_name', '')}
                    · {format_kickoff(match)}{score_text}
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ============================================================
# ANALYSE INDIVIDUELLE
# ============================================================

with tab_analysis:
    st.subheader("🧠 Analyse individuelle")

    if not all_matches:
        st.info("Aucune rencontre disponible.")
    else:
        match_options = {
            match_label(match): match
            for match in all_matches
        }

        selected_label = st.selectbox(
            "Choisis un match",
            list(match_options.keys()),
        )
        match = match_options[selected_label]

        home_team = match.get("homeTeam", {})
        away_team = match.get("awayTeam", {})
        home_id = home_team.get("id")
        away_id = away_team.get("id")
        match_day = parse_date(match.get("utcDate")) or selected_day

        if not home_id or not away_id:
            st.error("Impossible d'identifier les équipes.")
        else:
            with st.spinner("Analyse des statistiques..."):
                result = analyze_match(
                    match.get("id"),
                    home_id,
                    away_id,
                    match_day.isoformat(),
                )

            if result.get("error"):
                st.warning(result["error"])
            else:
                home = safe_name(home_team)
                away = safe_name(away_team)

                st.markdown(f"## {home} - {away}")

                c1, c2, c3 = st.columns(3)
                c1.metric(f"Victoire {home}", pct(result["home"]))
                c2.metric("Match nul", pct(result["draw"]))
                c3.metric(f"Victoire {away}", pct(result["away"]))

                st.markdown("### ⚽ Probabilités de buts")

                g1, g2, g3, g4 = st.columns(4)
                g1.metric("Plus de 1,5 but", pct(result["over15"]))
                g2.metric("Plus de 2,5 buts", pct(result["over25"]))
                g3.metric("Plus de 3,5 buts", pct(result["over35"]))
                g4.metric("Les deux marquent", pct(result["btts"]))

                st.markdown("### 📊 Buts attendus")
                st.write(f"{home} : **{result['home_xg']:.2f}**")
                st.write(f"{away} : **{result['away_xg']:.2f}**")

                st.markdown("### 🔢 Scores exacts théoriques")
                for h, a, probability in result["scores"]:
                    st.write(f"**{h} - {a}** : {pct(probability)}")

                st.markdown("### 🏠 Domicile / extérieur")

                hs = result["home_stats"]
                aws = result["away_stats"]

                col1, col2 = st.columns(2)

                with col1:
                    st.write(f"**{home}**")
                    if hs["home"]:
                        st.write(
                            f"Domicile : {hs['home']['gf']:.2f} but(s) "
                            f"marqué(s), {hs['home']['ga']:.2f} encaissé(s)."
                        )
                    st.write(f"Matchs analysés : {hs['count']}")

                with col2:
                    st.write(f"**{away}**")
                    if aws["away"]:
                        st.write(
                            f"Extérieur : {aws['away']['gf']:.2f} but(s) "
                            f"marqué(s), {aws['away']['ga']:.2f} encaissé(s)."
                        )
                    st.write(f"Matchs analysés : {aws['count']}")

                st.caption(
                    "Les probabilités sont des estimations statistiques, "
                    "pas des garanties de résultat."
                )


# ============================================================
# CLASSEMENT ET COMBINES
# ============================================================

def build_candidates(matches):
    return [
        match for match in matches
        if match.get("status") in ("TIMED", "SCHEDULED")
        and match.get("homeTeam", {}).get("id")
        and match.get("awayTeam", {}).get("id")
    ]


def get_prediction(match):
    match_day = parse_date(match.get("utcDate")) or selected_day

    return analyze_match(
        match.get("id"),
        match["homeTeam"]["id"],
        match["awayTeam"]["id"],
        match_day.isoformat(),
    )


with tab_ranking:
    st.subheader("🏆 Classement des pronostics")
    candidates = build_candidates(all_matches)

    if not candidates:
        st.info("Aucun match à venir disponible.")
    else:
        # Analyse à la demande : évite de lancer des dizaines
        # d'appels API dès l'ouverture de l'application.
        if st.button("📊 Calculer le classement"):
            ranking = []
            progress = st.progress(0)

            for index, match in enumerate(candidates):
                result = get_prediction(match)

                if not result.get("error"):
                    home = safe_name(match.get("homeTeam"))
                    away = safe_name(match.get("awayTeam"))

                    markets = [
                        ("Plus de 1,5 but", result["over15"]),
                        ("Plus de 2,5 buts", result["over25"]),
                        ("Les deux marquent", result["btts"]),
                        (f"Victoire {home}", result["home"]),
                        ("Match nul", result["draw"]),
                        (f"Victoire {away}", result["away"]),
                    ]

                    best = max(markets, key=lambda item: item[1])

                    ranking.append({
                        "match": f"{home} - {away}",
                        "competition": match.get("_competition_name", ""),
                        "pick": best[0],
                        "probability": best[1],
                        "over25": result["over25"],
                        "btts": result["btts"],
                        "over15": result["over15"],
                    })

                progress.progress((index + 1) / len(candidates))

            progress.empty()
            ranking.sort(
                key=lambda item: item["probability"],
                reverse=True,
            )

            if not ranking:
                st.warning("Aucune analyse complète disponible.")
            else:
                for index, item in enumerate(ranking, 1):
                    st.markdown(
                        f"""
                        <div class="match-card">
                            <span class="badge">
                                #{index} · {pct(item['probability'])}
                            </span>
                            <h3>{item['match']}</h3>
                            <p>{item['competition']}</p>
                            <p>Pronostic : <b>{item['pick']}</b></p>
                            <p class="small-text">
                                +1,5 : {pct(item['over15'])}
                                · +2,5 : {pct(item['over25'])}
                                · BTTS : {pct(item['btts'])}
                            </p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )


with tab_combinations:
    st.subheader("🎯 Générateur de combinés")

    candidates = build_candidates(all_matches)

    if not candidates:
        st.info("Aucun match à venir pour les combinés.")
    else:
        mode = st.selectbox(
            "Type de combiné",
            ["Prudent", "Équilibré", "Audacieux"],
        )

        max_selections = st.slider(
            "Nombre maximum de sélections",
            2, 5, 3,
        )

        if st.button("🚀 Générer mes combinés"):
            min_probability = {
                "Prudent": 0.75,
                "Équilibré": 0.60,
                "Audacieux": 0.45,
            }[mode]

            selections = []
            progress = st.progress(0)

            for index, match in enumerate(candidates):
                result = get_prediction(match)

                if not result.get("error"):
                    home = safe_name(match.get("homeTeam"))
                    away = safe_name(match.get("awayTeam"))

                    markets = [
                        ("Plus de 1,5 but", result["over15"]),
                        ("Plus de 2,5 buts", result["over25"]),
                        ("Les deux marquent : OUI", result["btts"]),
                        (f"{home} ou nul", result["home"] + result["draw"]),
                        (f"{away} ou nul", result["away"] + result["draw"]),
                        (f"Victoire {home}", result["home"]),
                        (f"Victoire {away}", result["away"]),
                    ]

                    eligible = [
                        item for item in markets
                        if item[1] >= min_probability
                    ]

                    if eligible:
                        best = max(eligible, key=lambda item: item[1])
                        selections.append({
                            "match": f"{home} - {away}",
                            "market": best[0],
                            "probability": best[1],
                        })

                progress.progress((index + 1) / len(candidates))

            progress.empty()

            # Une seule sélection par match.
            selections.sort(
                key=lambda item: item["probability"],
                reverse=True,
            )
            selections = selections[:max_selections]

            if len(selections) < 2:
                st.warning(
                    "Pas assez de sélections répondent à ces critères. "
                    "Essaie un autre mode ou une autre date."
                )
            else:
                combined_probability = 1.0
                st.success(f"Combiné {mode.lower()} généré.")

                for index, selection in enumerate(selections, 1):
                    combined_probability *= selection["probability"]

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
                    "Cette estimation suppose l'indépendance des sélections. "
                    "Les résultats du modèle sont incertains et ne garantissent "
                    "aucun gain."
                )


# ============================================================
# PIED DE PAGE
# ============================================================

st.divider()

st.caption(
    "FOOT AI PRO · Probabilités statistiques indicatives. "
    "Les données disponibles dépendent de ton abonnement API."
)