import os
import json
import math
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone

import requests


# ============================================================
# FOOT AI PRO BOT V7
# Simulation virtuelle uniquement : aucun pari réel.
# API : football-data.org v4
# Compatible avec GitHub Actions.
# ============================================================

API_BASE = "https://api.football-data.org/v4"

STATE_FILE = Path("data/bankroll.json")

INITIAL_BANKROLL = 20.0
MAX_STAKE = 1.0
MAX_NEW_BETS_PER_DAY = 2

LOOKBACK_DAYS = 60
FORECAST_DAYS = 3

# Date limite pour créer de nouveaux paris virtuels.
BET_CUTOFF_DATE = "2026-10-25"

COMPETITIONS = {
    "FL1": "Ligue 1",
    "PL": "Premier League",
    "PD": "Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "CL": "Ligue des champions",
}

REQUEST_TIMEOUT = 25
API_DELAY_SECONDS = 0.3

MAX_GOALS = 8

HEADERS = {
    "User-Agent": "FOOT-AI-PRO-V7-Virtual-Simulation"
}


# ============================================================
# OUTILS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def utc_date():
    return utc_now().date().isoformat()


def round_money(value):
    return round(float(value), 2)


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_datetime(value):
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)

    except (ValueError, TypeError):
        return None


def parse_date(value):
    try:
        return datetime.strptime(
            value,
            "%Y-%m-%d"
        ).date()
    except (ValueError, TypeError):
        return None


def log(message):
    print(
        f"[{utc_now().strftime('%Y-%m-%d %H:%M:%S UTC')}] "
        f"{message}",
        flush=True
    )


# ============================================================
# GESTION DE LA CLÉ API
# ============================================================

def get_api_key():
    possible_names = [
        "FOOTBALL_DATA_API_KEY",
        "FOOTBALL_API_KEY",
        "FOOTBALL_DATA_TOKEN",
    ]

    for name in possible_names:
        value = os.environ.get(name, "").strip()

        if value:
            return value

    return None


# ============================================================
# API FOOTBALL-DATA.ORG
# ============================================================

def api_get(endpoint, params=None):
    api_key = get_api_key()

    if not api_key:
        raise RuntimeError(
            "Clé API manquante. Configure "
            "FOOTBALL_DATA_API_KEY dans GitHub Secrets."
        )

    url = f"{API_BASE}/{endpoint.lstrip('/')}"

    headers = {
        **HEADERS,
        "X-Auth-Token": api_key,
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            params=params or {},
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 429:
            log(
                "Limite API atteinte. "
                "Arrêt des nouvelles requêtes."
            )
            return None

        if response.status_code in (401, 403):
            log(
                "Accès API refusé : "
                f"HTTP {response.status_code}. "
                "Vérifie la clé et les compétitions autorisées."
            )
            return None

        if response.status_code == 404:
            log(f"Ressource API introuvable : {endpoint}")
            return None

        response.raise_for_status()

        return response.json()

    except requests.RequestException as exc:
        log(f"Erreur de connexion API : {exc}")
        return None


# ============================================================
# BANQUE VIRTUELLE ET SAUVEGARDE
# ============================================================

def default_state():
    return {
        "version": 7,
        "bankroll": INITIAL_BANKROLL,
        "initial_bankroll": INITIAL_BANKROLL,
        "bets": [],
        "history": [],
        "created_at": utc_now().isoformat(),
        "updated_at": utc_now().isoformat(),
    }


def load_state():
    STATE_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    if not STATE_FILE.exists():
        state = default_state()
        save_state(state)

        log("Nouvelle bankroll virtuelle de 20 € créée.")

        return state

    try:
        with STATE_FILE.open("r", encoding="utf-8") as file:
            state = json.load(file)

        if not isinstance(state, dict):
            raise ValueError("Format JSON invalide.")

        state.setdefault("version", 7)
        state.setdefault("initial_bankroll", INITIAL_BANKROLL)
        state.setdefault("bets", [])
        state.setdefault("history", [])
        state.setdefault("created_at", utc_now().isoformat())

        if not isinstance(state["bets"], list):
            state["bets"] = []

        if not isinstance(state["history"], list):
            state["history"] = []

        if "bankroll" not in state:
            state["bankroll"] = INITIAL_BANKROLL

        state["bankroll"] = round_money(
            safe_float(state["bankroll"], INITIAL_BANKROLL)
        )

        return state

    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            "Impossible de lire data/bankroll.json. "
            "Le fichier n'a pas été remplacé automatiquement "
            f"pour éviter de perdre tes données : {exc}"
        ) from exc


