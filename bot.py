import os
import json
import math
import time
from datetime import datetime, timedelta, timezone

import requests

# ============================================================
# FOOT AI PRO BOT V3 CORRIGE
# Simulation virtuelle uniquement - aucun pari réel
# ============================================================

API_BASE = "https://api.football-data.org/v4"
STATE_FILE = "data/bankroll.json"

COMPETITIONS = {
    "Ligue 1": "FL1",
    "Premier League": "PL",
    "Liga": "PD",
    "Bundesliga": "BL1",
    "Serie A": "SA",
    "Ligue des Champions": "CL",
}

CAPITAL_INITIAL = 20.00
MISE_MAXIMUM = 1.00
MAX_PARIS_PAR_JOUR = 2
JOURS_A_VENIR = 3
JOURS_HISTORIQUE = 60

PROBA_PRUDENTE = 0.72
PROBA_RISQUEE = 0.50
FRACTION_PRUDENTE = 0.02
FRACTION_RISQUEE = 0.015

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "FOOT-AI-PRO/3.1"})


# ============================================================
# ÉTAT ET SAUVEGARDE
# ============================================================

def load_state():
    os.makedirs("data", exist_ok=True)

    if not os.path.exists(STATE_FILE):
        return {
            "starting_bankroll": CAPITAL_INITIAL,
            "bankroll": CAPITAL_INITIAL,
            "day": "",
            "bets": [],
            "history": [],
            "message": "Capital virtuel initialisé.",
        }

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)

        if not isinstance(state, dict):
            raise ValueError("Le fichier ne contient pas un objet JSON.")

        state.setdefault("starting_bankroll", CAPITAL_INITIAL)
        state.setdefault("bankroll", CAPITAL_INITIAL)
        state.setdefault("bets", [])
        state.setdefault("history", [])
        state.setdefault("message", "")
        state.setdefault("day", "")

        if not isinstance(state["bets"], list):
            state["bets"] = []

        if not isinstance(state["history"], list):
            state["history"] = []

        return state

    except (json.JSONDecodeError, OSError, ValueError) as exc:
        raise RuntimeError(
            "Impossible de lire data/bankroll.json. "
            "Le fichier n'a pas été modifié. "
            "Vérifie son contenu avant de continuer."
        ) from exc


def save_state(state):
    os.makedirs("data", exist_ok=True)
    temp = STATE_FILE + ".tmp"

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    os.replace(temp, STATE_FILE)


# ============================================================
# API FOOTBALL-DATA.ORG
# ============================================================

def get_matches(competition, date_from, date_to, api_key):
    url = f"{API_BASE}/competitions/{competition}/matches"

    try:
        response = SESSION.get(
            url,
            headers={"X-Auth-Token": api_key},
            params={
                "dateFrom": date_from,
                "dateTo": date_to,
            },
            timeout=25,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Erreur de connexion pour {competition}: {exc}"
        ) from exc

    if response.status_code == 429:
        raise RuntimeError(
            "Limite API atteinte (429). Réessaie plus tard."
        )

    if response.status_code == 403:
        raise RuntimeError(
            f"Accès refusé à {competition} (403). "
            "Vérifie les compétitions autorisées par ton abonnement."
        )

    if response.status_code == 401:
        raise RuntimeError(
            "Clé API refusée (401). Vérifie le secret "
            "FOOTBALL_DATA_API_KEY dans GitHub."
        )

    if response.status_code >= 500:
        raise RuntimeError(
            f"Serveur football-data.org indisponible "
            f"({response.status_code})."
        )

    response.raise_for_status()

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"Réponse API invalide pour {competition}."
        ) from exc

    return data.get("matches", [])


# ============================================================
# PROBABILITE DE POISSON
# ============================================================

def poisson(mean, goals):
    if mean <= 0:
        return 1.0 if goals == 0 else 0.0

    return math.exp(-mean) * mean ** goals / math.factorial(goals)


# ============================================================
# ANALYSE DES MATCHS
# ============================================================

