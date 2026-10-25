import os
import math
import time
import requests
from datetime import datetime, timedelta, timezone
from functools import lru_cache
# ============================================================
# FOOT AI PRO V11 — MOTEUR DE PRÉDICTION
# Analyse uniquement : aucun pari réel
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
# 1. REQUÊTES API
# ============================================================
def api_get(endpoint, params=None):
    if not API_KEY:
        raise RuntimeError(
            "Clé API manquante : FOOTBALL_DATA_API_KEY."
        )
    url = f"{API_BASE}{endpoint}"
    for attempt in range(3):
        try:
            response = SESSION.get(
                url,
                params=params,
                timeout=20,
            )
            if response.status_code == 429:
                if attempt < 2:
                    time.sleep(15 * (attempt + 1))
                    continue
                raise RuntimeError("Quota API dépassé.")
            if response.status_code == 401:
                raise RuntimeError("Clé API invalide.")
            if response.status_code == 403:
                raise RuntimeError(
                    "Compétition non disponible avec cet abonnement."
                )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            if attempt == 2:
                raise RuntimeError(f"Erreur API : {exc}") from exc
            time.sleep(3 * (attempt + 1))
    return {}
# ============================================================
# 2. HISTORIQUE DES MATCHS D'UNE ÉQUIPE
# ============================================================
@lru_cache(maxsize=128)
def get_team_matches(team_id, date_to):
    end_date = datetime.strptime(
        date_to, "%Y-%m-%d"
    ).date()
    start_date = end_date - timedelta(days=240)
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
        key=lambda m: m.get("utcDate", ""),
        reverse=True,
    )
    return matches
# ============================================================
# 3. FORME RÉCENTE, ATTAQUE ET DÉFENSE
# ============================================================
def analyze_team(team_id, date_to, limit=10):
    matches = get_team_matches(team_id, date_to)
    valid_matches = []
    for match in matches:
        score = match.get("score", {}).get("fullTime", {})
        if score.get("home") is None:
            continue
        if score.get("away") is None:
            continue
        valid_matches.append(match)
    valid_matches = valid_matches[:limit]
    if len(valid_matches) < 5:
        return None
    goals_for = []
    goals_against = []
    points = []
    home_for = []
    home_against = []
    away_for = []
    away_against = []
    weighted_points = []
    total_weight = 0.0
    for index, match in enumerate(valid_matches):
        score = match["score"]["fullTime"]
        home_goals = score["home"]
        away_goals = score["away"]
        is_home = (
            match.get("homeTeam", {}).get("id") == team_id
        )
        if is_home:
            scored = home_goals
            conceded = away_goals
            home_for.append(scored)
            home_against.append(conceded)
        else:
            scored = away_goals
            conceded = home_goals
            away_for.append(scored)
            away_against.append(conceded)
        goals_for.append(scored)
        goals_against.append(conceded)
        if scored > conceded:
            result_points = 3
        elif scored == conceded:
            result_points = 1
        else:
            result_points = 0
        points.append(result_points)
        # Poids supérieur pour les matchs les plus récents.
        weight = 0.90 ** index
        weighted_points.append(
            (result_points / 3) * weight
        )
        total_weight += weight
    count = len(valid_matches)
    return {
        "matches": count,
        "goals_for": sum(goals_for) / count,
        "goals_against": sum(goals_against) / count,
        "points_per_match": sum(points) / count,
        "form": (
            sum(weighted_points) / total_weight
            if total_weight else 0.5
        ),
        "home_for": (
            sum(home_for) / len(home_for)
            if home_for else None
        ),
        "home_against": (
            sum(home_against) / len(home_against)
            if home_against else None
        ),
        "away_for": (
            sum(away_for) / len(away_for)
            if away_for else None
        ),
        "away_against": (
            sum(away_against) / len(away_against)
            if away_against else None
        ),
    }
# ============================================================
# 4. FORCE DE L'ADVERSAIRE
# ============================================================
@lru_cache(maxsize=32)
def get_standings(competition_code):
    return api_get(
        f"/competitions/{competition_code}/standings"
    )
def opponent_strength(match, team_id):
    """
    Estime la force de l'adversaire à partir du classement.
    Une équipe mieux classée reçoit une valeur plus élevée.
    En l'absence de classement, l'indicateur reste neutre.
    """
    code = match.get("competition", {}).get("code")
    if not code:
        return 0.5
    try:
        data = get_standings(code)
        for table in data.get("standings", []):
            if table.get("type") != "TOTAL":
                continue
            entries = table.get("table", [])
            if len(entries) < 2:
                continue
            for entry in entries:
                if entry.get("team", {}).get("id") == team_id:
                    position = entry.get("position", len(entries))
                    return max(
                        0.0,
                        min(
                            1.0,
                            1 - (position - 1) / (len(entries) - 1),
                        ),
                    )
    except Exception as exc:
        print(f"Classement indisponible : {exc}")
    return 0.5
