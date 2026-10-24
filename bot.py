import os
import json
import math
from pathlib import Path
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import requests

============================================================

FOOT AI PRO BOT V7

Simulation virtuelle uniquement — aucun pari réel

API : football-data.org v4

Date limite des nouveaux paris : 25 octobre 2026 inclus

============================================================

API_BASE = “https://api.football-data.org/v4”
STATE_FILE = Path(“data/bankroll.json”)

INITIAL_BANKROLL = 20.0
STAKE = 1.0
MAX_BETS_PER_RUN = 5

LOCAL_TIMEZONE = ZoneInfo(“Europe/Paris”)
MAX_MATCH_DATE = datetime(2026, 10, 25).date()

MIN_PROBABILITY = 0.45
MAX_ESTIMATED_ODDS = 2.50

COMPETITIONS = {
“FL1”: “Ligue 1”,
“PL”: “Premier League”,
“PD”: “Liga”,
“BL1”: “Bundesliga”,
“SA”: “Serie A”,
“CL”: “Ligue des Champions”,
}

API_TOKEN = (
os.getenv(“FOOTBALL_DATA_API_KEY”)
or os.getenv(“FOOTBALL_API_KEY”)
or os.getenv(“FOOTBALL_DATA_TOKEN”)
)

HEADERS = {“User-Agent”: “FOOT-AI-PRO/7.0”}

if API_TOKEN:
HEADERS[“X-Auth-Token”] = API_TOKEN

============================================================

OUTILS

============================================================

def now_utc():
return datetime.now(timezone.utc)

def today_local():
return datetime.now(LOCAL_TIMEZONE).date()

def money(value):
try:
value = float(value)
return round(value, 2) if math.isfinite(value) else 0.0
except (TypeError, ValueError):
return 0.0

def print_line():
print(”-” * 60)

def get_bet_status(bet):
status = str(
bet.get(“statut”)
or bet.get(“status”)
or bet.get(“result”)
or “”
).strip().lower()

if status in ("gagne", "gagné", "won", "win"):
    return "GAGNE"
if status in ("perdu", "lost", "loss"):
    return "PERDU"
if status in ("annulé", "annule", "void", "cancelled"):
    return "ANNULE"
return "EN_ATTENTE"

============================================================

ÉTAT ET COMPATIBILITÉ AVEC APP.PY

============================================================

def default_state():
return {
“bankroll_initiale”: INITIAL_BANKROLL,
“bankroll_actuelle”: INITIAL_BANKROLL,
“benefice_total”: 0.0,
“mises_totales”: 0.0,
“gains_totaux”: 0.0,
“paris”: [],
“historique”: [],
“statistiques”: {
“total_paris”: 0,
“paris_gagnes”: 0,
“paris_perdus”: 0,
“paris_en_attente”: 0,
“taux_reussite”: 0.0,
},
“starting_bankroll”: INITIAL_BANKROLL,
“bankroll”: INITIAL_BANKROLL,
“profit”: 0.0,
“bets”: [],
“message”: “”,
“derniere_mise_a_jour”: None,
}

def convert_app_bet(bet):
return {
**bet,
“match_id”: bet.get(“match_id”, bet.get(“fixture_id”)),
“competition”: bet.get(“competition”) or bet.get(“league”) or “Compétition”,
“date_match”: (
bet.get(“date_match”)
or bet.get(“date”)
or bet.get(“match_date”)
),
“domicile”: (
bet.get(“domicile”)
or bet.get(“home”)
or bet.get(“home_team”)
or “Domicile”
),
“exterieur”: (
bet.get(“exterieur”)
or bet.get(“away”)
or bet.get(“away_team”)
or “Extérieur”
),
“marche”: (
bet.get(“marche”)
or bet.get(“pick”)
or bet.get(“market”)
or bet.get(“pronostic”)
or “”
),
“probabilite”: money(
bet.get(“probabilite”, bet.get(“probability”, 0))
),
“cote_estimee”: money(
bet.get(“cote_estimee”, bet.get(“odds”, bet.get(“cote”, 0)))
),
“mise”: money(bet.get(“mise”, bet.get(“stake”, 0))),
“statut”: get_bet_status(bet),
“gain”: money(bet.get(“gain”, bet.get(“payout”, 0))),
“score_prevu”: bet.get(“score_prevu”) or bet.get(“score”) or “”,
“score_final”: bet.get(“score_final”) or bet.get(“actual_score”) or “”,
}

