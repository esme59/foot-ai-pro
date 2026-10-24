import os
import json
import math
from datetime import date, datetime, timedelta, timezone

import requests

# ============================================================
# FOOT AI PRO BOT V2
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
MISE_MINIMUM = 0.10
MAX_PARIS_PAR_JOUR = 2

# Stratégie mixte : prudent et plus risqué.
PROBA_PRUDENTE = 0.68
PROBA_RISQUEE = 0.48

# Mise limitée à 2 % du capital pour la stratégie prudente.
FRACTION_PRUDENTE = 0.02

# La stratégie risquée n'a pas de mise supérieure.
FRACTION_RISQUEE = 0.015

JOURS_A_VENIR = 3
JOURS_HISTORIQUE = 60


# ============================================================
# ÉTAT DU CAPITAL
# ============================================================

def load_state():
    os.makedirs("data", exist_ok=True)

    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as file:
                state = json.load(file)

            state.setdefault("starting_bankroll", CAPITAL_INITIAL)
            state.setdefault("bankroll", CAPITAL_INITIAL)
            state.setdefault("bets", [])
            state.setdefault("history", [])
            state.setdefault("message", "")
            state.setdefault("day", "")

            return state

        except (json.JSONDecodeError, OSError):
            raise RuntimeError(
                "Impossible de lire data/bankroll.json. "
                "Sauvegarde le fichier avant de le réparer."
            )

    return {
        "starting_bankroll": CAPITAL_INITIAL,
        "bankroll": CAPITAL_INITIAL,
        "day": "",
        "bets": [],
        "history": [],
        "message": "Capital virtuel initialisé.",
    }


def save_state(state):
    os.makedirs("data", exist_ok=True)

    temporary_file = STATE_FILE + ".tmp"

    with open(temporary_file, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)

    os.replace(temporary_file, STATE_FILE)


# ============================================================
# API FOOTBALL-DATA.ORG
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
        raise RuntimeError("Limite de requêtes API atteinte.")

    if response.status_code == 403:
        raise RuntimeError(
            f"Accès refusé pour {competition}. "
            "Vérifie les compétitions autorisées par ton abonnement."
        )

    response.raise_for_status()

    return response.json().get("matches", [])


# ============================================================
# POISSON
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
# ANALYSE D'UN MATCH
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

    home_attack = (
        sum(home_scored) / len(home_scored)
        if home_scored else avg_home
    )
    home_defense = (
        sum(home_conceded) / len(home_conceded)
        if home_conceded else avg_away
    )
    away_attack = (
        sum(away_scored) / len(away_scored)
        if away_scored else avg_away
    )
    away_defense = (
        sum(away_conceded) / len(away_conceded)
        if away_conceded else avg_home
    )

    # Réduire l'effet d'un historique trop court.
    if len(home_scored) < 3:
        home_attack = (home_attack + avg_home) / 2
        home_defense = (home_defense + avg_away) / 2

    if len(away_scored) < 3:
        away_attack = (away_attack + avg_away) / 2
        away_defense = (away_defense + avg_home) / 2

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
            scores[(h, a)] = poisson(
                lambda_home, h
            ) * poisson(lambda_away, a)

    total = sum(scores.values())

    if total <= 0:
        return None

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

    p_under35 = sum(
        p for (h, a), p in scores.items() if h + a <= 3
    ) / total

    p_btts = sum(
        p for (h, a), p in scores.items() if h > 0 and a > 0
    ) / total

    p_double_home = p_home + p_draw
    p_double_away = p_away + p_draw

    markets = [
        ("Plus de 1,5 but", p_over15),
        ("Plus de 2,5 buts", p_over25),
        ("Moins de 3,5 buts", p_under35),
        ("Les deux équipes marquent : oui", p_btts),
        ("Victoire domicile", p_home),
        ("Match nul", p_draw),
        ("Victoire extérieur", p_away),
        ("Double chance 1X", p_double_home),
        ("Double chance X2", p_double_away),
    ]

    # Éviter les marchés incompatibles avec le résultat réel.
    best_market, best_probability = max(
        markets,
        key=lambda item: item[1],
    )

    exact_score = max(scores, key=scores.get)

    sample = min(len(home_scored), len(away_scored))

    return {
        "home": home_team,
        "away": away_team,
        "pick": best_market,
        "probability": round(best_probability, 4),
        "sample": sample,
        "score": f"{exact_score[0]}-{exact_score[1]}",
        "lambda_home": round(lambda_home, 3),
        "lambda_away": round(lambda_away, 3),
    }


