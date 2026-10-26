import os
import math
import time
import requests

from datetime import datetime, timedelta, timezone
from functools import lru_cache

# ============================================================
# FOOT AI PRO V11
# Moteur de prédiction football amélioré
# Simulation et analyse uniquement
# API : football-data.org v4
# ============================================================

API_BASE = "https://api.football-data.org/v4"

API_KEY = (
    os.getenv("FOOTBALL_DATA_API_KEY")
    or os.getenv("FOOTBALL_DATA_TOKEN")
    or os.getenv("FOOTBALL_API_KEY")
    or ""
).strip()

COMPETITIONS = {
    "FL1": "Ligue 1",
    "PL": "Premier League",
    "PD": "La Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "CL": "Ligue des Champions",
}

SESSION = requests.Session()

if API_KEY:
    SESSION.headers.update({"X-Auth-Token": API_KEY})


# ============================================================
# 1. COMMUNICATION AVEC L'API
# ============================================================

def api_get(endpoint, params=None):
    """Interroge l'API avec gestion des erreurs et du quota."""

    if not API_KEY:
        raise RuntimeError(
            "Clé API manquante. Vérifie le secret "
            "FOOTBALL_DATA_API_KEY dans GitHub."
        )

    url = f"{API_BASE}{endpoint}"

    for attempt in range(3):
        try:
            response = SESSION.get(
                url,
                params=params,
                timeout=20
            )

            if response.status_code == 429:
                if attempt < 2:
                    wait = 15 * (attempt + 1)
                    print(
                        f"Limite API atteinte. "
                        f"Nouvel essai dans {wait} secondes."
                    )
                    time.sleep(wait)
                    continue

                raise RuntimeError(
                    "Quota API dépassé. Réessaie plus tard."
                )

            if response.status_code == 401:
                raise RuntimeError(
                    "Clé API invalide."
                )

            if response.status_code == 403:
                raise RuntimeError(
                    "Accès refusé : compétition ou saison "
                    "non disponible avec ton abonnement."
                )

            response.raise_for_status()
            return response.json()

        except requests.RequestException as exc:
            if attempt == 2:
                raise RuntimeError(
                    f"Erreur de communication avec l'API : {exc}"
                ) from exc

            time.sleep(3 * (attempt + 1))

    return {}


# ============================================================
# 2. RÉCUPÉRATION DES MATCHS TERMINÉS
# ============================================================

@lru_cache(maxsize=64)
def get_team_matches(team_id, date_to, days=240):
    """
    Récupère les matchs terminés d'une équipe.

    Le cache évite de répéter inutilement les mêmes requêtes
    pendant une exécution du programme.
    """

    end_date = datetime.strptime(
        date_to, "%Y-%m-%d"
    ).date()

    start_date = end_date - timedelta(days=days)

    data = api_get(
        f"/teams/{team_id}/matches",
        params={
            "status": "FINISHED",
            "dateFrom": start_date.isoformat(),
            "dateTo": date_to,
            "limit": 100,
        },
    )

    matches = data.get("matches", [])

    matches.sort(
        key=lambda match: match.get("utcDate", ""),
        reverse=True,
    )

    return matches


# ============================================================
# 3. HISTORIQUE DES CONFRONTATIONS DIRECTES
# ============================================================

def get_head_to_head(home_id, away_id, date_to):
    """
    Retourne les dernières confrontations directes disponibles.

    Ces résultats sont utilisés comme indicateur secondaire.
    """

    try:
        data = api_get(
            f"/teams/{home_id}/matches",
            params={
                "status": "FINISHED",
                "dateTo": date_to,
                "limit": 100,
            },
        )

        matches = []

        for match in data.get("matches", []):
            home_team = match.get("homeTeam", {}).get("id")
            away_team = match.get("awayTeam", {}).get("id")

            if (
                {home_team, away_team}
                == {home_id, away_id}
            ):
                matches.append(match)

        matches.sort(
            key=lambda match: match.get("utcDate", ""),
            reverse=True,
        )

        return matches[:5]

    except Exception as exc:
        print(
            f"Confrontations directes indisponibles : {exc}"
        )
        return []


