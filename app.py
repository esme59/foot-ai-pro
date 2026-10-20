import os
import math
import itertools
from datetime import date, timedelta

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

COMPETITIONS = {
    "France - Ligue 1": "FL1",
    "Angleterre - Premier League": "PL",
    "Espagne - La Liga": "PD",
    "Allemagne - Bundesliga": "BL1",
    "Italie - Serie A": "SA",
    "Ligue des champions": "CL",
}

DEFAULT_DAYS = 7
MAX_HISTORY_MATCHES = 10


# =========================================================
# CLÉ API
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


# =========================================================
# API
# =========================================================

@st.cache_data(ttl=300, show_spinner=False)
def api_get(endpoint, params=None):
    if not API_KEY:
        return None, "Clé API manquante."

    try:
        response = requests.get(
            f"{API_BASE}{endpoint}",
            headers={"X-Auth-Token": API_KEY},
            params=params,
            timeout=20,
        )

        if response.status_code == 200:
            return response.json(), None

        if response.status_code == 401:
            return None, "Clé API invalide ou non autorisée."

        if response.status_code == 403:
            return None, (
                "Accès refusé par football-data.org. "
                "Vérifie les compétitions disponibles avec ta clé."
            )

        if response.status_code == 429:
            return None, "Limite de requêtes API atteinte."

        return None, (
            f"Erreur API HTTP {response.status_code}: "
            f"{response.text[:200]}"
        )

    except requests.RequestException as exc:
        return None, f"Erreur de connexion : {exc}"


# =========================================================
# MATCHS ET HISTORIQUE
# =========================================================

@st.cache_data(ttl=300, show_spinner=False)
def get_competition_matches(competition_code, date_from, date_to):
    data, error = api_get(
        f"/competitions/{competition_code}/matches",
        {
            "dateFrom": date_from,
            "dateTo": date_to,
        },
    )

    if error or not data:
        return [], error

    matches = data.get("matches", [])
    matches.sort(key=lambda m: m.get("utcDate", ""))

    return matches, None


@st.cache_data(ttl=600, show_spinner=False)
def get_team_history(team_id, before_date):
    data, error = api_get(
        f"/teams/{team_id}/matches",
        {
            "status": "FINISHED",
            "dateTo": before_date,
            "limit": MAX_HISTORY_MATCHES,
        },
    )

    if error or not data:
        return [], error

    matches = data.get("matches", [])
    matches.sort(
        key=lambda m: m.get("utcDate", ""),
        reverse=True,
    )

    return matches[:MAX_HISTORY_MATCHES], None


# =========================================================
# FORME DES ÉQUIPES
# =========================================================

def get_team_form(team_id, matches):
    goals_for = []
    goals_against = []
    points = []
    form_letters = []

    for match in matches:
        home = match.get("homeTeam", {})
        away = match.get("awayTeam", {})
        score = match.get("score", {}).get("fullTime", {})

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

        goals_for.append(gf)
        goals_against.append(ga)

        if gf > ga:
            points.append(3)
            form_letters.append("V")
        elif gf == ga:
            points.append(1)
            form_letters.append("N")
        else:
            points.append(0)
            form_letters.append("D")

    count = len(goals_for)

    if count == 0:
        return {
            "count": 0,
            "avg_for": 1.25,
            "avg_against": 1.25,
            "points": 0,
            "form": "Données insuffisantes",
        }

    return {
        "count": count,
        "avg_for": sum(goals_for) / count,
        "avg_against": sum(goals_against) / count,
        "points": sum(points),
        "form": " ".join(form_letters[:5]),
    }


# =========================================================
# MODÈLE DE POISSON
# =========================================================

def poisson_probability(lam, goals):
    lam = max(0.0, lam)
    return math.exp(-lam) * lam**goals / math.factorial(goals)