def predict_match(matches, home_team, away_team):
    league_home = []
    league_away = []

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

        league_home.append(gh)
        league_away.append(ga)

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

    if not league_home:
        return None

    avg_home = sum(league_home) / len(league_home)
    avg_away = sum(league_away) / len(league_away)

    def average(values, fallback):
        return sum(values) / len(values) if values else fallback

    home_attack = average(home_scored, avg_home)
    home_defense = average(home_conceded, avg_away)
    away_attack = average(away_scored, avg_away)
    away_defense = average(away_conceded, avg_home)

    if len(home_scored) < 5:
        home_attack = (
            home_attack * len(home_scored) + avg_home * 5
        ) / (len(home_scored) + 5)

    if len(home_conceded) < 5:
        home_defense = (
            home_defense * len(home_conceded) + avg_away * 5
        ) / (len(home_conceded) + 5)

    if len(away_scored) < 5:
        away_attack = (
            away_attack * len(away_scored) + avg_away * 5
        ) / (len(away_scored) + 5)

    if len(away_conceded) < 5:
        away_defense = (
            away_defense * len(away_conceded) + avg_home * 5
        ) / (len(away_conceded) + 5)

    lambda_home = max(
        0.20,
        min(3.40, 0.55 * home_attack + 0.45 * away_defense),
    )

    lambda_away = max(
        0.20,
        min(3.40, 0.55 * away_attack + 0.45 * home_defense),
    )

    scores = {}

    for h in range(9):
        for a in range(9):
            scores[(h, a)] = (
                poisson(lambda_home, h)
                * poisson(lambda_away, a)
            )

    total = sum(scores.values())

    if total <= 0:
        return None

    def probability(condition):
        return sum(
            p for (h, a), p in scores.items()
            if condition(h, a)
        ) / total

    markets = {
        "Plus de 1,5 but": probability(lambda h, a: h + a >= 2),
        "Plus de 2,5 buts": probability(lambda h, a: h + a >= 3),
        "Moins de 2,5 buts": probability(lambda h, a: h + a <= 2),
        "Moins de 3,5 buts": probability(lambda h, a: h + a <= 3),
        "Les deux équipes marquent : oui": probability(
            lambda h, a: h > 0 and a > 0
        ),
        "Les deux équipes marquent : non": probability(
            lambda h, a: h == 0 or a == 0
        ),
        "Victoire domicile": probability(lambda h, a: h > a),
        "Match nul": probability(lambda h, a: h == a),
        "Victoire extérieur": probability(lambda h, a: h < a),
        "Double chance 1X": probability(lambda h, a: h >= a),
        "Double chance X2": probability(lambda h, a: a >= h),
    }

    exact_score = max(scores, key=scores.get)

    sample = min(len(home_scored), len(away_scored))

    return {
        "home": home_team,
        "away": away_team,
        "markets": {
            name: round(value, 4)
            for name, value in markets.items()
        },
        "score": f"{exact_score[0]}-{exact_score[1]}",
        "lambda_home": round(lambda_home, 3),
        "lambda_away": round(lambda_away, 3),
        "sample": sample,
    }


# ============================================================
# SELECTION DES MARCHES
# ============================================================

def select_pick(prediction, used_markets):
    allowed = []

    for name, probability in prediction["markets"].items():
        if name in used_markets:
            continue

        if probability < PROBA_RISQUEE:
            continue

        if probability >= 0.91:
            continue

        allowed.append((name, probability))

    if not allowed:
        return None

    allowed.sort(key=lambda item: item[1], reverse=True)
    return allowed[0]


def choose_strategy(probability, sample):
    if probability >= PROBA_PRUDENTE and sample >= 4:
        return "Prudent"

    if probability >= PROBA_RISQUEE and sample >= 2:
        return "Risqué"

    return None


def calculate_stake(bankroll, strategy):
    if bankroll <= 0:
        return 0.0

    fraction = (
        FRACTION_PRUDENTE
        if strategy == "Prudent"
        else FRACTION_RISQUEE
    )

    return round(min(MISE_MAXIMUM, bankroll * fraction), 2)


# ============================================================
# REGLEMENT DES PARIS VIRTUELS
# ============================================================

