import os
import json
import math
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

# ============================================================
# FOOT AI PRO BOT V10
# Simulation virtuelle uniquement — aucun pari réel.
# API : football-data.org v4
# Compatible avec GitHub Actions.
# ============================================================

API_BASE = "https://api.football-data.org/v4"
STATE_FILE = Path("data/bankroll.json")

INITIAL_BANKROLL = 20.0
MAX_STAKE = 1.0
MAX_NEW_BETS_PER_DAY = 6
MAX_BACKTESTS_PER_DAY = 6

LOOKBACK_DAYS = 60
MAX_GOALS = 10
MIN_HISTORY_MATCHES = 3
MIN_PROBABILITY = 0.60

REQUEST_TIMEOUT = 25
API_DELAY_SECONDS = 1.0
LOCAL_TZ = ZoneInfo("Europe/Paris")

COMPETITIONS = {
    "FL1": "Ligue 1",
    "PL": "Premier League",
    "PD": "Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "CL": "Ligue des champions",
}

HEADERS = {
    "User-Agent": "FOOT-AI-PRO-V10-Virtual-Simulation"
}


# ============================================================
# OUTILS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def local_now():
    return utc_now().astimezone(LOCAL_TZ)


def local_date():
    return local_now().date().isoformat()


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


def match_local_date(match):
    kickoff = parse_datetime(match.get("utcDate"))

    if kickoff is None:
        return None

    return kickoff.astimezone(LOCAL_TZ).date().isoformat()


def log(message):
    print(
        f"[{utc_now().strftime('%Y-%m-%d %H:%M:%S UTC')}] "
        f"{message}",
        flush=True
    )


# ============================================================
# CLE API
# ============================================================

def get_api_key():
    for name in (
        "FOOTBALL_DATA_API_KEY",
        "FOOTBALL_API_KEY",
        "FOOTBALL_DATA_TOKEN",
    ):
        value = os.environ.get(name, "").strip()

        if value:
            return value

    return None


# ============================================================
# API
# ============================================================

def api_get(endpoint, params=None):
    api_key = get_api_key()

    if not api_key:
        raise RuntimeError(
            "Clé API manquante : FOOTBALL_DATA_API_KEY."
        )

    url = f"{API_BASE}/{endpoint.lstrip('/')}"

    try:
        response = requests.get(
            url,
            headers={
                **HEADERS,
                "X-Auth-Token": api_key,
            },
            params=params or {},
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 429:
            log("Limite API atteinte : requête abandonnée.")
            return None

        if response.status_code in (401, 403):
            log(
                f"Accès API refusé : HTTP {response.status_code}. "
                "Vérifie la clé et les compétitions autorisées."
            )
            return None

        if response.status_code == 404:
            log(f"Ressource introuvable : {endpoint}")
            return None

        response.raise_for_status()

        data = response.json()

        return data if isinstance(data, dict) else None

    except requests.RequestException as exc:
        log(f"Erreur réseau API : {exc}")
        return None

    except ValueError as exc:
        log(f"Réponse JSON invalide : {exc}")
        return None


# ============================================================
# SAUVEGARDE COMPATIBLE AVEC L'ANCIEN JSON
# ============================================================

def default_state():
    now = utc_now().isoformat()

    return {
        "version": 10,
        "bankroll": INITIAL_BANKROLL,
        "initial_bankroll": INITIAL_BANKROLL,
        "bets": [],
        "history": [],
        "backtests": [],
        "created_at": now,
        "updated_at": now,
    }


def load_state():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not STATE_FILE.exists():
        state = default_state()
        save_state(state)
        return state

    try:
        with STATE_FILE.open("r", encoding="utf-8") as file:
            state = json.load(file)

        if not isinstance(state, dict):
            raise ValueError("Le JSON doit contenir un objet.")

        # Préserver les données existantes.
        state.setdefault("version", 10)
        state.setdefault("bets", [])
        state.setdefault("history", [])
        state.setdefault("backtests", [])
        state.setdefault("created_at", utc_now().isoformat())

        for key in ("bets", "history", "backtests"):
            if not isinstance(state.get(key), list):
                raise ValueError(
                    f"Le champ {key} doit être une liste."
                )

        # Compatibilité entre les anciens noms et les nouveaux.
        if "bankroll" not in state:
            state["bankroll"] = state.get(
                "bankroll_actuelle",
                state.get("starting_bankroll", INITIAL_BANKROLL),
            )

        if "initial_bankroll" not in state:
            state["initial_bankroll"] = state.get(
                "bankroll_initiale",
                state.get("starting_bankroll", INITIAL_BANKROLL),
            )

        state["bankroll"] = round_money(
            safe_float(state["bankroll"], INITIAL_BANKROLL)
        )

        state["initial_bankroll"] = round_money(
            safe_float(state["initial_bankroll"], INITIAL_BANKROLL)
        )

        state["version"] = 10

        return state

    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            "Impossible de lire bankroll.json. "
            "Le fichier n'a pas été remplacé pour protéger tes données : "
            f"{exc}"
        ) from exc


