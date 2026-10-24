import os
import json
import math
from pathlib import Path
from datetime import datetime, timedelta, timezone

import requests


# ============================================================
# FOOT AI PRO BOT V4
# Simulation virtuelle uniquement
# Capital initial : 20 €
# API : football-data.org v4
# ============================================================

API_BASE = "https://api.football-data.org/v4"

STATE_FILE = Path("data/bankroll.json")

INITIAL_BANKROLL = 20.0
STAKE = 1.0
MAX_BETS_PER_RUN = 5

PAST_DAYS = 60
FUTURE_DAYS = 7

MIN_PROBABILITY = 0.65
MAX_ESTIMATED_ODDS = 2.50

COMPETITIONS = {
    "FL1": "Ligue 1",
    "PL": "Premier League",
    "PD": "Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "CL": "Ligue des champions",
}

HEADERS = {
    "User-Agent": "FOOT-AI-PRO/4.0"
}

API_TOKEN = (
    os.getenv("FOOTBALL_DATA_API_KEY")
    or os.getenv("FOOTBALL_API_KEY")
    or os.getenv("FOOTBALL_DATA_TOKEN")
)

if API_TOKEN:
    HEADERS["X-Auth-Token"] = API_TOKEN


# ============================================================
# OUTILS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc)


def today_utc():
    return now_utc().date()


def money(value):
    return round(float(value), 2)


def print_line():
    print("-" * 60)


# ============================================================
# BANKROLL
# ============================================================

def default_state():
    return {
        "bankroll_initiale": INITIAL_BANKROLL,
        "bankroll_actuelle": INITIAL_BANKROLL,
        "benefice_total": 0.0,
        "mises_totales": 0.0,
        "gains_totaux": 0.0,
        "paris": [],
        "historique": [],
        "statistiques": {
            "total_paris": 0,
            "paris_gagnes": 0,
            "paris_perdus": 0,
            "paris_en_attente": 0,
            "taux_reussite": 0.0,
        },
        "derniere_mise_a_jour": None,
    }


def load_state():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not STATE_FILE.exists():
        state = default_state()
        save_state(state)
        print("Nouvelle bankroll virtuelle créée : 20 €")
        return state

    try:
        with STATE_FILE.open("r", encoding="utf-8") as file:
            state = json.load(file)

        if not isinstance(state, dict):
            raise ValueError("Le fichier JSON ne contient pas un objet.")

        defaults = default_state()

        for key, value in defaults.items():
            if key not in state:
                state[key] = value

        if not isinstance(state["paris"], list):
            state["paris"] = []

        if not isinstance(state["historique"], list):
            state["historique"] = []

        if not isinstance(state["statistiques"], dict):
            state["statistiques"] = defaults["statistiques"]

        for key, value in defaults["statistiques"].items():
            state["statistiques"].setdefault(key, value)

        state["bankroll_initiale"] = float(
            state.get("bankroll_initiale", INITIAL_BANKROLL)
        )

        state["bankroll_actuelle"] = float(
            state.get("bankroll_actuelle", INITIAL_BANKROLL)
        )

        state["mises_totales"] = float(
            state.get("mises_totales", 0.0)
        )

        state["gains_totaux"] = float(
            state.get("gains_totaux", 0.0)
        )

        state["benefice_total"] = float(
            state.get("benefice_total", 0.0)
        )

        return state

    except (json.JSONDecodeError, OSError, ValueError, TypeError) as exc:
        raise RuntimeError(
            f"Impossible de lire {STATE_FILE}: {exc}"
        ) from exc


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    state["derniere_mise_a_jour"] = now_utc().isoformat()

    temporary_file = STATE_FILE.with_suffix(".tmp")

    with temporary_file.open("w", encoding="utf-8") as file:
        json.dump(
            state,
            file,
            ensure_ascii=False,
            indent=2,
        )

    temporary_file.replace(STATE_FILE)