def save_state(state):
    STATE_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    state["updated_at"] = utc_now().isoformat()

    temporary_file = STATE_FILE.with_suffix(".tmp")

    with temporary_file.open("w", encoding="utf-8") as file:
        json.dump(
            state,
            file,
            indent=2,
            ensure_ascii=False
        )

    temporary_file.replace(STATE_FILE)


# ============================================================
# STATISTIQUES ET MODÈLE DE POISSON
# ============================================================

def poisson_probability(lam, goals):
    if lam <= 0:
        return 1.0 if goals == 0 else 0.0

    try:
        return (
            math.exp(-lam)
            * (lam ** goals)
            / math.factorial(goals)
        )
    except (OverflowError, ValueError):
        return 0.0


def get_team_statistics(matches, team_id):
    goals_for = []
    goals_against = []

    for match in matches:
        if match.get("status") != "FINISHED":
            continue

        home = match.get("homeTeam") or {}
        away = match.get("awayTeam") or {}
        score = match.get("score") or {}
        full_time = score.get("fullTime") or {}

        home_goals = full_time.get("home")
        away_goals = full_time.get("away")

        if home_goals is None or away_goals is None:
            continue

        if home.get("id") == team_id:
            goals_for.append(float(home_goals))
            goals_against.append(float(away_goals))

        elif away.get("id") == team_id:
            goals_for.append(float(away_goals))
            goals_against.append(float(home_goals))

    if not goals_for:
        return {
            "matches": 0,
            "scored": 1.25,
            "conceded": 1.25,
        }

    return {
        "matches": len(goals_for),
        "scored": sum(goals_for) / len(goals_for),
        "conceded": sum(goals_against) / len(goals_against),
    }


def estimate_goals(home_stats, away_stats):
    home_scoring = home_stats["scored"]
    away_defending = away_stats["conceded"]

    away_scoring = away_stats["scored"]
    home_defending = home_stats["conceded"]

    # Pondération simple des buts marqués et encaissés.
    home_lambda = (
        0.55 * home_scoring
        + 0.45 * away_defending
        + 0.15
    )

    away_lambda = (
        0.55 * away_scoring
        + 0.45 * home_defending
    )

    home_lambda = max(0.15, min(home_lambda, 4.0))
    away_lambda = max(0.15, min(away_lambda, 4.0))

    return home_lambda, away_lambda


def analyze_match(home_stats, away_stats):
    home_lambda, away_lambda = estimate_goals(
        home_stats,
        away_stats
    )

    home_win = 0.0
    draw = 0.0
    away_win = 0.0

    over_15 = 0.0
    over_25 = 0.0
    btts_yes = 0.0

    best_score = (0, 0)
    best_score_probability = 0.0

    for home_goals in range(MAX_GOALS + 1):
        home_probability = poisson_probability(
            home_lambda,
            home_goals
        )

        for away_goals in range(MAX_GOALS + 1):
            away_probability = poisson_probability(
                away_lambda,
                away_goals
            )

            probability = (
                home_probability * away_probability
            )

            if home_goals > away_goals:
                home_win += probability

            elif home_goals == away_goals:
                draw += probability

            else:
                away_win += probability

            total_goals = home_goals + away_goals

            if total_goals >= 2:
                over_15 += probability

            if total_goals >= 3:
                over_25 += probability

            if home_goals > 0 and away_goals > 0:
                btts_yes += probability

            if probability > best_score_probability:
                best_score_probability = probability

                best_score = (
                    home_goals,
                    away_goals
                )

    # La somme est légèrement inférieure à 1 car
    # le calcul est limité à huit buts par équipe.

    return {
        "home_win": home_win,
        "draw": draw,
        "away_win": away_win,
        "over_15": over_15,
        "over_25": over_25,
        "under_25": 1.0 - over_25,
        "btts_yes": btts_yes,
        "btts_no": 1.0 - btts_yes,
        "home_or_draw": home_win + draw,
        "away_or_draw": away_win + draw,
        "exact_score": (
            f"{best_score[0]}-{best_score[1]}"
        ),
        "home_lambda": home_lambda,
        "away_lambda": away_lambda,
    }