# ============================================================
# 5. CONFRONTATIONS DIRECTES
# ============================================================
def get_head_to_head(home_id, away_id, date_to):
    try:
        matches = get_team_matches(home_id, date_to)
        direct_matches = []
        for match in matches:
            h_id = match.get("homeTeam", {}).get("id")
            a_id = match.get("awayTeam", {}).get("id")
            if {h_id, a_id} == {home_id, away_id}:
                direct_matches.append(match)
        return direct_matches[:5]
    except Exception as exc:
        print(f"Confrontations directes indisponibles : {exc}")
        return []
def calculate_h2h_adjustment(matches, home_id):
    """
    Ajustement limité : les confrontations directes restent
    secondaires par rapport à la forme et aux statistiques.
    """
    results = []
    for match in matches:
        score = match.get("score", {}).get("fullTime", {})
        hg = score.get("home")
        ag = score.get("away")
        if hg is None or ag is None:
            continue
        home_is_home = (
            match.get("homeTeam", {}).get("id") == home_id
        )
        if hg == ag:
            value = 0.5
        elif home_is_home:
            value = 1.0 if hg > ag else 0.0
        else:
            value = 1.0 if ag > hg else 0.0
        results.append(value)
    if len(results) < 2:
        return 0.0
    average = sum(results) / len(results)
    return max(-0.08, min(0.08, (average - 0.5) * 0.16))
# ============================================================
# 6. BUTS ATTENDUS
# ============================================================
def calculate_expected_goals(
    home,
    away,
    home_strength=0.5,
    away_strength=0.5,
    h2h_adjustment=0.0,
):
    # Attaque domicile et défense extérieure.
    home_attack = (
        0.65 * (
            home["home_for"]
            if home["home_for"] is not None
            else home["goals_for"]
        )
        + 0.35 * home["goals_for"]
    )
    away_defense = (
        0.65 * (
            away["away_against"]
            if away["away_against"] is not None
            else away["goals_against"]
        )
        + 0.35 * away["goals_against"]
    )
    # Attaque extérieure et défense domicile.
    away_attack = (
        0.65 * (
            away["away_for"]
            if away["away_for"] is not None
            else away["goals_for"]
        )
        + 0.35 * away["goals_for"]
    )
    home_defense = (
        0.65 * (
            home["home_against"]
            if home["home_against"] is not None
            else home["goals_against"]
        )
        + 0.35 * home["goals_against"]
    )
    home_lambda = (
        0.55 * home_attack
        + 0.45 * away_defense
    )
    away_lambda = (
        0.55 * away_attack
        + 0.45 * home_defense
    )
    # Avantage du terrain modéré.
    home_lambda *= 1.08
    # Forme récente.
    home_lambda *= 0.90 + 0.20 * home["form"]
    away_lambda *= 0.90 + 0.20 * away["form"]
    # Niveau approximatif des adversaires rencontrés.
    home_lambda *= 0.95 + 0.10 * home_strength
    away_lambda *= 0.95 + 0.10 * away_strength
    # Influence limitée des confrontations directes.
    home_lambda *= 1 + h2h_adjustment
    away_lambda *= 1 - h2h_adjustment
    return (
        max(0.20, min(3.50, home_lambda)),
        max(0.20, min(3.20, away_lambda)),
    )
# ============================================================
# 7. PROBABILITÉS DE POISSON
# ============================================================
def poisson_probability(lam, goals):
    if lam <= 0:
        return 1.0 if goals == 0 else 0.0
    return (
        math.exp(-lam)
        * lam ** goals
        / math.factorial(goals)
    )
def calculate_probabilities(home_lambda, away_lambda):
    markets = {
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
    }
    score_matrix = []
    for hg in range(11):
        ph = poisson_probability(home_lambda, hg)
        for ag in range(11):
            pa = poisson_probability(away_lambda, ag)
            probability = ph * pa
            total = hg + ag
            score_matrix.append((probability, hg, ag))
            if hg > ag:
                markets["1"] += probability
            elif hg == ag:
                markets["N"] += probability
            else:
                markets["2"] += probability
            if hg >= ag:
                markets["1X"] += probability
            if ag >= hg:
                markets["X2"] += probability
            if hg != ag:
                markets["12"] += probability
            if total >= 1:
                markets["over_0_5"] += probability
            if total >= 2:
                markets["over_1_5"] += probability
            if total >= 3:
                markets["over_2_5"] += probability
            if total >= 4:
                markets["over_3_5"] += probability
            if total <= 2:
                markets["under_2_5"] += probability
            if total <= 3:
                markets["under_3_5"] += probability
            if hg > 0 and ag > 0:
                markets["btts_yes"] += probability
    markets["btts_no"] = 1 - markets["btts_yes"]
    score_matrix.sort(reverse=True)
    markets["exact_score"] = (
        f"{score_matrix[0][1]}-{score_matrix[0][2]}"
    )
    return markets