def calculate_probabilities(lambda_home, lambda_away):
    home_win = 0.0
    draw = 0.0
    away_win = 0.0
    over_15 = 0.0
    over_25 = 0.0
    btts = 0.0
    score_probs = []

    for hg in range(9):
        ph = poisson_probability(lambda_home, hg)

        for ag in range(9):
            pa = poisson_probability(lambda_away, ag)
            p = ph * pa

            score_probs.append((hg, ag, p))

            if hg > ag:
                home_win += p
            elif hg == ag:
                draw += p
            else:
                away_win += p

            if hg + ag >= 2:
                over_15 += p

            if hg + ag >= 3:
                over_25 += p

            if hg >= 1 and ag >= 1:
                btts += p

    total = home_win + draw + away_win

    if total:
        home_win /= total
        draw /= total
        away_win /= total

    return {
        "home_win": home_win,
        "draw": draw,
        "away_win": away_win,
        "over_15": over_15,
        "over_25": over_25,
        "btts": btts,
        "score_probs": sorted(
            score_probs,
            key=lambda item: item[2],
            reverse=True,
        ),
    }


# =========================================================
# ANALYSE D'UN MATCH
# =========================================================

def analyze_match(match):
    home = match.get("homeTeam", {})
    away = match.get("awayTeam", {})

    home_id = home.get("id")
    away_id = away.get("id")

    if not home_id or not away_id:
        return None

    home_name = home.get("name", "Équipe domicile")
    away_name = away.get("name", "Équipe extérieure")

    match_date = match.get("utcDate", "")
    before_date = (
        match_date[:10]
        if match_date
        else date.today().isoformat()
    )

    home_history, home_error = get_team_history(
        home_id, before_date
    )
    away_history, away_error = get_team_history(
        away_id, before_date
    )

    home_form = get_team_form(home_id, home_history)
    away_form = get_team_form(away_id, away_history)

    lambda_home = (
        home_form["avg_for"] + away_form["avg_against"]
    ) / 2 + 0.20

    lambda_away = (
        away_form["avg_for"] + home_form["avg_against"]
    ) / 2

    if home_form["count"] >= 3:
        points_per_match = (
            home_form["points"] / home_form["count"]
        )
        lambda_home *= 0.90 + points_per_match / 3 * 0.20

    if away_form["count"] >= 3:
        points_per_match = (
            away_form["points"] / away_form["count"]
        )
        lambda_away *= 0.90 + points_per_match / 3 * 0.20

    lambda_home = max(0.15, min(lambda_home, 3.5))
    lambda_away = max(0.15, min(lambda_away, 3.5))

    probs = calculate_probabilities(
        lambda_home,
        lambda_away,
    )

    home_win = probs["home_win"]
    draw = probs["draw"]
    away_win = probs["away_win"]

    selections = [
        {"name": "1X - Domicile ou nul",
         "market": "double_chance",
         "probability": home_win + draw},

        {"name": "X2 - Extérieur ou nul",
         "market": "double_chance",
         "probability": away_win + draw},

        {"name": "Plus de 1,5 but",
         "market": "over15",
         "probability": probs["over_15"]},

        {"name": "Plus de 2,5 buts",
         "market": "over25",
         "probability": probs["over_25"]},

        {"name": "Victoire domicile",
         "market": "home_win",
         "probability": home_win},

        {"name": "Match nul",
         "market": "draw",
         "probability": draw},

        {"name": "Victoire extérieur",
         "market": "away_win",
         "probability": away_win},

        {"name": "Les deux équipes marquent",
         "market": "btts",
         "probability": probs["btts"]},
    ]

    best_score = probs["score_probs"][0]

    return {
        "id": match.get("id"),
        "date": match_date,
        "competition": match.get("competition", {}).get(
            "name", "Compétition"
        ),
        "home_name": home_name,
        "away_name": away_name,
        "home_form": home_form,
        "away_form": away_form,
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "probabilities": probs,
        "selections": selections,
        "best_score": f"{best_score[0]} - {best_score[1]}",
        "history_error": bool(home_error or away_error),
    }


# =========================================================
# MARCHÉS DISPONIBLES
# =========================================================

def market_selection(result, market):
    for selection in result["selections"]:
        if selection["market"] == market:
            return selection
    return None


def candidate_from_result(result, selection):
    history_count = min(
        result["home_form"]["count"],
        result["away_form"]["count"],
    )

    return {
        "match_id": result["id"],
        "match": (
            f'{result["home_name"]} - {result["away_name"]}'
        ),
        "market": selection["market"],
        "name": selection["name"],
        "probability": float(selection["probability"]),
        "history_count": history_count,
    }


