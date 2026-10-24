import os
import json
import math
from pathlib import Path
from datetime import datetime, timedelta, timezone

import requests

# ============================================================
# FOOT AI PRO BOT V5
# Simulation virtuelle uniquement — aucun pari réel
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
    "CL": "Ligue des Champions",
}

API_TOKEN = (
    os.getenv("FOOTBALL_DATA_API_KEY")
    or os.getenv("FOOTBALL_API_KEY")
    or os.getenv("FOOTBALL_DATA_TOKEN")
)

HEADERS = {"User-Agent": "FOOT-AI-PRO/5.0"}

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
    try:
        result = round(float(value), 2)
        return result if math.isfinite(result) else 0.0
    except (TypeError, ValueError):
        return 0.0


def print_line():
    print("-" * 60)


def get_bet_status(bet):
    status = str(
        bet.get("statut")
        or bet.get("status")
        or bet.get("result")
        or ""
    ).strip().lower()

    if status in ("gagne", "gagné", "won", "win", "gagne!"):
        return "GAGNE"

    if status in ("perdu", "lost", "loss"):
        return "PERDU"

    if status in ("annulé", "annule", "void", "cancelled"):
        return "ANNULE"

    return "EN_ATTENTE"


# ============================================================
# BANKROLL ET COMPATIBILITÉ APP.PY
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

        # Compatibilité avec l'ancien tableau de bord Streamlit.
        "starting_bankroll": INITIAL_BANKROLL,
        "bankroll": INITIAL_BANKROLL,
        "profit": 0.0,
        "bets": [],
        "message": "",
        "derniere_mise_a_jour": None,
    }


def convert_app_bet(bet):
    """Convertit un pari du format app.py vers le format du bot."""

    return {
        **bet,
        "match_id": bet.get("match_id", bet.get("fixture_id")),
        "competition": (
            bet.get("competition")
            or bet.get("league")
            or "Compétition"
        ),
        "date_match": (
            bet.get("date_match")
            or bet.get("date")
            or bet.get("match_date")
        ),
        "domicile": (
            bet.get("domicile")
            or bet.get("home")
            or bet.get("home_team")
            or "Domicile"
        ),
        "exterieur": (
            bet.get("exterieur")
            or bet.get("away")
            or bet.get("away_team")
            or "Extérieur"
        ),
        "marche": (
            bet.get("marche")
            or bet.get("pick")
            or bet.get("market")
            or bet.get("pronostic")
            or ""
        ),
        "probabilite": money(
            bet.get(
                "probabilite",
                bet.get("probability", bet.get("probability_pct", 0)),
            )
        ),
        "cote_estimee": money(
            bet.get(
                "cote_estimee",
                bet.get("odds", bet.get("cote", 0)),
            )
        ),
        "mise": money(bet.get("mise", bet.get("stake", 0))),
        "statut": get_bet_status(bet),
        "gain": money(bet.get("gain", bet.get("payout", 0))),
        "score_prevu": bet.get("score_prevu") or bet.get("score") or "",
        "score_final": (
            bet.get("score_final")
            or bet.get("actual_score")
            or ""
        ),
    }


