import os
import json
import math
import time
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

# ============================================================
# FOOT AI PRO BOT V12
# Simulation virtuelle uniquement — aucun pari réel.
# API : football-data.org v4
# Compatible avec GitHub Actions. Aucune dépendance en plus
# de "requests".
#
# NOUVEAUTES V12 (par rapport à la V10) :
#  1. Poisson avec forces d'attaque / défense (pondérées par
#     la récence), avantage du terrain et correction
#     Dixon-Coles sur les petits scores.
#  2. Analyse de la forme (5 derniers matchs).
#  3. Apprentissage automatique léger : calibration
#     adaptative de chaque marché d'après les résultats
#     réels récents (sans bibliothèque externe).
#  4. Sélection multi-marchés : avantage vs fréquence réelle
#     de la ligue, pénalité de répétition, plafond par marché.
#  5. Tests historiques walk-forward (rapport enregistré
#     dans le JSON) + backtests d'hier comme en V10.
# ============================================================

API_BASE = "https://api.football-data.org/v4"
STATE_FILE = Path(os.environ.get("BOT_STATE_FILE", "data/bankroll.json"))

INITIAL_BANKROLL = 20.0
MAX_STAKE = 1.0
MAX_NEW_BETS_PER_DAY = 6
MAX_BACKTESTS_PER_DAY = 6
MAX_SAME_MARKET_PER_DAY = 2

LOOKBACK_DAYS = 100
MAX_GOALS = 10
MIN_HISTORY_MATCHES = 4
MIN_MODEL_MATCHES = 40

MIN_PROBABILITY = 0.60
MAX_PROBABILITY = 0.92
MIN_LIFT = 0.03

HALF_LIFE_DAYS = 40
FORM_MATCHES = 5
FORM_WEIGHT = 0.10
SHRINK = 3.0
DC_RHO = -0.06

REPORT_DAYS = 21
CALIBRATION_PRIOR = 30
MAX_CALIBRATION_SHIFT = 0.10

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

MARKETS = [
    "1", "N", "2", "1X", "X2", "12",
    "Over 0.5", "Over 1.5", "Over 2.5", "Over 3.5",
    "Under 1.5", "Under 2.5", "Under 3.5",
    "BTTS Oui", "BTTS Non",
]

# Over 0.5 est exclu de la sélection automatique : choisi presque
# toujours, il n'apporte aucune information.
EXCLUDED_MARKETS = {"Over 0.5"}