def synchronize_legacy_fields(state):
    """Met à jour les champs utilisés par l'ancienne application."""

    bets = state["bets"]

    won = sum(
        1 for bet in bets if bet.get("status") == "WON"
    )
    lost = sum(
        1 for bet in bets if bet.get("status") == "LOST"
    )
    pending = sum(
        1 for bet in bets if bet.get("status") == "PENDING"
    )

    settled = won + lost

    total_stakes = sum(
        safe_float(bet.get("stake"))
        for bet in bets
        if bet.get("status") in ("WON", "LOST")
    )

    total_returns = sum(
        safe_float(bet.get("returned_amount"))
        for bet in bets
        if bet.get("status") in ("WON", "LOST")
    )

    profit = round_money(
        sum(
            safe_float(bet.get("profit"))
            for bet in bets
            if bet.get("status") in ("WON", "LOST")
        )
    )

    state["bankroll_initiale"] = state["initial_bankroll"]
    state["bankroll_actuelle"] = state["bankroll"]
    state["starting_bankroll"] = state["initial_bankroll"]
    state["initial_bankroll"] = state["initial_bankroll"]

    state["benefice_total"] = profit
    state["profit"] = profit
    state["mises_totales"] = round_money(total_stakes)
    state["gains_totaux"] = round_money(total_returns)

    state["paris"] = bets
    state["historique"] = state["history"]

    state["statistiques"] = {
        "total_paris": len(bets),
        "paris_gagnes": won,
        "paris_perdus": lost,
        "paris_en_attente": pending,
        "taux_reussite": (
            round(won / settled * 100, 2)
            if settled else 0.0
        ),
    }

    state["derniere_mise_a_jour"] = utc_now().isoformat()


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    synchronize_legacy_fields(state)

    state["updated_at"] = utc_now().isoformat()

    temporary_file = STATE_FILE.with_suffix(".tmp")

    with temporary_file.open("w", encoding="utf-8") as file:
        json.dump(
            state,
            file,
            indent=2,
            ensure_ascii=False,
        )

    temporary_file.replace(STATE_FILE)


# ============================================================
# STATISTIQUES DES EQUIPES
# ============================================================

def get_team_statistics(matches, team_id, before=None):
    performances = []

    for match in matches:
        if match.get("status") != "FINISHED":
            continue

        kickoff = parse_datetime(match.get("utcDate"))

        if kickoff is None:
            continue

        if before is not None and kickoff >= before:
            continue

        home = match.get("homeTeam") or {}
        away = match.get("awayTeam") or {}

        full_time = (
            (match.get("score") or {}).get("fullTime") or {}
        )

        hg = full_time.get("home")
        ag = full_time.get("away")

        if hg is None or ag is None:
            continue

        if home.get("id") == team_id:
            performances.append(
                (kickoff, float(hg), float(ag))
            )
        elif away.get("id") == team_id:
            performances.append(
                (kickoff, float(ag), float(hg))
            )

    performances.sort(key=lambda item: item[0], reverse=True)
    performances = performances[:10]

    if not performances:
        return {
            "matches": 0,
            "scored": 1.25,
            "conceded": 1.25,
        }

    weights = [
        1.0 / (1.0 + 0.12 * index)
        for index in range(len(performances))
    ]

    total_weight = sum(weights)

    scored = sum(
        item[1] * weight
        for item, weight in zip(performances, weights)
    ) / total_weight

    conceded = sum(
        item[2] * weight
        for item, weight in zip(performances, weights)
    ) / total_weight

    return {
        "matches": len(performances),
        "scored": scored,
        "conceded": conceded,
    }


# ============================================================
# POISSON
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