def sync_app_format(state):
    """Expose les données du bot dans le format attendu par app.py."""

    app_bets = []

    for bet in state.get("paris", []):
        status = bet.get("statut", "EN_ATTENTE")

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
        print(f"Nouvelle bankroll virtuelle : {INITIAL_BANKROLL:.2f} €")
        return state

    try:
        with STATE_FILE.open("r", encoding="utf-8") as file:
            state = json.load(file)

        if not isinstance(state, dict):
            raise ValueError("Le fichier JSON doit contenir un objet.")

        defaults = default_state()

        if not isinstance(state.get("paris"), list):
            state["paris"] = []

        # Migration depuis l'ancien format de l'application.
        if not state["paris"] and isinstance(state.get("bets"), list):
            state["paris"] = [
                convert_app_bet(bet)
                for bet in state["bets"]
                if isinstance(bet, dict)
            ]

        if not isinstance(state.get("historique"), list):
            state["historique"] = []

        if not isinstance(state.get("statistiques"), dict):
            state["statistiques"] = defaults["statistiques"].copy()

        # Compléter les champs manquants sans remplacer les valeurs existantes.
        for key, value in defaults.items():
            state.setdefault(key, value)

        # Ne jamais réinitialiser un capital déjà enregistré.
        if "bankroll_actuelle" not in state:
            state["bankroll_actuelle"] = state.get(
                "bankroll",
                state.get("starting_bankroll", INITIAL_BANKROLL),
            )

        if "bankroll_initiale" not in state:
            state["bankroll_initiale"] = state.get(
                "starting_bankroll",
                INITIAL_BANKROLL,
            )

        for key in (
            "bankroll_initiale",
            "bankroll_actuelle",
            "mises_totales",
            "gains_totaux",
            "benefice_total",
        ):
            state[key] = money(state.get(key, 0))

        # Si app.py a réglé un pari, récupérer le statut connu.
        app_bets = state.get("bets", [])

        if isinstance(app_bets, list):
            app_by_id = {
                str(bet.get("match_id")): bet
                for bet in app_bets
                if isinstance(bet, dict)
                and bet.get("match_id") is not None
            }

            for bet in state["paris"]:
                app_bet = app_by_id.get(str(bet.get("match_id")))

                if not app_bet:
                    continue

                app_status = get_bet_status(app_bet)

                if (
                    app_status in ("GAGNE", "PERDU", "ANNULE")
                    and bet.get("statut") == "EN_ATTENTE"
                ):
                    # On récupère le statut mais on ne modifie pas ici
                    # le capital, pour éviter de créditer deux fois un gain.
                    bet["statut"] = app_status
                    bet["score_final"] = (
                        app_bet.get("actual_score")
                        or app_bet.get("score_final")
                        or ""
                    )

        update_statistics(state)
        return sync_app_format(state)

    except (json.JSONDecodeError, OSError, ValueError, TypeError) as exc:
        # Surtout ne pas écraser automatiquement un fichier corrompu.
        raise RuntimeError(
            f"Impossible de lire {STATE_FILE}: {exc}. "
            "Le fichier existant est conservé pour protéger les paris."
        ) from exc


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    state["derniere_mise_a_jour"] = now_utc().isoformat()
    sync_app_format(state)

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
    bets = state.get("paris", [])

    won = sum(1 for bet in bets if bet.get("statut") == "GAGNE")
    lost = sum(1 for bet in bets if bet.get("statut") == "PERDU")
    pending = sum(1 for bet in bets if bet.get("statut") == "EN_ATTENTE")

    settled = won + lost

    state["statistiques"] = {
        "total_paris": len(bets),
        "paris_gagnes": won,
        "paris_perdus": lost,
        "paris_en_attente": pending,
        "taux_reussite": round(won / settled * 100, 2) if settled else 0.0,
    }

    # Le gain d'un pari gagné représente le retour total, mise comprise.
    gross_payouts = sum(
        money(bet.get("gain", 0))
        for bet in bets
        if bet.get("statut") == "GAGNE"
    )

    settled_stakes = sum(
        money(bet.get("mise", 0))
        for bet in bets
        if bet.get("statut") in ("GAGNE", "PERDU")
    )

    state["gains_totaux"] = money(gross_payouts)
    state["benefice_total"] = money(gross_payouts - settled_stakes)


# ============================================================
# API FOOTBALL-DATA.ORG
# ============================================================

