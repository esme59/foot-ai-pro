#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FOOT AI PRO BOT V12.2 — simulation virtuelle uniquement, aucun pari réel.
API : football-data.org v4 (clé dans FOOTBALL_DATA_API_KEY).

Nouveautés V12.2 :
- Règlement des paris à partir des matchs déjà téléchargés (0 appel en plus),
  appel /matches/{id} seulement en secours.
- Matchs reportés/suspendus : pari remboursé après POSTPONED_VOID_DAYS jours.
- Score réglementaire (90 min) : prolongation et tirs au but ignorés
  (règlement ET historique).
- 1 seul pari par match, historique minimum 5 matchs, lissage vers la moyenne.
- Réponses API non-JSON gérées proprement.
"""

import json
import math
import os
import time
import unicodedata
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
MAX_NEW_BETS_PER_DAY = 5
STAKE_FRACTION = 0.05
MAX_STAKE = 1.0
MIN_HISTORY_MATCHES = 5
SHRINK_WEIGHT = 3              # poids de la moyenne de ligue (en "matchs fictifs")
LEAGUE_AVG_GOALS = 1.30
REQUEST_TIMEOUT = 20
API_PAUSE_SECONDS = 6.5        # 10 requêtes/minute max (plan gratuit)
MAX_RUNTIME_SECONDS = 15 * 60
MAX_SETTLE_CALLS = 20          # appels de secours max
DAYS_AHEAD = 7
HISTORY_MATCHES = 10
MAX_GOALS = 10
VOID_AFTER_DAYS = 3            # pari sans match_id annulé après N jours
POSTPONED_VOID_DAYS = 3        # match reporté > N jours : pari remboursé
LOCAL_TZ = ZoneInfo("Europe/Paris")
START_TIME = time.time()

COMPETITIONS = {
    "FL1": "Ligue 1",
    "PL": "Premier League",
    "PD": "La Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "CL": "Ligue des champions",
}

SETTLED = ("GAGNÉ", "PERDU", "REMBOURSÉ")

SESSION = requests.Session()
SESSION.headers.update({"X-Auth-Token": API_KEY} if API_KEY else {})
_last_call = 0.0


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


def time_left():
    return MAX_RUNTIME_SECONDS - (time.time() - START_TIME)


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
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def parse_kickoff(match):
    raw = match.get("utcDate")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(LOCAL_TZ)
    except ValueError:
        return None


def api_get(endpoint, params=None, retries=1):
    """Appel API avec cadence limitée (pause uniquement entre vrais appels)."""
    global _last_call
    if not API_KEY:
        raise RuntimeError("Clé API manquante (FOOTBALL_DATA_API_KEY).")
    wait = API_PAUSE_SECONDS - (time.time() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.time()
    url = f"{API_BASE}/{endpoint.lstrip('/')}"
    response = SESSION.get(url, params=params or {}, timeout=REQUEST_TIMEOUT)
    if response.status_code == 429:
        if retries > 0 and time_left() > 90:
            log("HTTP 429 : pause de 60 s puis nouvel essai.")
            time.sleep(60)
            return api_get(endpoint, params, retries - 1)
        raise RuntimeError("Limite de requêtes API atteinte (HTTP 429).")
    if response.status_code == 403:
        raise RuntimeError("Accès refusé (HTTP 403) : compétition non incluse dans l'abonnement.")
    response.raise_for_status()
    try:
        data = response.json()
    except ValueError:
        raise RuntimeError("Réponse API non valide (JSON attendu).")
    if not isinstance(data, dict):
        raise RuntimeError("Réponse API inattendue.")
    return data


# ------------------------- SCORE RÉGLEMENTAIRE -------------------------

def final_score(match):
    """Score à 90 minutes (hors prolongation et tirs au but). None si indéterminé."""
    score = match.get("score") or {}
    duration = score.get("duration") or "REGULAR"
    if duration == "REGULAR":
        part = score.get("fullTime") or {}
        hg, ag = part.get("home"), part.get("away")
        return (hg, ag) if hg is not None and ag is not None else None

    # Prolongation / tirs au but : on prend le temps réglementaire.
    part = score.get("regularTime") or {}
    hg, ag = part.get("home"), part.get("away")
    if hg is not None and ag is not None:
        return (hg, ag)

    # Secours : fullTime moins prolongation (+ tirs au but selon la version de l'API).
    full = score.get("fullTime") or {}
    extra = score.get("extraTime") or {}
    pens = score.get("penalties") or {}
    try:
        hg = full["home"] - (extra.get("home") or 0)
        ag = full["away"] - (extra.get("away") or 0)
        if duration == "PENALTY_SHOOTOUT" and pens.get("home") is not None:
            # Certaines versions incluent les tirs au but dans fullTime.
            if (full["home"] + full["away"]) >= (pens["home"] + pens["away"]) and not extra.get("home") is None:
                hg -= pens["home"]
                ag -= pens["away"]
        if hg >= 0 and ag >= 0:
            return (hg, ag)
    except (KeyError, TypeError):
        pass
    return None


# ------------------------- ÉTAT & CAPITAL -------------------------

def default_state():
    return {
        "bankroll_initiale": INITIAL_BANKROLL,
        "bankroll_actuelle": INITIAL_BANKROLL,
        "benefice_total": 0.0,
        "mises_totales": 0.0,
        "gains_totaux": 0.0,
        "mises_en_cours": 0.0,
        "paris": [],
        "historique": [],
        "last_updated": None,
    }


def norm_status(value):
    text = unicodedata.normalize(
        "NFD", str(value or "")
    ).encode("ascii", "ignore").decode().lower().strip()

    if text.startswith("gagn") or text in ("won", "win"):
        return "GAGNÉ"

    if text.startswith("perd") or text in ("lost", "loss"):
        return "PERDU"

    if text.startswith("rembours") or text in (
        "void", "annule", "annulee", "refunded", "cancelled", "canceled"
    ):
        return "REMBOURSÉ"

    if text in ("pending", "en_cours", "en cours", "open"):
        return "EN_COURS"

    return "EN_COURS"


def bet_odds(bet):
    # Accepte les anciens et les nouveaux noms de champs.
    odds = safe_float(
        bet.get("cote_virtuelle")
        or bet.get("cote")
        or bet.get("odds")
    )
    if odds > 1.0:
        return odds

    prob = safe_float(
        bet.get("probabilite_estimee")
        or bet.get("probability")
    )
    if 0 < prob < 1:
        return round(1.0 / prob, 3)

    potential_return = safe_float(
        bet.get("potential_return")
    )
    stake = safe_float(bet.get("mise") or bet.get("stake"))
    if stake > 0 and potential_return > stake:
        return round(potential_return / stake, 3)

    return 0.0


def repair_bet(bet):
    # Convertit les anciens champs V12 vers le format V12.3.
    bet["match_id"] = bet.get("match_id")
    bet["domicile"] = (
        bet.get("domicile") or bet.get("home_team") or "Domicile"
    )
    bet["exterieur"] = (
        bet.get("exterieur") or bet.get("away_team") or "Extérieur"
    )
    bet["date_match"] = (
        bet.get("date_match") or bet.get("match_date")
    )
    bet["date_placement"] = (
        bet.get("date_placement") or bet.get("created_date")
    )

    bet["mise"] = safe_float(
        bet.get("mise") or bet.get("stake")
    )

    odds = bet_odds(bet)
    if odds > 1.0:
        bet["cote_virtuelle"] = round(odds, 3)

    raw_status = bet.get("statut") or bet.get("status")
    bet["statut"] = norm_status(raw_status)

    # Récupère le résultat final déjà enregistré.
    if not bet.get("score_final") and bet.get("result"):
        bet["score_final"] = bet["result"]

    status = bet["statut"]
    stake = bet["mise"]

    if status == "GAGNÉ":
        # Le gain représente le retour total, mise comprise.
        payout = safe_float(bet.get("gain"))

        if payout <= 0:
            payout = safe_float(bet.get("returned_amount"))

        if payout <= 0:
            payout = safe_float(bet.get("potential_return"))

        if payout <= 0 and odds > 1:
            payout = round(stake * odds, 2)

        bet["gain"] = round(payout, 2)

    elif status == "PERDU":
        bet["gain"] = 0.0

    elif status == "REMBOURSÉ":
        bet["gain"] = round(stake, 2)

    else:
        bet["statut"] = "EN_COURS"
        bet["gain"] = None


def recompute_totals(state):
    initial = safe_float(state.get("bankroll_initiale"), INITIAL_BANKROLL)

    stakes = 0.0
    gains = 0.0
    profit = 0.0
    open_stakes = 0.0

    paris = state.get("paris", [])

    for bet in paris:
        stake = safe_float(
            bet.get("mise", bet.get("stake", 0))
        )

        # Addition de toutes les mises
        stakes += stake

        statut = norm_status(
            bet.get("statut", bet.get("status", "EN_COURS"))
        )

        bet["mise"] = round(stake, 2)
        bet["statut"] = statut

        payout = safe_float(
            bet.get("gain", bet.get("returned_amount", 0))
        )

        if statut == "EN_COURS":
            open_stakes += stake

        elif statut in SETTLED:
            if statut == "GAGNÉ" and payout <= 0:
                payout = safe_float(
                    bet.get(
                        "returned_amount",
                        bet.get("potential_return", 0)
                    )
                )

            if statut == "PERDU":
                payout = 0.0

            if statut == "REMBOURSÉ":
                payout = stake

            bet["gain"] = round(payout, 2)
            gains += payout
            profit += payout - stake

    state["mises_totales"] = round(stakes, 2)
    state["gains_totaux"] = round(gains, 2)
    state["benefice_total"] = round(profit, 2)
    state["mises_en_cours"] = round(open_stakes, 2)

    state["bankroll_actuelle"] = round(
        initial + profit - open_stakes, 2
    )

    state["historique"] = [
        dict(b)
        for b in paris
        if norm_status(b.get("statut", "EN_COURS")) in SETTLED
    ]


def load_state():
    state = read_json(STATE_FILE, default_state())
    for key, value in default_state().items():
        state.setdefault(key, value)
    if not isinstance(state["paris"], list):
        state["paris"] = []
    state["paris"] = [b for b in state["paris"] if isinstance(b, dict)]
    for bet in state["paris"]:
        repair_bet(bet)
    recompute_totals(state)
    return state


def save_state(state):
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    write_json(STATE_FILE, state)


# ------------------------- MODÈLE DE POISSON -------------------------

def poisson_probability(lam, goals):
    lam = max(0.001, min(float(lam), 8.0))
    return math.exp(-lam) * (lam ** goals) / math.factorial(goals)


def poisson_matrix(home_lambda, away_lambda):
    hp = [poisson_probability(home_lambda, g) for g in range(MAX_GOALS + 1)]
    ap = [poisson_probability(away_lambda, g) for g in range(MAX_GOALS + 1)]
    matrix = [[h * a for a in ap] for h in hp]
    total = sum(sum(r) for r in matrix)
    if total > 0:
        matrix = [[p / total for p in r] for r in matrix]
    return matrix


def derive_markets(matrix):
    hw = dr = aw = o05 = o15 = o25 = o35 = u15 = u25 = u35 = btts = 0.0
    for hg, row in enumerate(matrix):
        for ag, p in enumerate(row):
            if hg > ag:
                hw += p
            elif hg == ag:
                dr += p
            else:
                aw += p
            t = hg + ag
            if t >= 1: o05 += p
            if t >= 2: o15 += p
            if t >= 3: o25 += p
            if t >= 4: o35 += p
            if t <= 1: u15 += p
            if t <= 2: u25 += p
            if t <= 3: u35 += p
            if hg >= 1 and ag >= 1: btts += p
    markets = {
        "1": hw, "N": dr, "2": aw, "1X": hw + dr, "X2": aw + dr, "12": hw + aw,
        "Over 0.5": o05, "Over 1.5": o15, "Over 2.5": o25, "Over 3.5": o35,
        "Under 1.5": u15, "Under 2.5": u25, "Under 3.5": u35,
        "BTTS Oui": btts, "BTTS Non": 1.0 - btts,
    }
    return {k: max(0.0, min(1.0, v)) for k, v in markets.items()}


def top_scores(matrix, limit=5):
    scores = [{"score": f"{h}-{a}", "probability": p}
              for h, row in enumerate(matrix) for a, p in enumerate(row)]
    scores.sort(key=lambda x: x["probability"], reverse=True)
    return scores[:limit]


# ------------------------- DONNÉES FOOTBALL (1 appel / compétition) -------------------------

def fetch_season_matches():
    """Un appel par compétition. Retourne (terminés, à venir, tous les matchs par id)."""
    finished, upcoming, all_matches = {}, [], {}
    today = local_now().date()
    last_day = today + timedelta(days=DAYS_AHEAD)
    for code in COMPETITIONS:
        if time_left() < 60:
            log("Budget de temps presque épuisé : récupération interrompue.")
            break
        try:
            matches = api_get(f"competitions/{code}/matches").get("matches", [])
        except Exception as exc:
            log(f"Compétition {code} non récupérée : {exc}")
            continue
        log(f"{COMPETITIONS[code]} : {len(matches)} matchs reçus.")
        for m in matches:
            if m.get("id") is not None:
                all_matches[str(m["id"])] = m
            status = m.get("status")
            if status == "FINISHED":
                finished[m.get("id")] = m
            elif status in ("SCHEDULED", "TIMED"):
                kick = parse_kickoff(m)
                if kick and today <= kick.date() <= last_day:
                    upcoming.append((code, m))
    return finished, upcoming, all_matches


def build_history_index(finished):
    index = {}
    for m in finished.values():
        for side in ("homeTeam", "awayTeam"):
            tid = (m.get(side) or {}).get("id")
            if tid:
                index.setdefault(tid, []).append(m)
    for tid in index:
        index[tid].sort(key=lambda m: m.get("utcDate", ""), reverse=True)
        index[tid] = index[tid][:HISTORY_MATCHES]
    return index


def team_results(team_id, matches):
    out = []  # (marqués, encaissés) — score réglementaire
    for m in matches:
        sc = final_score(m)
        if sc is None:
            continue
        hg, ag = sc
        if team_id == (m.get("homeTeam") or {}).get("id"):
            out.append((float(hg), float(ag)))
        elif team_id == (m.get("awayTeam") or {}).get("id"):
            out.append((float(ag), float(hg)))
    return out


def summarize_team_history(team_id, matches):
    res = team_results(team_id, matches)
    if not res:
        return {"scored": LEAGUE_AVG_GOALS, "conceded": LEAGUE_AVG_GOALS, "count": 0}
    n = len(res)
    k = SHRINK_WEIGHT
    return {
        "scored": (sum(r[0] for r in res) + k * LEAGUE_AVG_GOALS) / (n + k),
        "conceded": (sum(r[1] for r in res) + k * LEAGUE_AVG_GOALS) / (n + k),
        "count": n,
    }


def team_form_string(team_id, matches):
    res = team_results(team_id, matches)[:5]
    if not res:
        return "Indisponible"
    return " ".join("V" if s > c else "N" if s == c else "D" for s, c in res)


def analyze_match(match, code, index):
    home, away = match.get("homeTeam") or {}, match.get("awayTeam") or {}
    home_id, away_id = home.get("id"), away.get("id")
    kickoff = parse_kickoff(match)
    if not home_id or not away_id or kickoff is None:
        return None

    home_hist, away_hist = index.get(home_id, []), index.get(away_id, [])
    hs, as_ = summarize_team_history(home_id, home_hist), summarize_team_history(away_id, away_hist)

    home_l = max(0.15, min((hs["scored"] * 0.55 + as_["conceded"] * 0.45) * 1.08, 4.0))
    away_l = max(0.15, min((as_["scored"] * 0.55 + hs["conceded"] * 0.45) * 0.94, 4.0))

    matrix = poisson_matrix(home_l, away_l)
    markets = derive_markets(matrix)
    ranked = sorted(markets.items(), key=lambda kv: kv[1], reverse=True)
    best_picks = [{"market": m, "probability": p} for m, p in ranked[:3]]
    probable = top_scores(matrix, 5)
    best = max(("1", markets["1"]), ("N", markets["N"]), ("2", markets["2"]), key=lambda x: x[1])

    history_ok = hs["count"] >= MIN_HISTORY_MATCHES and as_["count"] >= MIN_HISTORY_MATCHES
    hname, aname = home.get("name", "Domicile"), away.get("name", "Extérieur")
    if history_ok:
        summary = f"Le modèle estime {home_l:.2f} but(s) pour {hname} et {away_l:.2f} pour {aname}."
        confidence = "Indicative — non calibrée"
    else:
        summary = "Données historiques limitées : interpréter avec prudence."
        confidence = "Faible"

    return {
        "id": match.get("id"),
        "date": kickoff.strftime("%Y-%m-%d"),
        "kickoff_local": kickoff.strftime("%H:%M"),
        "competition_code": code,
        "competition_name": COMPETITIONS.get(code, code),
        "home_team": hname,
        "away_team": aname,
        "status": match.get("status", "SCHEDULED"),
        "history_ok": history_ok,
        "all_markets": {k: round(v, 5) for k, v in markets.items()},
        "expected_goals": {"home": round(home_l, 3), "away": round(away_l, 3)},
        "top_scores": [{"score": s["score"], "probability": round(s["probability"], 5)} for s in probable],
        "probable_score": probable[0]["score"] if probable else "-",
        "form": {"home": team_form_string(home_id, home_hist), "away": team_form_string(away_id, away_hist)},
        "goal_averages": {
            "home": {"scored": round(hs["scored"], 2), "conceded": round(hs["conceded"], 2)},
            "away": {"scored": round(as_["scored"], 2), "conceded": round(as_["conceded"], 2)},
        },
        "strengths": {
            "home_attack": round(hs["scored"], 2), "home_defense": round(hs["conceded"], 2),
            "away_attack": round(as_["scored"], 2), "away_defense": round(as_["conceded"], 2),
        },
        "best_picks": best_picks,
        "decision": f"{best[0]} ({best[1]:.1%})",
        "confidence": confidence,
        "summary": summary,
    }


# ------------------------- RAPPORT -------------------------

MARKET_LABELS = [
    ("1", "Victoire de l'équipe à domicile"), ("N", "Match nul"),
    ("2", "Victoire de l'équipe à l'extérieur"),
    ("1X", "Double chance : domicile ou nul"), ("X2", "Double chance : extérieur ou nul"),
    ("12", "Une équipe gagne"),
    ("Over 0.5", "Plus de 0,5 but"), ("Over 1.5", "Plus de 1,5 but"),
    ("Over 2.5", "Plus de 2,5 buts"), ("Over 3.5", "Plus de 3,5 buts"),
    ("Under 1.5", "Moins de 1,5 but"), ("Under 2.5", "Moins de 2,5 buts"),
    ("Under 3.5", "Moins de 3,5 buts"),
    ("BTTS Oui", "Les deux équipes marquent : OUI"), ("BTTS Non", "Les deux équipes marquent : NON"),
]


def write_analyses_markdown(analyses):
    lines = [
        f"# FOOT AI PRO BOT V12.2 — Analyses détaillées du {local_date()}", "",
        "> Simulation virtuelle uniquement — aucun pari réel.", "",
        f"**Matchs analysés :** {analyses.get('count', 0)}", "",
        "**Important :** les pourcentages sont des estimations mathématiques, pas des garanties.", "",
    ]
    current_day = None
    for item in analyses.get("matches", []):
        if item.get("date") != current_day:
            current_day = item.get("date")
            lines.extend(["", "---", "", f"# 📅 Matchs du {current_day}", ""])
        probs = item.get("all_markets", {})
        xg = item.get("expected_goals", {})
        form = item.get("form", {})
        avgs = item.get("goal_averages", {})
        st = item.get("strengths", {})
        home, away = item.get("home_team", "Domicile"), item.get("away_team", "Extérieur")

        lines.extend([
            f"## ⚽ {item.get('kickoff_local', '--:--')} — {home} vs {away}", "",
            f"**Compétition :** {item.get('competition_name', '-')}", "",
            f"**Résumé :** {item.get('summary', '-')}", "",
            "### 📊 Pourcentage estimé de chaque marché", "",
            "| Marché | Probabilité estimée |", "|---|---:|",
        ])
        for market, label in MARKET_LABELS:
            if probs.get(market) is not None:
                lines.append(f"| {label} | **{safe_float(probs[market]):.1%}** |")

        lines.extend(["", "### 🎯 Scores exacts les plus probables", ""])
        for s in item.get("top_scores", []) or []:
            lines.append(f"- **{s.get('score', '?')}** : {safe_float(s.get('probability')):.1%}")
        lines.extend([
            "", "### ⚽ Buts attendus par le modèle", "",
            f"- **{home} :** {safe_float(xg.get('home')):.2f} but(s)",
            f"- **{away} :** {safe_float(xg.get('away')):.2f} but(s)",
            "", "### 📈 Forme récente", "",
            f"- **{home} :** {form.get('home', '-')}",
            f"- **{away} :** {form.get('away', '-')}",
            "", "### ⚽ Moyennes de buts sur les derniers matchs", "",
        ])
        for name, key in ((home, "home"), (away, "away")):
            a = avgs.get(key, {})
            if a.get("scored") is not None:
                lines.append(f"- **{name} :** {safe_float(a.get('scored')):.2f} marqué(s) "
                             f"et {safe_float(a.get('conceded')):.2f} encaissé(s) en moyenne.")
        lines.extend([
            "", "### 🧠 Indicateurs des équipes", "",
            f"- **Attaque domicile :** {st.get('home_attack', '-')}",
            f"- **Défense domicile :** {st.get('home_defense', '-')}",
            f"- **Attaque extérieure :** {st.get('away_attack', '-')}",
            f"- **Défense extérieure :** {st.get('away_defense', '-')}",
            "", "### ⭐ Marchés les plus probables", "",
        ])
        for p in item.get("best_picks", []) or []:
            lines.append(f"- **{p.get('market', '-')} :** {safe_float(p.get('probability')):.1%} de probabilité estimée.")
        lines.extend([
            "", "### 🤖 Décision du modèle", "",
            f"- **Pronostic 1/N/2 :** {item.get('decision', '-')}",
            f"- **Confiance indicative :** {item.get('confidence', '-')}",
            f"- **Score le plus probable :** {item.get('probable_score', '-')}", "",
        ])
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ANALYSES_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"Rapport détaillé enregistré : {ANALYSES_FILE}")


# ------------------------- PARIS VIRTUELS -------------------------

def place_virtual_bets(analyses, state):
    today = local_date()
    placed_today = sum(1 for b in state["paris"] if b.get("date_placement") == today)
    remaining = max(0, MAX_NEW_BETS_PER_DAY - placed_today)
    if remaining == 0:
        log("Limite de paris virtuels atteinte pour aujourd'hui.")
        return
    existing = {(str(b.get("match_id")), str(b.get("market"))) for b in state["paris"]}
    # Un match déjà parié (en cours) ne reçoit pas de second pari.
    matches_with_bet = {str(b.get("match_id")) for b in state["paris"] if b["statut"] == "EN_COURS"}

    best_per_match = {}
    for item in analyses.get("matches", []):
        if item.get("status") not in ("SCHEDULED", "TIMED") or not item.get("history_ok"):
            continue
        mid = str(item.get("id"))
        if mid in matches_with_bet:
            continue
        for market, prob in item.get("all_markets", {}).items():
            p = safe_float(prob)
            if 0.66 <= p <= 0.86 and (mid, market) not in existing:
                if mid not in best_per_match or p > best_per_match[mid][0]:
                    best_per_match[mid] = (p, item, market)
    candidates = sorted(best_per_match.values(), key=lambda x: x[0], reverse=True)

    for p, item, market in candidates[:remaining]:
        bankroll = safe_float(state.get("bankroll_actuelle"))
        stake = round(min(MAX_STAKE, bankroll * STAKE_FRACTION), 2)
        if stake <= 0 or bankroll < stake:
            break
        state["paris"].append({
            "match_id": item.get("id"),
            "date_match": item.get("date"),
            "heure_match": item.get("kickoff_local"),
            "competition": item.get("competition_name"),
            "domicile": item.get("home_team"),
            "exterieur": item.get("away_team"),
            "market": market,
            "probabilite_estimee": round(p, 5),
            "cote_virtuelle": round(1.0 / p, 3),
            "mise": stake,
            "statut": "EN_COURS",
            "date_placement": today,
            "gain": None,
        })
        recompute_totals(state)
        log(f"Pari virtuel ajouté : {item.get('home_team')} - {item.get('away_team')} / {market}")


def market_won(market, hg, ag):
    total = hg + ag
    if market == "1": return hg > ag
    if market == "N": return hg == ag
    if market == "2": return hg < ag
    if market == "1X": return hg >= ag
    if market == "X2": return ag >= hg
    if market == "12": return hg != ag
    if market == "BTTS Oui": return hg >= 1 and ag >= 1
    if market == "BTTS Non": return hg == 0 or ag == 0
    if market.startswith("Over "): return total > float(market.split()[1])
    if market.startswith("Under "): return total < float(market.split()[1])
    return None


def close_bet(bet, status, score=None):
    stake = safe_float(bet.get("mise"))
    odds = bet_odds(bet)
    if status == "GAGNÉ":
        bet["gain"] = round(stake * odds, 2) if odds > 1.0 else stake
    elif status == "REMBOURSÉ":
        bet["gain"] = stake
    else:
        bet["gain"] = 0.0
    bet["statut"] = status
    if score:
        bet["score_final"] = score
    bet["date_reglement"] = local_date()


def parse_day(value, default):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return default


def apply_match_result(bet, match, today):
    """Règle un pari selon l'état du match. Retourne True si le pari est clos."""
    status = match.get("status")
    bet_day = parse_day(bet.get("date_match"), today)

    if status in ("CANCELLED", "AWARDED"):
        close_bet(bet, "REMBOURSÉ")
        log(f"Match annulé/attribué : pari remboursé ({bet.get('market')}).")
        return True

    if status == "FINISHED":
        sc = final_score(match)
        if sc is None:
            log(f"Score réglementaire indisponible pour le match {bet.get('match_id')} : pari laissé en attente.")
            return False
        hg, ag = sc
        try:
            won = market_won(str(bet.get("market")), hg, ag)
        except (ValueError, IndexError):
            won = None
        if won is None:
            log(f"Marché inconnu, pari ignoré : {bet.get('market')}")
            return False
        close_bet(bet, "GAGNÉ" if won else "PERDU", f"{hg}-{ag}")
        log(f"Pari virtuel réglé : {bet['market']} — {bet['statut']} ({hg}-{ag})")
        return True

    if status in ("POSTPONED", "SUSPENDED"):
        if (today - bet_day).days >= POSTPONED_VOID_DAYS:
            close_bet(bet, "REMBOURSÉ")
            log(f"Match reporté/suspendu depuis plus de {POSTPONED_VOID_DAYS} j : pari remboursé ({bet.get('market')}).")
            return True
        return False

    if status in ("SCHEDULED", "TIMED"):
        # Match déplacé : nouvelle date trop éloignée de la date initiale.
        kick = parse_kickoff(match)
        if kick and (kick.date() - bet_day).days >= POSTPONED_VOID_DAYS:
            close_bet(bet, "REMBOURSÉ")
            log(f"Match déplacé au {kick.date()} : pari remboursé ({bet.get('market')}).")
            return True
    return False