# ============================================================
# 4. ANALYSE DE LA FORME RÉCENTE
# ============================================================

def analyze_team_form(team_id, date_to, limit=10):
    """
    Calcule les indicateurs d'une équipe sur ses derniers matchs.

    Indicateurs :
    - buts marqués et encaissés ;
    - points par match ;
    - forme récente ;
    - statistiques à domicile et à l'extérieur ;
    - force approximative des adversaires.
    """

    matches = get_team_matches(
        team_id,
        date_to
    )

    matches = [
        match
        for match in matches
        if match.get("status") == "FINISHED"
        and match.get("score", {})
            .get("fullTime", {})
            .get("home") is not None
        and match.get("score", {})
            .get("fullTime", {})
            .get("away") is not None
    ][:limit]

    if len(matches) < 3:
        return None

    goals_for = []
    goals_against = []

    home_goals_for = []
    home_goals_against = []

    away_goals_for = []
    away_goals_against = []

    points = []
    weighted_points = []

    for index, match in enumerate(matches):

        score = match["score"]["fullTime"]

        home_goals = score["home"]
        away_goals = score["away"]

        is_home = (
            match.get("homeTeam", {}).get("id")
            == team_id
        )

        if is_home:
            scored = home_goals
            conceded = away_goals

            home_goals_for.append(scored)
            home_goals_against.append(conceded)

        else:
            scored = away_goals
            conceded = home_goals

            away_goals_for.append(scored)
            away_goals_against.append(conceded)

        goals_for.append(scored)
        goals_against.append(conceded)

        if scored > conceded:
            pts = 3
        elif scored == conceded:
            pts = 1
        else:
            pts = 0

        points.append(pts)

        # Les matchs récents reçoivent davantage de poids.
        weight = 0.85 ** index

        weighted_points.append(
            (pts / 3) * weight
        )

    total_weight = sum(
        0.85 ** index
        for index in range(len(matches))
    )

    recent_form = (
        sum(weighted_points) / total_weight
        if total_weight
        else 0.5
    )

    count = len(matches)

    return {
        "matches": count,

        "goals_for": sum(goals_for) / count,
        "goals_against": sum(goals_against) / count,

        "points_per_match": sum(points) / count,

        "recent_form": recent_form,

        "home_goals_for": (
            sum(home_goals_for) / len(home_goals_for)
            if home_goals_for
            else None
        ),

        "home_goals_against": (
            sum(home_goals_against) / len(home_goals_against)
            if home_goals_against
            else None
        ),

        "away_goals_for": (
            sum(away_goals_for) / len(away_goals_for)
            if away_goals_for
            else None
        ),

        "away_goals_against": (
            sum(away_goals_against) / len(away_goals_against)
            if away_goals_against
            else None
        ),
    }


# ============================================================
# 5. FORCE APPROXIMATIVE DES ADVERSAIRES
# ============================================================

def opponent_strength(match, team_id):
    """
    Utilise le classement de la compétition lorsqu'il est
    disponible pour estimer la force de l'adversaire.

    Si le classement est indisponible, utilise une valeur neutre.
    """

    try:
        competition_code = (
            match.get("competition", {}).get("code")
        )

        if not competition_code:
            return 0.5

        standings = api_get(
            f"/competitions/{competition_code}/standings"
        )

        for table in standings.get("standings", []):
            if table.get("type") != "TOTAL":
                continue

            entries = table.get("table", [])

            if not entries:
                continue

            total_teams = len(entries)

            for entry in entries:
                if entry.get("team", {}).get("id") == team_id:
                    position = entry.get("position", total_teams)

                    if total_teams <= 1:
                        return 0.5

                    return 1 - (
                        (position - 1) / (total_teams - 1)
                    )

        return 0.5

    except Exception:
        return 0.5


# ============================================================
# 6. CONFRONTATIONS DIRECTES
# ============================================================