def api_get(endpoint, params=None):
    if not API_TOKEN:
        print("API : clé absente.")
        return None

    try:
        response = requests.get(
            f"{API_BASE}{endpoint}",
            headers=HEADERS,
            params=params,
            timeout=25,
        )

        if response.status_code == 429:
            print("API : limite de requêtes atteinte. Les données locales sont conservées.")
            return None

        if response.status_code == 403:
            print("API : accès refusé à cette compétition ou à ces données.")
            return None

        if response.status_code == 401:
            print("API : clé invalide ou non reconnue.")
            return None

        response.raise_for_status()
        return response.json()

    except requests.Timeout:
        print(f"API : délai dépassé pour {endpoint}.")
    except requests.RequestException as exc:
        print(f"API : erreur réseau : {exc}")
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

    if not isinstance(data, dict):
        return None

    matches = data.get("matches")
    return matches if isinstance(matches, list) else None


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
        if match.get("status") not in ("FINISHED", "AWARDED"):
            continue

        score = (match.get("score") or {}).get("fullTime") or {}
        home_goals = score.get("home")
        away_goals = score.get("away")

        home_id = (match.get("homeTeam") or {}).get("id")
        away_id = (match.get("awayTeam") or {}).get("id")

        if (
            home_goals is None
            or away_goals is None
            or home_id is None
            or away_id is None
        ):
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
        if match.get("status") not in ("FINISHED", "AWARDED"):
            continue

        score = (match.get("score") or {}).get("fullTime") or {}
        home = score.get("home")
        away = score.get("away")

        if home is not None and away is not None:
            home_goals.append(home)
            away_goals.append(away)

    avg_home = sum(home_goals) / len(home_goals) if home_goals else 1.45
    avg_away = sum(away_goals) / len(away_goals) if away_goals else 1.10

    return max(avg_home, 0.2), max(avg_away, 0.2)


def expected_goals(team_stats, team_id, opponent_id, avg_home, avg_away, home):
    team = team_stats.get(team_id, {})
    opponent = team_stats.get(opponent_id, {})

    if home:
        scored = (
            team.get("home_scored", 0) / team.get("home_played", 1)
            if team.get("home_played", 0)
            else avg_home
        )

        conceded = (
            opponent.get("away_conceded", 0) / opponent.get("away_played", 1)
            if opponent.get("away_played", 0)
            else avg_home
        )

        expected = (scored / avg_home) * (conceded / avg_home) * avg_home

    else:
        scored = (
            team.get("away_scored", 0) / team.get("away_played", 1)
            if team.get("away_played", 0)
            else avg_away
        )

        conceded = (
            opponent.get("home_conceded", 0) / opponent.get("home_played", 1)
            if opponent.get("home_played", 0)
            else avg_away
        )

        expected = (scored / avg_away) * (conceded / avg_away) * avg_away

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
    max_goals = 10

    home_probs = [
        poisson_probability(i, home_xg)
        for i in range(max_goals + 1)
    ]

    away_probs = [
        poisson_probability(i, away_xg)
        for i in range(max_goals + 1)
    ]

    home_win = draw = away_win = 0.0
    over15 = over25 = under35 = btts_yes = 0.0
    score_probs = []

    for home in range(max_goals + 1):
        for away in range(max_goals + 1):
            probability = home_probs[home] * away_probs[away]

            if home > away:
                home_win += probability
            elif home == away:
                draw += probability
            else:
                away_win += probability

            if home + away >= 2:
                over15 += probability

            if home + away >= 3:
                over25 += probability

            if home + away <= 3:
                under35 += probability

            if home >= 1 and away >= 1:
                btts_yes += probability

            score_probs.append((probability, home, away))

    total = home_win + draw + away_win

    if total:
        home_win /= total
        draw /= total
        away_win /= total

    score_probs.sort(reverse=True)
    best_score = score_probs[0]

    return {
        "home": home_win,
        "draw": draw,
        "away": away_win,
        "over15": over15,
        "over25": over25,
        "under35": under35,
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

        # Cote théorique sans marge bookmaker : estimation seulement.
        estimated_odds = 1.0 / probability if probability > 0 else 99.0

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
    market = bet.get("marche", "")

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

            # Le gain représente le retour total, mise comprise.
            payout = money(stake * odds)
            bet["gain"] = payout

            state["bankroll_actuelle"] = money(
                state["bankroll_actuelle"] + payout
            )

            print(
                f"PARI GAGNÉ : {bet.get('domicile')} - "
                f"{bet.get('exterieur')} | {bet.get('marche')}"
            )

        else:
            bet["statut"] = "PERDU"
            bet["gain"] = 0.0

            print(
                f"PARI PERDU : {bet.get('domicile')} - "
                f"{bet.get('exterieur')} | {bet.get('marche')}"
            )

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

    if updated:
        print(f"Paris réglés : {updated}")

    return updated


# ============================================================
# CRÉATION DES PARIS VIRTUELS
# ============================================================

def create_virtual_bets(
    state,
    upcoming_matches,
    competition_name,
    team_stats,
    averages,
    total_created=0,
):
    created = 0
    avg_home, avg_away = averages

    existing_ids = {
        str(bet.get("match_id"))
        for bet in state["paris"]
        if bet.get("match_id") is not None
    }

    for match in upcoming_matches:
        if total_created + created >= MAX_BETS_PER_RUN:
            break

        match_id = match.get("id")

        if match_id is None or str(match_id) in existing_ids:
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
            True,
        )

        away_xg = expected_goals(
            team_stats,
            away_id,
            home_id,
            avg_home,
            avg_away,
            False,
        )

        probabilities = calculate_probabilities(home_xg, away_xg)
        selection = select_bet(probabilities)

        if not selection:
            print(
                f"Pas de sélection au seuil demandé : "
                f"{home.get('name')} - {away.get('name')}"
            )
            continue

        if money(state["bankroll_actuelle"]) < STAKE:
            print("Capital disponible insuffisant.")
            return created

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

        # La mise est réservée immédiatement.
        state["bankroll_actuelle"] = money(
            state["bankroll_actuelle"] - STAKE
        )

        state["mises_totales"] = money(
            state.get("mises_totales", 0) + STAKE
        )

        existing_ids.add(str(match_id))
        created += 1

        print(
            f"PARI VIRTUEL CRÉÉ : {bet['domicile']} - "
            f"{bet['exterieur']}"
        )
        print(f"  Compétition : {competition_name}")
        print(f"  Marché : {bet['marche']}")
        print(f"  Probabilité estimée : {bet['probabilite']} %")
        print(f"  Cote virtuelle estimée : {bet['cote_estimee']}")
        print(f"  Score indicatif : {bet['score_prevu']}")
        print(f"  Mise virtuelle : {bet['mise']:.2f} €")

    return created


