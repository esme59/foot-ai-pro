import os
import json
import math
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests


# ============================================================
# FOOT AI PRO BOT V9
# Simulation virtuelle uniquement : aucun pari réel.
# API : football-data.org v4
# Compatible avec GitHub Actions.
# ============================================================

API_BASE = "https://api.football-data.org/v4"
STATE_FILE = Path("data/bankroll.json")

INITIAL_BANKROLL = 20.0
MAX_STAKE = 1.0
MAX_NEW_BETS_PER_DAY = 6

# Simulations rétrospectives : maximum 6 pour hier.
MAX_BACKTESTS_PER_DAY = 6

# Statistiques et prédictions.
LOOKBACK_DAYS = 60
MAX_GOALS = 8
MIN_HISTORY_MATCHES = 3
MIN_PROBABILITY = 0.60

# Limitation des requêtes.
REQUEST_TIMEOUT = 25
API_DELAY_SECONDS = 0.5

# Heure française pour définir la journée.
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
    "User-Agent": "FOOT-AI-PRO-V9-Virtual-Simulation"
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
            log(
                "Limite de requêtes API atteinte. "
                "Cette requête est abandonnée."
            )
            return None

        if response.status_code in (401, 403):
            log(
                f"Accès API refusé : HTTP {response.status_code}. "
                "Vérifie la clé et les compétitions autorisées."
            )
            return None

        if response.status_code == 404:
            log(f"Ressource API introuvable : {endpoint}")
            return None

        response.raise_for_status()

        data = response.json()

        if not isinstance(data, dict):
            log("Réponse API inattendue.")
            return None

        return data

    except requests.RequestException as exc:
        log(f"Erreur de connexion API : {exc}")
        return None

    except ValueError as exc:
        log(f"Réponse JSON invalide : {exc}")
        return None


# ============================================================
# BANQUE VIRTUELLE ET SAUVEGARDE
# ============================================================

def default_state():
    now = utc_now().isoformat()

    return {
        "version": 9,
        "bankroll": INITIAL_BANKROLL,
        "initial_bankroll": INITIAL_BANKROLL,
        "bets": [],
        "history": [],
        "backtests": [],
        "created_at": now,
        "updated_at": now,
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
            raise ValueError("Le contenu JSON n'est pas un objet.")

        # Mise à niveau sans supprimer les données existantes.
        state.setdefault("version", 9)
        state.setdefault("initial_bankroll", INITIAL_BANKROLL)
        state.setdefault("bets", [])
        state.setdefault("history", [])
        state.setdefault("backtests", [])
        state.setdefault("created_at", utc_now().isoformat())

        for key in ("bets", "history", "backtests"):
            if not isinstance(state.get(key), list):
                state[key] = []

        if "bankroll" not in state:
            state["bankroll"] = INITIAL_BANKROLL

        state["bankroll"] = round_money(
            safe_float(state["bankroll"], INITIAL_BANKROLL)
        )

        return state

    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            "Impossible de lire data/bankroll.json. "
            "Le fichier est conservé pour éviter de perdre "
            f"tes données : {exc}"
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
# STATISTIQUES DES EQUIPES
# ============================================================

def get_team_statistics(matches, team_id, before=None):
    """
    Calcule les moyennes de buts marqués et encaissés.

    before permet d'exclure les matchs joués après le coup
    d'envoi du match que l'on souhaite simuler.
    """

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

        score = match.get("score") or {}
        full_time = score.get("fullTime") or {}

        home_goals = full_time.get("home")
        away_goals = full_time.get("away")

        if home_goals is None or away_goals is None:
            continue

        if home.get("id") == team_id:
            performances.append((
                kickoff,
                float(home_goals),
                float(away_goals),
            ))

        elif away.get("id") == team_id:
            performances.append((
                kickoff,
                float(away_goals),
                float(home_goals),
            ))

    performances.sort(
        key=lambda item: item[0],
        reverse=True
    )

    # Les dix dernières rencontres maximum.
    performances = performances[:10]

    if not performances:
        return {
            "matches": 0,
            "scored": 1.25,
            "conceded": 1.25,
            "home_matches": 0,
            "away_matches": 0,
        }

    # Pondération : les matchs les plus récents comptent
    # un peu plus que les matchs anciens.
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
        "home_matches": 0,
        "away_matches": 0,
    }