def evaluate_pick(pick, home, away):
    total = home + away

    rules = {
        "Plus de 1,5 but": total >= 2,
        "Plus de 2,5 buts": total >= 3,
        "Moins de 2,5 buts": total <= 2,
        "Moins de 3,5 buts": total <= 3,
        "Les deux équipes marquent : oui": home > 0 and away > 0,
        "Les deux équipes marquent : non": home == 0 or away == 0,
        "Victoire domicile": home > away,
        "Match nul": home == away,
        "Victoire extérieur": home < away,
        "Double chance 1X": home >= away,
        "Double chance X2": away >= home,
    }

    return rules.get(pick)


def settle_bets(state, matches_by_id):
    for bet in state["bets"]:
        if bet.get("settled"):
            continue

        match = matches_by_id.get(str(bet.get("match_id")))

        if not match or match.get("status") not in ("FINISHED", "AWARDED"):
            continue

        score = match.get("score", {}).get("fullTime", {})
        home_goals = score.get("home")
        away_goals = score.get("away")

        if home_goals is None or away_goals is None:
            continue

        won = evaluate_pick(bet.get("pick", ""), home_goals, away_goals)

        if won is None:
            continue

        stake = float(bet.get("stake", 0))
        probability = max(
            0.05,
            min(0.95, float(bet.get("probability", 0.5))),
        )

        virtual_odds = round(0.92 / probability, 2)
        profit = (
            round(stake * (virtual_odds - 1), 2)
            if won else round(-stake, 2)
        )

        state["bankroll"] = round(
            max(0.0, float(state["bankroll"]) + profit), 2
        )

        bet.update({
            "settled": True,
            "result": "Gagné" if won else "Perdu",
            "score_final": f"{home_goals}-{away_goals}",
            "virtual_odds": virtual_odds,
            "profit": profit,
            "settled_at": datetime.now(timezone.utc).isoformat(),
        })


# ============================================================
# HISTORIQUE QUOTIDIEN
# ============================================================

def update_daily_history(state, today):
    settled = [bet for bet in state["bets"] if bet.get("settled")]

    wins = sum(1 for bet in settled if bet.get("result") == "Gagné")
    losses = sum(1 for bet in settled if bet.get("result") == "Perdu")
    profit = round(
        sum(float(bet.get("profit") or 0) for bet in settled), 2
    )

    state["stats"] = {
        "wins": wins,
        "losses": losses,
        "settled": len(settled),
        "win_rate": round(100 * wins / len(settled), 2)
        if settled else 0.0,
        "profit": profit,
        "bankroll": round(float(state["bankroll"]), 2),
    }

    entry = {
        "date": today,
        "bankroll": round(float(state["bankroll"]), 2),
        "bets_total": len(state["bets"]),
        "open_bets": sum(
            1 for bet in state["bets"] if not bet.get("settled")
        ),
        "wins": wins,
        "losses": losses,
        "profit": profit,
    }

    history = [
        item for item in state["history"]
        if item.get("date") != today
    ]
    history.append(entry)
    history.sort(key=lambda item: item.get("date", ""))
    state["history"] = history[-180:]


# ============================================================
# EXECUTION PRINCIPALE
# ============================================================