def estimate_goals(home_stats, away_stats):
    home_lambda = (
        0.55 * home_stats["scored"]
        + 0.45 * away_stats["conceded"]
        + 0.15
    )

    away_lambda = (
        0.55 * away_stats["scored"]
        + 0.45 * home_stats["conceded"]
    )

    return (
        max(0.15, min(home_lambda, 4.0)),
        max(0.15, min(away_lambda, 4.0)),
    )


def analyze_match(home_stats, away_stats):
    home_lambda, away_lambda = estimate_goals(
        home_stats,
        away_stats,
    )

        markets = {
        "1": 0.0,
        "N": 0.0,
        "2": 0.0,
        "1X": 0.0,
        "X2": 0.0,
        "Over 2.5": 0.0,
        "Over 3.5": 0.0,
        "Under 2.5": 0.0,
        "Under 3.5": 0.0,
        "BTTS Oui": 0.0,
        "BTTS Non": 0.0,
    }

    best_score = "1-1"
    best_score_probability = -1.0

    for hg in range(MAX_GOALS + 1):
        ph = poisson_probability(home_lambda, hg)

        for ag in range(MAX_GOALS + 1):
            pa = poisson_probability(away_lambda, ag)
            p = ph * pa
            total = hg + ag

            if hg > ag:
                markets["1"] += p
            elif hg == ag:
                markets["N"] += p
            else:
                markets["2"] += p

            if hg >= ag:
                markets["1X"] += p
            if ag >= hg:
                markets["X2"] += p

            if total >= 3:
                markets["Over 2.5"] += p
            if total >= 4:
                markets["Over 3.5"] += p
            if total <= 2:
                markets["Under 2.5"] += p
            if total <= 3:
                markets["Under 3.5"] += p

            if hg > 0 and ag > 0:
                markets["BTTS Oui"] += p
            else:
                markets["BTTS Non"] += p

            if p > best_score_probability:
                best_score_probability = p
                best_score = f"{hg}-{ag}"

    return {
        "markets": markets,
        "exact_score": best_score,
        "home_lambda": home_lambda,
        "away_lambda": away_lambda,
    }


# ============================================================
# SELECTION PLUS VARIEE
# ============================================================

def select_prediction(analysis):
    candidates = []

    # On écarte le marché Over 0.5 de la sélection automatique :
    # il était choisi presque systématiquement et offre peu de valeur.
    excluded_markets = {"Over 0.5"}

    for market, probability in analysis["markets"].items():
        if market in excluded_markets:
            continue

        if probability < MIN_PROBABILITY:
            continue

        # Une probabilité extrêmement haute ne garantit pas un pari sûr.
        # On estime la cote théorique sans prétendre qu'elle existe chez
        # un bookmaker.
        estimated_odds = 1.0 / probability

        # Score de classement : favorise les probabilités élevées tout
        # en évitant de toujours sélectionner les mêmes marchés.
        score = probability

        if market in ("1X", "X2"):
            score -= 0.025
        if market in ("Over 3.5", "Under 2.5", "Under 3.5"):
            score += 0.015

        candidates.append({
            "market": market,
            "probability": probability,
            "odds": max(1.01, min(estimated_odds, 10.0)),
            "score": score,
            "exact_score": analysis["exact_score"],
        })

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    chosen = candidates[0]

    return {
        "market": chosen["market"],
        "probability": round(chosen["probability"], 4),
        "odds": round(chosen["odds"], 2),
        "exact_score": chosen["exact_score"],
    }


# ============================================================
# MATCHS DE CHAQUE COMPETITION
# ============================================================

def fetch_competition_matches(competition_code):
    today = local_now().date()

    date_from = today - timedelta(days=LOOKBACK_DAYS)
    date_to = today + timedelta(days=1)

    payload = api_get(
        f"competitions/{competition_code}/matches",
        params={
            "dateFrom": date_from.isoformat(),
            "dateTo": date_to.isoformat(),
        },
    )

    if not payload:
        return None

    matches = payload.get("matches")

    return matches if isinstance(matches, list) else None


# ============================================================
# IDENTIFIANTS
# ============================================================

def make_bet_id(match_id, market):
    return f"{match_id}:{market}"


def get_existing_bet_ids(state):
    return {
        make_bet_id(bet.get("match_id"), bet.get("market"))
        for bet in state["bets"]
        if bet.get("match_id") is not None and bet.get("market")
    }


def count_bets_today(state):
    today = local_date()

    return sum(
        1 for bet in state["bets"]
        if bet.get("created_date") == today
    )


# ============================================================
# CREATION DES PARIS DU JOUR
# ============================================================