# ============================================================
# MODELE DE POISSON
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
    over_05 = 0.0
    over_15 = 0.0
    over_25 = 0.0
    over_35 = 0.0
    btts_yes = 0.0

    best_score = (0, 0)
    best_score_probability = 0.0

    for home_goals in range(MAX_GOALS + 1):
        p_home = poisson_probability(
            home_lambda,
            home_goals
        )

        for away_goals in range(MAX_GOALS + 1):
            p_away = poisson_probability(
                away_lambda,
                away_goals
            )

            probability = p_home * p_away
            total_goals = home_goals + away_goals

            if home_goals > away_goals:
                home_win += probability
            elif home_goals == away_goals:
                draw += probability
            else:
                away_win += probability

            if total_goals >= 1:
                over_05 += probability
            if total_goals >= 2:
                over_15 += probability
            if total_goals >= 3:
                over_25 += probability
            if total_goals >= 4:
                over_35 += probability

            if home_goals > 0 and away_goals > 0:
                btts_yes += probability

            if probability > best_score_probability:
                best_score_probability = probability
                best_score = (home_goals, away_goals)

    return {
        "home_win": home_win,
        "draw": draw,
        "away_win": away_win,
        "home_or_draw": home_win + draw,
        "away_or_draw": away_win + draw,
        "over_05": over_05,
        "over_15": over_15,
        "over_25": over_25,
        "over_35": over_35,
        "under_25": 1.0 - over_25,
        "under_35": 1.0 - over_35,
        "btts_yes": btts_yes,
        "btts_no": 1.0 - btts_yes,
        "exact_score": f"{best_score[0]}-{best_score[1]}",
        "home_lambda": home_lambda,
        "away_lambda": away_lambda,
    }


# ============================================================
# SELECTION DU PRONOSTIC
# ============================================================

def select_prediction(analysis):
    markets = [
        ("1", analysis["home_win"]),
        ("N", analysis["draw"]),
        ("2", analysis["away_win"]),
        ("1X", analysis["home_or_draw"]),
        ("X2", analysis["away_or_draw"]),
        ("Over 0.5", analysis["over_05"]),
        ("Over 1.5", analysis["over_15"]),
        ("Over 2.5", analysis["over_25"]),
        ("Over 3.5", analysis["over_35"]),
        ("Under 2.5", analysis["under_25"]),
        ("Under 3.5", analysis["under_35"]),
        ("BTTS Oui", analysis["btts_yes"]),
        ("BTTS Non", analysis["btts_no"]),
    ]

    candidates = [
        (market, probability)
        for market, probability in markets
        if probability >= MIN_PROBABILITY
    ]

    if not candidates:
        return None

    # Retient le marché ayant la plus forte probabilité.
    market, probability = max(
        candidates,
        key=lambda item: item[1]
    )

    # Cote théorique prudente. Ce n'est pas une cote bookmaker.
    estimated_odds = max(
        1.10,
        min(0.90 / probability, 3.00)
    )

    return {
        "market": market,
        "probability": round(probability, 4),
        "odds": round(estimated_odds, 2),
        "exact_score": analysis["exact_score"],
    }


# ============================================================
# RECUPERATION DES MATCHS
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

    matches = payload.get("matches", [])

    if not isinstance(matches, list):
        return None

    return matches


# ============================================================
# IDENTIFICATION DES PARIS ET LIMITES
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
# CREATION DES PARIS VIRTUELS DU JOUR
# ============================================================