# =========================================================
# CRÉATION DES CANDIDATS POUR CHAQUE CATÉGORIE
# =========================================================

def get_candidates(results, category):
    candidates = []

    # FIABLE : les marchés les plus prudents sont favorisés,
    # mais pas exclusivement le Plus de 1,5 but.
    if category == "fiable":
        allowed_markets = [
            "double_chance",
            "over15",
            "over25",
            "home_win",
            "away_win",
            "btts",
            "draw",
        ]
        minimum_probability = 0.58

    # ÉQUILIBRÉ : davantage de diversité des marchés.
    elif category == "equilibre":
        allowed_markets = [
            "double_chance",
            "over15",
            "over25",
            "home_win",
            "away_win",
            "btts",
            "draw",
        ]
        minimum_probability = 0.35

    # RISQUÉ : marchés plus incertains acceptés.
    else:
        allowed_markets = [
            "over25",
            "home_win",
            "away_win",
            "btts",
            "draw",
            "over15",
            "double_chance",
        ]
        minimum_probability = 0.20

    for result in results:
        match_candidates = []

        for market in allowed_markets:
            selection = market_selection(result, market)

            if not selection:
                continue

            p = float(selection["probability"])

            if p < minimum_probability or p >= 0.99:
                continue

            # Le combiné fiable conserve les sélections les
            # plus probables, tout en évitant de forcer un marché.
            match_candidates.append(
                candidate_from_result(result, selection)
            )

        if not match_candidates:
            continue

        if category == "fiable":
            # Favorise la probabilité sans supprimer les autres marchés.
            match_candidates.sort(
                key=lambda c: (
                    c["probability"]
                    + min(c["history_count"], 5) * 0.008
                ),
                reverse=True,
            )

        elif category == "equilibre":
            # Favorise un compromis autour de 55 %, avec une
            # petite prime à la diversité des marchés.
            match_candidates.sort(
                key=lambda c: (
                    c["probability"]
                    - abs(c["probability"] - 0.55) * 0.10
                ),
                reverse=True,
            )

        else:
            # Les marchés moins probables sont permis.
            # On évite toutefois les probabilités extrêmement faibles.
            match_candidates.sort(
                key=lambda c: (
                    0.55 - abs(c["probability"] - 0.42)
                ),
                reverse=True,
            )

        # Un seul marché par match et par catégorie.
        candidates.append(match_candidates[0])

    # Trier les candidats en fonction de la probabilité.
    candidates.sort(
        key=lambda c: c["probability"],
        reverse=True,
    )

    return candidates


# =========================================================
# COMBINÉS DIVERSIFIÉS
# =========================================================

def combo_score(combo, category):
    probabilities = [item["probability"] for item in combo]

    if not probabilities:
        return 0.0

    product = math.prod(probabilities)

    markets = [item["market"] for item in combo]
    unique_markets = len(set(markets))
    diversity_bonus = unique_markets / len(markets)

    if category == "fiable":
        # La probabilité combinée domine le classement.
        return product * (1 + 0.03 * diversity_bonus)

    if category == "equilibre":
        # Récompense davantage la diversité, sans la faire
        # passer devant une probabilité trop faible.
        return product * (1 + 0.20 * diversity_bonus)

    # Pour le combiné risqué, on privilégie un profil de marchés
    # plus variés et plus incertains.
    return product * (1 + 0.25 * diversity_bonus)


def generate_combinations(candidates, size, category, limit=5):
    if len(candidates) < size:
        return []

    # Plusieurs marchés ont été évalués par match en amont.
    # La génération combine des matchs distincts.
    pool = candidates[:30]
    combos = []

    for combo in itertools.combinations(pool, size):
        ids = [item["match_id"] for item in combo]

        if len(ids) != len(set(ids)):
            continue

        probability = math.prod(
            item["probability"] for item in combo
        )

        combos.append({
            "selections": combo,
            "probability": probability,
            "score": combo_score(combo, category),
        })

    combos.sort(
        key=lambda c: c["score"],
        reverse=True,
    )

    # Enlève les doublons de combinaisons.
    unique = []
    seen = set()

    for combo in combos:
        signature = tuple(sorted(
            (
                item["match_id"],
                item["market"],
            )
            for item in combo["selections"]
        ))

        if signature in seen:
            continue

        seen.add(signature)
        unique.append(combo)

        if len(unique) >= limit:
            break

    return unique