def sync_app_format(state):
app_bets = []

for bet in state.get("paris", []):
    status = get_bet_status(bet)
    translated_status = {
        "EN_ATTENTE": "En attente",
        "GAGNE": "Gagné",
        "PERDU": "Perdu",
        "ANNULE": "Annulé",
    }.get(status, "En attente")
    stake = money(bet.get("mise", 0))
    payout = money(bet.get("gain", 0))
    if status == "GAGNE":
        profit = money(payout - stake)
    elif status == "PERDU":
        profit = -stake
    else:
        profit = 0.0
    app_bets.append({
        **bet,
        "match_id": bet.get("match_id"),
        "date": bet.get("date_match") or bet.get("date_creation", ""),
        "match_date": bet.get("date_match") or bet.get("date_creation", ""),
        "league": bet.get("competition", ""),
        "competition": bet.get("competition", ""),
        "home": bet.get("domicile", ""),
        "home_team": bet.get("domicile", ""),
        "away": bet.get("exterieur", ""),
        "away_team": bet.get("exterieur", ""),
        "pick": bet.get("marche", ""),
        "market": bet.get("marche", ""),
        "pronostic": bet.get("marche", ""),
        "probability": bet.get("probabilite", 0),
        "probability_pct": bet.get("probabilite", 0),
        "odds": bet.get("cote_estimee", 0),
        "stake": stake,
        "status": translated_status,
        "result": translated_status,
        "score": bet.get("score_prevu", ""),
        "actual_score": bet.get("score_final", ""),
        "settled": status in ("GAGNE", "PERDU", "ANNULE"),
        "profit": profit,
    })
state["starting_bankroll"] = money(
    state.get("bankroll_initiale", INITIAL_BANKROLL)
)
state["bankroll"] = money(
    state.get("bankroll_actuelle", INITIAL_BANKROLL)
)
state["profit"] = money(state.get("benefice_total", 0))
state["bets"] = app_bets
return state

def load_state():
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

if not STATE_FILE.exists():
    state = default_state()
    save_state(state)
    return state
with STATE_FILE.open("r", encoding="utf-8") as file:
    state = json.load(file)
if not isinstance(state, dict):
    raise RuntimeError("bankroll.json doit contenir un objet JSON.")
old_bankroll = state.get(
    "bankroll_actuelle",
    state.get("bankroll", state.get("starting_bankroll", INITIAL_BANKROLL)),
)
old_initial = state.get(
    "bankroll_initiale",
    state.get("starting_bankroll", INITIAL_BANKROLL),
)
defaults = default_state()
if not isinstance(state.get("paris"), list):
    state["paris"] = []
if not state["paris"] and isinstance(state.get("bets"), list):
    state["paris"] = [
        convert_app_bet(bet)
        for bet in state["bets"]
        if isinstance(bet, dict)
    ]
if not isinstance(state.get("historique"), list):
    state["historique"] = []
for key, value in defaults.items():
    state.setdefault(key, value)
state["bankroll_actuelle"] = money(old_bankroll)
state["bankroll_initiale"] = money(old_initial)
for key in ("mises_totales", "gains_totaux", "benefice_total"):
    state[key] = money(state.get(key, 0))
update_statistics(state)
return sync_app_format(state)

def save_state(state):
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

state["derniere_mise_a_jour"] = now_utc().isoformat()
sync_app_format(state)
temporary_file = STATE_FILE.with_suffix(".tmp")
with temporary_file.open("w", encoding="utf-8") as file:
    json.dump(state, file, ensure_ascii=False, indent=2)
temporary_file.replace(STATE_FILE)

def update_statistics(state):
bets = state.get(“paris”, [])

for bet in bets:
    bet["statut"] = get_bet_status(bet)
