import os
import math
import itertools
from datetime import date, timedelta

import requests
import pandas as pd
import streamlit as st


# =====================================================
# FOOT AI PRO - VERSION AUTOMATIQUE
# =====================================================

st.set_page_config(
    page_title="FOOT AI PRO",
    page_icon="⚽",
    layout="wide"
)

API_URL = "https://api.football-data.org/v4"

COMPETITIONS = {
    "Ligue 1 France": "FL1",
    "Premier League Angleterre": "PL",
    "Liga Espagne": "PD",
    "Bundesliga Allemagne": "BL1",
    "Serie A Italie": "SA",
    "Ligue des champions": "CL",
    "Eredivisie Pays-Bas": "DED",
    "Liga Portugal": "PPL",
    "Pro League Belgique": "BJL",
    "Ligue 2 France": "FL2",
}

st.markdown("""
<style>
.title {
    text-align: center;
    font-size: 38px;
    font-weight: 900;
    color: #00c878;
}
.subtitle {
    text-align: center;
    margin-bottom: 20px;
}
div[data-testid="stMetric"] {
    border: 1px solid #444;
    padding: 12px;
    border-radius: 12px;
}
</style>
""", unsafe_allow_html=True)

st.markdown(
    '<div class="title">⚽ FOOT AI PRO</div>',
    unsafe_allow_html=True
)

st.markdown(
    '<div class="subtitle">Pronostics et combinés automatiques</div>',
    unsafe_allow_html=True
)


# =====================================================
# CLÉ API
# =====================================================

def get_api_key():
    try:
        key = st.secrets.get("FOOTBALL_DATA_API_KEY", "")
        if key:
            return key
    except Exception:
        pass

    return os.getenv("FOOTBALL_DATA_API_KEY", "")


API_KEY = get_api_key()


# =====================================================
# APPELS API
# =====================================================

@st.cache_data(ttl=300, show_spinner=False)
def api_get(endpoint, api_key):
    try:
        response = requests.get(
            API_URL + endpoint,
            headers={"X-Auth-Token": api_key},
            timeout=20
        )

        if response.status_code == 200:
            return response.json(), None

        messages = {
            401: "Clé API invalide.",
            403: "Accès refusé pour cette compétition ou donnée.",
            429: "Limite de requêtes atteinte. Réessaie plus tard.",
        }

        return None, messages.get(
            response.status_code,
            f"Erreur API : {response.status_code}"
        )

    except requests.RequestException:
        return None, "Connexion à l'API impossible."


if not API_KEY:
    st.error("Clé API manquante.")
    st.info(
        'Dans Streamlit > Settings > Secrets, ajoute :\n\n'
        'FOOTBALL_DATA_API_KEY = "TA_CLE_API"'
    )
    st.stop()


# =====================================================
# MATCHS
# =====================================================

@st.cache_data(ttl=300, show_spinner=False)
def get_matches(api_key, code, start_date, end_date):
    endpoint = (
        f"/competitions/{code}/matches"
        f"?dateFrom={start_date}&dateTo={end_date}"
    )

    data, error = api_get(endpoint, api_key)

    if error:
        return [], error

    return data.get("matches", []), None


# =====================================================
# HISTORIQUE DES ÉQUIPES
# =====================================================

@st.cache_data(ttl=900, show_spinner=False)
def get_history(api_key, team_id, before_date):
    endpoint = (
        f"/teams/{team_id}/matches"
        f"?status=FINISHED&dateTo={before_date}&limit=10"
    )

    data, error = api_get(endpoint, api_key)

    if error or not data:
        return []

    matches = data.get("matches", [])

    matches.sort(
        key=lambda m: m.get("utcDate", ""),
        reverse=True
    )

    return matches[:10]


def analyze_team(team_id, api_key, before_date):
    matches = get_history(api_key, team_id, before_date)

    goals_for = []
    goals_against = []
    home_scored = []
    away_scored = []
    form = []

    for match in matches:
        home = match.get("homeTeam") or {}
        away = match.get("awayTeam") or {}
        score = match.get("score", {}).get("fullTime") or {}

        hg = score.get("home")
        ag = score.get("away")

        if hg is None or ag is None:
            continue

        if home.get("id") == team_id:
            gf, ga = hg, ag
            home_scored.append(hg)

        elif away.get("id") == team_id:
            gf, ga = ag, hg
            away_scored.append(ag)

        else:
            continue

        goals_for.append(gf)
        goals_against.append(ga)

        if gf > ga:
            form.append("V")
        elif gf == ga:
            form.append("N")
        else:
            form.append("D")

    count = len(goals_for)

    if count == 0:
        return {
            "count": 0,
            "attack": 1.2,
            "defense": 1.2,
            "form": "Inconnue",
            "reliability": 0.0,
            "home_scored": [],
            "away_scored": [],
        }

    return {
        "count": count,
        "attack": sum(goals_for) / count,
        "defense": sum(goals_against) / count,
        "form": " - ".join(form[:5]),
        "reliability": min(count / 5, 1.0),
        "home_scored": home_scored,
        "away_scored": away_scored,
    }