def update_statistics(state):
    bets = state["paris"]

    won = sum(
        1 for bet in bets
        if bet.get("statut") == "GAGNE"
    )

    lost = sum(
        1 for bet in bets
        if bet.get("statut") == "PERDU"
    )

    pending = sum(
        1 for bet in bets
        if bet.get("statut") == "EN_ATTENTE"
    )

    settled = won + lost

    state["statistiques"] = {
        "total_paris": len(bets),
        "paris_gagnes": won,
        "paris_perdus": lost,
        "paris_en_attente": pending,
        "taux_reussite": round(
            (won / settled) * 100, 2
        ) if settled else 0.0,
    }

    settled_stakes = sum(
        float(bet.get("mise", 0))
        for bet in bets
        if bet.get("statut") in ("GAGNE", "PERDU")
    )

    state["benefice_total"] = money(
        state["gains_totaux"] - settled_stakes
    )


# ============================================================
# API FOOTBALL-DATA.ORG
# ============================================================

def api_get(endpoint, params=None):
    url = f"{API_BASE}{endpoint}"

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            params=params,
            timeout=25,
        )

        if response.status_code == 429:
            print("API : limite de requêtes atteinte.")
            print("Le bot réessaiera lors de la prochaine exécution.")
            return None

        if response.status_code == 403:
            print(
                "API : accès refusé à cette compétition "
                "ou à ces données."
            )
            return None

        if response.status_code == 401:
            print("API : clé invalide ou non reconnue.")
            return None

        response.raise_for_status()

        return response.json()

    except requests.Timeout:
        print(f"API : délai dépassé pour {endpoint}.")
        return None

    except requests.RequestException as exc:
        print(f"API : erreur réseau : {exc}")
        return None

    except ValueError:
        print("API : réponse JSON invalide.")
        return None


def get_competition_matches(code, date_from, date_to):
    data = api_get(
        f"/competitions/{code}/matches",
        params={
            "dateFrom": date_from,
            "dateTo": date_to,
        },
    )

    if not data:
        return None

    return data.get("matches", [])


# ============================================================
# STATISTIQUES DES ÉQUIPES
# ============================================================

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
        if match.get("status") != "FINISHED":
            continue

        score = match.get("score", {}).get("fullTime", {})

        home_goals = score.get("home")
        away_goals = score.get("away")

        if home_goals is None or away_goals is None:
            continue

        home_id = (match.get("homeTeam") or {}).get("id")
        away_id = (match.get("awayTeam") or {}).get("id")

        if home_id is None or away_id is None:
            continue

        home = ensure_team(home_id)
        away = ensure_team(away_id)

        home["played"] += 1
        home["scored"] += home_goals
        home["conceded"] += away_goals

        home["home_played"] += 1
        home["home_scored"] += home_goals
        home["home_conceded"] += away_goals

        away["played"] += 1
        away["scored"] += away_goals
        away["conceded"] += home_goals

        away["away_played"] += 1
        away["away_scored"] += away_goals
        away["away_conceded"] += home_goals

    return stats


def league_averages(matches):
    home_goals = []
    away_goals = []

    for match in matches:
        if match.get("status") != "FINISHED":
            continue

        score = match.get("score", {}).get("fullTime", {})

        h = score.get("home")
        a = score.get("away")

        if h is None or a is None:
            continue

        home_goals.append(h)
        away_goals.append(a)

    avg_home = (
        sum(home_goals) / len(home_goals)
        if home_goals else 1.45
    )

    avg_away = (
        sum(away_goals) / len(away_goals)
        if away_goals else 1.10
    )

    return max(avg_home, 0.2), max(avg_away, 0.2)


def expected_goals(team_stats, team_id, opponent_id, avg_home, avg_away, home):
    team = team_stats.get(team_id, {})
    opponent = team_stats.get(opponent_id, {})

    if home:
        scored = (
            team.get("home_scored", 0)
            / team.get("home_played", 1)
            if team.get("home_played", 0) else avg_home
        )

        conceded = (
            opponent.get("away_conceded", 0)
            / opponent.get("away_played", 1)
            if opponent.get("away_played", 0) else avg_home
        )

        expected = (scored / avg_home) * (
            conceded / avg_home
        ) * avg_home

        return max(0.15, min(expected, 4.5))

    scored = (
        team.get("away_scored", 0)
        / team.get("away_played", 1)
        if team.get("away_played", 0) else avg_away
    )

    conceded = (
        opponent.get("home_conceded", 0)
        / opponent.get("home_played", 1)
        if opponent.get("home_played", 0) else avg_away
    )

    expected = (scored / avg_away) * (
        conceded / avg_away
    ) * avg_away

    return max(0.15, min(expected, 4.5))