won = sum(1 for bet in bets if bet["statut"] == "GAGNE")
lost = sum(1 for bet in bets if bet["statut"] == "PERDU")
pending = sum(1 for bet in bets if bet["statut"] == "EN_ATTENTE")
settled = won + lost
state["statistiques"] = {
    "total_paris": len(bets),
    "paris_gagnes": won,
    "paris_perdus": lost,
    "paris_en_attente": pending,
    "taux_reussite": round(won / settled * 100, 2) if settled else 0.0,
}
gross_payouts = sum(
    money(bet.get("gain", 0))
    for bet in bets
    if bet["statut"] == "GAGNE"
)
settled_stakes = sum(
    money(bet.get("mise", 0))
    for bet in bets
    if bet["statut"] in ("GAGNE", "PERDU")
)
state["gains_totaux"] = money(gross_payouts)
state["benefice_total"] = money(gross_payouts - settled_stakes)

============================================================

API

============================================================

def api_get(endpoint, params=None):
if not API_TOKEN:
raise RuntimeError(
“Clé API absente. Vérifie FOOTBALL_DATA_API_KEY dans GitHub Secrets.”
)

try:
    response = requests.get(
        f"{API_BASE}{endpoint}",
        headers=HEADERS,
        params=params,
        timeout=25,
    )
    if response.status_code == 429:
        print("API : limite de requêtes atteinte.")
        return None
    if response.status_code == 403:
        print("API : compétition ou période non autorisée.")
        return None
    if response.status_code == 401:
        print("API : clé invalide.")
        return None
    response.raise_for_status()
    return response.json()
except requests.RequestException as exc:
    print(f"API : erreur réseau : {exc}")
    return None

def get_competition_matches(code, date_from, date_to):
data = api_get(
f”/competitions/{code}/matches”,
params={“dateFrom”: date_from, “dateTo”: date_to},
)

if not isinstance(data, dict):
    return None
matches = data.get("matches")
return matches if isinstance(matches, list) else None

============================================================

STATISTIQUES DES ÉQUIPES

============================================================

def build_team_stats(matches):
stats = {}

def ensure_team(team_id):
    if team_id not in stats:
        stats[team_id] = {
            "played": 0,
            "scored": 0,
            "conceded": 0,
            "home_played": 0,
            "home_scored": 0,
            "home_conceded": 0,
            "away_played": 0,
            "away_scored": 0,
            "away_conceded": 0,
        }
    return stats[team_id]
for match in matches:
    if match.get("status") not in ("FINISHED", "AWARDED"):
        continue
    score = (match.get("score") or {}).get("fullTime") or {}
    hg, ag = score.get("home"), score.get("away")
    home_id = (match.get("homeTeam") or {}).get("id")
    away_id = (match.get("awayTeam") or {}).get("id")
    if None in (hg, ag, home_id, away_id):
        continue
    home, away = ensure_team(home_id), ensure_team(away_id)
    home["played"] += 1
    home["scored"] += hg
    home["conceded"] += ag
    home["home_played"] += 1
    home["home_scored"] += hg
    home["home_conceded"] += ag
    away["played"] += 1
    away["scored"] += ag
    away["conceded"] += hg
    away["away_played"] += 1
    away["away_scored"] += ag
    away["away_conceded"] += hg
return stats

def league_averages(matches):
home_goals, away_goals = [], []

for match in matches:
    if match.get("status") not in ("FINISHED", "AWARDED"):
        continue
    score = (match.get("score") or {}).get("fullTime") or {}
    hg, ag = score.get("home"), score.get("away")
    if hg is not None and ag is not None:
        home_goals.append(hg)
        away_goals.append(ag)
avg_home = sum(home_goals) / len(home_goals) if home_goals else 1.45
avg_away = sum(away_goals) / len(away_goals) if away_goals else 1.10
return max(avg_home, 0.2), max(avg_away, 0.2)

def expected_goals(team_stats, team_id, opponent_id, avg_home, avg_away, home):
team = team_stats.get(team_id, {})
opponent = team_stats.get(opponent_id, {})