# =========================================================
# AFFICHAGE DES COMBINÉS
# =========================================================

def display_category(results, category, title, description):
    st.subheader(title)
    st.caption(description)

    candidates = get_candidates(results, category)

    if len(candidates) < 2:
        st.warning(
            "Pas assez de matchs admissibles pour cette catégorie. "
            "Essaie une période plus large."
        )
        return

    st.write(
        f"Matchs candidats pour cette catégorie : **{len(candidates)}**"
    )

    tabs = st.tabs([
        "2 matchs",
        "3 matchs",
        "4 matchs",
    ])

    for tab, size in zip(tabs, [2, 3, 4]):
        with tab:
            combos = generate_combinations(
                candidates,
                size,
                category,
                limit=5,
            )

            if not combos:
                st.info(
                    f"Pas assez de matchs pour un combiné de {size}."
                )
                continue

            for number, combo in enumerate(combos, start=1):
                st.markdown(
                    f"### Combiné {number} — {size} matchs"
                )

                st.metric(
                    "Probabilité théorique combinée",
                    f'{combo["probability"] * 100:.2f} %',
                )

                for item in combo["selections"]:
                    st.write(
                        f'• **{item["match"]}** — {item["name"]} '
                        f'({item["probability"] * 100:.1f} %)'
                    )

                    if item["history_count"] < 3:
                        st.caption(
                            "⚠️ Historique insuffisant ou limité."
                        )

                st.divider()


def display_combinations(results):
    st.header("🔗 Les 3 types de combinés FOOT AI PRO")

    st.info(
        "Les probabilités sont des estimations statistiques. "
        "Elles ne garantissent pas le résultat des matchs."
    )

    display_category(
        results,
        "fiable",
        "🟢 Combiné fiable",
        "Privilégie les probabilités estimées les plus élevées.",
    )

    display_category(
        results,
        "equilibre",
        "🟠 Combiné équilibré",
        "Recherche un compromis entre probabilité et diversité.",
    )

    display_category(
        results,
        "risque",
        "🔴 Combiné risqué",
        "Explore des marchés plus incertains et plus variés.",
    )


# =========================================================
# AFFICHAGE DES ANALYSES
# =========================================================

def display_match_analysis(result):
    probs = result["probabilities"]

    st.subheader(
        f'⚽ {result["home_name"]} - {result["away_name"]}'
    )

    st.caption(
        f'Date : {result["date"]} | '
        f'Compétition : {result["competition"]}'
    )

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Victoire domicile",
        f'{probs["home_win"] * 100:.1f} %',
    )

    col2.metric(
        "Match nul",
        f'{probs["draw"] * 100:.1f} %',
    )

    col3.metric(
        "Victoire extérieur",
        f'{probs["away_win"] * 100:.1f} %',
    )

    st.write(
        f'**Forme domicile :** {result["home_form"]["form"]} '
        f'({result["home_form"]["count"]} matchs)'
    )

    st.write(
        f'**Forme extérieur :** {result["away_form"]["form"]} '
        f'({result["away_form"]["count"]} matchs)'
    )

    st.write(
        f'**Buts attendus :** {result["home_name"]} '
        f'{result["lambda_home"]:.2f} — '
        f'{result["lambda_away"]:.2f} {result["away_name"]}'
    )

    st.write(
        f'**Score exact le plus probable :** {result["best_score"]}'
    )

    st.markdown("**Probabilités par marché :**")

    for selection in sorted(
        result["selections"],
        key=lambda s: s["probability"],
        reverse=True,
    ):
        st.write(
            f'• {selection["name"]} : '
            f'**{selection["probability"] * 100:.1f} %**'
        )

    if (
        result["home_form"]["count"] < 3
        or result["away_form"]["count"] < 3
    ):
        st.warning(
            "Historique récent incomplet : la fiabilité de "
            "l'estimation peut être réduite."
        )

    st.divider()


# =========================================================
# INTERFACE
# =========================================================