# ============================================================
# CHOIX DU PRONOSTIC VIRTUEL
# ============================================================

def select_prediction(analysis):
    markets = [
        ("1", analysis["home_win"]),
        ("N", analysis["draw"]),
        ("2", analysis["away_win"]),
        ("1X", analysis["home_or_draw"]),
        ("X2", analysis["away_or_draw"]),
        ("Over 1.5", analysis["over_15"]),
        ("Over 2.5", analysis["over_25"]),
        ("Under 2.5", analysis["under_25"]),
        ("BTTS Oui", analysis["btts_yes"]),
        ("BTTS Non", analysis["btts_no"]),
    ]

    # Filtre minimum pour éviter les pronostics
    # dont la probabilité calculée est trop faible.
    candidates = [
        item for item in markets
        if item[1] >= 0.60
    ]

    if not candidates:
        return None

    # Le marché le plus probable est sélectionné.
    # Les probabilités ne constituent pas une garantie.
    market, probability = max(
        candidates,
        key=lambda item: item[1]
    )

    # Cote théorique avec marge de prudence.
    estimated_odds = 0.90 / probability

    estimated_odds = max(
        1.10,
        min(estimated_odds, 3.00)
    )

    return {
        "market": market,
        "probability": round(probability, 4),
        "odds": round(estimated_odds, 2),
        "exact_score": analysis["exact_score"],
    }


# ============================================================
# HISTORIQUE DES MATCHS
# ============================================================

def fetch_competition_matches(competition_code):
    today = utc_now().date()

    date_from = today - timedelta(
        days=LOOKBACK_DAYS
    )

    date_to = today + timedelta(
        days=FORECAST_DAYS
    )

    payload = api_get(
        f"competitions/{competition_code}/matches",
        params={
            "dateFrom": date_from.isoformat(),
            "dateTo": date_to.isoformat(),
        },
    )

    if not payload:
        return []

    matches = payload.get("matches", [])

    if not isinstance(matches, list):
        return []

    return matches


# ============================================================
# IDENTIFICATION DES PARIS
# ============================================================

def make_bet_id(match_id, market):
    return f"{match_id}:{market}"


def get_existing_bet_ids(state):
    existing = set()

    for bet in state["bets"]:
        match_id = bet.get("match_id")
        market = bet.get("market")

        if match_id is not None and market:
            existing.add(
                make_bet_id(match_id, market)
            )

    return existing


def count_bets_today(state):
    today = utc_date()
    count = 0

    for bet in state["bets"]:
        if bet.get("created_date") == today:
            count += 1

    return count


# ============================================================
# CRÉATION DES PARIS VIRTUELS
# ============================================================

def create_virtual_bet(
    state,
    match,
    competition_code,
    prediction,
):
    if prediction is None:
        return False

    match_id = match.get("id")

    if match_id is None:
        return False

    existing_ids = get_existing_bet_ids(state)

    bet_id = make_bet_id(
        match_id,
        prediction["market"]
    )

    if bet_id in existing_ids:
        return False

    if count_bets_today(state) >= MAX_NEW_BETS_PER_DAY:
        return False

    match_date = parse_datetime(
        match.get("utcDate")
    )

    if match_date is None:
        return False

    if match_date <= utc_now():
        return False

    cutoff = parse_date(BET_CUTOFF_DATE)

    if cutoff and match_date.date() > cutoff:
        return False

    stake = min(
        MAX_STAKE,
        safe_float(state.get("bankroll"))
    )

    if stake <= 0:
        log("Capital virtuel insuffisant.")
        return False

    home_team = (
        match.get("homeTeam") or {}
    ).get("name", "Équipe domicile")

    away_team = (
        match.get("awayTeam") or {}
    ).get("name", "Équipe extérieure")

    bet = {
        "bet_id": bet_id,
        "match_id": match_id,
        "competition": competition_code,
        "competition_name": COMPETITIONS.get(
            competition_code,
            competition_code
        ),
        "home_team": home_team,
        "away_team": away_team,
        "match_date": match_date.isoformat(),
        "created_date": utc_date(),
        "market": prediction["market"],
        "probability": prediction["probability"],
        "odds": prediction["odds"],
        "exact_score_prediction": prediction["exact_score"],
        "stake": round_money(stake),
        "potential_return": round_money(
            stake * prediction["odds"]
        ),
        "profit": 0.0,
        "status": "PENDING",
        "result": None,
    }

    state["bets"].append(bet)

    log(
        f"PARI VIRTUEL CRÉÉ : {home_team} - {away_team} | "
        f"{prediction['market']} | "
        f"Probabilité : {prediction['probability']:.1%} | "
        f"Mise : {stake:.2f} €"
    )

    return True