# =====================================================
# MODÈLE DE POISSON
# =====================================================

def poisson(lam, goals):
    return math.exp(-lam) * lam ** goals / math.factorial(goals)


def analyze_probabilities(home_stats, away_stats):
    # Modèle simplifié basé sur les buts historiques.
    home_lambda = (
        0.55 * home_stats["attack"]
        + 0.45 * away_stats["defense"]
        + 0.25
    )

    away_lambda = (
        0.55 * away_stats["attack"]
        + 0.45 * home_stats["defense"]
    )

    home_lambda = max(0.1, min(home_lambda, 3.5))
    away_lambda = max(0.1, min(away_lambda, 3.5))

    home_win = 0.0
    draw = 0.0
    away_win = 0.0
    over15 = 0.0
    over25 = 0.0
    btts = 0.0

    for hg in range(9):
        for ag in range(9):
            p = poisson(home_lambda, hg) * poisson(away_lambda, ag)

            if hg > ag:
                home_win += p
            elif hg == ag:
                draw += p
            else:
                away_win += p

            if hg + ag >= 2:
                over15 += p

            if hg + ag >= 3:
                over25 += p

            if hg >= 1 and ag >= 1:
                btts += p

    total = home_win + draw + away_win

    if total:
        home_win /= total
        draw /= total
        away_win /= total

    # Double chance calculée à partir du 1N2.
    double_home = home_win + draw
    double_away = away_win + draw

    return {
        "home_win": home_win,
        "draw": draw,
        "away_win": away_win,
        "double_home": double_home,
        "double_away": double_away,
        "over15": over15,
        "over25": over25,
        "btts": btts,
        "home_lambda": home_lambda,
        "away_lambda": away_lambda,
    }


# =====================================================
# MARCHÉS ET SÉLECTIONS
# =====================================================

MARKETS = {
    "Double chance 1X": "double_home",
    "Double chance X2": "double_away",
    "Plus de 1,5 but": "over15",
    "Victoire domicile": "home_win",
    "Match nul": "draw",
    "Victoire extérieur": "away_win",
    "Plus de 2,5 buts": "over25",
    "Les deux équipes marquent": "btts",
}


def get_selections(probabilities):
    selections = []

    for name, key in MARKETS.items():
        selections.append({
            "name": name,
            "probability": probabilities[key]
        })

    return sorted(
        selections,
        key=lambda x: x["probability"],
        reverse=True
    )


# =====================================================
# ANALYSE D'UN MATCH
# =====================================================

def analyze_match(match, api_key):
    home = match.get("homeTeam") or {}
    away = match.get("awayTeam") or {}

    if not home.get("id") or not away.get("id"):
        return None

    kickoff = match.get("utcDate", "")[:10]

    home_stats = analyze_team(
        home["id"], api_key, kickoff
    )

    away_stats = analyze_team(
        away["id"], api_key, kickoff
    )

    probabilities = analyze_probabilities(
        home_stats, away_stats
    )

    selections = get_selections(probabilities)

    min_history = min(
        home_stats["count"],
        away_stats["count"]
    )

    if min_history < 3:
        reliability = "Insuffisante"
    elif min_history < 5:
        reliability = "Limitée"
    else:
        reliability = "Correcte"

    return {
        "id": match.get("id"),
        "date": match.get("utcDate", ""),
        "competition": (
            match.get("competition", {}).get("name", "")
        ),
        "home": home.get("name", "Domicile"),
        "away": away.get("name", "Extérieur"),
        "home_form": home_stats["form"],
        "away_form": away_stats["form"],
        "home_count": home_stats["count"],
        "away_count": away_stats["count"],
        "reliability": reliability,
        "home_lambda": probabilities["home_lambda"],
        "away_lambda": probabilities["away_lambda"],
        "probabilities": probabilities,
        "selections": selections,
    }


# =====================================================
# PARAMÈTRES
# =====================================================

st.sidebar.header("⚙️ Paramètres")

today = date.today()

start_date = st.sidebar.date_input(
    "Date de début",
    value=today
)

end_date = st.sidebar.date_input(
    "Date de fin",
    value=today + timedelta(days=3),
    min_value=start_date
)

competitions = st.sidebar.multiselect(
    "Championnats",
    list(COMPETITIONS.keys()),
    default=[
        "Ligue 1 France",
        "Premier League Angleterre",
        "Liga Espagne",
        "Bundesliga Allemagne",
        "Serie A Italie",
        "Ligue des champions",
    ]
)