def settle_virtual_bets(state, known_matches):
    """Règle les paris ouverts avec les résultats réels de l'API."""
    today = local_now().date()

    open_bets = [
        b for b in state["paris"]
        if b.get("statut") == "EN_COURS"
    ]

    if not open_bets:
        log("Aucun pari en attente.")
        return

    # 1. Première tentative : résultats déjà téléchargés
    missing = []

    for bet in open_bets:
        match_id = bet.get("match_id")

        if match_id is None:
            continue

        match = known_matches.get(str(match_id))

        if match:
            apply_match_result(bet, match, today)
        elif parse_day(bet.get("date_match"), today) <= today:
            missing.append(str(match_id))

    # 2. Deuxième tentative : récupération individuelle des matchs absents
    calls = 0

    for match_id in dict.fromkeys(missing):
        if calls >= MAX_SETTLE_CALLS or time_left() < 120:
            log("Limite de récupération atteinte. Les autres paris seront vérifiés au prochain passage.")
            break

        try:
            data = api_get(f"matches/{match_id}")
            match = data.get("match", {})

            if not match:
                log(f"Aucun résultat retourné pour le match {match_id}.")
                continue

            calls += 1

            for bet in state["paris"]:
                if (
                    bet.get("statut") == "EN_COURS"
                    and str(bet.get("match_id")) == match_id
                ):
                    apply_match_result(bet, match, today)

        except Exception as exc:
            log(f"Impossible de régler le match {match_id} : {exc}")

    recompute_totals(state)

    remaining = sum(
        1 for b in state["paris"]
        if b.get("statut") == "EN_COURS"
    )

    settled = sum(
        1 for b in state["paris"]
        if b.get("statut") in SETTLED
    )

    log(
        f"Règlement terminé : {settled} paris réglés au total, "
        f"{remaining} paris encore en attente."
    )