# ============================================================
# 8. ANALYSE COMPLÈTE D'UN MATCH
# ============================================================
def analyze_match(match):
    home_team = match.get("homeTeam", {})
    away_team = match.get("awayTeam", {})
    home_id = home_team.get("id")
    away_id = away_team.get("id")
    if not home_id or not away_id:
        return None
    match_date = match.get("utcDate")
    if not match_date:
        return None
    kickoff = datetime.fromisoformat(
        match_date.replace("Z", "+00:00")
    )
    date_to = kickoff.date().isoformat()
    home = analyze_team(home_id, date_to)
    away = analyze_team(away_id, date_to)
    if not home or not away:
        print(
            f"Données insuffisantes : "
            f"{home_team.get('name')} - {away_team.get('name')}"
        )
        return None
    home_strength = opponent_strength(match, home_id)
    away_strength = opponent_strength(match, away_id)
    h2h = get_head_to_head(home_id, away_id, date_to)
    h2h_adjustment = calculate_h2h_adjustment(
        h2h,
        home_id,
    )
    home_lambda, away_lambda = calculate_expected_goals(
        home,
        away,
        home_strength,
        away_strength,
        h2h_adjustment,
    )
    probabilities = calculate_probabilities(
        home_lambda,
        away_lambda,
    )
    return {
        "match_id": match.get("id"),
        "date": kickoff.isoformat(),
        "competition": match.get(
            "competition", {}
        ).get("name", "Inconnue"),
        "domicile": home_team.get("name", "Inconnu"),
        "exterieur": away_team.get("name", "Inconnu"),
        "forme_domicile": round(home["form"] * 100, 1),
        "forme_exterieur": round(away["form"] * 100, 1),
        "buts_attendus_domicile": round(home_lambda, 2),
        "buts_attendus_exterieur": round(away_lambda, 2),
        "probabilites": {
            key: (
                round(value * 100, 2)
                if isinstance(value, float)
                else value
            )
            for key, value in probabilities.items()
        },
        "version_modele": "V11",
    }
# ============================================================
# 9. AFFICHAGE
# ============================================================
def print_analysis(result):
    if not result:
        return
    print("\n" + "=" * 50)
    print(f"{result['domicile']} - {result['exterieur']}")
    print(f"Compétition : {result['competition']}")
    print(
        f"Forme domicile : {result['forme_domicile']}%"
    )
    print(
        f"Forme extérieur : {result['forme_exterieur']}%"
    )
    print(
        f"Buts attendus : "
        f"{result['buts_attendus_domicile']} - "
        f"{result['buts_attendus_exterieur']}"
    )
    probs = result["probabilites"]
    print("\nRésultat du match")
    print(f"1 : {probs['1']}%")
    print(f"N : {probs['N']}%")
    print(f"2 : {probs['2']}%")
    print(f"1X : {probs['1X']}%")
    print(f"X2 : {probs['X2']}%")
    print("\nMarchés de buts")
    print(f"Plus de 0,5 : {probs['over_0_5']}%")
    print(f"Plus de 1,5 : {probs['over_1_5']}%")
    print(f"Plus de 2,5 : {probs['over_2_5']}%")
    print(f"Plus de 3,5 : {probs['over_3_5']}%")
    print(f"Moins de 2,5 : {probs['under_2_5']}%")
    print(f"Moins de 3,5 : {probs['under_3_5']}%")
    print(f"Les deux équipes marquent : {probs['btts_yes']}%")
    print(f"Score exact estimé : {probs['exact_score']}")
    print(
        "Ces probabilités sont des estimations "
        "mathématiques, pas des garanties."
    )
    print("=" * 50)
# ============================================================
# 10. TEST DU MOTEUR SUR LES MATCHS À VENIR
# ============================================================
def main():
    print("FOOT AI PRO V11")
    print("Moteur de prédiction — simulation uniquement")
    if not API_KEY:
        print(
            "ERREUR : le secret FOOTBALL_DATA_API_KEY "
            "est absent."
        )
        return
    today = datetime.now(timezone.utc).date()
    date_from = today.isoformat()
    date_to = (today + timedelta(days=7)).isoformat()
    total = 0
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
            for match in data.get("matches", []):
                if match.get("status") not in (
                    "SCHEDULED",
                    "TIMED",
                ):
                    continue
                try:
                    result = analyze_match(match)
                    if result:
                        print_analysis(result)
                        total += 1
                except Exception as exc:
                    print(
                        f"Erreur d'analyse du match "
                        f"{match.get('id')} : {exc}"
                    )
        except Exception as exc:
            print(f"Erreur {name} : {exc}")
    print(f"\nNombre de matchs analysés : {total}")
    print("Fin des analyses V11.")
if __name__ == "__main__":
    main()