def head_to_head_factor(matches, home_id):
    """
    Retourne un ajustement limité entre -0.10 et +0.10.

    Les confrontations directes ne doivent jamais dominer
    la forme récente et les statistiques générales.
    """

    if len(matches) < 2:
        return 0.0

    values = []

    for match in matches[:5]:

        score = match.get("score", {}).get("fullTime", {})

        hg = score.get("home")
        ag = score.get("away")

        if hg is None or ag is None:
            continue

        actual_home = (
            match.get("homeTeam", {}).get("id")
            == home_id
        )

        if hg == ag:
            value = 0.5
        elif actual_home:
            value = 1.0 if hg > ag else 0.0
        else:
            value = 1.0 if ag > hg else 0.0

        values.append(value)

    if not values:
        return 0.0

    average = sum(values) / len(values)

    return max(
        -0.10,
        min(0.10, (average - 0.5) * 0.20)
    )


# ============================================================
# 7. CALCUL DU NOMBRE DE BUTS ATTENDUS
# ============================================================

def calculate_expected_goals(
    home_form,
    away_form,
    home_opponent_strength=0.5,
    away_opponent_strength=0.5,
    h2h_adjustment=0.0,
):
    """
    Combine :
    - attaque ;
    - défense adverse ;
    - performances domicile/extérieur ;
    - forme récente ;
    - force des adversaires ;
    - avantage du terrain.
    """

    home_attack = (
        0.65 * (
            home_form["home_goals_for"]
            if home_form["home_goals_for"] is not None
            else home_form["goals_for"]
        )
        + 0.35 * home_form["goals_for"]
    )

    away_defense = (
        0.65 * (
            away_form["away_goals_against"]
            if away_form["away_goals_against"] is not None
            else away_form["goals_against"]
        )
        + 0.35 * away_form["goals_against"]
    )

    away_attack = (
        0.65 * (
            away_form["away_goals_for"]
            if away_form["away_goals_for"] is not None
            else away_form["goals_for"]
        )
        + 0.35 * away_form["goals_for"]
    )

    home_defense = (
        0.65 * (
            home_form["home_goals_against"]
            if home_form["home_goals_against"] is not None
            else home_form["goals_against"]
        )
        + 0.35 * home_form["goals_against"]
    )

    home_lambda = (
        0.55 * home_attack
        + 0.45 * away_defense
    )

    away_lambda = (
        0.55 * away_attack
        + 0.45 * home_defense
    )

    # Avantage modéré du terrain.
    home_lambda *= 1.08

    # Correction modérée de forme.
    home_lambda *= (
        0.90 + 0.20 * home_form["recent_form"]
    )

    away_lambda *= (
        0.90 + 0.20 * away_form["recent_form"]
    )

    # Force des adversaires : correction prudente.
    home_lambda *= (
        0.95 + 0.10 * home_opponent_strength
    )

    away_lambda *= (
        0.95 + 0.10 * away_opponent_strength
    )

    # Ajustement léger issu des confrontations directes.
    home_lambda *= (
        1 + h2h_adjustment
    )

    away_lambda *= (
        1 - h2h_adjustment
    )

    # Bornes pour éviter les estimations extrêmes.
    home_lambda = max(
        0.20,
        min(3.50, home_lambda)
    )

    away_lambda = max(
        0.20,
        min(3.20, away_lambda)
    )

    return home_lambda, away_lambda


# ============================================================
# 8. MODÈLE DE POISSON
# ============================================================

def poisson_probability(lam, goals):
    if lam <= 0:
        return 1.0 if goals == 0 else 0.0

    return (
        math.exp(-lam)
        * lam ** goals
        / math.factorial(goals)
    )