# ============================================================
# MODÈLE DE POISSON
# ============================================================

def poisson_probability(goals, expected):
    return (
        math.exp(-expected)
        * (expected ** goals)
        / math.factorial(goals)
    )


def calculate_probabilities(home_xg, away_xg):
    max_goals = 9

    home_probs = [
        poisson_probability(i, home_xg)
        for i in range(max_goals + 1)
    ]

    away_probs = [
        poisson_probability(i, away_xg)
        for i in range(max_goals + 1)
    ]

    home_win = 0.0
    draw = 0.0
    away_win = 0.0

    over_15 = 0.0
    over_25 = 0.0
    under_35 = 0.0
    btts_yes = 0.0

    score_probs = []

    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            probability = home_probs[h] * away_probs[a]

            if h > a:
                home_win += probability
            elif h == a:
                draw += probability
            else:
                away_win += probability

            if h + a >= 2:
                over_15 += probability

            if h + a >= 3:
                over_25 += probability

            if h + a <= 3:
                under_35 += probability

            if h >= 1 and a >= 1:
                btts_yes += probability

            score_probs.append((probability, h, a))

    total = home_win + draw + away_win

    if total > 0:
        home_win /= total
        draw /= total
        away_win /= total

    score_probs.sort(reverse=True)

    best_score = score_probs[0]

    return {
        "home": home_win,
        "draw": draw,
        "away": away_win,
        "over15": over_15,
        "over25": over_25,
        "under35": under_35,
        "btts_yes": btts_yes,
        "btts_no": max(0.0, 1.0 - btts_yes),
        "score": f"{best_score[1]}-{best_score[2]}",
    }


# ============================================================
# SÉLECTION DU PARI VIRTUEL
# ============================================================

def select_bet(probabilities):
    candidates = [
        ("1X", probabilities["home"] + probabilities["draw"]),
        ("X2", probabilities["draw"] + probabilities["away"]),
        ("Plus de 1,5 but", probabilities["over15"]),
        ("Moins de 3,5 buts", probabilities["under35"]),
        ("Les deux équipes marquent : OUI", probabilities["btts_yes"]),
        ("Les deux équipes marquent : NON", probabilities["btts_no"]),
    ]

    candidates.sort(key=lambda item: item[1], reverse=True)

    for market, probability in candidates:
        if probability < MIN_PROBABILITY:
            continue

        # Cote virtuelle estimée, non fournie par un bookmaker.
        estimated_odds = 1.0 / probability

        if estimated_odds > MAX_ESTIMATED_ODDS:
            continue

        return {
            "marche": market,
            "probabilite": round(probability * 100, 2),
            "cote_estimee": round(estimated_odds, 2),
        }

    return None


# ============================================================
# RÈGLEMENT DES PARIS
# ============================================================

def bet_won(bet, home_goals, away_goals):
    market = bet["marche"]

    if market == "1X":
        return home_goals >= away_goals

    if market == "X2":
        return away_goals >= home_goals

    total = home_goals + away_goals

    if market == "Plus de 1,5 but":
        return total >= 2

    if market == "Moins de 3,5 buts":
        return total <= 3

    if market == "Les deux équipes marquent : OUI":
        return home_goals >= 1 and away_goals >= 1

    if market == "Les deux équipes marquent : NON":
        return home_goals == 0 or away_goals == 0

    return False