def create_virtual_bet(state, match, competition_code, prediction):
    match_id = match.get("id")

    if match_id is None or prediction is None:
        return False

    if make_bet_id(match_id, prediction["market"]) in get_existing_bet_ids(state):
        return False

    if count_bets_today(state) >= MAX_NEW_BETS_PER_DAY:
        return False

    kickoff = parse_datetime(match.get("utcDate"))

    if kickoff is None or kickoff <= utc_now():
        return False

    if match_local_date(match) != local_date():
        return False

    stake = min(
        MAX_STAKE,
        max(0.0, safe_float(state.get("bankroll"))),
    )

    if stake <= 0:
        log("Capital virtuel insuffisant.")
        return False

    home = match.get("homeTeam") or {}
    away = match.get("awayTeam") or {}

    bet = {
        "bet_id": make_bet_id(match_id, prediction["market"]),
        "match_id": match_id,
        "competition": competition_code,
        "competition_name": COMPETITIONS.get(
            competition_code,
            competition_code,
        ),
        "home_team": home.get("name", "Équipe domicile"),
        "away_team": away.get("name", "Équipe extérieure"),
        "match_date": kickoff.isoformat(),
        "created_date": local_date(),
        "market": prediction["market"],
        "probability": prediction["probability"],
        "odds": prediction["odds"],
        "exact_score_prediction": prediction["exact_score"],
        "stake": round_money(stake),
        "potential_return": round_money(stake * prediction["odds"]),
        "profit": 0.0,
        "status": "PENDING",
        "result": None,
    }

    state["bets"].append(bet)

    log(
        f"NOUVEAU PARI : {bet['home_team']} - {bet['away_team']} | "
        f"{bet['market']} | {prediction['probability']:.1%}"
    )

    return True


# ============================================================
# EVALUATION DES MARCHES
# ============================================================

def evaluate_market(bet, home_goals, away_goals):
    market = bet.get("market")
    total = home_goals + away_goals

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
    if market == "Over 0.5":
        return total >= 1
    if market == "Over 1.5":
        return total >= 2
    if market == "Over 2.5":
        return total >= 3
    if market == "Over 3.5":
        return total >= 4
    if market == "Under 2.5":
        return total <= 2
    if market == "Under 3.5":
        return total <= 3
    if market == "BTTS Oui":
        return home_goals > 0 and away_goals > 0
    if market == "BTTS Non":
        return home_goals == 0 or away_goals == 0

    return None


# ============================================================
# REGLEMENT DES PARIS
# ============================================================

def settle_bet(state, bet, home_goals, away_goals):
    if bet.get("status") != "PENDING":
        return False

    won = evaluate_market(bet, home_goals, away_goals)

    if won is None:
        log(f"Marché non reconnu : {bet.get('bet_id')}")
        return False

    stake = safe_float(bet.get("stake"))
    odds = safe_float(bet.get("odds"))

    if won:
        returned_amount = round_money(stake * odds)
        profit = round_money(returned_amount - stake)

        bet["status"] = "WON"
        bet["profit"] = profit
        bet["returned_amount"] = returned_amount

        state["bankroll"] = round_money(
            safe_float(state.get("bankroll")) + profit
        )
    else:
        bet["status"] = "LOST"
        bet["profit"] = round_money(-stake)
        bet["returned_amount"] = 0.0

        state["bankroll"] = round_money(
            safe_float(state.get("bankroll")) - stake
        )

    bet["result"] = f"{home_goals}-{away_goals}"
    bet["settled_at"] = utc_now().isoformat()

    history_ids = {
        item.get("bet_id")
        for item in state["history"]
    }

    if bet.get("bet_id") not in history_ids:
        state["history"].append({
            "bet_id": bet.get("bet_id"),
            "match": (
                f"{bet.get('home_team')} - {bet.get('away_team')}"
            ),
            "market": bet.get("market"),
            "result": bet["result"],
            "status": bet["status"],
            "stake": round_money(stake),
            "profit": bet["profit"],
            "settled_at": bet["settled_at"],
        })

    log(
        f"PARI {bet['status']} : {bet.get('home_team')} - "
        f"{bet.get('away_team')} | "
        f"{bet['profit']:+.2f} €"
    )

    return True