def create_virtual_bet(state, match, competition_code, prediction):
    match_id = match.get("id")

    if match_id is None or prediction is None:
        return False

    bet_id = make_bet_id(
        match_id,
        prediction["market"]
    )

    if bet_id in get_existing_bet_ids(state):
        return False

    if count_bets_today(state) >= MAX_NEW_BETS_PER_DAY:
        return False

    kickoff = parse_datetime(match.get("utcDate"))

    if kickoff is None or kickoff <= utc_now():
        return False

    # Interdit les nouveaux paris sur demain ou sur une date passée.
    if match_local_date(match) != local_date():
        return False

    stake = min(
        MAX_STAKE,
        max(0.0, safe_float(state.get("bankroll")))
    )

    if stake <= 0:
        log("Capital virtuel insuffisant.")
        return False

    home = match.get("homeTeam") or {}
    away = match.get("awayTeam") or {}

    bet = {
        "bet_id": bet_id,
        "match_id": match_id,
        "competition": competition_code,
        "competition_name": COMPETITIONS.get(
            competition_code,
            competition_code
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
        "potential_return": round_money(
            stake * prediction["odds"]
        ),
        "profit": 0.0,
        "status": "PENDING",
        "result": None,
    }

    state["bets"].append(bet)

    log(
        f"PARI VIRTUEL : {bet['home_team']} - "
        f"{bet['away_team']} | {bet['market']} | "
        f"Probabilité {prediction['probability']:.1%} | "
        f"Mise {stake:.2f} €"
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
# REGLEMENT AUTOMATIQUE DES PARIS
# ============================================================

def settle_bet(state, bet, home_goals, away_goals):
    if bet.get("status") != "PENDING":
        return False

    won = evaluate_market(
        bet,
        home_goals,
        away_goals
    )

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
            safe_float(state["bankroll"]) + profit
        )

        log(
            f"PARI GAGNÉ : {bet.get('home_team')} - "
            f"{bet.get('away_team')} | +{profit:.2f} €"
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
            f"{bet.get('away_team')} | -{stake:.2f} €"
        )

    bet["result"] = f"{home_goals}-{away_goals}"
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


def settle_finished_matches(state, matches):
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
# SIMULATIONS RETROSPECTIVES DES MATCHS D'HIER
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

            home_stats = get_team_statistics(
                matches,
                home_id,
                before=kickoff,
            )

            away_stats = get_team_statistics(
                matches,
                away_id,
                before=kickoff,
            )

            if (
                home_stats["matches"] < MIN_HISTORY_MATCHES
                or away_stats["matches"] < MIN_HISTORY_MATCHES
            ):
                continue

            analysis = analyze_match(
                home_stats,
                away_stats
            )

            prediction = select_prediction(analysis)

            if prediction is None:
                continue

            match_id = match.get("id")
            unique_id = backtest_id(
                match_id,
                prediction["market"]
            )

            if unique_id in existing_ids:
                continue

            full_time = (
                (match.get("score") or {}).get("fullTime") or {}
            )

            home_goals = full_time.get("home")
            away_goals = full_time.get("away")

            if home_goals is None or away_goals is None:
                continue

            won = evaluate_market(
                {"market": prediction["market"]},
                int(home_goals),
                int(away_goals),
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
                    competition_code
                ),
                "home_team": home.get("name", "Équipe domicile"),
                "away_team": away.get("name", "Équipe extérieure"),
                "market": prediction["market"],
                "probability": prediction["probability"],
                "estimated_odds": prediction["odds"],
                "predicted_score": prediction["exact_score"],
                "actual_score": f"{home_goals}-{away_goals}",
                "stake_simulated": MAX_STAKE,
                "status": "WON" if won else "LOST",
                "profit_simulated": (
                    round_money(MAX_STAKE * prediction["odds"] - MAX_STAKE)
                    if won else round_money(-MAX_STAKE)
                ),
                "created_at": utc_now().isoformat(),
                "note": (
                    "Simulation rétrospective. "
                    "Ne modifie pas la bankroll."
                ),
            })

    # Les meilleurs scores de probabilité estimée sont retenus,
    # dans la limite globale de 6 simulations par journée.
    candidates.sort(
        key=lambda item: item["probability"],
        reverse=True
    )

    selected = candidates[:MAX_BACKTESTS_PER_DAY]

    for item in selected:
        state["backtests"].append(item)

        log(
            f"SIMULATION D'HIER : {item['home_team']} - "
            f"{item['away_team']} | {item['market']} | "
            f"Score réel {item['actual_score']} | "
            f"{item['status']} | "
            f"Profit simulé {item['profit_simulated']:+.2f} €"
        )

    if not selected:
        log(
            "Aucune nouvelle simulation d'hier : "
            "aucun match éligible ou historique insuffisant."
        )

    return len(selected)


# ============================================================
# NOUVEAUX PRONOSTICS : MATCHS DU JOUR UNIQUEMENT
# ============================================================