max_matches = st.sidebar.slider(
    "Nombre maximum de matchs",
    5, 60, 30, 5
)

if st.sidebar.button("🔄 Actualiser"):
    st.cache_data.clear()
    st.rerun()


# =====================================================
# RÉCUPÉRATION AUTOMATIQUE
# =====================================================

if start_date > end_date:
    st.error("La date de début doit précéder la date de fin.")
    st.stop()

if not competitions:
    st.warning("Sélectionne au moins un championnat.")
    st.stop()

all_matches = []
errors = []

with st.spinner("Recherche des matchs..."):
    for competition in competitions:
        matches, error = get_matches(
            API_KEY,
            COMPETITIONS[competition],
            start_date.isoformat(),
            end_date.isoformat()
        )

        if error:
            errors.append(f"{competition} : {error}")
            continue

        for match in matches:
            match["competition"] = {"name": competition}
            all_matches.append(match)

if errors:
    with st.expander("Problèmes API"):
        for error in errors:
            st.warning(error)

unique = {}

for match in all_matches:
    if match.get("id") is not None:
        unique[match["id"]] = match

all_matches = list(unique.values())
all_matches.sort(key=lambda m: m.get("utcDate", ""))

if not all_matches:
    st.warning(
        "Aucun match disponible pour cette période. "
        "Essaie d'autres dates ou vérifie les droits de ta clé API."
    )
    st.stop()

st.success(f"{len(all_matches)} matchs trouvés.")


# =====================================================
# ANALYSE AUTOMATIQUE
# =====================================================

matches_to_analyze = all_matches[:max_matches]
results = []

progress = st.progress(0)

with st.spinner("Analyse des équipes et des probabilités..."):
    for index, match in enumerate(matches_to_analyze):
        result = analyze_match(match, API_KEY)

        if result:
            results.append(result)

        progress.progress(
            int((index + 1) / len(matches_to_analyze) * 100)
        )

progress.empty()

if not results:
    st.warning("Aucune analyse exploitable.")
    st.stop()


# =====================================================
# CLASSEMENT DES PRONOSTICS
# =====================================================

st.header("🏆 Classement des pronostics")

for result in results:
    result["best"] = result["selections"][0]

results.sort(
    key=lambda r: (
        r["best"]["probability"]
        * min(r["home_count"], r["away_count"]) / 5
    ),
    reverse=True
)

rows = []

for rank, result in enumerate(results, 1):
    rows.append({
        "Rang": rank,
        "Match": f'{result["home"]} - {result["away"]}',
        "Championnat": result["competition"],
        "Meilleur choix": result["best"]["name"],
        "Probabilité": (
            f'{result["best"]["probability"] * 100:.1f}%'
        ),
        "Historique": result["reliability"],
    })

st.dataframe(
    pd.DataFrame(rows),
    use_container_width=True,
    hide_index=True
)


# =====================================================
# DÉTAILS DES MATCHS
# =====================================================

st.header("🔎 Analyse détaillée")

for result in results:
    with st.expander(
        f'{result["home"]} vs {result["away"]}'
    ):
        st.write(f'**Championnat :** {result["competition"]}')
        st.write(f'**Date :** {result["date"]}')
        st.write(f'**Forme domicile :** {result["home_form"]}')
        st.write(f'**Forme extérieur :** {result["away_form"]}')

        if result["reliability"] == "Insuffisante":
            st.warning(
                "Historique insuffisant : pronostic à considérer "
                "avec une prudence particulière."
            )

        p = result["probabilities"]

        cols = st.columns(3)

        cols[0].metric(
            "Victoire domicile",
            f'{p["home_win"] * 100:.1f}%'
        )

        cols[1].metric(
            "Match nul",
            f'{p["draw"] * 100:.1f}%'
        )

        cols[2].metric(
            "Victoire extérieur",
            f'{p["away_win"] * 100:.1f}%'
        )

        cols = st.columns(3)

        cols[0].metric(
            "Double chance 1X",
            f'{p["double_home"] * 100:.1f}%'
        )

        cols[1].metric(
            "Double chance X2",
            f'{p["double_away"] * 100:.1f}%'
        )

        cols[2].metric(
            "Plus de 1,5 but",
            f'{p["over15"] * 100:.1f}%'
        )

        cols = st.columns(2)

        cols[0].metric(
            "Plus de 2,5 buts",
            f'{p["over25"] * 100:.1f}%'
        )

        cols[1].metric(
            "Les deux marquent",
            f'{p["btts"] * 100:.1f}%'
        )

        st.write(
            "**Score moyen estimé :** "
            f'{result["home_lambda"]:.2f} - '
            f'{result["away_lambda"]:.2f}'
        )

        st.write("**Meilleurs choix pour ce match :**")

        for selection in result["selections"][:5]:
            st.write(
                f'- {selection["name"]} : '
                f'{selection["probability"] * 100:.1f}%'
            )