# ------------------------- EXÉCUTION -------------------------

def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log("Démarrage FOOT AI PRO BOT V12.2.")
    if not API_KEY:
        raise RuntimeError("Clé API manquante. Ajoute FOOTBALL_DATA_API_KEY dans les secrets GitHub.")

    state = load_state()

    finished, upcoming, all_matches = fetch_season_matches()
    index = build_history_index(finished)
    log(f"{len(finished)} matchs terminés, {len(upcoming)} à venir.")

    settle_virtual_bets(state, all_matches)

    analyses, seen = [], set()
    for code, match in upcoming:
        if match.get("id") in seen:
            continue
        seen.add(match.get("id"))
        try:
            item = analyze_match(match, code, index)
            if item:
                analyses.append(item)
        except Exception as exc:
            log(f"Analyse ignorée pour le match {match.get('id')} : {exc}")

    analyses.sort(key=lambda i: (i.get("date", ""), i.get("kickoff_local", "")))
    report = {"count": len(analyses), "matches": analyses}
    write_analyses_markdown(report)
    write_json(DATA_DIR / "analyses.json", report)

    place_virtual_bets(report, state)
    recompute_totals(state)
    save_state(state)
    log(f"Terminé en {time.time() - START_TIME:.0f}s. Matchs analysés : {len(analyses)}. "
        f"Capital virtuel : {state['bankroll_actuelle']:.2f} € (dont {state['mises_en_cours']:.2f} € en jeu).")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"ERREUR FATALE : {exc}")
        raise