def create_today_bets(state, all_matches):
    created = 0
    candidates = []
    today = local_date()

    for competition_code, matches in all_matches.items():
        if matches is None:
            continue

        finished_matches = [
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

            home_stats = get_team_statistics(
                finished_matches,
                home_id,
            )

            away_stats = get_team_statistics(
                finished_matches,
                away_id,
            )

            if (
                home_stats["matches"] < MIN_HISTORY_MATCHES
                or away_stats["matches"] < MIN_HISTORY_MATCHES
            ):
                continue

            analysis = analyze_match(
                home_stats,
                away_stats
            )

            prediction = select_prediction(analysis)

            if prediction is None:
                continue

            candidate_id = make_bet_id(
                match.get("id"),
                prediction["market"]
            )

            if candidate_id in get_existing_bet_ids(state):
                continue

            candidates.append({
                "match": match,
                "competition_code": competition_code,
                "prediction": prediction,
            })

    # Priorité aux pronostics dont la probabilité estimée est la plus élevée.
    candidates.sort(
        key=lambda item: item["prediction"]["probability"],
        reverse=True
    )

    remaining = max(
        0,
        MAX_NEW_BETS_PER_DAY - count_bets_today(state)
    )

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
        f"Nouveaux paris créés aujourd'hui : {created}. "
        f"Limite quotidienne : {MAX_NEW_BETS_PER_DAY}."
    )

    return created


# ============================================================
# BILAN ET STATISTIQUES
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

    settled = won + lost

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

    backtests = state["backtests"]

    bt_won = sum(
        1 for item in backtests
        if item.get("status") == "WON"
    )

    bt_lost = sum(
        1 for item in backtests
        if item.get("status") == "LOST"
    )

    bt_profit = round_money(
        sum(
            safe_float(item.get("profit_simulated"))
            for item in backtests
        )
    )

    log("=" * 55)
    log("BILAN FOOT AI PRO BOT V9")
    log(f"Date française : {local_date()}")
    log(f"Capital initial : {initial:.2f} €")
    log(f"Capital virtuel : {bankroll:.2f} €")
    log(f"Profit net des paris réglés : {total_profit:.2f} €")
    log(f"Paris gagnés : {won}")
    log(f"Paris perdus : {lost}")
    log(f"Paris en attente : {pending}")

    if settled:
        log(f"Taux de réussite : {won / settled:.1%}")
    else:
        log("Taux de réussite : aucun résultat réglé.")

    log("--- SIMULATIONS RETROSPECTIVES ---")
    log(f"Simulations enregistrées : {len(backtests)}")
    log(f"Simulations gagnantes : {bt_won}")
    log(f"Simulations perdantes : {bt_lost}")
    log(f"Profit simulé cumulé : {bt_profit:+.2f} €")

    if bt_won + bt_lost:
        log(
            "Taux de réussite rétrospectif : "
            f"{bt_won / (bt_won + bt_lost):.1%}"
        )

    log("=" * 55)


# ============================================================
# EXECUTION PRINCIPALE
# ============================================================

def main():
    log("Démarrage de FOOT AI PRO BOT V9.")
    log("Mode simulation virtuelle uniquement.")
    log("Nouveaux paris : matchs du jour uniquement.")

    if not get_api_key():
        raise RuntimeError(
            "Clé API manquante. Ajoute le secret "
            "FOOTBALL_DATA_API_KEY dans GitHub Secrets."
        )

    state = load_state()
    all_matches = {}

    # 1. Récupération des rencontres de chaque compétition.
    for index, competition_code in enumerate(COMPETITIONS):
        log(
            f"Récupération : {COMPETITIONS[competition_code]}"
        )

        matches = fetch_competition_matches(competition_code)
        all_matches[competition_code] = matches

        # 2. Règlement des anciens paris en attente.
        if matches is not None:
            settle_finished_matches(state, matches)

        save_state(state)

        if index < len(COMPETITIONS) - 1:
            time.sleep(API_DELAY_SECONDS)

    # 3. Simulation rétrospective des matchs d'hier.
    log("Démarrage des simulations rétrospectives.")

    create_yesterday_backtests(
        state,
        all_matches
    )

    save_state(state)

    # 4. Nouveaux paris : aujourd'hui uniquement.
    log("Analyse des matchs du jour.")

    create_today_bets(
        state,
        all_matches
    )

    # 5. Sauvegarde finale et bilan.
    save_state(state)
    print_statistics(state)

    log("Exécution terminée.")


if __name__ == "__main__":
    main()