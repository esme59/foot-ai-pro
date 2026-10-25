#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FOOT AI PRO BOT V12 — version complète autonome
Simulation virtuelle uniquement : aucun pari réel.
API : football-data.org v4
Clé API attendue dans la variable d'environnement FOOTBALL_DATA_API_KEY
ou dans les secrets GitHub Actions.

Ce fichier peut être ajouté comme bot_v12.py afin de ne pas écraser bot.py.
Il produit data/analyses.md et conserve l'état virtuel dans data/bankroll.json.
"""

import json
import math
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# ------------------------- CONFIGURATION -------------------------

API_BASE = "https://api.football-data.org/v4"
API_KEY = (
    os.getenv("FOOTBALL_DATA_API_KEY")
    or os.getenv("FOOTBALL_API_KEY")
    or os.getenv("FOOTBALL_DATA_TOKEN")
    or ""
).strip()

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
STATE_FILE = DATA_DIR / "bankroll.json"
ANALYSES_FILE = DATA_DIR / "analyses.md"
LOG_FILE = DATA_DIR / "bot.log"

INITIAL_BANKROLL = 20.0
MAX_NEW_BETS_PER_RUN = 5
REQUEST_TIMEOUT = 20
API_PAUSE_SECONDS = 6
HISTORY_MATCHES = 10
HISTORY_DAYS = 180
MAX_GOALS = 10
LOCAL_TZ = ZoneInfo("Europe/Paris")

COMPETITIONS = {
    "FL1": "Ligue 1",
    "PL": "Premier League",
    "PD": "La Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "CL": "Ligue des champions",
}

# Markets shown in the report. Probabilities are model estimates, not guarantees.
MARKETS = [
    "1", "N", "2", "1X", "X2", "12",
    "Over 0.5", "Over 1.5", "Over 2.5", "Over 3.5",
    "Under 1.5", "Under 2.5", "Under 3.5",
    "BTTS Oui", "BTTS Non",
]

SESSION = requests.Session()
SESSION.headers.update({"X-Auth-Token": API_KEY} if API_KEY else {})


# ------------------------- OUTILS -------------------------

def log(message):
    stamp = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {message}"
    print(line, flush=True)
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def local_now():
    return datetime.now(LOCAL_TZ)


def local_date():
    return local_now().strftime("%Y-%m-%d")


def safe_float(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def read_json(path, default):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    temporary.replace(path)


def default_state():
    return {
        "bankroll_initiale": INITIAL_BANKROLL,
        "bankroll_actuelle": INITIAL_BANKROLL,
        "benefice_total": 0.0,
        "mises_totales": 0.0,
        "gains_totaux": 0.0,
        "paris": [],
        "historique": [],
        "last_updated": None,
    }


def load_state():
    state = read_json(STATE_FILE, default_state())
    defaults = default_state()
    for key, value in defaults.items():
        if key not in state:
            state[key] = value
    if not isinstance(state.get("paris"), list):
        state["paris"] = []
    if not isinstance(state.get("historique"), list):
        state["historique"] = []
    return state


def save_state(state):
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    write_json(STATE_FILE, state)


def api_get(endpoint, params=None):
    if not API_KEY:
        raise RuntimeError(
            "Clé API manquante. Ajoute FOOTBALL_DATA_API_KEY dans les secrets "
            "GitHub du dépôt."
        )
    url = f"{API_BASE}/{endpoint.lstrip('/')}"
    response = SESSION.get(url, params=params or {}, timeout=REQUEST_TIMEOUT)
    if response.status_code == 429:
        raise RuntimeError("Limite de requêtes API atteinte (HTTP 429). Réessaie plus tard.")
    if response.status_code == 403:
        raise RuntimeError(
            "Accès API refusé (HTTP 403). Vérifie les compétitions autorisées "
            "par ton abonnement football-data.org."
        )
    response.raise_for_status()
    return response.json()


# ------------------------- MODÈLE DE POISSON -------------------------

def poisson_probability(lam, goals):
    lam = max(0.001, min(float(lam), 8.0))
    return math.exp(-lam) * (lam ** goals) / math.factorial(goals)


def poisson_matrix(home_lambda, away_lambda):
    home_probs = [poisson_probability(home_lambda, g) for g in range(MAX_GOALS + 1)]
    away_probs = [poisson_probability(away_lambda, g) for g in range(MAX_GOALS + 1)]
    matrix = []
    for hg, hp in enumerate(home_probs):
        row = []
        for ag, ap in enumerate(away_probs):
            row.append(hp * ap)
        matrix.append(row)
    total = sum(sum(row) for row in matrix)
    if total > 0:
        matrix = [[p / total for p in row] for row in matrix]
    return matrix


def derive_markets(matrix):
    home_win = draw = away_win = over05 = over15 = over25 = over35 = 0.0
    under15 = under25 = under35 = btts_yes = 0.0

    for hg, row in enumerate(matrix):
        for ag, p in enumerate(row):
            if hg > ag:
                home_win += p
            elif hg == ag:
                draw += p
            else:
                away_win += p
            total_goals = hg + ag
            if total_goals >= 1:
                over05 += p
            if total_goals >= 2:
                over15 += p
            if total_goals >= 3:
                over25 += p
            if total_goals >= 4:
                over35 += p
            if total_goals <= 1:
                under15 += p
            if total_goals <= 2:
                under25 += p
            if total_goals <= 3:
                under35 += p
            if hg >= 1 and ag >= 1:
                btts_yes += p

    markets = {
        "1": home_win,
        "N": draw,
        "2": away_win,
        "1X": home_win + draw,
        "X2": away_win + draw,
        "12": home_win + away_win,
        "Over 0.5": over05,
        "Over 1.5": over15,
        "Over 2.5": over25,
        "Over 3.5": over35,
        "Under 1.5": under15,
        "Under 2.5": under25,
        "Under 3.5": under35,
        "BTTS Oui": btts_yes,
        "BTTS Non": 1.0 - btts_yes,
    }
    return {k: max(0.0, min(1.0, v)) for k, v in markets.items()}


def top_scores(matrix, limit=5):
    scores = []
    for hg, row in enumerate(matrix):
        for ag, probability in enumerate(row):
            scores.append({
                "score": f"{hg}-{ag}",
                "probability": probability,
            })
    scores.sort(key=lambda x: x["probability"], reverse=True)
    return scores[:limit]


# ------------------------- DONNÉES FOOTBALL -------------------------

def get_matches_for_competition(code, date_from, date_to):
    payload = api_get(
        f"competitions/{code}/matches",
        {"dateFrom": date_from, "dateTo": date_to},
    )
    return payload.get("matches", [])


def get_team_history(team_id, before_date):
    date_to = before_date.date().isoformat()
    date_from = (before_date.date() - timedelta(days=HISTORY_DAYS)).isoformat()
    payload = api_get(
        f"teams/{team_id}/matches",
        {
            "dateFrom": date_from,
            "dateTo": date_to,
            "status": "FINISHED",
            "limit": 50,
        },
    )
    matches = payload.get("matches", [])
    matches.sort(key=lambda m: m.get("utcDate", ""), reverse=True)
    return matches[:HISTORY_MATCHES]


def summarize_team_history(team_id, matches):
    scored = []
    conceded = []
    for match in matches:
        home_id = (match.get("homeTeam") or {}).get("id")
        away_id = (match.get("awayTeam") or {}).get("id")
        score = match.get("score", {}).get("fullTime") or {}
        hg, ag = score.get("home"), score.get("away")
        if hg is None or ag is None:
            continue
        if team_id == home_id:
            scored.append(float(hg))
            conceded.append(float(ag))
        elif team_id == away_id:
            scored.append(float(ag))
            conceded.append(float(hg))
    if not scored:
        return {"scored": 1.25, "conceded": 1.25, "count": 0, "form": "Données insuffisantes"}
    return {
        "scored": sum(scored) / len(scored),
        "conceded": sum(conceded) / len(conceded),
        "count": len(scored),
        "form": f"{len(scored)} matchs analysés",
    }


def team_form_string(team_id, matches):
    results = []
    for match in matches:
        home_id = (match.get("homeTeam") or {}).get("id")
        away_id = (match.get("awayTeam") or {}).get("id")
        score = match.get("score", {}).get("fullTime") or {}
        hg, ag = score.get("home"), score.get("away")
        if hg is None or ag is None:
            continue
        if team_id == home_id:
            results.append("V" if hg > ag else "N" if hg == ag else "D")
        elif team_id == away_id:
            results.append("V" if ag > hg else "N" if ag == hg else "D")
        if len(results) >= 5:
            break
    return " ".join(results) if results else "Indisponible"


def analyze_match(match, competition_code):
    home = match.get("homeTeam") or {}
    away = match.get("awayTeam") or {}
    home_id, away_id = home.get("id"), away.get("id")
    if not home_id or not away_id:
        return None

    kickoff_text = match.get("utcDate")
    if not kickoff_text:
        return None
    kickoff = datetime.fromisoformat(kickoff_text.replace("Z", "+00:00"))
    kickoff_local = kickoff.astimezone(LOCAL_TZ)

    home_history = get_team_history(home_id, kickoff)
    time.sleep(API_PAUSE_SECONDS)
    away_history = get_team_history(away_id, kickoff)
    time.sleep(API_PAUSE_SECONDS)

    home_stats = summarize_team_history(home_id, home_history)
    away_stats = summarize_team_history(away_id, away_history)

    # Modèle simple fondé sur les buts marqués/encaissés récents.
    # Le facteur domicile est modéré pour éviter des prédictions extrêmes.
    home_lambda = (home_stats["scored"] * 0.55 + away_stats["conceded"] * 0.45) * 1.08
    away_lambda = (away_stats["scored"] * 0.55 + home_stats["conceded"] * 0.45) * 0.94
    home_lambda = max(0.15, min(home_lambda, 4.0))
    away_lambda = max(0.15, min(away_lambda, 4.0))

    matrix = poisson_matrix(home_lambda, away_lambda)
    markets = derive_markets(matrix)
    sorted_markets = sorted(markets.items(), key=lambda kv: kv[1], reverse=True)
    best_picks = [
        {"market": market, "probability": prob, "lift": 0.0}
        for market, prob in sorted_markets[:3]
    ]
    probable = top_scores(matrix, 5)
    best_outcome = max(("1", markets["1"]), ("N", markets["N"]), ("2", markets["2"]), key=lambda x: x[1])

    if home_stats["count"] < 3 or away_stats["count"] < 3:
        summary = "Données historiques limitées : interpréter avec prudence."
        confidence = "Faible"
    else:
        summary = f"Le modèle estime {home_lambda:.2f} but(s) pour {home.get('name', 'Domicile')} et {away_lambda:.2f} pour {away.get('name', 'Extérieur')}."
        confidence = "Indicative — non calibrée"

    return {
        "id": match.get("id"),
        "date": kickoff_local.strftime("%Y-%m-%d"),
        "kickoff_local": kickoff_local.strftime("%H:%M"),
        "competition_code": competition_code,
        "competition_name": COMPETITIONS.get(competition_code, competition_code),
        "home_team": home.get("name", "Domicile"),
        "away_team": away.get("name", "Extérieur"),
        "status": match.get("status", "SCHEDULED"),
        "all_markets": {k: round(v, 5) for k, v in markets.items()},
        "expected_goals": {"home": round(home_lambda, 3), "away": round(away_lambda, 3)},
        "top_scores": [{"score": s["score"], "probability": round(s["probability"], 5)} for s in probable],
        "probable_score": probable[0]["score"] if probable else "-",
        "form": {
            "home": team_form_string(home_id, home_history),
            "away": team_form_string(away_id, away_history),
        },
        "goal_averages": {
            "home": {"scored": round(home_stats["scored"], 2), "conceded": round(home_stats["conceded"], 2)},
            "away": {"scored": round(away_stats["scored"], 2), "conceded": round(away_stats["conceded"], 2)},
        },
        "strengths": {
            "home_attack": round(home_stats["scored"], 2),
            "home_defense": round(home_stats["conceded"], 2),
            "away_attack": round(away_stats["scored"], 2),
            "away_defense": round(away_stats["conceded"], 2),
        },
        "best_picks": best_picks,
        "decision": f"{best_outcome[0]} ({best_outcome[1]:.1%})",
        "confidence": confidence,
        "summary": summary,
        "bet_placed": False,
    }


# ------------------------- RAPPORT COMPLET -------------------------

MARKET_LABELS = [
    ("1", "Victoire de l'équipe à domicile"),
    ("N", "Match nul"),
    ("2", "Victoire de l'équipe à l'extérieur"),
    ("1X", "Double chance : domicile ou nul"),
    ("X2", "Double chance : extérieur ou nul"),
    ("12", "Une équipe gagne"),
    ("Over 0.5", "Plus de 0,5 but"),
    ("Over 1.5", "Plus de 1,5 but"),
    ("Over 2.5", "Plus de 2,5 buts"),
    ("Over 3.5", "Plus de 3,5 buts"),
    ("Under 1.5", "Moins de 1,5 but"),
    ("Under 2.5", "Moins de 2,5 buts"),
    ("Under 3.5", "Moins de 3,5 buts"),
    ("BTTS Oui", "Les deux équipes marquent : OUI"),
    ("BTTS Non", "Les deux équipes marquent : NON"),
]


def write_analyses_markdown(analyses):
    """Écrit toutes les probabilités de marché pour chaque match analysé."""
    lines = [
        f"# FOOT AI PRO BOT V12 — Analyses détaillées du {local_date()}",
        "",
        "> Simulation virtuelle uniquement — aucun pari réel.",
        "",
        f"**Matchs analysés :** {analyses.get('count', 0)}",
        "",
        "**Important :** les pourcentages sont des estimations mathématiques, pas des garanties.",
        "",
    ]

    current_day = None
    for item in analyses.get("matches", []):
        if item.get("date") != current_day:
            current_day = item.get("date")
            lines.extend(["", "---", "", f"# 📅 Matchs du {current_day}", ""])

        probabilities = item.get("all_markets", {})
        expected_goals = item.get("expected_goals", {})
        scores = item.get("top_scores", [])
        averages = item.get("goal_averages", {})
        form = item.get("form", {})
        strengths = item.get("strengths", {})
        home = item.get("home_team", "Domicile")
        away = item.get("away_team", "Extérieur")

        lines.extend([
            f"## ⚽ {item.get('kickoff_local', '--:--')} — {home} vs {away}",
            "",
            f"**Compétition :** {item.get('competition_name', '-')}",
            "",
            f"**Résumé :** {item.get('summary', '-')}",
            "",
            "### 📊 Pourcentage estimé de chaque marché",
            "",
            "| Marché | Probabilité estimée |",
            "|---|---:|",
        ])
        for market, label in MARKET_LABELS:
            probability = probabilities.get(market)
            if probability is not None:
                lines.append(f"| {label} | **{safe_float(probability):.1%}** |")

        lines.extend(["", "### 🎯 Scores exacts les plus probables", ""])
        if scores:
            for score in scores:
                lines.append(f"- **{score.get('score', '?')}** : {safe_float(score.get('probability')):.1%}")
        else:
            lines.append("- Aucun score disponible.")

        lines.extend([
            "", "### ⚽ Buts attendus par le modèle", "",
            f"- **{home} :** {safe_float(expected_goals.get('home')):.2f} but(s)",
            f"- **{away} :** {safe_float(expected_goals.get('away')):.2f} but(s)",
            "", "### 📈 Forme récente", "",
            f"- **{home} :** {form.get('home', '-')}",
            f"- **{away} :** {form.get('away', '-')}",
            "", "### ⚽ Moyennes de buts sur les derniers matchs", "",
        ])
        for team_name, key in [(home, "home"), (away, "away")]:
            average = averages.get(key, {})
            if average.get("scored") is not None and average.get("conceded") is not None:
                lines.append(
                    f"- **{team_name} :** {safe_float(average.get('scored')):.2f} but(s) marqué(s) "
                    f"et {safe_float(average.get('conceded')):.2f} encaissé(s) en moyenne."
                )
        lines.extend([
            "", "### 🧠 Indicateurs des équipes", "",
            f"- **Attaque domicile :** {strengths.get('home_attack', '-')}",
            f"- **Défense domicile :** {strengths.get('home_defense', '-')}",
            f"- **Attaque extérieure :** {strengths.get('away_attack', '-')}",
            f"- **Défense extérieure :** {strengths.get('away_defense', '-')}",
            "", "### ⭐ Marchés les plus probables", "",
        ])
        if item.get("best_picks"):
            for pick in item["best_picks"]:
                lines.append(
                    f"- **{pick.get('market', '-')} :** {safe_float(pick.get('probability')):.1%} "
                    "de probabilité estimée."
                )
        else:
            lines.append("- Aucun marché disponible.")
        lines.extend([
            "", "### 🤖 Décision du modèle", "",
            f"- **Pronostic 1/N/2 :** {item.get('decision', '-')}",
            f"- **Confiance indicative :** {item.get('confidence', '-')}",
            f"- **Score le plus probable :** {item.get('probable_score', '-')}",
            "",
        ])

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ANALYSES_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"Rapport détaillé enregistré : {ANALYSES_FILE}")


# ------------------------- PARIS VIRTUELS -------------------------

def place_virtual_bets(analyses, state):
    """Enregistre au plus cinq sélections virtuelles, sans doublons de match/marché."""
    existing = {
        (str(bet.get("match_id")), str(bet.get("market")))
        for bet in state.get("paris", [])
    }
    open_count_today = sum(
        1 for bet in state.get("paris", [])
        if bet.get("date_placement") == local_date() and bet.get("statut") == "EN_COURS"
    )
    remaining = max(0, MAX_NEW_BETS_PER_RUN - open_count_today)
    if remaining == 0:
        log("Limite de nouveaux paris virtuels atteinte pour aujourd'hui.")
        return

    # Ne sélectionner que des matchs futurs/scheduled, avec probabilité élevée.
    candidates = []
    for item in analyses.get("matches", []):
        if item.get("status") not in ("SCHEDULED", "TIMED"):
            continue
        for market, probability in item.get("all_markets", {}).items():
            # Éviter les marchés quasi certains et les marchés très peu probables.
            if 0.66 <= safe_float(probability) <= 0.86:
                key = (str(item.get("id")), str(market))
                if key not in existing:
                    candidates.append((safe_float(probability), item, market))
    candidates.sort(key=lambda x: x[0], reverse=True)

    for probability, item, market in candidates[:remaining]:
        stake = min(1.0, safe_float(state.get("bankroll_actuelle")) * 0.05)
        if stake <= 0 or safe_float(state.get("bankroll_actuelle")) < stake:
            break
        bet = {
            "match_id": item.get("id"),
            "date_match": item.get("date"),
            "heure_match": item.get("kickoff_local"),
            "competition": item.get("competition_name"),
            "domicile": item.get("home_team"),
            "exterieur": item.get("away_team"),
            "market": market,
            "probabilite_estimee": round(probability, 5),
            "cote_virtuelle": round(1.0 / probability, 3) if probability > 0 else None,
            "mise": round(stake, 2),
            "statut": "EN_COURS",
            "date_placement": local_date(),
            "gain": None,
        }
        state["paris"].append(bet)
        state["bankroll_actuelle"] = round(safe_float(state["bankroll_actuelle"]) - stake, 2)
        state["mises_totales"] = round(safe_float(state.get("mises_totales")) + stake, 2)
        existing.add((str(item.get("id")), str(market)))
        log(f"Pari virtuel ajouté : {item.get('home_team')} - {item.get('away_team')} / {market}")


def settle_virtual_bets(state):
    """Règle les paris virtuels quand le match est terminé."""
    open_bets = [b for b in state.get("paris", []) if b.get("statut") == "EN_COURS"]
    if not open_bets:
        return

    ids = {str(b.get("match_id")) for b in open_bets if b.get("match_id") is not None}
    for match_id in ids:
        try:
            match = api_get(f"matches/{match_id}").get("match", {})
        except Exception as exc:
            log(f"Règlement différé pour le match {match_id}: {exc}")
            continue
        if match.get("status") != "FINISHED":
            continue
        score = match.get("score", {}).get("fullTime") or {}
        hg, ag = score.get("home"), score.get("away")
        if hg is None or ag is None:
            continue
        for bet in open_bets:
            if str(bet.get("match_id")) != match_id:
                continue
            market = bet.get("market")
            total = hg + ag
            if market == "1":
                won = hg > ag
            elif market == "N":
                won = hg == ag
            elif market == "2":
                won = hg < ag
            elif market == "1X":
                won = hg >= ag
            elif market == "X2":
                won = ag >= hg
            elif market == "12":
                won = hg != ag
            elif market.startswith("Over "):
                threshold = float(market.split()[1])
                won = total > threshold
            elif market.startswith("Under "):
                threshold = float(market.split()[1])
                won = total < threshold
            elif market == "BTTS Oui":
                won = hg >= 1 and ag >= 1
            elif market == "BTTS Non":
                won = hg == 0 or ag == 0
            else:
                continue

            stake = safe_float(bet.get("mise"))
            odds = safe_float(bet.get("cote_virtuelle"))
            payout = round(stake * odds, 2) if won else 0.0
            state["bankroll_actuelle"] = round(safe_float(state.get("bankroll_actuelle")) + payout, 2)
            state["gains_totaux"] = round(safe_float(state.get("gains_totaux")) + payout, 2)
            if won:
                state["benefice_total"] = round(safe_float(state.get("benefice_total")) + payout - stake, 2)
            else:
                state["benefice_total"] = round(safe_float(state.get("benefice_total")) - stake, 2)
            bet["statut"] = "GAGNÉ" if won else "PERDU"
            bet["score_final"] = f"{hg}-{ag}"
            bet["gain"] = payout
            bet["date_reglement"] = local_date()
            state.setdefault("historique", []).append(dict(bet))
            log(f"Pari virtuel réglé : {bet.get('market')} — {bet['statut']} ({hg}-{ag})")


# ------------------------- EXÉCUTION -------------------------

def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log("Démarrage FOOT AI PRO BOT V12.")
    if not API_KEY:
        raise RuntimeError(
            "Clé API manquante. Dans GitHub : Settings > Secrets and variables > Actions, "
            "ajoute FOOTBALL_DATA_API_KEY."
        )

    state = load_state()
    settle_virtual_bets(state)

    # Analyse aujourd'hui et les sept prochains jours, pour afficher les prochains matchs.
    today = local_now().date()
    date_from = today.isoformat()
    date_to = (today + timedelta(days=7)).isoformat()
    all_analyses = []
    seen_match_ids = set()

    for code in COMPETITIONS:
        try:
            matches = get_matches_for_competition(code, date_from, date_to)
            log(f"{COMPETITIONS[code]} : {len(matches)} matchs reçus.")
            for match in matches:
                match_id = match.get("id")
                if match_id in seen_match_ids:
                    continue
                seen_match_ids.add(match_id)
                if match.get("status") not in ("SCHEDULED", "TIMED"):
                    continue
                try:
                    item = analyze_match(match, code)
                    if item:
                        all_analyses.append(item)
                except Exception as exc:
                    log(f"Analyse ignorée pour le match {match_id}: {exc}")
        except Exception as exc:
            log(f"Compétition {code} non récupérée : {exc}")
        time.sleep(API_PAUSE_SECONDS)

    all_analyses.sort(key=lambda item: (item.get("date", ""), item.get("kickoff_local", "")))
    report = {"count": len(all_analyses), "matches": all_analyses}
    write_analyses_markdown(report)
    place_virtual_bets(report, state)
    save_state(state)

    log(
        f"Terminé. Matchs analysés : {len(all_analyses)}. "
        f"Capital virtuel : {safe_float(state.get('bankroll_actuelle')):.2f} €."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"ERREUR FATALE : {exc}")
        raise