# ============================================================
# PROGRAMME PRINCIPAL
# ============================================================

def main():
    print_line()
    print("FOOT AI PRO BOT V5")
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

    # Un appel par compétition au maximum.
    for code, name in COMPETITIONS.items():
        print(f"Recherche des matchs : {name} ({code})")

        matches = get_competition_matches(
            code,
            start_date,
            end_date,
        )

        if matches is None:
            print(
                "  Données indisponibles. "
                "Les paris locaux sont conservés."
            )
            print_line()
            continue

        finished = [
            match for match in matches
            if match.get("status") in ("FINISHED", "AWARDED")
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

        print(f"  Matchs récupérés : {len(matches)}")
        print(f"  Matchs terminés : {len(finished)}")
        print(f"  Matchs à venir : {len(upcoming)}")
        print_line()

    # Règle uniquement les paris pour lesquels le résultat officiel
    # est disponible et le score final complet.
    refresh_pending_bets(state, all_finished_matches)

    total_created = 0

    for info in competition_data.values():
        if total_created >= MAX_BETS_PER_RUN:
            break

        if not info["upcoming"]:
            continue

        team_stats = build_team_stats(info["matches"])
        averages = league_averages(info["matches"])

        created = create_virtual_bets(
            state,
            info["upcoming"],
            info["name"],
            team_stats,
            averages,
            total_created=total_created,
        )

        total_created += created

    update_statistics(state)
    save_state(state)

    print_line()
    print("RÉSUMÉ DE LA SIMULATION")
    print_line()

    print(f"Nouveaux paris : {total_created}")
    print(f"Capital disponible : {state['bankroll_actuelle']:.2f} €")
    print(f"Bénéfice réalisé : {state['benefice_total']:.2f} €")

    stats = state["statistiques"]

    print(f"Paris enregistrés : {stats['total_paris']}")
    print(f"Paris gagnés : {stats['paris_gagnes']}")
    print(f"Paris perdus : {stats['paris_perdus']}")
    print(f"Paris en attente : {stats['paris_en_attente']}")
    print(f"Taux de réussite : {stats['taux_reussite']} %")

    if total_created == 0:
        print("Aucun nouveau pari créé lors de cette exécution.")

    print(f"Fichier enregistré : {STATE_FILE}")
    print("Simulation terminée.")
    print_line()


if __name__ == "__main__":
    main()