st.title("⚽ FOOT AI PRO")
st.write(
    "Analyse automatique des matchs avec modèle de Poisson, "
    "forme récente et génération de combinés."
)

if not API_KEY:
    st.error(
        "Clé API introuvable. Dans Streamlit Secrets, ajoute :\n\n"
        'FOOTBALL_DATA_API_KEY = "TA_CLE_API"'
    )
    st.stop()

today = date.today()

col1, col2 = st.columns(2)

with col1:
    date_from = st.date_input(
        "Date de début",
        value=today,
        key="date_from",
    )

with col2:
    date_to = st.date_input(
        "Date de fin",
        value=today + timedelta(days=DEFAULT_DAYS),
        key="date_to",
    )

selected_competitions = st.multiselect(
    "Championnats à analyser",
    options=list(COMPETITIONS.keys()),
    default=list(COMPETITIONS.keys()),
)

if date_to < date_from:
    st.error("La date de fin doit être égale ou postérieure à la date de début.")
    st.stop()

if not selected_competitions:
    st.warning("Sélectionne au moins un championnat.")
    st.stop()

if st.button(
    "🔎 Rechercher les matchs et lancer les pronostics",
    type="primary",
    use_container_width=True,
):
    all_matches = []
    api_errors = []

    progress = st.progress(0)
    status = st.empty()

    for index, competition_name in enumerate(
        selected_competitions,
        start=1,
    ):
        status.write(
            f"Recherche : {competition_name} "
            f"({index}/{len(selected_competitions)})..."
        )

        matches, error = get_competition_matches(
            COMPETITIONS[competition_name],
            date_from.isoformat(),
            date_to.isoformat(),
        )

        if error:
            api_errors.append(
                f"{competition_name} : {error}"
            )
        else:
            for match in matches:
                match.setdefault("competition", {})
                match["competition"]["name"] = competition_name
                all_matches.append(match)

        progress.progress(
            index / len(selected_competitions)
        )

    progress.empty()
    status.empty()

    unique_matches = {}

    for match in all_matches:
        unique_matches[match.get("id", str(match))] = match

    all_matches = sorted(
        unique_matches.values(),
        key=lambda m: m.get("utcDate", ""),
    )

    if api_errors:
        with st.expander("Problèmes API"):
            for error in api_errors:
                st.warning(error)

    if not all_matches:
        st.warning(
            "Aucun match trouvé. Essaie une période plus large "
            "ou vérifie les accès de ta clé API."
        )
        st.stop()

    results = []
    progress = st.progress(0)

    for index, match in enumerate(all_matches, start=1):
        result = analyze_match(match)

        if result is not None:
            results.append(result)

        progress.progress(index / len(all_matches))

    progress.empty()

    if not results:
        st.error(
            "Aucune analyse exploitable n'a été produite."
        )
        st.stop()

    st.session_state["foot_ai_results"] = results

    st.success(
        f"{len(results)} match(s) analysé(s)."
    )


# =========================================================
# RÉSULTATS
# =========================================================

results = st.session_state.get("foot_ai_results", [])

if results:
    tab_matches, tab_ranking, tab_combos = st.tabs([
        "📋 Analyses des matchs",
        "🏆 Classement",
        "🔗 Combinés",
    ])

    with tab_matches:
        for result in results:
            display_match_analysis(result)

    with tab_ranking:
        ranking = []

        for result in results:
            for selection in result["selections"]:
                ranking.append({
                    "Match": (
                        f'{result["home_name"]} - '
                        f'{result["away_name"]}'
                    ),
                    "Pronostic": selection["name"],
                    "Probabilité": (
                        f'{selection["probability"] * 100:.1f} %'
                    ),
                })

        ranking.sort(
            key=lambda row: float(
                row["Probabilité"].replace("%", "")
            ),
            reverse=True,
        )

        st.dataframe(
            ranking,
            use_container_width=True,
            hide_index=True,
        )

    with tab_combos:
        display_combinations(results)

else:
    st.info(
        "Choisis les dates et les championnats, puis lance l'analyse."
    )


st.caption(
    "Les probabilités sont des estimations statistiques et ne "
    "garantissent aucun résultat. Les compositions, blessures, "
    "suspensions et informations de dernière minute ne sont pas "
    "automatiquement intégrées à cette version."
)