# =====================================================
# COMBINÉS AUTOMATIQUES
# =====================================================

st.header("🎯 Combinés automatiques")

st.info(
    "L'application cherche les meilleurs choix disponibles. "
    "Elle ne bloque pas les combinés parce qu'une sélection "
    "est sous un seuil arbitraire."
)

st.warning(
    "Les probabilités des combinés sont des estimations. "
    "Le calcul suppose que les sélections sont indépendantes, "
    "ce qui peut être inexact. Aucun combiné n'est garanti."
)


def best_combo_selection(result):
    # Pour privilégier la prudence, les choix à forte probabilité
    # passent avant les choix plus risqués.
    # On écarte les matchs avec moins de 3 résultats historiques.
    if min(result["home_count"], result["away_count"]) < 3:
        return None

    # Les doubles chances et le marché plus de 1,5 but sont
    # examinés en priorité, mais les autres marchés restent possibles.
    preferred = [
        "Double chance 1X",
        "Double chance X2",
        "Plus de 1,5 but",
        "Victoire domicile",
        "Victoire extérieur",
        "Match nul",
        "Plus de 2,5 buts",
        "Les deux équipes marquent",
    ]

    available = {
        item["name"]: item["probability"]
        for item in result["selections"]
    }

    # On choisit la probabilité la plus élevée parmi les marchés
    # disponibles, sans inventer de sélection.
    ranked = sorted(
        available.items(),
        key=lambda item: item[1],
        reverse=True
    )

    if not ranked:
        return None

    name, probability = ranked[0]

    return {
        "match_id": result["id"],
        "match": f'{result["home"]} - {result["away"]}',
        "competition": result["competition"],
        "date": result["date"],
        "pick": name,
        "probability": probability,
        "reliability": result["reliability"],
    }


combo_candidates = []

for result in results:
    candidate = best_combo_selection(result)

    if candidate:
        combo_candidates.append(candidate)

# Un seul choix par match.
seen = set()
unique_candidates = []

for candidate in combo_candidates:
    if candidate["match_id"] not in seen:
        seen.add(candidate["match_id"])
        unique_candidates.append(candidate)

combo_candidates = sorted(
    unique_candidates,
    key=lambda x: x["probability"],
    reverse=True
)

if len(combo_candidates) < 2:
    st.warning(
        "Pas assez de matchs avec un historique suffisant pour "
        "générer un combiné. Essaie d'élargir les dates."
    )

else:
    for size in (2, 3, 4):
        st.subheader(f"Combinés de {size} matchs")

        if len(combo_candidates) < size:
            st.info(
                f"Il faut au moins {size} matchs analysables."
            )
            continue

        # Les combinaisons sont construites à partir des choix
        # les plus probables, sans multiplier toutes les possibilités.
        pool = combo_candidates[:min(18, len(combo_candidates))]

        combos = []

        for combination in itertools.combinations(pool, size):
            probability = math.prod(
                item["probability"] for item in combination
            )

            combos.append({
                "items": combination,
                "probability": probability,
            })

        combos.sort(
            key=lambda item: item["probability"],
            reverse=True
        )

        # Montrer les 5 combinés avec la probabilité théorique
        # la plus élevée dans le pool étudié.
        for rank, combo in enumerate(combos[:5], 1):
            with st.expander(
                f'Combiné {rank} — '
                f'{combo["probability"] * 100:.2f}% théorique'
            ):
                for item in combo["items"]:
                    st.write(
                        f'⚽ **{item["match"]}** : {item["pick"]} '
                        f'({item["probability"] * 100:.1f}%)'
                    )
                    st.caption(
                        f'{item["competition"]} · {item["date"]}'
                    )

                st.metric(
                    "Probabilité théorique",
                    f'{combo["probability"] * 100:.2f}%'
                )

                st.caption(
                    "Cette estimation ne tient pas compte de toutes "
                    "les dépendances possibles entre les événements."
                )


# =====================================================
# LIMITES
# =====================================================

st.divider()

st.header("ℹ️ Informations importantes")

st.write("""
- Les données proviennent de football-data.org.
- Certaines compétitions ou statistiques peuvent être indisponibles.
- Les compositions probables, blessures et suspensions ne sont pas
  automatiquement analysées par cette version.
- Le modèle de Poisson est simplifié et n'est pas calibré sur un
  historique complet de résultats et de cotes.
- Une probabilité élevée ne signifie pas qu'un pari est rentable.
- Les probabilités des combinés diminuent généralement quand on ajoute
  des sélections.
""")

st.caption("FOOT AI PRO — analyse statistique expérimentale")