if home:
    scored = (
        team["home_scored"] / team["home_played"]
        if team.get("home_played", 0) else avg_home
    )
    conceded = (
        opponent["away_conceded"] / opponent["away_played"]
        if opponent.get("away_played", 0) else avg_home
    )
    expected = (scored / avg_home) * (conceded / avg_home) * avg_home
else:
    scored = (
        team["away_scored"] / team["away_played"]
        if team.get("away_played", 0) else avg_away
    )
    conceded = (
        opponent["home_conceded"] / opponent["home_played"]
        if opponent.get("home_played", 0) else avg_away
    )
    expected = (scored / avg_away) * (conceded / avg_away) * avg_away
return max(0.15, min(expected, 4.5))

============================================================

POISSON

============================================================

def poisson_probability(goals, expected):
return math.exp(-expected) * expected ** goals / math.factorial(goals)

def calculate_probabilities(home_xg, away_xg):
max_goals = 10

home_probs = [poisson_probability(i, home_xg) for i in range(max_goals + 1)]
away_probs = [poisson_probability(i, away_xg) for i in range(max_goals + 1)]
result = {
    "home": 0.0,
    "draw": 0.0,
    "away": 0.0,
    "over15": 0.0,
    "over25": 0.0,
    "over35": 0.0,
    "under35": 0.0,
    "btts_yes": 0.0,
    "btts_no": 0.0,
}
scores = []
for hg in range(max_goals + 1):
    for ag in range(max_goals + 1):
        probability = home_probs[hg] * away_probs[ag]
        if hg > ag:
            result["home"] += probability
        elif hg == ag:
            result["draw"] += probability
        else:
            result["away"] += probability
        total = hg + ag
        if total >= 2:
            result["over15"] += probability
        if total >= 3:
            result["over25"] += probability
        if total >= 4:
            result["over35"] += probability
        if total <= 3:
            result["under35"] += probability
        if hg >= 1 and ag >= 1:
            result["btts_yes"] += probability
        scores.append((probability, hg, ag))
result["btts_no"] = max(0.0, 1.0 - result["btts_yes"])
best_score = max(scores, key=lambda item: item[0])
result["score"] = f"{best_score[1]}-{best_score[2]}"
return result

============================================================

SÉLECTION DES MARCHÉS

============================================================

def select_candidates(probabilities):
markets = [
(“Les deux équipes marquent : OUI”, probabilities[“btts_yes”], 1.30),
(“Plus de 2,5 buts”, probabilities[“over25”], 1.20),
(“Plus de 3,5 buts”, probabilities[“over35”], 1.10),
(“Victoire domicile”, probabilities[“home”], 1.00),
(“Victoire extérieur”, probabilities[“away”], 1.00),
(“Plus de 1,5 but”, probabilities[“over15”], 0.95),
(“1X”, probabilities[“home”] + probabilities[“draw”], 0.75),
(“X2”, probabilities[“draw”] + probabilities[“away”], 0.75),
(“Moins de 3,5 buts”, probabilities[“under35”], 0.65),
(“Les deux équipes marquent : NON”, probabilities[“btts_no”], 0.60),
]

candidates = []
for market, probability, risk_weight in markets:
    probability = max(0.0, min(1.0, probability))
    if probability < MIN_PROBABILITY:
        continue
    odds = 1.0 / probability if probability > 0 else 99.0
    if odds > MAX_ESTIMATED_ODDS:
        continue
    candidates.append({
        "marche": market,
        "probabilite": round(probability * 100, 2),
        "cote_estimee": round(odds, 2),
        "classement": probability * risk_weight,
    })
candidates.sort(key=lambda item: item["classement"], reverse=True)
return candidates

def bet_won(bet, home_goals, away_goals):
market = bet.get(“marche”, “”)
total = home_goals + away_goals

if market == "1X":
    return home_goals >= away_goals
if market == "X2":
    return away_goals >= home_goals
if market == "Victoire domicile":
    return home_goals > away_goals
if market == "Victoire extérieur":
    return away_goals > home_goals
if market == "Plus de 1,5 but":
    return total >= 2
if market == "Plus de 2,5 buts":
    return total >= 3
if market == "Plus de 3,5 buts":
    return total >= 4
if market == "Moins de 3,5 buts":
    return total <= 3