# ============================================================
# RÈGLEMENT AUTOMATIQUE DES PARIS
# ============================================================

def evaluate_market(bet, home_goals, away_goals):
    market = bet.get("market")

    total_goals = home_goals + away_goals

    if market == "1":
        return home_goals > away_goals

    if market == "N":
        return home_goals == away_goals

    if market == "2":
        return away_goals > home_goals

    if market == "1X":
        return home_goals >= away_goals

    if market == "X2":
        return away_goals >= home_goals

    if market == "Over 1.5":
        return total_goals >= 2

    if market == "Over 2.5":
        return total_goals >= 3

    if market == "Under 2.5":
        return total_goals <= 2

    if market == "BTTS Oui":
        return home_goals > 0 and away_goals > 0

    if market == "BTTS Non":
        return home_goals == 0 or away_goals == 0

    return None


def settle_bet(state, bet, home_goals, away_goals):
    if bet.get("status") != "PENDING":
        return False

    won = evaluate_market(
        bet,
        home_goals,
        away_goals
    )

    if won is None:
        log(
            f"Marché non reconnu pour "
            f"{bet.get('bet_id')}. "
            "Paris conservé en attente."
        )
        return False

    stake = safe_float(bet.get("stake"))
    odds = safe_float(bet.get("odds"))

    if won:
        returned_amount = round_money(
            stake * odds
        )

        profit = round_money(
            returned_amount - stake
        )

        bet["status"] = "WON"
        bet["profit"] = profit
        bet["returned_amount"] = returned_amount

        state["bankroll"] = round_money(
            safe_float(state["bankroll"]) + profit
        )

        log(
            f"PARI GAGNÉ : {bet.get('home_team')} - "
            f"{bet.get('away_team')} | "
            f"+{profit:.2f} €"
        )

    else:
        bet["status"] = "LOST"
        bet["profit"] = round_money(-stake)
        bet["returned_amount"] = 0.0

        state["bankroll"] = round_money(
            safe_float(state["bankroll"]) - stake
        )

        log(
            f"PARI PERDU : {bet.get('home_team')} - "
            f"{bet.get('away_team')} | "
            f"-{stake:.2f} €"
        )

    bet["result"] = (
        f"{home_goals}-{away_goals}"
    )

    bet["settled_at"] = utc_now().isoformat()

    state["history"].append({
        "bet_id": bet.get("bet_id"),
        "match": (
            f"{bet.get('home_team')} - "
            f"{bet.get('away_team')}"
        ),
        "market": bet.get("market"),
        "result": bet["result"],
        "status": bet["status"],
        "stake": round_money(stake),
        "profit": bet["profit"],
        "settled_at": bet["settled_at"],
    })

    return True


def settle_finished_matches(state, competition_matches):
    matches_by_id = {
        str(match.get("id")): match
        for match in competition_matches
        if match.get("id") is not None
    }

    changed = False

    for bet in state["bets"]:
        if bet.get("status") != "PENDING":
            continue

        match = matches_by_id.get(
            str(bet.get("match_id"))
        )

        if not match:
            continue

        if match.get("status") != "FINISHED":
            continue

        score = match.get("score") or {}
        full_time = score.get("fullTime") or {}

        home_goals = full_time.get("home")
        away_goals = full_time.get("away")

        if home_goals is None or away_goals is None:
            continue

        if settle_bet(
            state,
            bet,
            int(home_goals),
            int(away_goals),
        ):
            changed = True

    return changed


# ============================================================
# GÉNÉRATION DES STATISTIQUES
# ============================================================