def refresh_pending_bets(state, finished_matches):
    by_id = {
        match.get("id"): match
        for match in finished_matches
        if match.get("id") is not None
    }

    updated = 0

    for bet in state["paris"]:
        if bet.get("statut") != "EN_ATTENTE":
            continue

        match = by_id.get(bet.get("match_id"))

        if not match or match.get("status") != "FINISHED":
            continue

        score = match.get("score", {}).get("fullTime", {})

        home_goals = score.get("home")
        away_goals = score.get("away")

        if home_goals is None or away_goals is None:
            continue

        bet["score_final"] = f"{home_goals}-{away_goals}"

        if bet_won(bet, home_goals, away_goals):
            bet["statut"] = "GAGNE"

            payout = money(
                float(bet["mise"])
                * float(bet["cote_estimee"])
            )

            bet["gain"] = payout
            state["bankroll_actuelle"] = money(
                state["bankroll_actuelle"] + payout
            )
            state["gains_totaux"] = money(
                state["gains_totaux"] + payout
            )

            print(
                f"PARI GAGNÉ : {bet['domicile']} - "
                f"{bet['exterieur']} | {bet['marche']}"
            )

        else:
            bet["statut"] = "PERDU"
            bet["gain"] = 0.0

            print(
                f"PARI PERDU : {bet['domicile']} - "
                f"{bet['exterieur']} | {bet['marche']}"
            )

        bet["date_reglement"] = now_utc().isoformat()

        state["historique"].append({
            "match_id": bet["match_id"],
            "domicile": bet["domicile"],
            "exterieur": bet["exterieur"],
            "marche": bet["marche"],
            "statut": bet["statut"],
            "score_final": bet["score_final"],
            "mise": bet["mise"],
            "gain": bet["gain"],
        })

        updated += 1

    if updated:
        print(f"Paris réglés : {updated}")

    return updated


# ============================================================
# CRÉATION DES PARIS VIRTUELS
# ============================================================

def create_virtual_bets(state, upcoming_matches, competition_name, team_stats, averages):
    created = 0
    avg_home, avg_away = averages

    existing_ids = {
        bet.get("match_id")
        for bet in state["paris"]
    }

    for match in upcoming_matches:
        if created >= MAX_BETS_PER_RUN:
            break

        match_id = match.get("id")

        if match_id is None or match_id in existing_ids:
            continue

        if match.get("status") not in ("SCHEDULED", "TIMED"):
            continue

        try:
            kickoff = datetime.fromisoformat(
                match["utcDate"].replace("Z", "+00:00")
            )

            if kickoff <= now_utc():
                continue

        except (KeyError, ValueError, TypeError):
            continue

        home = match.get("homeTeam") or {}
        away = match.get("awayTeam") or {}

        home_id = home.get("id")
        away_id = away.get("id")

        if home_id is None or away_id is None:
            continue

        home_xg = expected_goals(
            team_stats,
            home_id,
            away_id,
            avg_home,
            avg_away,
            home=True,
        )

        away_xg = expected_goals(
            team_stats,
            away_id,
            home_id,
            avg_home,
            avg_away,
            home=False,
        )

        probabilities = calculate_probabilities(
            home_xg,
            away_xg,
        )

        selection = select_bet(probabilities)

        if not selection:
            print(
                f"Pas de pari suffisamment fiable : "
                f"{home.get('name')} - {away.get('name')}"
            )
            continue

        if state["bankroll_actuelle"] < STAKE:
            print("Capital disponible insuffisant.")
            break

        bet = {
            "match_id": match_id,
            "competition": competition_name,
            "date_match": match["utcDate"],
            "domicile": home.get("name", "Équipe domicile"),
            "exterieur": away.get("name", "Équipe extérieure"),
            "marche": selection["marche"],
            "probabilite": selection["probabilite"],
            "cote_estimee": selection["cote_estimee"],
            "mise": STAKE,
            "statut": "EN_ATTENTE",
            "gain": 0.0,
            "score_prevu": probabilities["score"],
            "buts_attendus_domicile": round(home_xg, 2),
            "buts_attendus_exterieur": round(away_xg, 2),
            "date_creation": now_utc().isoformat(),
        }

        state["paris"].append(bet)

        state["bankroll_actuelle"] = money(
            state["bankroll_actuelle"] - STAKE
        )

        state["mises_totales"] = money(
            state["mises_totales"] + STAKE
        )

        existing_ids.add(match_id)
        created += 1

        print(
            f"PARI VIRTUEL CRÉÉ : {bet['domicile']} - "
            f"{bet['exterieur']}"
        )
        print(
            f"  Compétition : {competition_name}"
        )
        print(
            f"  Marché : {bet['marche']}"
        )
        print(
            f"  Probabilité estimée : {bet['probabilite']} %"
        )
        print(
            f"  Cote virtuelle estimée : {bet['cote_estimee']}"
        )
        print(
            f"  Score indicatif : {bet['score_prevu']}"
        )
        print(
            f"  Mise virtuelle : {bet['mise']} €"
        )

    return created