if market == "Les deux équipes marquent : OUI":
    return home_goals >= 1 and away_goals >= 1
if market == "Les deux équipes marquent : NON":
    return home_goals == 0 or away_goals == 0
return False

============================================================

RÈGLEMENT DES PARIS

============================================================

def refresh_pending_bets(state, finished_matches):
by_id = {
match.get(“id”): match
for match in finished_matches
if match.get(“id”) is not None
}

updated = 0
for bet in state["paris"]:
    if get_bet_status(bet) != "EN_ATTENTE":
        continue
    match = by_id.get(bet.get("match_id"))
    if not match or match.get("status") not in ("FINISHED", "AWARDED"):
        continue
    score = (match.get("score") or {}).get("fullTime") or {}
    home_goals = score.get("home")
    away_goals = score.get("away")
    if home_goals is None or away_goals is None:
        continue
    bet["score_final"] = f"{home_goals}-{away_goals}"
    stake = money(bet.get("mise", 0))
    odds = money(bet.get("cote_estimee", 0))
    if bet_won(bet, home_goals, away_goals):
        bet["statut"] = "GAGNE"
        bet["gain"] = money(stake * odds)
        state["bankroll_actuelle"] = money(
            state["bankroll_actuelle"] + bet["gain"]
        )
        print(f"PARI GAGNÉ : {bet.get('domicile')} - {bet.get('exterieur')}")
    else:
        bet["statut"] = "PERDU"
        bet["gain"] = 0.0
        print(f"PARI PERDU : {bet.get('domicile')} - {bet.get('exterieur')}")
    bet["date_reglement"] = now_utc().isoformat()
    state["historique"].append({
        "match_id": bet.get("match_id"),
        "domicile": bet.get("domicile"),
        "exterieur": bet.get("exterieur"),
        "marche": bet.get("marche"),
        "statut": bet.get("statut"),
        "score_final": bet.get("score_final"),
        "mise": stake,
        "gain": money(bet.get("gain", 0)),
        "date_reglement": bet["date_reglement"],
    })
    updated += 1
print(f"Paris réglés lors de cette exécution : {updated}")

============================================================

DATES

============================================================

def parse_match_date(match):
try:
kickoff = datetime.fromisoformat(
match[“utcDate”].replace(“Z”, “+00:00”)
)
return kickoff.astimezone(LOCAL_TIMEZONE).date(), kickoff
except (KeyError, ValueError, TypeError):
return None, None

def same_local_day(match):
match_date, _ = parse_match_date(match)
return match_date == today_local()

============================================================

ANALYSE PRINCIPALE

============================================================

def main():
print_line()
print(“FOOT AI PRO BOT V7”)
print(“Simulation virtuelle uniquement.”)
print(f”Date française : {datetime.now(LOCAL_TIMEZONE).isoformat()}”)
print(f”Date limite des nouveaux paris : {MAX_MATCH_DATE}”)
print_line()

if not API_TOKEN:
    raise SystemExit(
        "ERREUR : clé API absente. Vérifie le secret GitHub FOOTBALL_DATA_API_KEY."
    )
state = load_state()
print(f"Capital disponible : {money(state['bankroll_actuelle']):.2f} €")
today = today_local()
all_finished = []
all_candidates = []
# Ne pas créer de paris pour des dates après la limite.
can_create_bets = today <= MAX_MATCH_DATE
if can_create_bets:
    print(f"Recherche des matchs du jour : {today.isoformat()}")
else:
    print("Date limite dépassée : aucun nouveau pari ne sera créé.")
