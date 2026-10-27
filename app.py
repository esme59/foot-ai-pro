import os
import json
from pathlib import Path
from datetime import date, datetime, timedelta

import requests
import pandas as pd
import streamlit as st

# ============================================================
# FOOT AI PRO - INTERFACE PREMIUM
# Lecture seule de data/bankroll.json
# Ne modifie pas bot.py ni le fichier des simulations.
# ============================================================

st.set_page_config(
    page_title="FOOT AI PRO",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_BASE = "https://api.football-data.org/v4"
DATA_FILE = Path("data/bankroll.json")

COMPETITIONS = {
    "FL1": "Ligue 1",
    "PL": "Premier League",
    "PD": "Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "CL": "Ligue des Champions",
}

# -------------------- DESIGN --------------------

st.markdown("""
<style>
.stApp {
    background: linear-gradient(145deg, #07111f 0%, #0b1728 55%, #0a211f 100%);
    color: #f3f7fb;
}
[data-testid="stSidebar"] {
    background: #0b1423;
    border-right: 1px solid #20334a;
}
.block-container {
    padding-top: 1.5rem;
    padding-bottom: 2rem;
    max-width: 1450px;
}
h1, h2, h3 {
    color: #f4f8fc !important;
}
p, label, span {
    color: #d8e2ed;
}
.hero {
    padding: 25px;
    border-radius: 20px;
    background: linear-gradient(120deg, #102b3a, #123b34);
    border: 1px solid #235548;
    margin-bottom: 20px;
}
.hero-title {
    font-size: 30px;
    font-weight: 850;
    letter-spacing: 1px;
}
.hero-subtitle {
    color: #b5c9d6;
    margin-top: 6px;
}
.metric-card {
    background: linear-gradient(145deg, #14243a, #101c2c);
    border: 1px solid #263b53;
    border-radius: 16px;
    padding: 17px;
    min-height: 115px;
}
.metric-label {
    font-size: 13px;
    color: #a9bbce;
    margin-bottom: 9px;
}
.metric-value {
    font-size: 25px;
    font-weight: 800;
    color: #f5f8fc;
}
.metric-green { color: #4ce0a0; }
.metric-red { color: #ff7d89; }
.match-card {
    background: #101e30;
    border: 1px solid #263a51;
    border-radius: 15px;
    padding: 16px;
    margin: 10px 0;
}
.match-title {
    font-weight: 750;
    font-size: 17px;
    color: #f3f7fb;
}
.match-info {
    font-size: 12px;
    color: #9eb3c8;
    margin-bottom: 8px;
}
.badge {
    display: inline-block;
    padding: 5px 9px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 700;
    background: #193c37;
    color: #6ce7b2;
}
.section-title {
    font-size: 20px;
    font-weight: 800;
    margin-top: 10px;
    margin-bottom: 12px;
}
div[data-testid="stTabs"] button {
    border-radius: 10px;
}
.stButton > button {
    border-radius: 10px;
    border: 1px solid #2c6657;
    font-weight: 700;
}
div[data-testid="stDataFrame"] {
    border: 1px solid #263a51;
    border-radius: 12px;
}
.small-note {
    font-size: 12px;
    color: #9eb3c8;
}
</style>
""", unsafe_allow_html=True)


# -------------------- FONCTIONS UTILITAIRES --------------------

def to_float(value, default=0.0):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (ValueError, TypeError):
        return default


def format_money(value):
    return f"{to_float(value):.2f} €".replace(".", ",")


def empty_state():
    return {
        "initial_bankroll": 20.0,
        "starting_bankroll": 20.0,
        "bankroll": 20.0,
        "bets": [],
        "history": [],
        "message": "",
    }


def load_state():
    """Lecture seule : aucune écriture dans bankroll.json."""
    if not DATA_FILE.exists():
        return empty_state(), (
            "Fichier data/bankroll.json introuvable. "
            "Vérifie qu'il existe bien dans le dépôt GitHub."
        )

    try:
        with DATA_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            return empty_state(), "Le fichier JSON n'a pas le format attendu."

        # Compatibilité avec plusieurs versions du bot.
        bets = data.get("bets")
        if not isinstance(bets, list):
            bets = data.get("paris", [])
        if not isinstance(bets, list):
            bets = []

        history = data.get("history")
        if not isinstance(history, list):
            history = data.get("historique", [])
        if not isinstance(history, list):
            history = []

        initial = data.get(
            "initial_bankroll",
            data.get("starting_bankroll", data.get("bankroll_initiale", 20.0)),
        )
        bankroll = data.get(
            "bankroll",
            data.get("bankroll_actuelle", data.get("capital", initial)),
        )

        data["initial_bankroll"] = to_float(initial, 20.0)
        data["starting_bankroll"] = to_float(initial, 20.0)
        data["bankroll"] = to_float(bankroll, data["initial_bankroll"])
        data["bets"] = bets
        data["history"] = history

        return data, None

    except (OSError, json.JSONDecodeError) as exc:
        return empty_state(), f"Impossible de lire le fichier JSON : {exc}"


def bet_status(bet):
    status = str(bet.get("status", "")).strip().upper()

    if status in ("WON", "WIN", "GAGNÉ", "GAGNE", "GAGNE"):
        return "Gagné"
    if status in ("LOST", "LOSS", "PERDU"):
        return "Perdu"
    if status in ("VOID", "CANCELLED", "CANCELED", "ANNULÉ", "ANNULE"):
        return "Annulé"
    if status in ("PENDING", "OPEN", "EN ATTENTE"):
        return "En attente"

    # Compatibilité avec les anciennes versions.
    if bet.get("settled") is True:
        result = str(bet.get("result_status", bet.get("outcome", ""))).upper()
        if result in ("WON", "WIN", "GAGNÉ", "GAGNE"):
            return "Gagné"
        if result in ("LOST", "LOSS", "PERDU"):
            return "Perdu"
        if result in ("VOID", "CANCELLED", "CANCELED"):
            return "Annulé"

    return "En attente"


def bet_date(bet):
    raw = (
        bet.get("match_date")
        or bet.get("created_date")
        or bet.get("created_day")
        or bet.get("created_at")
        or bet.get("date")
        or ""
    )
    return str(raw)[:10] if raw else "—"


def match_name(bet):
    home = bet.get("home_team", bet.get("home", "Équipe domicile"))
    away = bet.get("away_team", bet.get("away", "Équipe extérieure"))
    return f"{home} – {away}"


def market_name(bet):
    return str(
        bet.get("market")
        or bet.get("market_name")
        or bet.get("selection")
        or "Marché non précisé"
    )


def competition_name(bet):
    return str(
        bet.get("competition_name")
        or bet.get("competition")
        or bet.get("competition_code")
        or "Compétition non précisée"
    )


def bet_odds(bet):
    return to_float(bet.get("odds", bet.get("virtual_odds", 0)))


def bet_probability(bet):
    value = bet.get("probability", bet.get("probability_pct"))
    if value is None:
        return None

    probability = to_float(value, -1)
    if probability < 0:
        return None

    # Le bot enregistre normalement une probabilité entre 0 et 1.
    if probability <= 1:
        probability *= 100

    if probability > 100:
        return None

    return probability


def bet_profit(bet):
    if bet.get("profit") is not None:
        return to_float(bet.get("profit"))

    stake = to_float(bet.get("stake", bet.get("mise", 0)))
    odds = bet_odds(bet)
    status = bet_status(bet)

    if status == "Gagné":
        return stake * (odds - 1) if odds > 0 else 0.0
    if status == "Perdu":
        return -stake

    return 0.0


def bet_score(bet):
    score = bet.get("actual_score")
    if score:
        return str(score)

    # Dans certaines versions, result contient le score final.
    if bet_status(bet) != "En attente":
        result = bet.get("result")
        if isinstance(result, str) and "-" in result:
            return result

    return "—"


def get_api_key():
    try:
        key = st.secrets.get("FOOTBALL_DATA_API_KEY", "")
        if key:
            return str(key).strip()
    except Exception:
        pass

    return os.environ.get("FOOTBALL_DATA_API_KEY", "").strip()


# -------------------- STATISTIQUES --------------------

def calculate_statistics(bets, initial_bankroll, bankroll):
    wins = sum(1 for bet in bets if bet_status(bet) == "Gagné")
    losses = sum(1 for bet in bets if bet_status(bet) == "Perdu")
    voids = sum(1 for bet in bets if bet_status(bet) == "Annulé")
    pending = sum(1 for bet in bets if bet_status(bet) == "En attente")

    settled = wins + losses
    success_rate = (wins / settled * 100) if settled else 0.0

    pending_stakes = sum(
        to_float(bet.get("stake", bet.get("mise", 0)))
        for bet in bets
        if bet_status(bet) == "En attente"
    )

    return {
        "wins": wins,
        "losses": losses,
        "voids": voids,
        "pending": pending,
        "settled": settled,
        "success_rate": success_rate,
        "profit": to_float(bankroll) - to_float(initial_bankroll),
        "pending_stakes": pending_stakes,
    }


def bets_dataframe(bets):
    rows = []

    for bet in bets:
        probability = bet_probability(bet)

        rows.append({
            "Date": bet_date(bet),
            "Match": match_name(bet),
            "Compétition": competition_name(bet),
            "Marché": market_name(bet),
            "Probabilité": f"{probability:.1f}%" if probability is not None else "—",
            "Cote": bet_odds(bet) or "—",
            "Mise": format_money(bet.get("stake", bet.get("mise", 0))),
            "Résultat": bet_status(bet),
            "Score": bet_score(bet),
            "Profit": format_money(bet_profit(bet)),
        })

    return pd.DataFrame(rows)


def metric_card(label, value, extra_class=""):
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value {extra_class}">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# -------------------- MATCHS API --------------------

@st.cache_data(ttl=900, show_spinner=False)
def fetch_matches(api_key, competitions, date_from, date_to):
    if not api_key:
        return [], "Clé API manquante"

    headers = {"X-Auth-Token": api_key}
    all_matches = []
    errors = []

    for code in competitions:
        try:
            response = requests.get(
                f"{API_BASE}/competitions/{code}/matches",
                headers=headers,
                params={
                    "dateFrom": date_from,
                    "dateTo": date_to,
                },
                timeout=15,
            )

            if response.status_code == 429:
                errors.append(
                    "Limite de requêtes API atteinte. Réessaie plus tard."
                )
                break

            if response.status_code == 403:
                errors.append(
                    f"Accès refusé pour {COMPETITIONS.get(code, code)} "
                    "(vérifie les compétitions autorisées par ton abonnement)."
                )
                continue

            if response.status_code == 401:
                errors.append("Clé API refusée : vérifie FOOTBALL_DATA_API_KEY.")
                break

            response.raise_for_status()
            payload = response.json()

            for match in payload.get("matches", []):
                match["local_competition_name"] = COMPETITIONS.get(code, code)
                all_matches.append(match)

        except requests.RequestException:
            errors.append(
                f"Erreur réseau lors du chargement de {COMPETITIONS.get(code, code)}."
            )
        except (ValueError, TypeError):
            errors.append(
                f"Réponse API illisible pour {COMPETITIONS.get(code, code)}."
            )

    # Évite les doublons et trie par date.
    unique = {}
    for match in all_matches:
        unique[match.get("id", str(match))] = match

    matches = list(unique.values())
    matches.sort(key=lambda item: item.get("utcDate", ""))

    return matches, " ".join(dict.fromkeys(errors))


def display_match_card(match):
    home = match.get("homeTeam", {}).get("name", "Équipe domicile")
    away = match.get("awayTeam", {}).get("name", "Équipe extérieure")
    competition = match.get("local_competition_name", "Football")
    status = match.get("status", "SCHEDULED")

    raw_date = match.get("utcDate", "")
    try:
        kickoff = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        kickoff = kickoff.astimezone().strftime("%d/%m à %H:%M")
    except (ValueError, TypeError):
        kickoff = "Horaire indisponible"

    score = match.get("score", {}).get("fullTime", {})
    home_score = score.get("home")
    away_score = score.get("away")

    if home_score is not None and away_score is not None:
        score_text = f"{home_score} – {away_score}"
    else:
        score_text = "VS"

    if status == "IN_PLAY":
        status_text = "EN DIRECT"
    elif status == "PAUSED":
        status_text = "MI-TEMPS"
    elif status == "FINISHED":
        status_text = "TERMINÉ"
    elif status == "POSTPONED":
        status_text = "REPORTÉ"
    elif status == "CANCELLED":
        status_text = "ANNULÉ"
    else:
        status_text = kickoff

    st.markdown(
        f"""
        <div class="match-card">
            <div class="match-info">{competition} · {status_text}</div>
            <div class="match-title">{home}</div>
            <div style="font-size:23px;font-weight:850;margin:6px 0;">
                {score_text}
            </div>
            <div class="match-title">{away}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# -------------------- CHARGEMENT --------------------

state, state_error = load_state()

bets = state.get("bets", [])
initial_bankroll = to_float(
    state.get("initial_bankroll", state.get("starting_bankroll", 20))
)
bankroll = to_float(state.get("bankroll", initial_bankroll))

stats = calculate_statistics(bets, initial_bankroll, bankroll)

# -------------------- MENU LATÉRAL --------------------

with st.sidebar:
    st.markdown("## ⚽ FOOT AI PRO")
    st.caption("Centre de contrôle football")

    st.markdown("---")
    st.markdown("### ⚙️ Paramètres des matchs")

    selected_competitions = st.multiselect(
        "Compétitions",
        options=list(COMPETITIONS.keys()),
        default=list(COMPETITIONS.keys()),
        format_func=lambda code: COMPETITIONS[code],
    )

    days_back = st.slider(
        "Jours précédents",
        min_value=0,
        max_value=7,
        value=1,
    )

    days_ahead = st.slider(
        "Jours à venir",
        min_value=0,
        max_value=7,
        value=3,
    )

    refresh = st.button("🔄 Actualiser les données", use_container_width=True)

    if refresh:
        fetch_matches.clear()
        st.rerun()

    st.markdown("---")
    st.markdown("### 💰 Capital virtuel")
    st.markdown(f"## {format_money(bankroll)}")
    st.caption("Simulation uniquement — aucun pari réel.")

if state_error:
    st.warning(state_error)

# -------------------- ENTÊTE --------------------

st.markdown(
    """
    <div class="hero">
        <div class="hero-title">FOOT AI PRO</div>
        <div class="hero-subtitle">
            Football · Analyse des simulations · Suivi des performances
        </div>
        <br>
        <span class="badge">MODE SIMULATION</span>
    </div>
    """,
    unsafe_allow_html=True,
)

# -------------------- INDICATEURS --------------------

col1, col2, col3, col4 = st.columns(4)

with col1:
    metric_card("💰 Capital virtuel", format_money(bankroll))

with col2:
    profit_class = "metric-green" if stats["profit"] >= 0 else "metric-red"
    metric_card("📈 Bénéfice / perte", format_money(stats["profit"]), profit_class)

with col3:
    metric_card("✅ Paris gagnés", str(stats["wins"]), "metric-green")

with col4:
    metric_card("🎯 Taux de réussite", f'{stats["success_rate"]:.1f}%')

st.write("")

col5, col6, col7, col8 = st.columns(4)

with col5:
    metric_card("❌ Paris perdus", str(stats["losses"]), "metric-red")

with col6:
    metric_card("⏳ En attente", str(stats["pending"]))

with col7:
    metric_card("↩️ Annulés", str(stats["voids"]))

with col8:
    metric_card("💵 Mises en attente", format_money(stats["pending_stakes"]))

st.write("")

# -------------------- ONGLETS --------------------

tab_home, tab_matches, tab_ai, tab_bets, tab_rankings = st.tabs([
    "🏠 Accueil",
    "⚽ Matchs",
    "🤖 Analyse IA",
    "🎯 Mes paris",
    "🏆 Classements",
])

# -------------------- ACCUEIL --------------------

with tab_home:
    st.markdown("### 📊 Vue d'ensemble")

    left, right = st.columns([1.3, 1])

    with left:
        st.markdown("#### Résumé des performances")

        if stats["settled"] > 0:
            chart_df = pd.DataFrame({
                "Résultat": ["Gagnés", "Perdus", "Annulés", "En attente"],
                "Nombre": [
                    stats["wins"],
                    stats["losses"],
                    stats["voids"],
                    stats["pending"],
                ],
            }).set_index("Résultat")

            st.bar_chart(chart_df)
        else:
            st.info("Les statistiques apparaîtront lorsque des paris seront enregistrés.")

    with right:
        st.markdown("#### État du système")
        st.markdown(
            f"""
            <div class="match-card">
                <div class="match-info">Capital initial</div>
                <div class="match-title">{format_money(initial_bankroll)}</div>
                <br>
                <div class="match-info">Paris enregistrés</div>
                <div class="match-title">{len(bets)}</div>
                <br>
                <div class="match-info">Paris terminés</div>
                <div class="match-title">{stats["settled"]}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.caption(
            "Les statistiques sont calculées à partir des données présentes "
            "dans bankroll.json."
        )

    st.markdown("### 🕒 Derniers paris enregistrés")

    if bets:
        recent = sorted(
            bets,
            key=lambda bet: bet_date(bet),
            reverse=True,
        )[:5]

        st.dataframe(
            bets_dataframe(recent),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Aucun pari enregistré pour le moment.")

# -------------------- MATCHS --------------------

with tab_matches:
    st.markdown("### ⚽ Rencontres des compétitions sélectionnées")

    today = date.today()
    date_from = (today - timedelta(days=days_back)).isoformat()
    date_to = (today + timedelta(days=days_ahead)).isoformat()

    api_key = get_api_key()

    if not selected_competitions:
        st.info("Sélectionne au moins une compétition dans le menu latéral.")
    elif not api_key:
        st.error(
            "Clé API manquante. Ajoute FOOTBALL_DATA_API_KEY dans "
            "les Secrets de ton application Streamlit."
        )
    else:
        with st.spinner("Chargement des rencontres..."):
            matches, api_message = fetch_matches(
                api_key,
                tuple(selected_competitions),
                date_from,
                date_to,
            )

        if api_message:
            st.warning(api_message)

        if matches:
            st.caption(
                f"{len(matches)} rencontre(s) trouvée(s) "
                f"du {date_from} au {date_to}."
            )

            filter_day = st.selectbox(
                "Filtrer les rencontres",
                [
                    "Toutes les dates",
                    "Aujourd'hui",
                    "À venir",
                    "Terminés",
                    "En direct",
                ],
            )

            if filter_day == "Aujourd'hui":
                matches = [
                    match for match in matches
                    if str(match.get("utcDate", ""))[:10] == today.isoformat()
                ]
            elif filter_day == "À venir":
                matches = [
                    match for match in matches
                    if match.get("status") in ("SCHEDULED", "TIMED")
                ]
            elif filter_day == "Terminés":
                matches = [
                    match for match in matches
                    if match.get("status") == "FINISHED"
                ]
            elif filter_day == "En direct":
                matches = [
                    match for match in matches
                    if match.get("status") in ("IN_PLAY", "PAUSED")
                ]

            if matches:
                for index in range(0, len(matches), 2):
                    left, right = st.columns(2)

                    with left:
                        display_match_card(matches[index])

                    if index + 1 < len(matches):
                        with right:
                            display_match_card(matches[index + 1])
            else:
                st.info("Aucune rencontre pour ce filtre.")
        else:
            st.info(
                "Aucun match trouvé sur la période sélectionnée. "
                "Vérifie les compétitions, les dates et les droits de ton API."
            )

# -------------------- ANALYSE IA --------------------

with tab_ai:
    st.markdown("### 🤖 Pronostics enregistrés par le bot")

    st.caption(
        "Cette section présente les sélections réellement enregistrées dans "
        "tes simulations. Les probabilités affichées proviennent du fichier "
        "des paris lorsqu'elles sont disponibles."
    )

    pending_bets = [
        bet for bet in bets
        if bet_status(bet) == "En attente"
    ]

    if pending_bets:
        for bet in sorted(
            pending_bets,
            key=lambda item: bet_date(item),
            reverse=True,
        ):
            probability = bet_probability(bet)
            probability_text = (
                f"{probability:.1f}%"
                if probability is not None
                else "Non disponible"
            )

            odds = bet_odds(bet)
            odds_text = f"{odds:.2f}" if odds else "Non disponible"

            st.markdown(
                f"""
                <div class="match-card">
                    <div class="match-info">
                        {competition_name(bet)} · {bet_date(bet)}
                    </div>
                    <div class="match-title">{match_name(bet)}</div>
                    <br>
                    <span class="badge">EN ATTENTE</span>
                    <br><br>
                    <div><b>Sélection :</b> {market_name(bet)}</div>
                    <div><b>Probabilité enregistrée :</b> {probability_text}</div>
                    <div><b>Cote :</b> {odds_text}</div>
                    <div><b>Mise virtuelle :</b>
                        {format_money(bet.get("stake", bet.get("mise", 0)))}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.info("Aucun pronostic en attente dans les données enregistrées.")

    st.markdown("#### 🔎 À propos des probabilités")
    st.write(
        "Les rencontres de l'onglet Matchs proviennent de football-data.org. "
        "Elles ne constituent pas automatiquement des pronostics. "
        "Si une probabilité n'est pas enregistrée dans un pari, elle est "
        "affichée comme indisponible plutôt que d'être inventée."
    )

# -------------------- MES PARIS --------------------

with tab_bets:
    st.markdown("### 🎯 Historique des simulations")

    filter_status = st.selectbox(
        "Filtrer par statut",
        ["Tous", "En attente", "Gagné", "Perdu", "Annulé"],
        key="bet_status_filter",
    )

    filtered_bets = bets

    if filter_status != "Tous":
        filtered_bets = [
            bet for bet in bets
            if bet_status(bet) == filter_status
        ]

    if filtered_bets:
        st.dataframe(
            bets_dataframe(filtered_bets),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Aucun pari ne correspond à ce filtre.")

    pending = [bet for bet in bets if bet_status(bet) == "En attente"]
    settled = [bet for bet in bets if bet_status(bet) != "En attente"]

    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("#### ⏳ En attente")
        if pending:
            st.dataframe(
                bets_dataframe(pending),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("Aucun pari en attente.")

    with col_b:
        st.markdown("#### ✅ Paris terminés")
        if settled:
            st.dataframe(
                bets_dataframe(settled),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("Aucun pari terminé.")

# -------------------- CLASSEMENTS --------------------

with tab_rankings:
    st.markdown("### 🏆 Performances par catégorie")

    if not bets:
        st.info("Les classements apparaîtront après l'enregistrement de paris.")
    else:
        ranking_rows = []

        for category in ("competition", "market"):
            groups = {}

            for bet in bets:
                key = (
                    competition_name(bet)
                    if category == "competition"
                    else market_name(bet)
                )

                if key not in groups:
                    groups[key] = {
                        "Paris": 0,
                        "Gagnés": 0,
                        "Perdus": 0,
                        "Profit virtuel": 0.0,
                    }

                groups[key]["Paris"] += 1

                status = bet_status(bet)
                if status == "Gagné":
                    groups[key]["Gagnés"] += 1
                elif status == "Perdu":
                    groups[key]["Perdus"] += 1

                groups[key]["Profit virtuel"] += bet_profit(bet)

            for key, values in groups.items():
                finished = values["Gagnés"] + values["Perdus"]
                rate = (
                    values["Gagnés"] / finished * 100
                    if finished else 0
                )

                ranking_rows.append({
                    "Catégorie": "Compétition" if category == "competition" else "Marché",
                    "Nom": key,
                    "Paris": values["Paris"],
                    "Gagnés": values["Gagnés"],
                    "Perdus": values["Perdus"],
                    "Réussite": f"{rate:.1f}%",
                    "Profit virtuel": format_money(values["Profit virtuel"]),
                    "_profit": values["Profit virtuel"],
                })

        ranking_df = pd.DataFrame(ranking_rows)

        if not ranking_df.empty:
            ranking_df = ranking_df.sort_values(
                "_profit",
                ascending=False,
            )
            ranking_df = ranking_df.drop(columns=["_profit"])

            st.dataframe(
                ranking_df,
                use_container_width=True,
                hide_index=True,
            )

            st.caption(
                "Le classement utilise uniquement les paris présents dans "
                "l'historique. Une catégorie avec peu de paris peut être "
                "peu représentative."
            )

# -------------------- PIED DE PAGE --------------------

st.markdown("---")
st.markdown(
    """
    <div style="text-align:center;color:#91a6ba;font-size:12px;">
        FOOT AI PRO · Tableau de bord de simulation football<br>
        Données des matchs : football-data.org · Aucun pari réel n'est placé.
    </div>
    """,
    unsafe_allow_html=True,
)