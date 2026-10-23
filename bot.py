import os
import json
import math
from datetime import date, datetime, timedelta, timezone

import requests

# ============================================================
# FOOT AI PRO — BOT AUTOMATIQUE
# Simulation virtuelle uniquement
# ============================================================

API_BASE = "https://api.football-data.org/v4"

COMPETITIONS = {
    "Ligue 1": "FL1",
    "Premier League": "PL",
    "Liga": "PD",
    "Bundesliga": "BL1",
    "Serie A": "SA",
    "Ligue des Champions": "CL",
}

STATE_FILE = "data/bankroll.json"

CAPITAL_INITIAL = 20.0
MISE_FRACTION = 0.02
MISE_MAXIMUM = 1.00
PROBABILITE_MINIMUM = 0.62
MAX_PARIS_PAR_JOUR = 2


# ============================================================
# CAPITAL VIRTUEL
# ============================================================

def load_state():
    os.makedirs("data", exist_ok=True)

    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            return json.load(file)

    return {
        "starting_bankroll": CAPITAL_INITIAL,
        "bankroll": CAPITAL_INITIAL,
        "day": "",
        "bets": [],
        "history": [],
        "message": "Initialisation du bot.",
    }


def save_state(state):
    os.makedirs("data", exist_ok=True)

    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(
            state,
            file,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# CONNEXION API
# ============================================================

def get_matches(competition, date_from, date_to, api_key):

    url = f"{API_BASE}/competitions/{competition}/matches"

    response = requests.get(
        url,
        headers={"X-Auth-Token": api_key},
        params={
            "dateFrom": date_from,
            "dateTo": date_to,
        },
        timeout=25,
    )

    if response.status_code == 429:
        raise RuntimeError(
            "Limite API atteinte. Réessaie lors du prochain passage."
        )

    if response.status_code == 403:
        raise RuntimeError(
            f"Accès refusé pour la compétition {competition}."
        )

    response.raise_for_status()

    return response.json().get("matches", [])


# ============================================================
# PROBABILITÉ DE POISSON
# ============================================================

def poisson(moyenne, buts):

    if moyenne <= 0:
        return 1.0 if buts == 0 else 0.0

    return (
        math.exp(-moyenne)
        * moyenne ** buts
        / math.factorial(buts)
    )


# ============================================================
# ANALYSE STATISTIQUE D'UN MATCH
# ============================================================

def predict_match(matches, home_team, away_team):

    buts_domicile_ligue = []
    buts_exterieur_ligue = []

    home_scored = []
    home_conceded = []

    away_scored = []
    away_conceded = []

    for match in matches:

        if match.get("status") != "FINISHED":
            continue

        score = match.get("score", {}).get("fullTime", {})

        gh = score.get("home")
        ga = score.get("away")

        if gh is None or ga is None:
            continue

        home_name = match.get("homeTeam", {}).get("name", "")
        away_name = match.get("awayTeam", {}).get("name", "")

        buts_domicile_ligue.append(gh)
        buts_exterieur_ligue.append(ga)

        if home_name == home_team:
            home_scored.append(gh)
            home_conceded.append(ga)

        elif away_name == home_team:
            home_scored.append(ga)
            home_conceded.append(gh)

        if home_name == away_team:
            away_scored.append(gh)
            away_conceded.append(ga)

        elif away_name == away_team:
            away_scored.append(ga)
            away_conceded.append(gh)

    moyenne_home = (
        sum(buts_domicile_ligue) / len(buts_domicile_ligue)
        if buts_domicile_ligue else 1.45
    )

    moyenne_away = (
        sum(buts_exterieur_ligue) / len(buts_exterieur_ligue)
        if buts_exterieur_ligue else 1.15
    )

    attaque_home = (
        sum(home_scored) / len(home_scored)
        if home_scored else moyenne_home
    )

    defense_home = (
        sum(home_conceded) / len(home_conceded)
        if home_conceded else moyenne_away
    )

    attaque_away = (
        sum(away_scored) / len(away_scored)
        if away_scored else moyenne_away
    )

    defense_away = (
        sum(away_conceded) / len(away_conceded)
        if away_conceded else moyenne_home
    )

    # Réduire l'influence des échantillons trop petits.
    if len(home_scored) < 3:
        attaque_home = (attaque_home + moyenne_home) / 2
        defense_home = (defense_home + moyenne_away) / 2

    if len(away_scored) < 3:
        attaque_away = (attaque_away + moyenne_away) / 2
        defense_away = (defense_away + moyenne_home) / 2

    lambda_home = max(
        0.20,
        min(3.40, 0.55 * attaque_home + 0.45 * defense_away),
    )

    lambda_away = max(
        0.20,
        min(3.40, 0.55 * attaque_away + 0.45 * defense_home),
    )

    scores = {}

    for home_goals in range(9):
        for away_goals in range(9):

            probability = (
                poisson(lambda_home, home_goals)
                * poisson(lambda_away, away_goals)
            )

            scores[(home_goals, away_goals)] = probability

    total = sum(scores.values()) or 1

    p_home = sum(
        p for (h, a), p in scores.items() if h > a
    ) / total

    p_draw = sum(
        p for (h, a), p in scores.items() if h == a
    ) / total

    p_away = sum(
        p for (h, a), p in scores.items() if h < a
    ) / total

    p_over15 = sum(
        p for (h, a), p in scores.items() if h + a >= 2
    ) / total

    p_over25 = sum(
        p for (h, a), p in scores.items() if h + a >= 3
    ) / total

    p_btts = sum(
        p for (h, a), p in scores.items() if h > 0 and a > 0
    ) / total

    score_exact = max(scores, key=scores.get)

    markets = [
        ("Plus de 1,5 but", p_over15),
        ("Plus de 2,5 buts", p_over25),
        ("Les deux équipes marquent : oui", p_btts),
        ("Victoire domicile", p_home),
        ("Match nul", p_draw),
        ("Victoire extérieur", p_away),
    ]

    meilleur_marche, probabilite = max(
        markets,
        key=lambda item: item[1],
    )

    return {
        "home": home_team,
        "away": away_team,
        "pick": meilleur_marche,
        "probability": round(probabilite, 4),
        "sample": min(
            len(home_scored),
            len(away_scored),
        ),
        "score": f"{score_exact[0]}-{score_exact[1]}",
    }


# ============================================================
# RÉSULTATS DES SIMULATIONS TERMINÉES
# ============================================================

def settle_bets(state, matches_by_id):

    for bet in state["bets"]:

        if bet.get("settled"):
            continue

        match = matches_by_id.get(str(bet.get("match_id")))

        if not match or match.get("status") != "FINISHED":
            continue

        score = match.get("score", {}).get("fullTime", {})

        home_goals = score.get("home")
        away_goals = score.get("away")

        if home_goals is None or away_goals is None:
            continue

        pick = bet["pick"]

        if pick == "Plus de 1,5 but":
            won = home_goals + away_goals >= 2

        elif pick == "Plus de 2,5 buts":
            won = home_goals + away_goals >= 3

        elif pick == "Les deux équipes marquent : oui":
            won = home_goals > 0 and away_goals > 0

        elif pick == "Victoire domicile":
            won = home_goals > away_goals

        elif pick == "Match nul":
            won = home_goals == away_goals

        elif pick == "Victoire extérieur":
            won = home_goals < away_goals

        else:
            continue

        stake = float(bet["stake"])

        # Cote artificielle de simulation, pas une cote bookmaker.
        probability = max(
            0.01,
            min(0.99, float(bet["probability"])),
        )

        virtual_odds = round(0.92 / probability, 2)

        if won:
            state["bankroll"] += stake * (virtual_odds - 1)
        else:
            state["bankroll"] -= stake

        bet.update({
            "settled": True,
            "result": "Gagné" if won else "Perdu",
            "score_final": f"{home_goals}-{away_goals}",
            "virtual_odds": virtual_odds,
            "settled_at": datetime.now(timezone.utc).isoformat(),
        })


# ============================================================
# EXÉCUTION DU BOT
# ============================================================

def main():

    api_key = os.getenv("FOOTBALL_DATA_API_KEY", "").strip()

    if not api_key:
        raise SystemExit(
            "Clé absente : configure FOOTBALL_DATA_API_KEY "
            "dans les secrets GitHub Actions."
        )

    state = load_state()

    today = date.today()

    date_from = (today - timedelta(days=60)).isoformat()
    date_to = (today + timedelta(days=3)).isoformat()

    all_matches = []
    matches_by_league = {}
    errors = []

    # Une requête par compétition et par exécution.
    for league, code in COMPETITIONS.items():

        try:
            matches = get_matches(
                code,
                date_from,
                date_to,
                api_key,
            )

            matches_by_league[league] = matches
            all_matches.extend(matches)

        except Exception as error:
            errors.append(f"{league}: {error}")

    # Mettre à jour les simulations déjà terminées.
    matches_by_id = {
        str(match["id"]): match
        for match in all_matches
        if match.get("id") is not None
    }

    settle_bets(state, matches_by_id)

    today_string = today.isoformat()

    existing_today = {
        str(bet.get("match_id"))
        for bet in state["bets"]
        if bet.get("date") == today_string
    }

    candidates = []

    for league, matches in matches_by_league.items():

        for match in matches:

            if match.get("status") not in ("SCHEDULED", "TIMED"):
                continue

            # L'API renvoie les dates en UTC.
            match_date = (match.get("utcDate") or "")[:10]

            if match_date != today_string:
                continue

            match_id = str(match.get("id", ""))

            if not match_id or match_id in existing_today:
                continue

            home = match.get("homeTeam", {}).get("name", "")
            away = match.get("awayTeam", {}).get("name", "")

            if not home or not away:
                continue

            prediction = predict_match(
                matches,
                home,
                away,
            )

            prediction.update({
                "match_id": match_id,
                "league": league,
                "date": today_string,
                "utcDate": match.get("utcDate", ""),
            })

            # Éviter de sélectionner des matchs sans historique suffisant.
            if (
                prediction["probability"] >= PROBABILITE_MINIMUM
                and prediction["sample"] >= 2
            ):
                candidates.append(prediction)

    # Classer les choix selon leur probabilité estimée.
    candidates.sort(
        key=lambda item: (
            item["probability"],
            item["sample"],
        ),
        reverse=True,
    )

    new_bets = []

    for prediction in candidates[:MAX_PARIS_PAR_JOUR]:

        bankroll = float(state["bankroll"])

        if bankroll <= 0:
            break

        stake = round(
            min(
                MISE_MAXIMUM,
                max(0.10, bankroll * MISE_FRACTION),
            ),
            2,
        )

        prediction.update({
            "stake": stake,
            "settled": False,
            "result": "En attente",
            "virtual_odds": None,
            "settled_at": None,
        })

        state["bets"].append(prediction)

        new_bets.append(
            f'{prediction["home"]} - {prediction["away"]}: '
            f'{prediction["pick"]} '
            f'({prediction["probability"] * 100:.1f} %)'
        )

    state["day"] = datetime.now(timezone.utc).isoformat()

    if new_bets:
        state["message"] = (
            "Nouveaux paris virtuels : "
            + " | ".join(new_bets)
        )
    elif errors:
        state["message"] = (
            "Aucun nouveau pari virtuel. Erreurs API : "
            + " ; ".join(errors)
        )
    else:
        state["message"] = (
            "Aucun match ne respecte les critères de simulation aujourd'hui."
        )

    state["history"].append({
        "date": today_string,
        "bankroll": round(float(state["bankroll"]), 2),
        "bets_total": len(state["bets"]),
        "open_bets": sum(
            1 for bet in state["bets"]
            if not bet.get("settled")
        ),
    })

    state["history"] = state["history"][-180:]

    save_state(state)

    print(state["message"])


if __name__ == "__main__":
    main()