HEADERS = {
    "User-Agent": "FOOT-AI-PRO-V12-Virtual-Simulation"
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


def clamp(value, low, high):
    return max(low, min(value, high))


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


def day_cutoff(day):
    """Début de journée (heure française) converti en UTC."""
    return datetime.combine(
        day,
        datetime.min.time(),
        tzinfo=LOCAL_TZ,
    ).astimezone(timezone.utc)


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
        "version": 12,
        "bankroll": INITIAL_BANKROLL,
        "initial_bankroll": INITIAL_BANKROLL,
        "bets": [],
        "history": [],
        "backtests": [],
        "backtest_report": {},
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
        state.setdefault("version", 12)
        state.setdefault("bets", [])
        state.setdefault("history", [])
        state.setdefault("backtests", [])
        state.setdefault("backtest_report", {})
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

        state["version"] = 12

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
# MARCHES
# ============================================================

def market_outcomes(home_goals, away_goals):
    """Pour un score donné, indique quels marchés sont gagnants."""
    total = home_goals + away_goals

    return {
        "1": home_goals > away_goals,
        "N": home_goals == away_goals,
        "2": away_goals > home_goals,
        "1X": home_goals >= away_goals,
        "X2": away_goals >= home_goals,
        "12": home_goals != away_goals,
        "Over 0.5": total >= 1,
        "Over 1.5": total >= 2,
        "Over 2.5": total >= 3,
        "Over 3.5": total >= 4,
        "Under 1.5": total <= 1,
        "Under 2.5": total <= 2,
        "Under 3.5": total <= 3,
        "BTTS Oui": home_goals > 0 and away_goals > 0,
        "BTTS Non": home_goals == 0 or away_goals == 0,
    }


def evaluate_market(bet, home_goals, away_goals):
    return market_outcomes(home_goals, away_goals).get(
        bet.get("market")
    )


# ============================================================
# DONNEES HISTORIQUES
# ============================================================

def extract_results(matches):
    """Transforme les matchs API en liste simple de résultats."""
    results = []

    for match in matches or []:
        if match.get("status") != "FINISHED":
            continue

        kickoff = parse_datetime(match.get("utcDate"))

        if kickoff is None:
            continue

        home = match.get("homeTeam") or {}
        away = match.get("awayTeam") or {}

        if home.get("id") is None or away.get("id") is None:
            continue

        full_time = (
            (match.get("score") or {}).get("fullTime") or {}
        )

        hg = full_time.get("home")
        ag = full_time.get("away")

        if hg is None or ag is None:
            continue

        results.append({
            "id": match.get("id"),
            "date": kickoff,
            "home": home["id"],
            "away": away["id"],
            "home_name": home.get("name", "Équipe domicile"),
            "away_name": away.get("name", "Équipe extérieure"),
            "hg": int(hg),
            "ag": int(ag),
        })

    results.sort(key=lambda item: item["date"])

    return results


def base_rates(results):
    """Fréquence réelle de chaque marché dans la ligue."""
    if not results:
        return {}

    totals = Counter()

    for item in results:
        for market, won in market_outcomes(
            item["hg"], item["ag"]
        ).items():
            if won:
                totals[market] += 1

    return {
        market: totals[market] / len(results)
        for market in MARKETS
    }


# ============================================================
# MOTEUR : FORCES D'ATTAQUE / DEFENSE + FORME
# ============================================================

def fit_model(results, now):
    """Ajuste le modèle sur les résultats passés."""
    if len(results) < MIN_MODEL_MATCHES:
        return None

    decay = math.log(2) / HALF_LIFE_DAYS

    weights = [
        math.exp(
            -decay * max(
                (now - item["date"]).total_seconds() / 86400.0,
                0.0,
            )
        )
        for item in results
    ]

    total_weight = sum(weights)

    if total_weight <= 0:
        return None

    mu_home = max(
        0.3,
        sum(w * item["hg"] for w, item in zip(weights, results))
        / total_weight,
    )

    mu_away = max(
        0.3,
        sum(w * item["ag"] for w, item in zip(weights, results))
        / total_weight,
    )

    by_team = defaultdict(list)

    for weight, item in zip(weights, results):
        by_team[item["home"]].append((weight, item, True))
        by_team[item["away"]].append((weight, item, False))

    attack = {team: 1.0 for team in by_team}
    defense = {team: 1.0 for team in by_team}

    for _ in range(15):
        for team, games in by_team.items():
            numerator = denominator = 0.0

            for weight, item, is_home in games:
                if is_home:
                    numerator += weight * item["hg"]
                    denominator += (
                        weight * mu_home * defense[item["away"]]
                    )
                else:
                    numerator += weight * item["ag"]
                    denominator += (
                        weight * mu_away * defense[item["home"]]
                    )

            attack[team] = (
                (numerator + SHRINK) / (denominator + SHRINK)
            )

        for team, games in by_team.items():
            numerator = denominator = 0.0

            for weight, item, is_home in games:
                if is_home:
                    numerator += weight * item["ag"]
                    denominator += (
                        weight * mu_away * attack[item["away"]]
                    )
                else:
                    numerator += weight * item["hg"]
                    denominator += (
                        weight * mu_home * attack[item["home"]]
                    )

            defense[team] = (
                (numerator + SHRINK) / (denominator + SHRINK)
            )

    # Forme : points pris sur les derniers matchs (0 à 1).
    form = {}
    counts = {}

    for team, games in by_team.items():
        counts[team] = len(games)

        last = sorted(
            games,
            key=lambda entry: entry[1]["date"],
        )[-FORM_MATCHES:]

        points = 0

        for _, item, is_home in last:
            goals_for = item["hg"] if is_home else item["ag"]
            goals_against = item["ag"] if is_home else item["hg"]

            if goals_for > goals_against:
                points += 3
            elif goals_for == goals_against:
                points += 1

        form[team] = points / (3.0 * len(last)) if last else 0.5

    return {
        "mu_home": mu_home,
        "mu_away": mu_away,
        "attack": attack,
        "defense": defense,
        "form": form,
        "counts": counts,
    }


def teams_have_history(model, home_id, away_id):
    counts = model["counts"]

    return (
        counts.get(home_id, 0) >= MIN_HISTORY_MATCHES
        and counts.get(away_id, 0) >= MIN_HISTORY_MATCHES
    )


def expected_goals(model, home_id, away_id):
    attack = model["attack"]
    defense = model["defense"]
    form = model["form"]

    home_lambda = (
        model["mu_home"]
        * attack.get(home_id, 1.0)
        * defense.get(away_id, 1.0)
    )

    away_lambda = (
        model["mu_away"]
        * attack.get(away_id, 1.0)
        * defense.get(home_id, 1.0)
    )

    home_lambda *= (
        1.0 + FORM_WEIGHT * 2.0 * (form.get(home_id, 0.5) - 0.5)
    )
    away_lambda *= (
        1.0 + FORM_WEIGHT * 2.0 * (form.get(away_id, 0.5) - 0.5)
    )

    return (
        clamp(home_lambda, 0.15, 4.0),
        clamp(away_lambda, 0.15, 4.0),
    )


# ============================================================
# POISSON + CORRECTION DIXON-COLES
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


def dixon_coles_tau(hg, ag, home_lambda, away_lambda):
    if hg == 0 and ag == 0:
        return 1.0 - home_lambda * away_lambda * DC_RHO
    if hg == 0 and ag == 1:
        return 1.0 + home_lambda * DC_RHO
    if hg == 1 and ag == 0:
        return 1.0 + away_lambda * DC_RHO
    if hg == 1 and ag == 1:
        return 1.0 - DC_RHO

    return 1.0


def analyze_match(model, home_id, away_id):
    home_lambda, away_lambda = expected_goals(
        model,
        home_id,
        away_id,
    )

    cells = []
    total_probability = 0.0

    for hg in range(MAX_GOALS + 1):
        ph = poisson_probability(home_lambda, hg)

        for ag in range(MAX_GOALS + 1):
            pa = poisson_probability(away_lambda, ag)

            p = max(
                0.0,
                ph * pa * dixon_coles_tau(
                    hg, ag, home_lambda, away_lambda
                ),
            )

            cells.append((hg, ag, p))
            total_probability += p

    if total_probability <= 0:
        return None

    markets = {market: 0.0 for market in MARKETS}

    best_score = "1-1"
    best_score_probability = -1.0

    for hg, ag, p in cells:
        p /= total_probability

        for market, won in market_outcomes(hg, ag).items():
            if won:
                markets[market] += p

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
# CALIBRATION ADAPTATIVE (APPRENTISSAGE LEGER)
# ============================================================

def calibrate(market, probability, calibration):
    """Corrige le biais moyen constaté sur ce marché."""
    if not calibration:
        return probability

    info = calibration.get(market)

    if not info or info.get("n", 0) <= 0:
        return probability

    reliability = info["n"] / (info["n"] + CALIBRATION_PRIOR)

    shift = clamp(
        info["hit_rate"] - info["mean_pred"],
        -MAX_CALIBRATION_SHIFT,
        MAX_CALIBRATION_SHIFT,
    )

    return clamp(probability + reliability * shift, 0.01, 0.99)


# ============================================================
# SELECTION MULTI-MARCHES
# ============================================================

def rank_candidates(analysis, rates, calibration, usage):
    """Classe les marchés intéressants d'un match."""
    candidates = []

    for market, raw_probability in analysis["markets"].items():
        if market in EXCLUDED_MARKETS:
            continue

        probability = calibrate(
            market,
            raw_probability,
            calibration,
        )

        if probability < MIN_PROBABILITY:
            continue

        if probability > MAX_PROBABILITY:
            continue

        base_rate = rates.get(market, 0.5)
        lift = probability - base_rate

        # Le marché doit faire mieux que sa fréquence habituelle.
        if lift < MIN_LIFT:
            continue

        score = probability + 0.5 * lift

        if market in ("1X", "X2", "12"):
            score -= 0.03

        score -= 0.03 * usage.get(market, 0)

        estimated_odds = clamp(1.0 / probability, 1.01, 10.0)

        candidates.append({
            "market": market,
            "probability": round(probability, 4),
            "raw_probability": round(raw_probability, 4),
            "base_rate": round(base_rate, 4),
            "lift": round(lift, 4),
            "odds": round(estimated_odds, 2),
            "score": score,
            "exact_score": analysis["exact_score"],
        })

    candidates.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    return candidates


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
        "engine": "V12",
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
        "raw_probability": prediction["raw_probability"],
        "base_rate": prediction["base_rate"],
        "lift": prediction["lift"],
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
        f"{bet['market']} | {prediction['probability']:.1%} | "
        f"avantage {prediction['lift']:+.1%}"
    )

    return True