# ============================================================
# PROGRAMME PRINCIPAL
# ============================================================

def main():
    print_line()
    print("FOOT AI PRO BOT V4")
    print("Simulation de paris virtuels uniquement.")
    print(f"Date UTC : {now_utc().isoformat()}")
    print_line()

    if not API_TOKEN:
        raise SystemExit(
            "ERREUR : clé API absente. "
            "Vérifie le secret GitHub FOOTBALL_DATA_API_KEY."
        )

    state = load_state()

    print(
        f"Capital virtuel disponible : "
        f"{state['bankroll_actuelle']:.2f} €"
    )

    start_date = (
        today_utc() - timedelta(days=PAST_DAYS)
    ).isoformat()

    end_date = (
        today_utc() + timedelta(days=FUTURE_DAYS)
    ).isoformat()

    print(f"Période analysée : {start_date} -> {end_date}")
    print_line()

    all_finished_matches = []
    competition_data = {}

    # Six appels au maximum pour récupérer les matchs.
    for code, name in COMPETITIONS.items():
        print(f"Recherche des matchs : {name} ({code})")

        matches = get_competition_matches(
            code,
            start_date,
            end_date,
        )

        if matches is None:
            print("  Données indisponibles pour cette compétition.")
            print_line()
            continue

        print(f"  Matchs récupérés : {len(matches)}")

        finished = [
            match for match in matches
            if match.get("status") == "FINISHED"
        ]

        upcoming = [
            match for match in matches
            if match.get("status") in ("SCHEDULED", "TIMED")
        ]

        all_finished_matches.extend(finished)

        competition_data[code] = {
            "name": name,
            "matches": matches,
            "upcoming": upcoming,
        }

        print(f"  Matchs terminés : {len(finished)}")
        print(f"  Matchs à venir : {len(upcoming)}")
        print_line()

    # Règle les paris déjà enregistrés.
    refresh_pending_bets(
        state,
        all_finished_matches,
    )

    # Crée de nouveaux paris virtuels.
    total_created = 0

    for code, info in competition_data.items():
        if total_created >= MAX_BETS_PER_RUN:
            break

        matches = info["matches"]
        upcoming = info["upcoming"]

        if not upcoming:
            continue

        team_stats = build_team_stats(matches)
        averages = league_averages(matches)

        created = create_virtual_bets(
            state,
            upcoming,
            info["name"],
            team_stats,
            averages,
        )

        total_created += created

    update_statistics(state)
    save_state(state)

    print_line()
    print("RÉSUMÉ DE LA SIMULATION")
    print_line()

    print(f"Nouveaux paris : {total_created}")

    print(
        f"Capital disponible : "
        f"{state['bankroll_actuelle']:.2f} €"
    )

    print(
        f"Bénéfice réalisé : "
        f"{state['benefice_total']:.2f} €"
    )

    stats = state["statistiques"]

    print(f"Paris enregistrés : {stats['total_paris']}")
    print(f"Paris gagnés : {stats['paris_gagnes']}")
    print(f"Paris perdus : {stats['paris_perdus']}")
    print(f"Paris en attente : {stats['paris_en_attente']}")
    print(f"Taux de réussite : {stats['taux_reussite']} %")

    if total_created == 0:
        print(
            "Aucun nouveau pari créé. Vérifie les matchs récupérés, "
            "les accès API et les seuils de sélection."
        )

    print("Fichier enregistré : data/bankroll.json")
    print("Simulation terminée.")
    print_line()


if __name__ == "__main__":
    main()