def main():
    api_key = os.getenv("FOOTBALL_DATA_API_KEY", "").strip()

    if not api_key:
        raise SystemExit(
            "Clé API absente. Vérifie le secret "
            "FOOTBALL_DATA_API_KEY dans GitHub Actions."
        )

    state = load_state()
    now = datetime.now(timezone.utc)
    today = now.date()

    date_from = (today - timedelta(days=JOURS_HISTORIQUE)).isoformat()
    date_to = (today + timedelta(days=JOURS_A_VENIR)).isoformat()

    all_matches = []
    errors = []

    # Limiter les appels et respecter les quotas de l'API.
    for index, (league, code) in enumerate(COMPETITIONS.items()):
        if index:
            time.sleep(6)

        try:
            matches = get_matches(code, date_from, date_to, api_key)

            for match in matches:
                match["_league_name"] = league

            all_matches.extend(matches)

        except (requests.RequestException, RuntimeError) as error:
            errors.append(f"{league}: {error}")
            print(f"AVERTISSEMENT {league}: {error}")

    matches_by_id = {
        str(match["id"]): match
        for match in all_matches
        if match.get("id") is not None
    }

    settle_bets(state, matches_by_id)

    existing_match_ids = {
        str(bet.get("match_id")) for bet in state["bets"]
    }

    today_string = today.isoformat()

    bets_today = [
        bet for bet in state["bets"]
        if bet.get("created_day") == today_string
    ]

    remaining_slots = max(
        0, MAX_PARIS_PAR_JOUR - len(bets_today)
    )

    used_markets = {bet.get("pick") for bet in bets_today}
    candidates = []

    for match in matches_by_id.values():
        if match.get("status") not in ("SCHEDULED", "TIMED"):
            continue

        utc_date = match.get("utcDate", "")

        try:
            match_datetime = datetime.fromisoformat(
                utc_date.replace("Z", "+00:00")
            )
        except (ValueError, AttributeError):
            continue

        match_day = match_datetime.date()

        if not (today <= match_day <= today + timedelta(days=JOURS_A_VENIR)):
            continue

        match_id = str(match.get("id", ""))

        if not match_id or match_id in existing_match_ids:
            continue

        home = match.get("homeTeam", {}).get("name", "")
        away = match.get("awayTeam", {}).get("name", "")

        if not home or not away:
            continue

        league = match.get("_league_name", "")
        league_matches = [
            item for item in all_matches
            if item.get("_league_name") == league
        ]

        prediction = predict_match(league_matches, home, away)

        if not prediction:
            continue

        selected = select_pick(prediction, used_markets)

        if selected is None:
            selected = select_pick(prediction, set())

        if selected is None:
            continue

        pick, probability = selected
        strategy = choose_strategy(probability, prediction["sample"])

        if strategy is None:
            continue

        prediction.update({
            "match_id": match_id,
            "league": league,
            "date": match_day.isoformat(),
            "utcDate": utc_date,
            "pick": pick,
            "probability": probability,
            "strategy": strategy,
        })

        candidates.append(prediction)

    candidates.sort(
        key=lambda item: (
            item["strategy"] == "Prudent",
            item["probability"],
            item["sample"],
        ),
        reverse=True,
    )

    new_bets = []

    for prediction in candidates[:remaining_slots]:
        stake = calculate_stake(
            float(state["bankroll"]),
            prediction["strategy"],
        )

        if stake <= 0:
            break

        bet = {
            "home": prediction["home"],
            "away": prediction["away"],
            "pick": prediction["pick"],
            "probability": prediction["probability"],
            "sample": prediction["sample"],
            "score": prediction["score"],
            "lambda_home": prediction["lambda_home"],
            "lambda_away": prediction["lambda_away"],
            "match_id": prediction["match_id"],
            "league": prediction["league"],
            "date": prediction["date"],
            "utcDate": prediction["utcDate"],
            "strategy": prediction["strategy"],
            "stake": stake,
            "settled": False,
            "result": "En attente",
            "virtual_odds": None,
            "profit": None,
            "created_day": today_string,
            "settled_at": None,
        }

        state["bets"].append(bet)
        existing_match_ids.add(str(bet["match_id"]))
        used_markets.add(bet["pick"])

        new_bets.append(
            f'{bet["home"]} - {bet["away"]}: {bet["pick"]} '
            f'({bet["probability"] * 100:.1f} %, '
            f'{bet["strategy"]}, mise {stake:.2f} €)'
        )

    state["day"] = now.isoformat()

    if new_bets:
        state["message"] = (
            "Nouveaux paris virtuels : " + " | ".join(new_bets)
        )
    elif errors:
        state["message"] = "Erreurs API : " + " ; ".join(errors)
    else:
        state["message"] = (
            "Aucun nouveau pari ne correspond aux critères. "
            "Les paris existants ont été mis à jour."
        )

    update_daily_history(state, today_string)
    save_state(state)

    print(state["message"])
    print("Capital virtuel :", state["bankroll"], "€")
    print("Paris enregistrés :", len(state["bets"]))
    print("Statistiques :", json.dumps(state["stats"], ensure_ascii=False))


if __name__ == "__main__":
    main()