def create_today_bets(state, all_matches, all_results, calibration):
    today = local_date()
    now = utc_now()

    existing_ids = get_existing_bet_ids(state)

    matches_with_bets = {
        str(bet.get("match_id"))
        for bet in state["bets"]
        if bet.get("match_id") is not None
    }

    usage = Counter(
        bet.get("market")
        for bet in state["bets"]
        if bet.get("created_date") == today
    )

    flat = []

    for competition_code, matches in all_matches.items():
        if not matches:
            continue

        results = all_results.get(competition_code, [])
        model = fit_model(results, now)

        if model is None:
            log(
                f"Données insuffisantes pour "
                f"{COMPETITIONS[competition_code]}."
            )
            continue

        rates = base_rates(results)

        for match in matches:
            if match.get("status") not in ("SCHEDULED", "TIMED"):
                continue

            if match_local_date(match) != today:
                continue

            if str(match.get("id")) in matches_with_bets:
                continue

            kickoff = parse_datetime(match.get("utcDate"))

            if kickoff is None or kickoff <= now:
                continue

            home = match.get("homeTeam") or {}
            away = match.get("awayTeam") or {}

            home_id = home.get("id")
            away_id = away.get("id")

            if not home_id or not away_id:
                continue

            if not teams_have_history(model, home_id, away_id):
                log(
                    f"Historique insuffisant : "
                    f"{home.get('name')} - {away.get('name')}"
                )
                continue

            analysis = analyze_match(model, home_id, away_id)

            if analysis is None:
                continue

            candidates = rank_candidates(
                analysis,
                rates,
                calibration,
                usage,
            )

            for candidate in candidates:
                bet_id = make_bet_id(
                    match.get("id"),
                    candidate["market"],
                )

                if bet_id in existing_ids:
                    continue

                flat.append({
                    "match": match,
                    "competition_code": competition_code,
                    "prediction": candidate,
                })

    flat.sort(
        key=lambda item: item["prediction"]["score"],
        reverse=True,
    )

    remaining = max(
        0,
        MAX_NEW_BETS_PER_DAY - count_bets_today(state),
    )

    created = 0
    used_matches = set()

    for item in flat:
        if created >= remaining:
            break

        match_key = str(item["match"].get("id"))
        market = item["prediction"]["market"]

        # Un seul pari par match et pas trop du même marché.
        if match_key in used_matches:
            continue

        if usage[market] >= MAX_SAME_MARKET_PER_DAY:
            continue

        if create_virtual_bet(
            state,
            item["match"],
            item["competition_code"],
            item["prediction"],
        ):
            created += 1
            used_matches.add(match_key)
            usage[market] += 1
            save_state(state)

    log(
        f"Nouveaux paris créés : {created}. "
        f"Limite quotidienne : {MAX_NEW_BETS_PER_DAY}."
    )

    return created


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
# TESTS HISTORIQUES (WALK-FORWARD)
# ============================================================