def calculate_probabilities(
    home_lambda,
    away_lambda,
    max_goals=10,
):
    """
    Calcule les marchés à partir de la matrice des scores.
    """

    probabilities = {
        "1": 0.0,
        "N": 0.0,
        "2": 0.0,
        "1X": 0.0,
        "X2": 0.0,
        "12": 0.0,
        "over_0_5": 0.0,
        "over_1_5": 0.0,
        "over_2_5": 0.0,
        "over_3_5": 0.0,
        "under_2_5": 0.0,
        "under_3_5": 0.0,
        "btts_yes": 0.0,
        "btts_no": 0.0,
    }

    score_matrix = []

    for home_goals in range(max_goals + 1):

        p_home = poisson_probability(
            home_lambda,
            home_goals
        )

        for away_goals in range(max_goals + 1):

            p_away = poisson_probability(
                away_lambda,
                away_goals
            )

            probability = p_home * p_away

            score_matrix.append(
                (
                    probability,
                    home_goals,
                    away_goals,
                )
            )

            total_goals = home_goals + away_goals

            if home_goals > away_goals:
                probabilities["1"] += probability

            elif home_goals == away_goals:
                probabilities["N"] += probability

            else:
                probabilities["2"] += probability

            if home_goals >= away_goals:
                probabilities["1X"] += probability

            if away_goals >= home_goals:
                probabilities["X2"] += probability

            if home_goals != away_goals:
                probabilities["12"] += probability

            if total_goals >= 1:
                probabilities["over_0_5"] += probability

            if total_goals >= 2:
                probabilities["over_1_5"] += probability

            if total_goals >= 3:
                probabilities["over_2_5"] += probability

            if total_goals >= 4:
                probabilities["over_3_5"] += probability

            if total_goals <= 2:
                probabilities["under_2_5"] += probability

            if total_goals <= 3:
                probabilities["under_3_5"] += probability

            if home_goals > 0 and away_goals > 0:
                probabilities["btts_yes"] += probability

    probabilities["btts_no"] = (
        1 - probabilities["btts_yes"]
    )

    score_matrix.sort(
        key=lambda item: item[0],
        reverse=True
    )

    probabilities["exact_score"] = (
        f"{score_matrix[0][1]}-{score_matrix[0][2]}"
    )

    probabilities["exact_score_probability"] = (
        score_matrix[0][0]
    )

    return probabilities


# ============================================================
# 9. ANALYSE COMPLÈTE D'UN MATCH
# ============================================================

def analyze_match(match):
    """
    Fonction principale à appeler pour chaque match.

    Retourne les statistiques, les probabilités et le score
    estimé, ou None si les données sont insuffisantes.
    """

    home = match.get("homeTeam", {})
    away = match.get("awayTeam", {})

    home_id = home.get("id")
    away_id = away.get("id")

    if not home_id or not away_id:
        print("Match ignoré : identifiants des équipes absents.")
        return None

    match_date = match.get("utcDate")

    if not match_date:
        print("Match ignoré : date absente.")
        return None

    match_datetime = datetime.fromisoformat(
        match_date.replace("Z", "+00:00")
    )

    date_to = (
        match_datetime.date()
    ).isoformat()

    # Ne pas utiliser les matchs futurs dans les statistiques.
    home_form = analyze_team_form(
        home_id,
        date_to,
        limit=10
    )

    away_form = analyze_team_form(
        away_id,
        date_to,
        limit=10
    )

    if not home_form or not away_form:
        print(
            f"Données insuffisantes : "
            f"{home.get('name')} - {away.get('name')}"
        )
        return None

    home_strength = opponent_strength(
        match,
        home_id
    )

    away_strength = opponent_strength(
        match,
        away_id
    )

    h2h = get_head_to_head(
        home_id,
        away_id,
        date_to
    )

    h2h_adjustment = head_to_head_factor(
        h2h,
        home_id
    )

    home_lambda, away_lambda = calculate_expected_goals(
        home_form,
        away_form,
        home_strength,
        away_strength,
        h2h_adjustment,
    )

    probabilities = calculate_probabilities(
        home_lambda,
        away_lambda
    )

    return {
        "match_id": match.get("id"),

        "date": match_datetime.isoformat(),

        "competition": match.get(
            "competition", {}
        ).get("name", "Inconnue"),

        "domicile": home.get("name", "Inconnu"),

        "exterieur": away.get("name", "Inconnu"),

        "forme_domicile": round(
            home_form["recent_form"] * 100,
            1
        ),

        "forme_exterieur": round(
            away_form["recent_form"] * 100,
            1
        ),

        "buts_attendus_domicile": round(
            home_lambda,
            2
        ),

        "buts_attendus_exterieur": round(
            away_lambda,
            2
        ),

        "probabilites": {
            key: (
                round(value * 100, 2)
                if isinstance(value, float)
                else value
            )
            for key, value in probabilities.items()
        },

        "matchs_forme_domicile": home_form["matches"],

        "matchs_forme_exterieur": away_form["matches"],

        "confrontations_directes": len(h2h),

        "version_modele": "V11",
    }