print_line()
# Pour pouvoir régler les paris en attente, récupérer les matchs
# du jour et des jours récents dans chaque compétition.
date_from = (today - timedelta(days=7)).isoformat()
date_to = today.isoformat()
for code, competition_name in COMPETITIONS.items():
    print(f"Analyse : {competition_name} ({code})")
    matches = get_competition_matches(code, date_from, date_to)
    if matches is None:
        print("  Données indisponibles.")
        continue
    all_finished.extend([
        match for match in matches
        if match.get("status") in ("FINISHED", "AWARDED")
    ])
    if not can_create_bets:
        continue
    today_matches = [
        match for match in matches
        if match.get("status") in ("SCHEDULED", "TIMED")
        and same_local_day(match)
    ]
    print(f"  Matchs du jour à venir : {len(today_matches)}")
    if not today_matches:
        continue
    team_stats = build_team_stats(matches)
    avg_home, avg_away = league_averages(matches)
    for match in today_matches:
        match_id = match.get("id")
        if match_id is None:
            continue
        # Bloquer les doublons.
        if any(
            str(bet.get("match_id")) == str(match_id)
            for bet in state["paris"]
        ):
            continue
        match_date, kickoff = parse_match_date(match)
        if match_date is None or match_date > MAX_MATCH_DATE:
            continue
        if kickoff is None or kickoff <= now_utc():
            continue
        home = match.get("homeTeam") or {}
        away = match.get("awayTeam") or {}
        if home.get("id") is None or away.get("id") is None:
            continue
        home_xg = expected_goals(
            team_stats, home["id"], away["id"],
            avg_home, avg_away, True
        )
        away_xg = expected_goals(
            team_stats, away["id"], home["id"],
            avg_home, avg_away, False
        )
        probabilities = calculate_probabilities(home_xg, away_xg)
        selections = select_candidates(probabilities)
        if not selections:
            continue
        best = selections[0]
        all_candidates.append({
            "match_id": match_id,
            "competition": competition_name,
            "date_match": match["utcDate"],
            "domicile": home.get("name", "Domicile"),
            "exterieur": away.get("name", "Extérieur"),
            "marche": best["marche"],
            "probabilite": best["probabilite"],
            "cote_estimee": best["cote_estimee"],
            "classement": best["classement"],
            "score_prevu": probabilities["score"],
            "buts_attendus_domicile": round(home_xg, 2),
            "buts_attendus_exterieur": round(away_xg, 2),
            "date_creation": now_utc().isoformat(),
        })
# Régler les paris existants, même si la date limite est dépassée.
refresh_pending_bets(state, all_finished)
all_candidates.sort(
    key=lambda item: (item["classement"], item["probabilite"]),
    reverse=True,
)
created = 0
if can_create_bets:
    for candidate in all_candidates:
        if created >= MAX_BETS_PER_RUN:
            break
        if money(state["bankroll_actuelle"]) < STAKE:
            print("Capital disponible insuffisant pour de nouveaux paris.")
            break
        bet = dict(candidate)
        bet.pop("classement", None)
        bet["mise"] = STAKE
        bet["statut"] = "EN_ATTENTE"
        bet["gain"] = 0.0
        state["paris"].append(bet)
        state["bankroll_actuelle"] = money(
            state["bankroll_actuelle"] - STAKE
        )
        state["mises_totales"] = money(
            state.get("mises_totales", 0) + STAKE
        )
        created += 1
        print_line()
        print(f"NOUVEAU PARI : {bet['domicile']} - {bet['exterieur']}")
        print(f"Compétition : {bet['competition']}")
        print(f"Marché : {bet['marche']}")
        print(f"Probabilité estimée : {bet['probabilite']} %")
        print(f"Cote virtuelle estimée : {bet['cote_estimee']}")
        print(f"Score indicatif : {bet['score_prevu']}")
        print(f"Mise virtuelle : {STAKE:.2f} €")
update_statistics(state)
save_state(state)
print_line()
print("RÉSUMÉ DE LA SIMULATION")
print_line()
print(f"Nouveaux paris : {created}")
print(f"Capital disponible : {state['bankroll_actuelle']:.2f} €")
print(f"Bénéfice réalisé : {state['benefice_total']:.2f} €")
stats = state["statistiques"]
print(f"Paris enregistrés : {stats['total_paris']}")
print(f"Paris gagnés : {stats['paris_gagnes']}")
print(f"Paris perdus : {stats['paris_perdus']}")
print(f"Paris en attente : {stats['paris_en_attente']}")
print(f"Taux de réussite : {stats['taux_reussite']} %")
print(f"Fichier enregistré : {STATE_FILE}")
print("Simulation terminée.")
print_line()

if name == “main”:
main()