def model_for_day(results, day):
    """Modèle ajusté uniquement sur les matchs AVANT ce jour."""
    cutoff = day_cutoff(day)

    prior = [item for item in results if item["date"] < cutoff]

    model = fit_model(prior, cutoff)

    if model is None:
        return None, None

    return model, base_rates(prior)


def run_historical_backtest(all_results, days=REPORT_DAYS):
    """
    Compare les prédictions aux résultats réels des derniers jours.
    Chaque jour est prédit avec un modèle qui ne connaît que le passé.
    Retourne (rapport, calibration).
    """
    start_day = local_now().date() - timedelta(days=days)

    market_stats = {
        market: {"n": 0, "hits": 0, "pred_sum": 0.0}
        for market in MARKETS
    }

    picks = defaultdict(lambda: {"n": 0, "wins": 0})

    brier_sum = 0.0
    accuracy_hits = 0
    match_count = 0

    for results in all_results.values():
        by_day = defaultdict(list)

        for item in results:
            day = item["date"].astimezone(LOCAL_TZ).date()

            if day >= start_day:
                by_day[day].append(item)

        for day in sorted(by_day):
            model, rates = model_for_day(results, day)

            if model is None:
                continue

            for item in by_day[day]:
                if not teams_have_history(
                    model, item["home"], item["away"]
                ):
                    continue

                analysis = analyze_match(
                    model, item["home"], item["away"]
                )

                if analysis is None:
                    continue

                outcomes = market_outcomes(item["hg"], item["ag"])

                for market, probability in analysis["markets"].items():
                    stats = market_stats[market]
                    stats["n"] += 1
                    stats["hits"] += 1 if outcomes[market] else 0
                    stats["pred_sum"] += probability

                p1x2 = [
                    analysis["markets"]["1"],
                    analysis["markets"]["N"],
                    analysis["markets"]["2"],
                ]

                actual = (
                    0 if item["hg"] > item["ag"]
                    else 1 if item["hg"] == item["ag"]
                    else 2
                )

                for index in range(3):
                    target = 1.0 if index == actual else 0.0
                    brier_sum += (p1x2[index] - target) ** 2

                if p1x2.index(max(p1x2)) == actual:
                    accuracy_hits += 1

                match_count += 1

                ranked = rank_candidates(
                    analysis, rates, None, Counter()
                )

                if ranked:
                    market = ranked[0]["market"]
                    picks[market]["n"] += 1

                    if outcomes[market]:
                        picks[market]["wins"] += 1

    calibration = {}
    report_markets = {}

    for market, stats in market_stats.items():
        if stats["n"] <= 0:
            continue

        hit_rate = stats["hits"] / stats["n"]
        mean_pred = stats["pred_sum"] / stats["n"]

        calibration[market] = {
            "n": stats["n"],
            "hit_rate": hit_rate,
            "mean_pred": mean_pred,
        }

        report_markets[market] = {
            "n": stats["n"],
            "hit_rate": round(hit_rate, 4),
            "mean_pred": round(mean_pred, 4),
        }

    pick_total = sum(item["n"] for item in picks.values())
    pick_wins = sum(item["wins"] for item in picks.values())

    report = {
        "generated_at": utc_now().isoformat(),
        "days": days,
        "matches": match_count,
        "brier_1x2": (
            round(brier_sum / match_count, 4)
            if match_count else None
        ),
        "accuracy_1x2": (
            round(accuracy_hits / match_count, 4)
            if match_count else None
        ),
        "markets": report_markets,
        "picks": dict(picks),
        "picks_total": pick_total,
        "picks_win_rate": (
            round(pick_wins / pick_total, 4)
            if pick_total else None
        ),
    }

    return report, calibration