# ============================================================
# 10. AFFICHAGE DES PRÉDICTIONS
# ============================================================

def print_analysis(result):

    if not result:
        return

    print("\n" + "=" * 55)

    print(
        f"{result['domicile']} - "
        f"{result['exterieur']}"
    )

    print(
        f"Compétition : {result['competition']}"
    )

    print(
        f"Forme récente domicile : "
        f"{result['forme_domicile']}%"
    )

    print(
        f"Forme récente extérieur : "
        f"{result['forme_exterieur']}%"
    )

    print(
        f"Buts attendus : "
        f"{result['buts_attendus_domicile']} - "
        f"{result['buts_attendus_exterieur']}"
    )

    probs = result["probabilites"]

    print("\nRésultat du match :")

    print(f"Victoire domicile : {probs['1']}%")
    print(f"Match nul : {probs['N']}%")
    print(f"Victoire extérieur : {probs['2']}%")

    print("\nMarchés de buts :")

    print(f"Plus de 0,5 : {probs['over_0_5']}%")
    print(f"Plus de 1,5 : {probs['over_1_5']}%")
    print(f"Plus de 2,5 : {probs['over_2_5']}%")
    print(f"Plus de 3,5 : {probs['over_3_5']}%")

    print(f"Moins de 2,5 : {probs['under_2_5']}%")
    print(f"Moins de 3,5 : {probs['under_3_5']}%")

    print(f"Les deux équipes marquent : {probs['btts_yes']}%")
    print(f"Les deux équipes ne marquent pas toutes les deux : {probs['btts_no']}%")

    print(f"\nScore exact estimé : {probs['exact_score']}")

    print(
        "Attention : ces pourcentages sont des estimations "
        "mathématiques, pas des garanties."
    )

    print("=" * 55)


# ============================================================
# 11. EXÉCUTION
# ============================================================

def main():

    print("FOOT AI PRO V11 — MOTEUR DE PRÉDICTION")
    print("Simulation uniquement, aucun pari réel.\n")

    if not API_KEY:
        print(
            "ERREUR : ajoute le secret GitHub "
            "FOOTBALL_DATA_API_KEY."
        )
        return

    today = datetime.now(
        timezone.utc
    ).date()

    date_from = today.isoformat()

    date_to = (
        today + timedelta(days=7)
    ).isoformat()

    total_analyzed = 0

    for code, name in COMPETITIONS.items():

        print(f"\nChargement : {name}")

        try:

            data = api_get(
                f"/competitions/{code}/matches",
                params={
                    "dateFrom": date_from,
                    "dateTo": date_to,
                },
            )

            matches = data.get("matches", [])

            for match in matches:

                if match.get("status") not in (
                    "SCHEDULED",
                    "TIMED",
                ):
                    continue

                try:

                    result = analyze_match(match)

                    if result:
                        print_analysis(result)
                        total_analyzed += 1

                except Exception as exc:

                    print(
                        f"Analyse impossible pour "
                        f"le match {match.get('id')} : {exc}"
                    )

        except Exception as exc:

            print(
                f"Impossible de charger {name} : {exc}"
            )

    print("\n" + "=" * 55)

    print(
        f"Nombre de matchs analysés : {total_analyzed}"
    )

    print("Fin des analyses V11.")

    print("=" * 55)


if __name__ == "__main__":
    main()