def settle_finished_matches(state, matches):
    if not matches:
        return False

    matches_by_id = {
        str(match.get("id")): match
        for match in matches
        if match.get("id") is not None
    }

    changed = False

    for bet in state["bets"]:
        if bet.get("status") != "PENDING":
            continue

        match = matches_by_id.get(str(bet.get("match_id")))

        if not match or match.get("status") != "FINISHED":
            continue

        full_time = (
            (match.get("score") or {}).get("fullTime") or {}
        )

        hg = full_time.get("home")
        ag = full_time.get("away")

        if hg is None or ag is None:
            continue

        if settle_bet(state, bet, int(hg), int(ag)):
            changed = True

    return changed


# ============================================================
# BACKTESTS D'HIER — SEPARES DE LA BANKROLL
# ============================================================

def backtest_id(match_id, market):
    return f"BACKTEST:{match_id}:{market}"


def create_yesterday_backtests(state, all_matches):
    yesterday = (
        local_now().date() - timedelta(days=1)
    ).isoformat()

    existing_ids = {
        item.get("backtest_id")
        for item in state["backtests"]
    }

    candidates = []

    for competition_code, matches in all_matches.items():
        if matches is None:
            continue

        for match in matches:
            if match_local_date(match) != yesterday:
                continue

            if match.get("status") != "FINISHED":
                continue

            kickoff = parse_datetime(match.get("utcDate"))

            if kickoff is None:
                continue

            home = match.get("homeTeam") or {}
            away = match.get("awayTeam") or {}

            home_id = home.get("id")
            away_id = away.get("id")

            if not home_id or not away_id:
                continue

            hs = get_team_statistics(matches, home_id, before=kickoff)
            aws = get_team_statistics(matches, away_id, before=kickoff)

            if (
                hs["matches"] < MIN_HISTORY_MATCHES
                or aws["matches"] < MIN_HISTORY_MATCHES
            ):
                continue

            analysis = analyze_match(hs, aws)
            prediction = select_prediction(analysis)

            if prediction is None:
                continue

            match_id = match.get("id")
            unique_id = backtest_id(match_id, prediction["market"])

            if unique_id in existing_ids:
                continue

            full_time = (
                (match.get("score") or {}).get("fullTime") or {}
            )

            hg = full_time.get("home")
            ag = full_time.get("away")

            if hg is None or ag is None:
                continue

            won = evaluate_market(
                {"market": prediction["market"]},
                int(hg),
                int(ag),
            )

            if won is None:
                continue

            candidates.append({
                "backtest_id": unique_id,
                "match_id": match_id,
                "date": yesterday,
                "competition": competition_code,
                "competition_name": COMPETITIONS.get(
                    competition_code,
                    competition_code,
                ),
                "home_team": home.get("name", "Équipe domicile"),
                "away_team": away.get("name", "Équipe extérieure"),
                "market": prediction["market"],
                "probability": prediction["probability"],
                "estimated_odds": prediction["odds"],
                "predicted_score": prediction["exact_score"],
                "actual_score": f"{hg}-{ag}",
                "stake_simulated": MAX_STAKE,
                "status": "WON" if won else "LOST",
                "profit_simulated": (
                    round_money(MAX_STAKE * prediction["odds"] - MAX_STAKE)
                    if won else round_money(-MAX_STAKE)
                ),
                "created_at": utc_now().isoformat(),
                "note": "Simulation rétrospective. Ne modifie pas la bankroll.",
            })

    candidates.sort(
        key=lambda item: item["probability"],
        reverse=True,
    )

    selected = candidates[:MAX_BACKTESTS_PER_DAY]

    for item in selected:
        state["backtests"].append(item)
        existing_ids.add(item["backtest_id"])

        log(
            f"BACKTEST : {item['home_team']} - {item['away_team']} | "
            f"{item['market']} | {item['actual_score']} | "
            f"{item['status']}"
        )

    if not selected:
        log("Aucun nouveau backtest éligible.")

    return len(selected)


# ============================================================
# PARIS DU JOUR
# ============================================================