# ============================================================
# BACKTESTS D'HIER — SEPARES DE LA BANKROLL
# ============================================================

def backtest_id(match_id, market):
    return f"BACKTEST:{match_id}:{market}"


def create_yesterday_backtests(state, all_results):
    yesterday_date = local_now().date() - timedelta(days=1)
    yesterday = yesterday_date.isoformat()

    existing_ids = {
        item.get("backtest_id")
        for item in state["backtests"]
    }

    candidates = []

    for competition_code, results in all_results.items():
        yesterday_matches = [
            item for item in results
            if item["date"].astimezone(LOCAL_TZ).date()
            == yesterday_date
        ]

        if not yesterday_matches:
            continue

        model, rates = model_for_day(results, yesterday_date)

        if model is None:
            continue

        for item in yesterday_matches:
            if not teams_have_history(
                model, item["home"], item["away"]
            ):
                continue

            analysis = analyze_match(
                model, item["home"], item["away"]
            )

            if analysis is None:
                continue

            ranked = rank_candidates(
                analysis, rates, None, Counter()
            )

            if not ranked:
                continue

            prediction = ranked[0]
            unique_id = backtest_id(item["id"], prediction["market"])

            if unique_id in existing_ids:
                continue

            won = evaluate_market(
                {"market": prediction["market"]},
                item["hg"],
                item["ag"],
            )

            if won is None:
                continue

            candidates.append({
                "backtest_id": unique_id,
                "engine": "V12",
                "match_id": item["id"],
                "date": yesterday,
                "competition": competition_code,
                "competition_name": COMPETITIONS.get(
                    competition_code,
                    competition_code,
                ),
                "home_team": item["home_name"],
                "away_team": item["away_name"],
                "market": prediction["market"],
                "probability": prediction["probability"],
                "estimated_odds": prediction["odds"],
                "predicted_score": prediction["exact_score"],
                "actual_score": f"{item['hg']}-{item['ag']}",
                "stake_simulated": MAX_STAKE,
                "status": "WON" if won else "LOST",
                "profit_simulated": (
                    round_money(
                        MAX_STAKE * prediction["odds"] - MAX_STAKE
                    )
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

    report = state.get("backtest_report") or {}

    log("=" * 50)
    log("BILAN FOOT AI PRO BOT V12")
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

    if report.get("matches"):
        log(f"--- TEST HISTORIQUE ({report['days']} derniers jours) ---")
        log(f"Matchs analysés : {report['matches']}")
        log(
            f"Brier 1X2 : {report['brier_1x2']} "
            f"(hasard = 0.667, plus bas = mieux)"
        )
        log(f"Précision 1X2 : {report['accuracy_1x2']:.1%}")

        if report.get("picks_total"):
            log(
                f"Paris sélectionnés : {report['picks_total']} | "
                f"réussite {report['picks_win_rate']:.1%}"
            )

            for market, info in sorted(
                report["picks"].items(),
                key=lambda entry: -entry[1]["n"],
            ):
                log(
                    f"   {market:10s} {info['n']:3d} paris | "
                    f"{info['wins'] / info['n']:.1%}"
                )

    log("=" * 50)


# ============================================================
# EXECUTION
# ============================================================

def main():
    log("Démarrage FOOT AI PRO BOT V12.")
    log("Simulation virtuelle uniquement.")

    if not get_api_key():
        raise RuntimeError(
            "Clé API manquante : configure FOOTBALL_DATA_API_KEY."
        )

    state = load_state()
    all_matches = {}
    all_results = {}

    for index, code in enumerate(COMPETITIONS):
        log(f"Récupération : {COMPETITIONS[code]}")

        matches = fetch_competition_matches(code)
        all_matches[code] = matches
        all_results[code] = extract_results(matches)

        if matches is not None:
            settle_finished_matches(state, matches)

        save_state(state)

        if index < len(COMPETITIONS) - 1:
            time.sleep(API_DELAY_SECONDS)

    log("Test historique walk-forward et calibration.")
    report, calibration = run_historical_backtest(all_results)
    state["backtest_report"] = report
    save_state(state)

    log("Création des simulations rétrospectives.")
    create_yesterday_backtests(state, all_results)
    save_state(state)

    log("Création des nouveaux pronostics du jour.")
    create_today_bets(state, all_matches, all_results, calibration)

    save_state(state)
    print_statistics(state)

    log("Exécution terminée.")


if __name__ == "__main__":
    main()
