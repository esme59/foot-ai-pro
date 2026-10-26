#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FOOT AI PRO V13
Simulation virtuelle uniquement : aucun pari réel.
API : football-data.org v4
Marchés autorisés : BTTS Oui/Non et Over/Under 2.5 buts.
"""

import json
import math
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

API_BASE = "https://api.football-data.org/v4"
PARIS_TZ = ZoneInfo("Europe/Paris")

COMPETITIONS = ["FL1", "PL", "PD", "BL1", "SA", "CL"]

INITIAL_BANKROLL = 100.0
MAX_NEW_BETS_PER_DAY = 5
STAKE_FRACTION = 0.02
MAX_STAKE = 2.0
MIN_PROBABILITY = 0.60
MAX_PROBABILITY = 0.90
API_PAUSE_SECONDS = 6.5
REQUEST_TIMEOUT = 25

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
BANKROLL_FILE = DATA_DIR / "bankroll.json"
ANALYSES_FILE = DATA_DIR / "analyses.json"
REPORT_FILE = ROOT / "analyses.md"

API_KEY = (
    os.getenv("FOOTBALL_DATA_API_KEY")
    or os.getenv("FOOTBALL_API_KEY")
    or os.getenv("FOOTBALL_DATA_TOKEN")
    or ""
).strip()


def now_local():
    return datetime.now(PARIS_TZ)


def now_utc():
    return datetime.now(timezone.utc)


def default_state():
    return {
        "version": 1,
        "bankroll_initiale": INITIAL_BANKROLL,
        "bankroll_actuelle": INITIAL_BANKROLL,
        "benefice_total": 0.0,
        "mises_totales": 0.0,
        "gains_totaux": 0.0,
        "mises_en_cours": 0.0,
        "paris": [],
        "last_updated": None,
    }


def load_state():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not BANKROLL_FILE.exists():
        state = default_state()
        save_state(state)
        return state

    try:
        with BANKROLL_FILE.open("r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        state = default_state()

    defaults = default_state()
    for key, value in defaults.items():
        state.setdefault(key, value)
    if not isinstance(state.get("paris"), list):
        state["paris"] = []
    # Respecte le capital initial déjà enregistré dans le fichier.
    try:
        state["bankroll_initiale"] = float(state.get("bankroll_initiale", INITIAL_BANKROLL))
    except (TypeError, ValueError):
        state["bankroll_initiale"] = INITIAL_BANKROLL
    return state


def save_state(state):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state["last_updated"] = now_local().isoformat()
    temp_file = BANKROLL_FILE.with_suffix(".tmp")
    with temp_file.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    temp_file.replace(BANKROLL_FILE)


def api_get(path, params=None):
    if not API_KEY:
        raise RuntimeError(
            "Clé API manquante : ajoute FOOTBALL_DATA_API_KEY dans les Secrets GitHub."
        )
    headers = {"X-Auth-Token": API_KEY}
    response = requests.get(
        f"{API_BASE}{path}",
        headers=headers,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code == 429:
        raise RuntimeError("Limite API atteinte (HTTP 429). Réessaie au prochain lancement.")
    if response.status_code == 403:
        raise RuntimeError("Accès refusé par l'API (HTTP 403) : vérifie l'accès à la compétition/saison.")
    response.raise_for_status()
    return response.json()


def fetch_upcoming_matches():
    start_date = now_local().date()
    end_date = start_date + timedelta(days=7)
    matches = []
    seen_ids = set()

    for index, competition in enumerate(COMPETITIONS):
        try:
            data = api_get(
                f"/competitions/{competition}/matches",
                {
                    "dateFrom": start_date.isoformat(),
                    "dateTo": end_date.isoformat(),
                    "status": "SCHEDULED",
                },
            )
            for match in data.get("matches", []):
                match_id = match.get("id")
                if match_id and match_id not in seen_ids:
                    match["_competition_code"] = competition
                    matches.append(match)
                    seen_ids.add(match_id)
        except Exception as exc:
            print(f"[AVERTISSEMENT] {competition}: {exc}")
        if index < len(COMPETITIONS) - 1:
            time.sleep(API_PAUSE_SECONDS)

    return sorted(matches, key=lambda m: m.get("utcDate", ""))


def fetch_team_history(team_id, before_date, limit=10):
    data = api_get(
        f"/teams/{team_id}/matches",
        {
            "status": "FINISHED",
            "dateTo": before_date[:10],
            "limit": limit,
        },
    )
    return data.get("matches", [])


def average(values):
    return sum(values) / len(values) if values else 0.0


def poisson_probability(lam, goals):
    if lam <= 0:
        return 1.0 if goals == 0 else 0.0
    return math.exp(-lam) * (lam ** goals) / math.factorial(goals)


def poisson_distribution(lam, max_goals=10):
    probabilities = [poisson_probability(lam, goals) for goals in range(max_goals + 1)]
    total = sum(probabilities)
    return [p / total for p in probabilities] if total else probabilities


def team_goal_rates(team_id, is_home, opponent_id, match_date):
    history = fetch_team_history(team_id, match_date, limit=10)
    goals_for = []
    goals_against = []

    for match in history:
        home = match.get("homeTeam", {})
        away = match.get("awayTeam", {})
        score = match.get("score", {}).get("fullTime", {})
        home_goals = score.get("home")
        away_goals = score.get("away")
        if home_goals is None or away_goals is None:
            continue

        if home.get("id") == team_id:
            goals_for.append(float(home_goals))
            goals_against.append(float(away_goals))
        elif away.get("id") == team_id:
            goals_for.append(float(away_goals))
            goals_against.append(float(home_goals))

    if len(goals_for) < 4:
        return None

    # Pondération légère en faveur de la moyenne générale des 10 derniers matchs.
    scored = average(goals_for)
    conceded = average(goals_against)
    if is_home:
        scored *= 1.08
    else:
        scored *= 0.92

    return max(0.15, min(scored, 3.5)), max(0.15, min(conceded, 3.5))


def predict_match(match):
    home = match.get("homeTeam", {})
    away = match.get("awayTeam", {})
    home_id, away_id = home.get("id"), away.get("id")
    match_date = match.get("utcDate", "")

    if not home_id or not away_id or not match_date:
        return None

    try:
        home_rates = team_goal_rates(home_id, True, away_id, match_date)
        time.sleep(0.15)
        away_rates = team_goal_rates(away_id, False, home_id, match_date)
    except Exception as exc:
        print(f"[AVERTISSEMENT] Historique indisponible pour {home.get('name')} - {away.get('name')}: {exc}")
        return None

    if not home_rates or not away_rates:
        return None

    # Estimation prudente : attaque d'une équipe et défense adverse.
    league_home_baseline = 1.45
    league_away_baseline = 1.15
    lambda_home = math.sqrt(home_rates[0] * away_rates[1] * league_home_baseline / 1.45)
    lambda_away = math.sqrt(away_rates[0] * home_rates[1] * league_away_baseline / 1.15)
    lambda_home = max(0.15, min(lambda_home, 4.0))
    lambda_away = max(0.15, min(lambda_away, 4.0))

    home_dist = poisson_distribution(lambda_home)
    away_dist = poisson_distribution(lambda_away)

    p_btts_yes = 0.0
    p_over_25 = 0.0
    p_home_goals_zero = home_dist[0]
    p_away_goals_zero = away_dist[0]

    for hg, ph in enumerate(home_dist):
        for ag, pa in enumerate(away_dist):
            p = ph * pa
            if hg >= 1 and ag >= 1:
                p_btts_yes += p
            if hg + ag >= 3:
                p_over_25 += p

    p_btts_no = 1.0 - p_btts_yes
    p_under_25 = 1.0 - p_over_25
    probs = {
        "BTTS Oui": p_btts_yes,
        "BTTS Non": p_btts_no,
        "Over 2.5": p_over_25,
        "Under 2.5": p_under_25,
    }

    return {
        "home_team": home.get("name", "Domicile"),
        "away_team": away.get("name", "Extérieur"),
        "match_id": match.get("id"),
        "competition": match.get("_competition_code", match.get("competition", {}).get("code", "")),
        "utc_date": match_date,
        "lambda_home": round(lambda_home, 3),
        "lambda_away": round(lambda_away, 3),
        "probabilities": {k: round(v, 4) for k, v in probs.items()},
        "best_market": max(probs, key=probs.get),
        "best_probability": round(max(probs.values()), 4),
    }


def market_won(market, home_goals, away_goals):
    total = home_goals + away_goals
    if market == "BTTS Oui":
        return home_goals >= 1 and away_goals >= 1
    if market == "BTTS Non":
        return home_goals == 0 or away_goals == 0
    if market == "Over 2.5":
        return total >= 3
    if market == "Under 2.5":
        return total <= 2
    return False


def recompute_totals(state):
    initial = float(state.get("bankroll_initiale", INITIAL_BANKROLL))
    settled_profit = 0.0
    total_stakes = 0.0
    total_payouts = 0.0
    open_stakes = 0.0

    for bet in state.get("paris", []):
        stake = float(bet.get("mise", 0.0))
        total_stakes += stake
        status = bet.get("statut", "EN_COURS")
        if status == "EN_COURS":
            open_stakes += stake
        elif status == "GAGNE":
            payout = float(bet.get("gain_brut", 0.0))
            total_payouts += payout
            settled_profit += payout - stake
        elif status == "PERDU":
            settled_profit -= stake

    state["bankroll_initiale"] = round(initial, 2)
    state["benefice_total"] = round(settled_profit, 2)
    state["mises_totales"] = round(total_stakes, 2)
    state["gains_totaux"] = round(total_payouts, 2)
    state["mises_en_cours"] = round(open_stakes, 2)
    state["bankroll_actuelle"] = round(initial + settled_profit - open_stakes, 2)


def place_virtual_bets(state, analyses):
    today = now_local().date().isoformat()
    bets_today = sum(
        1 for bet in state.get("paris", [])
        if str(bet.get("date_creation", ""))[:10] == today
    )
    remaining_slots = max(0, MAX_NEW_BETS_PER_DAY - bets_today)
    if remaining_slots == 0:
        print("[INFO] Limite de 5 nouveaux paris virtuels atteinte aujourd'hui.")
        return

    already_bet_match_ids = {
        str(bet.get("match_id")) for bet in state.get("paris", [])
        if bet.get("statut") in ("EN_COURS", "GAGNE", "PERDU")
    }
    available_bankroll = max(0.0, float(state.get("bankroll_actuelle", INITIAL_BANKROLL)))
    if available_bankroll < 1.0:
        print("[INFO] Capital disponible trop faible pour créer un pari.")
        return

    candidates = []
    allowed_markets = {"BTTS Oui", "BTTS Non", "Over 2.5", "Under 2.5"}

    for analysis in analyses:
        match_id = str(analysis.get("match_id"))
        if not match_id or match_id in already_bet_match_ids:
            continue
        probabilities = analysis.get("probabilities", {})
        allowed = [
            (market, float(probabilities.get(market, 0.0)))
            for market in allowed_markets
            if MIN_PROBABILITY <= float(probabilities.get(market, 0.0)) <= MAX_PROBABILITY
        ]
        if not allowed:
            continue
        market, probability = max(allowed, key=lambda item: item[1])
        candidates.append((probability, analysis, market))

    candidates.sort(key=lambda item: item[0], reverse=True)

    created = 0
    for probability, analysis, market in candidates:
        if created >= remaining_slots:
            break
        available_bankroll = max(0.0, float(state.get("bankroll_actuelle", INITIAL_BANKROLL)))
        stake = round(min(available_bankroll * STAKE_FRACTION, MAX_STAKE), 2)
        if stake < 1.0:
            break

        odds = round(1.0 / probability, 2) if probability > 0 else 0.0
        match_name = f"{analysis['home_team']} - {analysis['away_team']}"
        state.setdefault("paris", []).append({
            "id": f"{analysis.get('match_id')}-{market.replace(' ', '_')}",
            "match_id": analysis.get("match_id"),
            "match": match_name,
            "competition": analysis.get("competition", ""),
            "date_match": analysis.get("utc_date", ""),
            "date_creation": now_local().isoformat(),
            "marche": market,
            "probabilite": round(probability, 4),
            "cote_virtuelle": odds,
            "mise": stake,
            "gain_brut_potentiel": round(stake * odds, 2),
            "gain_brut": 0.0,
            "statut": "EN_COURS",
            "score_final": None,
        })
        # Réserver la mise immédiatement pour le calcul des prochains paris.
        state["bankroll_actuelle"] = round(available_bankroll - stake, 2)
        created += 1
        print(f"[PARI VIRTUEL] {match_name} | {market} | {probability:.1%} | mise {stake:.2f} €")

    if created == 0:
        print("[INFO] Aucun pari virtuel ne respecte le seuil de probabilité.")


def settle_bets(state, matches_by_id):
    changed = 0
    for bet in state.get("paris", []):
        if bet.get("statut") != "EN_COURS":
            continue
        match_id = bet.get("match_id")
        match = matches_by_id.get(str(match_id))
        if not match:
            continue

        status = match.get("status")
        if status != "FINISHED":
            continue

        score = match.get("score", {}).get("fullTime", {})
        home_goals, away_goals = score.get("home"), score.get("away")
        if home_goals is None or away_goals is None:
            continue

        won = market_won(bet.get("marche", ""), int(home_goals), int(away_goals))
        if won:
            odds = float(bet.get("cote_virtuelle", 0.0))
            bet["statut"] = "GAGNE"
            bet["gain_brut"] = round(float(bet.get("mise", 0.0)) * odds, 2)
        else:
            bet["statut"] = "PERDU"
            bet["gain_brut"] = 0.0
        bet["score_final"] = f"{home_goals}-{away_goals}"
        changed += 1
        print(f"[RÉSULTAT] {bet.get('match')} | {bet.get('marche')} | {bet['score_final']} | {bet['statut']}")

    if changed:
        print(f"[INFO] {changed} pari(s) virtuel(s) réglé(s).")


def fetch_recent_results_for_open_bets(state, matches_by_id):
    open_ids = {
        str(bet.get("match_id"))
        for bet in state.get("paris", [])
        if bet.get("statut") == "EN_COURS" and bet.get("match_id")
    }
    for match_id in open_ids:
        if match_id in matches_by_id:
            continue
        try:
            match_data = api_get(f"/matches/{match_id}")
            match = match_data.get("match", match_data)
            matches_by_id[match_id] = match
        except Exception as exc:
            print(f"[AVERTISSEMENT] Impossible de vérifier le match {match_id}: {exc}")
        time.sleep(1.0)


def build_report(state, analyses, api_errors=None):
    api_errors = api_errors or []
    lines = [
        "# FOOT AI PRO V13 — Simulation virtuelle",
        "",
        f"- Mise à jour : {now_local().strftime('%d/%m/%Y %H:%M')}",
        f"- Capital initial : {state['bankroll_initiale']:.2f} €",
        f"- Capital disponible : {state['bankroll_actuelle']:.2f} €",
        f"- Bénéfice/perte net(te) : {state['benefice_total']:+.2f} €",
        f"- Mises virtuelles cumulées : {state['mises_totales']:.2f} €",
        f"- Mises en cours : {state['mises_en_cours']:.2f} €",
        "",
        "## Marchés autorisés",
        "- BTTS Oui / Non (les deux équipes marquent)",
        "- Over 2.5 / Under 2.5 buts",
        "",
        "## Pronostics à venir",
        "",
    ]

    if analyses:
        for a in analyses:
            lines.append(f"### {a['home_team']} - {a['away_team']}")
            lines.append(f"- Compétition : {a.get('competition', '')}")
            lines.append(f"- Date : {a.get('utc_date', '')}")
            lines.append(f"- BTTS Oui : {a['probabilities']['BTTS Oui']:.1%}")
            lines.append(f"- BTTS Non : {a['probabilities']['BTTS Non']:.1%}")
            lines.append(f"- Over 2.5 : {a['probabilities']['Over 2.5']:.1%}")
            lines.append(f"- Under 2.5 : {a['probabilities']['Under 2.5']:.1%}")
            lines.append("")
    else:
        lines.append("Aucun match analysable trouvé. Vérifie la clé API, les limites et les historiques disponibles.")
        lines.append("")

    lines += ["## Paris virtuels en cours", ""]
    open_bets = [b for b in state.get("paris", []) if b.get("statut") == "EN_COURS"]
    if open_bets:
        for b in open_bets:
            lines.append(
                f"- {b.get('match')} | {b.get('marche')} | "
                f"{float(b.get('probabilite', 0)):.1%} | mise {float(b.get('mise', 0)):.2f} € | "
                f"cote virtuelle {float(b.get('cote_virtuelle', 0)):.2f}"
            )
    else:
        lines.append("Aucun pari virtuel en cours.")
    lines.append("")

    lines += ["## Derniers résultats", ""]
    settled = [b for b in state.get("paris", []) if b.get("statut") in ("GAGNE", "PERDU")]
    for b in settled[-20:][::-1]:
        lines.append(
            f"- {b.get('date_match', '')[:10]} | {b.get('match')} | {b.get('marche')} | "
            f"{b.get('score_final')} | {b.get('statut')} | mise {float(b.get('mise', 0)):.2f} €"
        )
    if not settled:
        lines.append("Pas encore de paris réglés.")
    lines.append("")

    if api_errors:
        lines += ["## Avertissements API", ""]
        lines.extend(f"- {e}" for e in api_errors)
        lines.append("")

    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")


def save_analyses(analyses):
    with ANALYSES_FILE.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "version": 13,
                "updated_at": now_local().isoformat(),
                "markets": ["BTTS Oui", "BTTS Non", "Over 2.5", "Under 2.5"],
                "matches": analyses,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


def main():
    print("=" * 60)
    print("FOOT AI PRO V13 — SIMULATION VIRTUELLE")
    print("Capital initial : 100.00 €")
    print("Marchés : BTTS Oui/Non et Over/Under 2.5")
    print("=" * 60)

    if not API_KEY:
        raise RuntimeError(
            "Clé API manquante : ajoute FOOTBALL_DATA_API_KEY dans Settings > Secrets and variables > Actions."
        )

    state = load_state()
    # Garantit le capital initial à 100 € seulement pour un fichier de départ vierge.
    # Si un état existant a déjà un capital initial enregistré, on le conserve.
    matches = fetch_upcoming_matches()
    matches_by_id = {}
    api_errors = []

    # Récupère aussi les matchs récents pour régler les paris en cours.
    for match in matches:
        if match.get("id"):
            matches_by_id[str(match["id"])] = match

    # Endpoint séparé pour retrouver les résultats des paris en cours.
    fetch_recent_results_for_open_bets(state, matches_by_id)
    settle_bets(state, matches_by_id)

    analyses = []
    for index, match in enumerate(matches):
        try:
            analysis = predict_match(match)
            if analysis:
                analyses.append(analysis)
        except Exception as exc:
            message = f"{match.get('homeTeam', {}).get('name', '?')} - {match.get('awayTeam', {}).get('name', '?')}: {exc}"
            api_errors.append(message)
            print(f"[AVERTISSEMENT] {message}")
        if index < len(matches) - 1:
            time.sleep(0.5)

    save_analyses(analyses)
    recompute_totals(state)
    place_virtual_bets(state, analyses)
    recompute_totals(state)
    save_state(state)
    build_report(state, analyses, api_errors)

    print(f"Matches analysés : {len(analyses)}")
    print(f"Capital disponible : {state['bankroll_actuelle']:.2f} €")
    print(f"Bénéfice/perte net(te) : {state['benefice_total']:+.2f} €")
    print(f"Paris virtuels en cours : {sum(1 for b in state.get('paris', []) if b.get('statut') == 'EN_COURS')}")
    print("Terminé.")


if __name__ == "__main__":
    main()