def create_today_bets(state, all_matches):
    today = local_date()
    candidates = []

    existing_ids = get_existing_bet_ids(state)

    for competition_code, matches in all_matches.items():
        if matches is None:
            continue

        finished = [
            match for match in matches
            if match.get("status") == "FINISHED"
        ]

        upcoming = [
            match for match in matches
            if match.get("status") in ("SCHEDULED", "TIMED")
            and match_local_date(match) == today
        ]

        for match in upcoming:
            kickoff = parse_datetime(match.get("utcDate"))

            if kickoff is None or kickoff <= utc_now():
                continue

            home = match.get("homeTeam") or {}
            away = match.get("awayTeam") or {}

            home_id = home.get("id")
            away_id = away.get("id")

            if not home_id or not away_id:
                continue

            hs = get_team_statistics(finished, home_id)
            aws = get_team_statistics(finished, away_id)

            if (
                hs["matches"] < MIN_HISTORY_MATCHES
                or aws["matches"] < MIN_HISTORY_MATCHES
            ):
                log(
                    f"Historique insuffisant : "
                    f"{home.get('name')} - {away.get('name')}"
                )
                continue

            analysis = analyze_match(hs, aws)
            prediction = select_prediction(analysis)

            if prediction is None:
                continue

            bet_id = make_bet_id(
                match.get("id"),
                prediction["market"],
            )

            if bet_id in existing_ids:
                continue

            candidates.append({
                "match": match,
                "competition_code": competition_code,
                "prediction": prediction,
            })

    candidates.sort(
        key=lambda item: item["prediction"]["probability"],
        reverse=True,
    )

    remaining = max(
        0,
        MAX_NEW_BETS_PER_DAY - count_bets_today(state),
    )

    created = 0

    for item in candidates:
        if created >= remaining:
            break

        if create_virtual_bet(
            state,
            item["match"],
            item["competition_code"],
            item["prediction"],
        ):
            created += 1
            save_state(state)

    log(
        f"Nouveaux paris créés : {created}. "
        f"Limite quotidienne : {MAX_NEW_BETS_PER_DAY}."
    )

    return created


# ============================================================
# STATISTIQUES
# ============================================================

def print_statistics(state):
    bets = state["bets"]

    won = sum(1 for bet in bets if bet.get("status") == "WON")
    lost = sum(1 for bet in bets if bet.get("status") == "LOST")
    pending = sum(1 for bet in bets if bet.get("status") == "PENDING")

    settled = won + lost

    profit = round_money(
        sum(
            safe_float(bet.get("profit"))
            for bet in bets
            if bet.get("status") in ("WON", "LOST")
        )
    )

    backtests = state["backtests"]
    bt_won = sum(1 for item in backtests if item.get("status") == "WON")
    bt_lost = sum(1 for item in backtests if item.get("status") == "LOST")

    bt_profit = round_money(
        sum(safe_float(item.get("profit_simulated")) for item in backtests)
    )

    log("=" * 50)
    log("BILAN FOOT AI PRO BOT V10")
    log(f"Date française : {local_date()}")
    log(f"Capital initial : {state['initial_bankroll']:.2f} €")
    log(f"Capital actuel : {state['bankroll']:.2f} €")
    log(f"Profit des paris réglés : {profit:+.2f} €")
    log(f"Paris gagnés : {won}")
    log(f"Paris perdus : {lost}")
    log(f"Paris en attente : {pending}")

    if settled:
        log(f"Taux de réussite : {won / settled:.1%}")
    else:
        log("Taux de réussite : aucun pari réglé.")

    log("--- BACKTESTS INDEPENDANTS ---")
    log(f"Total : {len(backtests)}")
    log(f"Gagnés : {bt_won}")
    log(f"Perdus : {bt_lost}")
    log(f"Profit simulé : {bt_profit:+.2f} €")

    if bt_won + bt_lost:
        log(f"Taux de réussite backtest : {bt_won / (bt_won + bt_lost):.1%}")

    log("=" * 50)


# ============================================================
# EXECUTION
# ============================================================

def main():
    log("Démarrage FOOT AI PRO BOT V10.")
    log("Simulation virtuelle uniquement.")

    if not get_api_key():
        raise RuntimeError(
            "Clé API manquante : configure FOOTBALL_DATA_API_KEY."
        )

    state = load_state()
    all_matches = {}

    for index, code in enumerate(COMPETITIONS):
        log(f"Récupération : {COMPETITIONS[code]}")

        matches = fetch_competition_matches(code)
        all_matches[code] = matches

        if matches is not None:
            settle_finished_matches(state, matches)

        save_state(state)

        if index < len(COMPETITIONS) - 1:
            time.sleep(API_DELAY_SECONDS)

    log("Création des simulations rétrospectives.")
    create_yesterday_backtests(state, all_matches)
    save_state(state)

    log("Création des nouveaux pronostics du jour.")
    create_today_bets(state, all_matches)

    save_state(state)
    print_statistics(state)

    log("Exécution terminée.")


if __name__ == "__main__":
    main()