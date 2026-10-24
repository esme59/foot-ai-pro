import os
import json
import math
from datetime import date, timedelta

import requests
import streamlit as st

st.set_page_config(
    page_title="FOOT AI PRO",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_BASE = "https://api.football-data.org/v4"

COMPETITIONS = {
    "Ligue 1": "FL1",
    "Premier League": "PL",
    "Liga": "PD",
    "Bundesliga": "BL1",
    "Serie A": "SA",
    "Ligue des Champions": "CL",
}

DATA_FILE = os.path.join(
    os.path.dirname(__file__),
    "data",
    "bankroll.json",
)


# ============================================================
# CHARGEMENT DES DONNEES
# ============================================================

def load_state():
    default = {
        "starting_bankroll": 20.0,
        "bankroll": 20.0,
        "day": "",
        "bets": [],
        "history": [],
        "stats": {},
        "message": "Le bot automatique n'a pas encore été lancé.",
    }

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            state = json.load(file)

        if not isinstance(state, dict):
            return default

        for key, value in default.items():
            state.setdefault(key, value)

        if not isinstance(state.get("bets"), list):
            state["bets"] = []

        if not isinstance(state.get("history"), list):
            state["history"] = []

        return state

    except FileNotFoundError:
        return default

    except (json.JSONDecodeError, OSError):
        return default


def number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def euro(value):
    return f"{number(value):+.2f} €"


def normalise_status(bet):
    status = str(bet.get("status", "")).upper()

    if status in ("WON", "WIN", "GAGNE", "GAGNÉ"):
        return "Gagné"

    if status in ("LOST", "LOSS", "PERDU"):
        return "Perdu"

    if status in ("VOID", "CANCELLED", "ANNULÉ", "ANNULE"):
        return "Annulé"

    if status in ("FINISHED", "SETTLED", "RESOLVED"):
        result = str(bet.get("result", "")).upper()

        if result in ("WON", "WIN", "GAGNE", "GAGNÉ"):
            return "Gagné"

        if result in ("LOST", "LOSS", "PERDU"):
            return "Perdu"

    return "En attente"


def get_stake(bet):
    return max(0.0, number(bet.get("stake", 0.0)))


def get_profit(bet):
    status = normalise_status(bet)

    if status == "Annulé":
        return 0.0

    if "profit" in bet:
        return number(bet.get("profit"))

    if status == "Gagné":
        return number(bet.get("return_amount")) - get_stake(bet)

    if status == "Perdu":
        return -get_stake(bet)

    return 0.0


def get_market(bet):
    return (
        bet.get("pick")
        or bet.get("market")
        or bet.get("prediction")
        or "Marché inconnu"
    )


def get_team_names(bet):
    home = (
        bet.get("home")
        or bet.get("home_team")
        or bet.get("homeTeam")
        or "Équipe domicile"
    )

    away = (
        bet.get("away")
        or bet.get("away_team")
        or bet.get("awayTeam")
        or "Équipe extérieure"
    )

    return str(home), str(away)


def prepare_bets(bets):
    prepared = []

    for original in bets:
        if not isinstance(original, dict):
            continue

        bet = dict(original)

        bet["_status"] = normalise_status(bet)
        bet["_stake"] = get_stake(bet)
        bet["_profit"] = get_profit(bet)
        bet["_market"] = get_market(bet)

        home, away = get_team_names(bet)

        bet["_match"] = f"{home} - {away}"
        bet["_league"] = (
            bet.get("league")
            or bet.get("competition")
            or "Non renseigné"
        )

        bet["_date"] = (
            bet.get("date")
            or bet.get("match_date")
            or bet.get("created_day")
            or "Non renseignée"
        )

        bet["_probability"] = number(
            bet.get("probability", bet.get("probability_pct", 0))
        )

        if 0 < bet["_probability"] <= 1:
            bet["_probability"] *= 100

        prepared.append(bet)

    return prepared


# ============================================================
# API FOOTBALL-DATA
# ============================================================

def get_api_key():
    try:
        key = st.secrets.get("FOOTBALL_DATA_API_KEY", "")
        if key:
            return key
    except Exception:
        pass

    return os.getenv("FOOTBALL_DATA_API_KEY", "")


@st.cache_data(ttl=900, show_spinner=False)
def get_matches(competition, start_date, end_date, api_key):
    url = f"{API_BASE}/competitions/{competition}/matches"

    response = requests.get(
        url,
        headers={"X-Auth-Token": api_key},
        params={
            "dateFrom": start_date,
            "dateTo": end_date,
        },
        timeout=20,
    )

    if response.status_code == 429:
        raise RuntimeError(
            "Limite de requêtes atteinte. Réessaie plus tard."
        )

    if response.status_code == 403:
        raise RuntimeError(
            f"Accès refusé pour {competition}. "
            "Cette compétition n'est peut-être pas comprise dans ton abonnement."
        )

    response.raise_for_status()

    return response.json().get("matches", [])


# ============================================================
# MODELE DE POISSON
# ============================================================

def poisson(lam, goals):
    if lam <= 0:
        return 1.0 if goals == 0 else 0.0

    return math.exp(-lam) * (lam ** goals) / math.factorial(goals)


def predict_match(matches, home_team, away_team):
    league_home_goals = []
    league_away_goals = []

    home_scored = []
    home_conceded = []

    away_scored = []
    away_conceded = []

    for match in matches:
        if match.get("status") != "FINISHED":
            continue

        score = match.get("score", {}).get("fullTime", {})
        hg = score.get("home")
        ag = score.get("away")

        if hg is None or ag is None:
            continue

        hn = match.get("homeTeam", {}).get("name", "")
        an = match.get("awayTeam", {}).get("name", "")

        league_home_goals.append(hg)
        league_away_goals.append(ag)

        if hn == home_team:
            home_scored.append(hg)
            home_conceded.append(ag)
        elif an == home_team:
            home_scored.append(ag)
            home_conceded.append(hg)

        if hn == away_team:
            away_scored.append(hg)
            away_conceded.append(ag)
        elif an == away_team:
            away_scored.append(ag)
            away_conceded.append(hg)

    avg_home = (
        sum(league_home_goals) / len(league_home_goals)
        if league_home_goals else 1.45
    )

    avg_away = (
        sum(league_away_goals) / len(league_away_goals)
        if league_away_goals else 1.15
    )

    home_attack = (
        sum(home_scored) / len(home_scored)
        if home_scored else avg_home
    )

    home_defence = (
        sum(home_conceded) / len(home_conceded)
        if home_conceded else avg_away
    )

    away_attack = (
        sum(away_scored) / len(away_scored)
        if away_scored else avg_away
    )

    away_defence = (
        sum(away_conceded) / len(away_conceded)
        if away_conceded else avg_home
    )

    if len(home_scored) < 3:
        home_attack = (home_attack + avg_home) / 2
        home_defence = (home_defence + avg_away) / 2

    if len(away_scored) < 3:
        away_attack = (away_attack + avg_away) / 2
        away_defence = (away_defence + avg_home) / 2

    lambda_home = max(
        0.15,
        min(3.5, 0.55 * home_attack + 0.45 * away_defence),
    )

    lambda_away = max(
        0.15,
        min(3.5, 0.55 * away_attack + 0.45 * home_defence),
    )

    scores = {}

    for hg in range(9):
        for ag in range(9):
            scores[(hg, ag)] = (
                poisson(lambda_home, hg)
                * poisson(lambda_away, ag)
            )

    total = sum(scores.values()) or 1.0

    def probability(condition):
        return sum(
            p for (hg, ag), p in scores.items()
            if condition(hg, ag)
        ) / total

    p_home = probability(lambda hg, ag: hg > ag)
    p_draw = probability(lambda hg, ag: hg == ag)
    p_away = probability(lambda hg, ag: hg < ag)

    over05 = probability(lambda hg, ag: hg + ag >= 1)
    over15 = probability(lambda hg, ag: hg + ag >= 2)
    over25 = probability(lambda hg, ag: hg + ag >= 3)
    over35 = probability(lambda hg, ag: hg + ag >= 4)

    under25 = probability(lambda hg, ag: hg + ag <= 2)
    under35 = probability(lambda hg, ag: hg + ag <= 3)

    btts_yes = probability(lambda hg, ag: hg > 0 and ag > 0)
    btts_no = 1 - btts_yes

    markets = {
        "Plus de 0,5 but": over05,
        "Plus de 1,5 but": over15,
        "Plus de 2,5 buts": over25,
        "Plus de 3,5 buts": over35,
        "Moins de 2,5 buts": under25,
        "Moins de 3,5 buts": under35,
        "Les deux équipes marquent : oui": btts_yes,
        "Les deux équipes marquent : non": btts_no,
        "Victoire domicile": p_home,
        "Match nul": p_draw,
        "Victoire extérieur": p_away,
        "Double chance 1X": p_home + p_draw,
        "Double chance X2": p_draw + p_away,
    }

    best_score = max(scores, key=scores.get)
    best_market = max(markets, key=markets.get)

    sample = min(len(home_scored), len(away_scored))

    return {
        "home": home_team,
        "away": away_team,
        "home_win": round(p_home * 100, 1),
        "draw": round(p_draw * 100, 1),
        "away_win": round(p_away * 100, 1),
        "over05": round(over05 * 100, 1),
        "over15": round(over15 * 100, 1),
        "over25": round(over25 * 100, 1),
        "over35": round(over35 * 100, 1),
        "under25": round(under25 * 100, 1),
        "under35": round(under35 * 100, 1),
        "btts_yes": round(btts_yes * 100, 1),
        "btts_no": round(btts_no * 100, 1),
        "double_1x": round((p_home + p_draw) * 100, 1),
        "double_x2": round((p_draw + p_away) * 100, 1),
        "score": f"{best_score[0]}-{best_score[1]}",
        "best_market": best_market,
        "best_probability": round(markets[best_market] * 100, 1),
        "sample": sample,
        "quality": (
            "Données limitées"
            if sample < 3 else "Échantillon statistique"
        ),
        "lambda_home": round(lambda_home, 2),
        "lambda_away": round(lambda_away, 2),
    }


# ============================================================
# TABLEAU DE BORD
# ============================================================

st.title("⚽ FOOT AI PRO")
st.caption("Tableau de bord des analyses et de la simulation virtuelle.")

state = load_state()
bets = prepare_bets(state.get("bets", []))

capital = number(state.get("bankroll", 20.0))
starting_capital = number(state.get("starting_bankroll", 20.0))

open_bets = [b for b in bets if b["_status"] == "En attente"]
won_bets = [b for b in bets if b["_status"] == "Gagné"]
lost_bets = [b for b in bets if b["_status"] == "Perdu"]
cancelled_bets = [b for b in bets if b["_status"] == "Annulé"]

settled_bets = won_bets + lost_bets
total_staked_open = sum(b["_stake"] for b in open_bets)
total_profit_settled = sum(b["_profit"] for b in settled_bets)

win_rate = (
    len(won_bets) / len(settled_bets) * 100
    if settled_bets else 0.0
)

# La bankroll du bot est utilisée comme référence principale.
# Les mises en attente sont affichées séparément et ne sont pas déduites
# une seconde fois du capital.
net_change = capital - starting_capital

st.subheader("💰 Vue d'ensemble")

c1, c2, c3 = st.columns(3)

c1.metric("Capital virtuel", f"{capital:.2f} €")
c2.metric("Résultat depuis le départ", euro(net_change))
c3.metric("Mises en attente", f"{total_staked_open:.2f} €")

c4, c5, c6, c7 = st.columns(4)

c4.metric("Paris enregistrés", len(bets))
c5.metric("Gagnés", len(won_bets))
c6.metric("Perdus", len(lost_bets))
c7.metric("Taux de réussite", f"{win_rate:.1f} %")

c8, c9, c10 = st.columns(3)

c8.metric("Bénéfices/pertes réglés", euro(total_profit_settled))
c9.metric("Paris en attente", len(open_bets))
c10.metric("Paris annulés", len(cancelled_bets))

st.info(
    state.get(
        "message",
        "Le bot automatique n'a pas encore été lancé.",
    )
)

st.caption(
    "Les mises en attente sont affichées séparément. "
    "Elles ne sont pas retranchées une deuxième fois du capital."
)

# ============================================================
# BARRE LATERALE
# ============================================================

with st.sidebar:
    st.header("⚙️ Paramètres")

    selected_competitions = st.multiselect(
        "Compétitions à analyser",
        list(COMPETITIONS.keys()),
        default=list(COMPETITIONS.keys()),
    )

    days_ahead = st.slider(
        "Jours à analyser",
        min_value=1,
        max_value=7,
        value=3,
    )

    st.divider()
    st.subheader("Filtres du tableau de bord")

    league_options = sorted({
        b["_league"] for b in bets
    })

    selected_leagues = st.multiselect(
        "Championnats des paris",
        league_options,
        default=league_options,
    )

    status_options = ["En attente", "Gagné", "Perdu", "Annulé"]

    selected_statuses = st.multiselect(
        "Statut des paris",
        status_options,
        default=status_options,
    )

    market_options = sorted({
        b["_market"] for b in bets
    })

    selected_markets = st.multiselect(
        "Marchés",
        market_options,
        default=market_options,
    )

filtered_bets = [
    b for b in bets
    if b["_league"] in selected_leagues
    and b["_status"] in selected_statuses
    and b["_market"] in selected_markets
]

# ============================================================
# ONGLETS
# ============================================================

tab_dashboard, tab_matches, tab_ai, tab_history = st.tabs([
    "📊 Tableau de bord",
    "📅 Matchs",
    "🤖 Analyse IA",
    "📚 Historique",
])

# ============================================================
# TABLEAU DE BORD DETAILLE
# ============================================================

with tab_dashboard:
    st.subheader("📋 Paris virtuels")

    if filtered_bets:
        table_rows = []

        for b in filtered_bets:
            table_rows.append({
                "Date": b["_date"],
                "Championnat": b["_league"],
                "Match": b["_match"],
                "Marché": b["_market"],
                "Probabilité estimée (%)": round(b["_probability"], 1),
                "Mise virtuelle (€)": round(b["_stake"], 2),
                "Statut": b["_status"],
                "Profit/perte (€)": round(b["_profit"], 2),
                "Score prédit": b.get("score", "—"),
                "Stratégie": b.get("strategy", "—"),
            })

        st.dataframe(
            table_rows,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Aucun pari ne correspond aux filtres sélectionnés.")

    st.subheader("🏆 Performance par marché")

    market_stats = {}

    for b in bets:
        market = b["_market"]

        if market not in market_stats:
            market_stats[market] = {
                "Paris réglés": 0,
                "Gagnés": 0,
                "Perdus": 0,
                "Profit/perte (€)": 0.0,
            }

        if b["_status"] in ("Gagné", "Perdu"):
            market_stats[market]["Paris réglés"] += 1
            market_stats[market]["Profit/perte (€)"] += b["_profit"]

            if b["_status"] == "Gagné":
                market_stats[market]["Gagnés"] += 1
            else:
                market_stats[market]["Perdus"] += 1

    market_rows = []

    for market, stats in market_stats.items():
        settled = stats["Paris réglés"]

        rate = (
            stats["Gagnés"] / settled * 100
            if settled else 0.0
        )

        market_rows.append({
            "Marché": market,
            "Paris réglés": settled,
            "Gagnés": stats["Gagnés"],
            "Perdus": stats["Perdus"],
            "Taux de réussite (%)": round(rate, 1),
            "Profit/perte (€)": round(stats["Profit/perte (€)"], 2),
        })

    market_rows.sort(
        key=lambda row: (
            row["Paris réglés"] > 0,
            row["Taux de réussite (%)"],
            row["Profit/perte (€)"],
        ),
        reverse=True,
    )

    if market_rows:
        st.dataframe(
            market_rows,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Les statistiques des marchés apparaîtront après les premiers résultats.")

    st.caption(
        "Un marché avec peu de paris réglés ne permet pas de conclure "
        "qu'il est réellement meilleur. Attends un échantillon plus large."
    )

# ============================================================
# MATCHS A ANALYSER
# ============================================================

with tab_matches:
    key = get_api_key()

    if not key:
        st.error("Clé API manquante.")
        st.code('FOOTBALL_DATA_API_KEY = "TA_CLE_API"')
        st.caption(
            "Ajoute cette clé dans les Secrets Streamlit. "
            "Ne publie jamais ta véritable clé dans le code."
        )

    elif st.button("🔎 Analyser les matchs", type="primary"):
        start_date = date.today()
        end_date = start_date + timedelta(days=days_ahead)

        all_predictions = []
        errors = []

        with st.spinner("Analyse des rencontres en cours..."):
            for league in selected_competitions:
                code = COMPETITIONS[league]

                try:
                    matches = get_matches(
                        code,
                        start_date.isoformat(),
                        end_date.isoformat(),
                        key,
                    )

                    for match in matches:
                        if match.get("status") not in (
                            "SCHEDULED",
                            "TIMED",
                            "IN_PLAY",
                            "PAUSED",
                        ):
                            continue

                        home = match.get("homeTeam", {}).get("name", "Domicile")
                        away = match.get("awayTeam", {}).get("name", "Extérieur")

                        prediction = predict_match(matches, home, away)
                        prediction["league"] = league
                        prediction["date"] = (
                            match.get("utcDate", "")
                            .replace("T", " ")[:16] + " UTC"
                        )

                        all_predictions.append(prediction)

                except Exception as error:
                    errors.append(f"{league} : {error}")

        for error in errors:
            st.warning(error)

        if not all_predictions:
            st.info(
                "Aucun match disponible pour cette période. "
                "Vérifie les droits de ta clé API et les dates."
            )
        else:
            all_predictions.sort(
                key=lambda item: item["best_probability"],
                reverse=True,
            )

            st.success(
                f"{len(all_predictions)} rencontre(s) analysée(s)."
            )

            for prediction in all_predictions:
                with st.container(border=True):
                    st.subheader(
                        f'{prediction["home"]} - {prediction["away"]}'
                    )

                    st.caption(
                        f'{prediction["league"]} · {prediction["date"]}'
                    )

                    a, b, c = st.columns(3)

                    a.metric("Victoire domicile", f'{prediction["home_win"]} %')
                    b.metric("Match nul", f'{prediction["draw"]} %')
                    c.metric("Victoire extérieur", f'{prediction["away_win"]} %')

                    st.markdown("#### ⚽ Marchés de buts")

                    a, b, c = st.columns(3)

                    a.metric("+ 1,5 but", f'{prediction["over15"]} %')
                    b.metric("+ 2,5 buts", f'{prediction["over25"]} %')
                    c.metric("+ 3,5 buts", f'{prediction["over35"]} %')

                    a, b, c = st.columns(3)

                    a.metric("BTTS oui", f'{prediction["btts_yes"]} %')
                    b.metric("BTTS non", f'{prediction["btts_no"]} %')
                    c.metric("Double chance 1X", f'{prediction["double_1x"]} %')

                    st.markdown("#### 🤖 Sélection statistique")

                    st.write(f'**Marché :** {prediction["best_market"]}')
                    st.write(
                        f'**Probabilité estimée :** '
                        f'{prediction["best_probability"]} %'
                    )
                    st.write(f'**Score indicatif :** {prediction["score"]}')

                    st.caption(
                        f'{prediction["quality"]} · '
                        f'{prediction["sample"]} match(s) '
                        f'dans l’échantillon minimum'
                    )

# ============================================================
# ANALYSE IA
# ============================================================

with tab_ai:
    st.subheader("🤖 Simulation automatique")

    st.write(f"Capital de départ : {starting_capital:.2f} €")
    st.write(f"Capital virtuel actuel : {capital:.2f} €")
    st.write(f"Date de dernière exécution : {state.get('day') or 'Aucune'}")

    st.write(f"Paris enregistrés : {len(bets)}")
    st.write(f"Paris encore en attente : {len(open_bets)}")
    st.write(f"Taux de réussite des paris réglés : {win_rate:.1f} %")

    st.warning(
        "Cette application effectue uniquement une simulation virtuelle. "
        "Les probabilités ne sont pas des garanties et les cotes affichées "
        "par le bot sont simulées, pas des cotes réelles de bookmaker."
    )

    st.markdown("#### Règles de gestion")
    st.write("- Capital virtuel de départ : 20 €.")
    st.write("- Mises virtuelles limitées.")
    st.write("- Pas de martingale.")
    st.write("- Résultats calculés lorsque le bot règle les paris.")
    st.write("- Historique conservé dans data/bankroll.json.")

# ============================================================
# HISTORIQUE
# ============================================================

with tab_history:
    st.subheader("📚 Historique des paris")

    if bets:
        history_rows = []

        for b in bets:
            history_rows.append({
                "Date": b["_date"],
                "Championnat": b["_league"],
                "Match": b["_match"],
                "Marché": b["_market"],
                "Probabilité (%)": round(b["_probability"], 1),
                "Mise (€)": round(b["_stake"], 2),
                "Statut": b["_status"],
                "Profit/perte (€)": round(b["_profit"], 2),
            })

        st.dataframe(
            history_rows,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Aucun pari virtuel enregistré.")

    st.subheader("📈 Historique quotidien du capital")

    history = state.get("history", [])

    if history:
        st.dataframe(
            history,
            use_container_width=True,
            hide_index=True,
        )

        chart_rows = []

        for row in history:
            if isinstance(row, dict) and "bankroll" in row:
                chart_rows.append({
                    "Date": row.get("date", ""),
                    "Capital (€)": number(row.get("bankroll")),
                })

        if chart_rows:
            st.line_chart(
                {
                    row["Date"]: row["Capital (€)"]
                    for row in chart_rows
                    if row["Date"]
                }
            )
    else:
        st.info("L'évolution du capital apparaîtra après les premières simulations.")

# ============================================================
# AVERTISSEMENT
# ============================================================

st.divider()

st.caption(
    "FOOT AI PRO est un outil expérimental de simulation. "
    "Il ne garantit aucun gain. Les blessures, compositions officielles, "
    "suspensions et cotes réelles ne sont pas intégrées."
)