# ============================================================
# ÉVALUATION DES PARIS TERMINÉS
# ============================================================

def evaluate_pick(pick, home_goals, away_goals):
    total_goals = home_goals + away_goals

    if pick == "Plus de 1,5 but":
        return total_goals >= 2

    if pick == "Plus de 2,5 buts":
        return total_goals >= 3

    if pick == "Moins de 3,5 buts":
        return total_goals <= 3

    if pick == "Les deux équipes marquent : oui":
        return home_goals > 0 and away_goals > 0

    if pick == "Victoire domicile":
        return home_goals > away_goals

    if pick == "Match nul":
        return home_goals == away_goals

    if pick == "Victoire extérieur":
        return home_goals < away_goals

    if pick == "Double chance 1X":
        return home_goals >= away_goals

    if pick == "Double chance X2":
        return away_goals >= home_goals

    return None


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

        won = evaluate_pick(
            bet.get("pick", ""),
            home_goals,
            away_goals,
        )

        if won is None:
            continue

        stake = float(bet["stake"])
        probability = max(
            0.01,
            min(0.99, float(bet["probability"])),
        )

        # Cote simulée théorique : ce n'est pas une cote réelle.
        virtual_odds = round(0.92 / probability, 2)

        if won:
            profit = round(stake * (virtual_odds - 1), 2)
        else:
            profit = round(-stake, 2)

        state["bankroll"] = round(
            max(0.0, float(state["bankroll"]) + profit),
            2,
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
# STRATÉGIE MIXTE
# ============================================================

def choose_strategy(prediction):
    probability = prediction["probability"]

    if probability >= PROBA_PRUDENTE and prediction["sample"] >= 3:
        return "Prudent"

    if probability >= PROBA_RISQUEE and prediction["sample"] >= 2:
        return "Risqué"

    return None


def calculate_stake(bankroll, strategy):
    if bankroll <= 0:
        return 0.0

    if strategy == "Prudent":
        fraction = FRACTION_PRUDENTE
    else:
        fraction = FRACTION_RISQUEE

    stake = min(
        MISE_MAXIMUM,
        bankroll * fraction,
    )

    # Ne jamais dépasser le capital disponible.
    stake = min(stake, bankroll)

    return round(stake, 2)


# ============================================================
# EXÉCUTION AUTOMATIQUE
# ============================================================

def main():
    api_key = os.getenv("FOOTBALL_DATA_API_KEY", "").strip()

    if not api_key:
        raise SystemExit(
            "Clé API absente : configure FOOTBALL_DATA_API_KEY "
            "dans les secrets GitHub Actions."
        )

    state = load_state()

    now_utc = datetime.now(timezone.utc)
    today_utc = now_utc.date()

    date_from = (
        today_utc - timedelta(days=JOURS_HISTORIQUE)
    ).isoformat()

    date_to = (
        today_utc + timedelta(days=JOURS_A_VENIR)
    ).isoformat()

    all_matches = []
    errors = []

    # Une requête par compétition.
    for league, code in COMPETITIONS.items():
        try:
            matches = get_matches(
                code,
                date_from,
                date_to,
                api_key,
            )

            for match in matches:
                match["_league_name"] = league

            all_matches.extend(matches)

        except Exception as error:
            errors.append(f"{league}: {error}")

    # Un match peut apparaître dans plusieurs réponses.
    matches_by_id = {
        str(match["id"]): match
        for match in all_matches
        if match.get("id") is not None
    }

    # Mettre à jour les paris déjà ouverts.
    settle_bets(state, matches_by_id)

    existing_match_ids = {
        str(bet.get("match_id"))
        for bet in state["bets"]
    }

    # Un seul pari par match.
    candidates = []

    for match in matches_by_id.values():
        if match.get("status") not in ("SCHEDULED", "TIMED"):
            continue

        utc_date = match.get("utcDate", "")

        if not utc_date:
            continue

        try:
            match_datetime = datetime.fromisoformat(
                utc_date.replace("Z", "+00:00")
            )
        except ValueError:
            continue

        match_day = match_datetime.date()

        # Aujourd'hui et les trois prochains jours.
        if not (today_utc <= match_day <= today_utc + timedelta(days=3)):
            continue

        match_id = str(match.get("id", ""))

        if not match_id or match_id in existing_match_ids:
            continue

        home = match.get("homeTeam", {}).get("name", "")
        away = match.get("awayTeam", {}).get("name", "")

        if not home or not away:
            continue

        league_name = match.get("_league_name", "")

        league_matches = [
            item for item in all_matches
            if item.get("_league_name") == league_name
        ]

        prediction = predict_match(
            league_matches,
            home,
            away,
        )

        if prediction is None:
            continue

        strategy = choose_strategy(prediction)

        if strategy is None:
            continue

        prediction.update({
            "match_id": match_id,
            "league": league_name,
            "date": match_day.isoformat(),
            "utcDate": utc_date,
            "strategy": strategy,
        })

        candidates.append(prediction)

    # Priorité aux meilleures probabilités estimées.
    candidates.sort(
        key=lambda item: (
            item["probability"],
            item["sample"],
        ),
        reverse=True,
    )

    # Ne pas dépasser le quota quotidien, même si le bot
    # est lancé plusieurs fois dans la même journée.
    today_string = today_utc.isoformat()

    bets_today = [
        bet for bet in state["bets"]
        if bet.get("created_day") == today_string
    ]

    remaining_slots = max(
        0,
        MAX_PARIS_PAR_JOUR - len(bets_today),
    )

    new_bets = []

    for prediction in candidates[:remaining_slots]:
        bankroll = float(state["bankroll"])

        strategy = prediction["strategy"]
        stake = calculate_stake(bankroll, strategy)

        if stake <= 0:
            break

        prediction.update({
            "stake": stake,
            "settled": False,
            "result": "En attente",
            "virtual_odds": None,
            "profit": None,
            "created_day": today_string,
            "settled_at": None,
        })

        state["bets"].append(prediction)

        new_bets.append(
            f'{prediction["home"]} - {prediction["away"]}: '
            f'{prediction["pick"]} '
            f'({prediction["probability"] * 100:.1f} %, '
            f'{strategy}, mise {stake:.2f} €)'
        )

    state["day"] = now_utc.isoformat()

    if new_bets:
        state["message"] = (
            "Nouveaux paris virtuels : " + " | ".join(new_bets)
        )
    elif errors:
        state["message"] = (
            "Aucun nouveau pari. Erreurs API : " + " ; ".join(errors)
        )
    else:
        state["message"] = (
            "Aucun nouveau pari ne correspond aux critères "
            "de la stratégie mixte."
        )

    settled_bets = [
        bet for bet in state["bets"]
        if bet.get("settled")
    ]

    wins = sum(
        1 for bet in settled_bets
        if bet.get("result") == "Gagné"
    )

    losses = sum(
        1 for bet in settled_bets
        if bet.get("result") == "Perdu"
    )

    total_profit = round(
        sum(float(bet.get("profit") or 0) for bet in settled_bets),
        2,
    )

    state["stats"] = {
        "wins": wins,
        "losses": losses,
        "settled": len(settled_bets),
        "win_rate": round(
            100 * wins / len(settled_bets), 2
        ) if settled_bets else 0.0,
        "profit": total_profit,
        "bankroll": round(float(state["bankroll"]), 2),
    }

    state["history"].append({
        "date": today_string,
        "bankroll": round(float(state["bankroll"]), 2),
        "bets_total": len(state["bets"]),
        "open_bets": sum(
            1 for bet in state["bets"]
            if not bet.get("settled")
        ),
        "wins": wins,
        "losses": losses,
        "profit": total_profit,
    })

    state["history"] = state["history"][-180:]

    save_state(state)

    print(state["message"])
    print("Capital virtuel :", state["bankroll"], "€")
    print("Paris enregistrés :", len(state["bets"]))
    print("Paris réglés :", len(settled_bets))
    print("Gagnés :", wins, "| Perdus :", losses)
    print("Taux de réussite :", state["stats"]["win_rate"], "%")
    print("Bénéfice/perte cumulé :", total_profit, "€")


if __name__ == "__main__":
    main()