def print_statistics(state):
    bets = state["bets"]

    won = sum(
        1 for bet in bets
        if bet.get("status") == "WON"
    )

    lost = sum(
        1 for bet in bets
        if bet.get("status") == "LOST"
    )

    pending = sum(
        1 for bet in bets
        if bet.get("status") == "PENDING"
    )

    total_profit = round_money(
        sum(
            safe_float(bet.get("profit"))
            for bet in bets
            if bet.get("status") in ("WON", "LOST")
        )
    )

    initial = safe_float(
        state.get("initial_bankroll"),
        INITIAL_BANKROLL
    )

    bankroll = safe_float(
        state.get("bankroll"),
        INITIAL_BANKROLL
    )

    log("=" * 55)
    log("BILAN FOOT AI PRO V7")
    log(f"Capital initial : {initial:.2f} €")
    log(f"Capital virtuel : {bankroll:.2f} €")
    log(f"Profit net enregistré : {total_profit:.2f} €")
    log(f"Paris gagnés : {won}")
    log(f"Paris perdus : {lost}")
    log(f"Paris en attente : {pending}")

    settled = won + lost

    if settled:
        log(
            f"Taux de réussite : "
            f"{won / settled:.1%}"
        )
    else:
        log("Taux de réussite : aucun résultat réglé.")

    log("=" * 55)


# ============================================================
# EXÉCUTION PRINCIPALE
# ============================================================

def main():
    log("Démarrage de FOOT AI PRO BOT V7.")
    log("Mode simulation virtuelle uniquement.")

    api_key = get_api_key()

    if not api_key:
        raise RuntimeError(
            "Clé API manquante. Ajoute le secret "
            "FOOTBALL_DATA_API_KEY dans les paramètres "
            "de ton dépôt GitHub."
        )

    state = load_state()

    matches_by_competition = {}

    # 1. Récupération des matchs et règlement des paris.
    for competition_code in COMPETITIONS:
        log(
            f"Récupération des matchs : "
            f"{COMPETITIONS[competition_code]}"
        )

        matches = fetch_competition_matches(
            competition_code
        )

        matches_by_competition[
            competition_code
        ] = matches

        if matches:
            settle_finished_matches(
                state,
                matches
            )

        save_state(state)

        time.sleep(API_DELAY_SECONDS)

    # 2. Création des nouveaux paris virtuels.
    cutoff = parse_date(BET_CUTOFF_DATE)
    today = utc_now().date()

    if cutoff and today > cutoff:
        log(
            "Date limite dépassée : aucun nouveau "
            "pari virtuel ne sera créé."
        )

    else:
        new_bets = 0

        for competition_code, matches in (
            matches_by_competition.items()
        ):
            if count_bets_today(state) >= MAX_NEW_BETS_PER_DAY:
                log("Limite quotidienne de paris atteinte.")
                break

            finished_matches = [
                match
                for match in matches
                if match.get("status") == "FINISHED"
            ]

            upcoming_matches = [
                match
                for match in matches
                if match.get("status") in (
                    "SCHEDULED",
                    "TIMED",
                )
            ]

            upcoming_matches.sort(
                key=lambda match: (
                    match.get("utcDate") or ""
                )
            )

            for match in upcoming_matches:
                if count_bets_today(state) >= MAX_NEW_BETS_PER_DAY:
                    break

                match_date = parse_datetime(
                    match.get("utcDate")
                )

                if not match_date:
                    continue

                if match_date <= utc_now():
                    continue

                home_team = match.get("homeTeam") or {}
                away_team = match.get("awayTeam") or {}

                home_id = home_team.get("id")
                away_id = away_team.get("id")

                if not home_id or not away_id:
                    continue

                home_stats = get_team_statistics(
                    finished_matches,
                    home_id
                )

                away_stats = get_team_statistics(
                    finished_matches,
                    away_id
                )

                # Évite de créer des paris à partir
                # de statistiques insuffisantes.
                if (
                    home_stats["matches"] < 3
                    or away_stats["matches"] < 3
                ):
                    log(
                        f"Statistiques insuffisantes : "
                        f"{home_team.get('name')} - "
                        f"{away_team.get('name')}"
                    )
                    continue

                analysis = analyze_match(
                    home_stats,
                    away_stats
                )

                prediction = select_prediction(
                    analysis
                )

                if prediction is None:
                    continue

                created = create_virtual_bet(
                    state,
                    match,
                    competition_code,
                    prediction,
                )

                if created:
                    new_bets += 1
                    save_state(state)

            if count_bets_today(state) >= MAX_NEW_BETS_PER_DAY:
                break

        log(
            f"Nouveaux paris virtuels créés : "
            f"{new_bets}"
        )

    # 3. Sauvegarde finale et bilan.
    save_state(state)
    print_statistics(state)

    log("Exécution terminée.")


if __name__ == "__main__":
    main()