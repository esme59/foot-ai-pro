import os
import json
from pathlib import Path
from datetime import date, datetime, timedelta

import requests
import pandas as pd
import streamlit as st


# ============================================================
# FOOT AI PRO — TABLEAU DE BORD
# Le bot.py reste responsable du règlement des paris.
# Cette application lit bankroll.json sans le modifier.
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


# ============================================================
# STYLE
# ============================================================

st.markdown(
    """
    <style>
    .stApp {
        background: #0b1220;
        color: #f1f5f9;
    }

    [data-testid="stSidebar"] {
        background: #101b2d;
    }

    div[data-testid="stMetric"] {
        background: #142238;
        border: 1px solid #263b57;
        padding: 16px;
        border-radius: 12px;
    }

    div[data-testid="stMetricLabel"] {
        color: #b8c7dc;
    }

    div[data-testid="stMetricValue"] {
        color: #ffffff;
    }

    .main-title {
        font-size: 32px;
        font-weight: 800;
        color: #ffffff;
    }

    .sub-title {
        color: #9fb2cc;
        font-size: 14px;
    }

    .info-card {
        background: #142238;
        border: 1px solid #263b57;
        padding: 16px;
        border-radius: 12px;
        margin-bottom: 10px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# LECTURE DES DONNÉES
# ============================================================

def empty_state():
    return {
        "starting_bankroll": 20.0,
        "bankroll": 20.0,
        "day": str(date.today()),
        "bets": [],
        "history": [],
        "message": "Aucune donnée disponible.",
    }


def load_state():
    """
    Lecture seule de data/bankroll.json.
    Aucun pari n'est réglé et aucun capital n'est modifié ici.
    """
    if not DATA_FILE.exists():
        return empty_state(), (
            "Le fichier data/bankroll.json est introuvable."
        )

    try:
        with DATA_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            return empty_state(), "Le fichier JSON n'a pas le format attendu."

        data.setdefault("starting_bankroll", 20.0)
        data.setdefault("bankroll", data["starting_bankroll"])
        data.setdefault("bets", [])
        data.setdefault("history", [])
        data.setdefault("message", "")

        if not isinstance(data["bets"], list):
            data["bets"] = []

        if not isinstance(data["history"], list):
            data["history"] = []

        return data, None

    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return empty_state(), f"Impossible de lire les données : {exc}"


def to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def is_settled(bet):
    return bool(bet.get("settled", False))


def get_bet_status(bet):
    if is_settled(bet):
        result = str(bet.get("result", "")).strip().lower()

        if result in {"win", "won", "gagné", "gagne", "victoire"}:
            return "Gagné"

        if result in {"loss", "lost", "perdu", "défaite", "defaite"}:
            return "Perdu"

        if result in {"void", "annulé", "annule", "remboursé", "rembourse"}:
            return "Annulé / remboursé"

        return "Terminé"

    return "En attente"


def normalize_result(bet):
    result = str(bet.get("result", "")).strip().lower()

    if not is_settled(bet):
        return "En attente"

    if result in {"win", "won", "gagné", "gagne", "victoire"}:
        return "Gagné"

    if result in {"loss", "lost", "perdu", "défaite", "defaite"}:
        return "Perdu"

    if result in {"void", "annulé", "annule", "remboursé", "rembourse"}:
        return "Annulé"

    return "Autre"


def bet_profit(bet):
    """
    Lit le bénéfice déjà enregistré par bot.py.
    Ne recalcule pas les gains et ne modifie pas les paris.
    """
    for key in ("profit", "net_profit", "gain"):
        if key in bet and bet.get(key) is not None:
            return to_float(bet.get(key))

    # Compatibilité avec les paris de l'ancienne version du bot.
    # Si le bot n'a pas enregistré le bénéfice, on ne l'invente pas.
    return None


def get_match_name(bet):
    home = (
        bet.get("home_team")
        or bet.get("home")
        or bet.get("homeTeam")
        or "Équipe domicile"
    )

    away = (
        bet.get("away_team")
        or bet.get("away")
        or bet.get("awayTeam")
        or "Équipe extérieure"
    )

    return f"{home} - {away}"


def get_competition_name(bet):
    comp = (
        bet.get("competition_name")
        or bet.get("competition")
        or bet.get("league")
        or bet.get("competition_code")
        or "Non renseignée"
    )

    return COMPETITIONS.get(str(comp), str(comp))


def get_market_name(bet):
    return str(
        bet.get("market")
        or bet.get("pick")
        or bet.get("selection")
        or "Marché non renseigné"
    )


def get_bet_date(bet):
    for key in ("created_day", "created_at", "date", "match_date"):
        value = bet.get(key)

        if value:
            return str(value)[:10]

    return "Date inconnue"


# ============================================================
# STATISTIQUES
# ============================================================

def calculate_statistics(data):
    bets = data.get("bets", [])

    settled_bets = [
        bet for bet in bets
        if is_settled(bet)
    ]

    pending_bets = [
        bet for bet in bets
        if not is_settled(bet)
    ]

    wins = sum(
        1 for bet in settled_bets
        if normalize_result(bet) == "Gagné"
    )

    losses = sum(
        1 for bet in settled_bets
        if normalize_result(bet) == "Perdu"
    )

    voids = sum(
        1 for bet in settled_bets
        if normalize_result(bet) == "Annulé"
    )

    decisive_bets = wins + losses
    win_rate = (
        wins / decisive_bets * 100
        if decisive_bets > 0
        else 0.0
    )

    known_profits = [
        bet_profit(bet)
        for bet in settled_bets
        if bet_profit(bet) is not None
    ]

    recorded_profit = sum(known_profits)

    starting_bankroll = to_float(
        data.get("starting_bankroll"),
        20.0,
    )

    current_bankroll = to_float(
        data.get("bankroll"),
        starting_bankroll,
    )

    pending_stakes = sum(
        to_float(bet.get("stake", 0))
        for bet in pending_bets
    )

    # Le capital actuel est celui enregistré par bot.py.
    # Le bénéfice cumulé calculé à partir du capital peut être
    # plus fiable que la somme des bénéfices si des paris anciens
    # ne possèdent pas encore de champ profit.
    bankroll_profit = current_bankroll - starting_bankroll

    return {
        "total": len(bets),
        "settled": len(settled_bets),
        "pending": len(pending_bets),
        "wins": wins,
        "losses": losses,
        "voids": voids,
        "win_rate": win_rate,
        "starting_bankroll": starting_bankroll,
        "current_bankroll": current_bankroll,
        "bankroll_profit": bankroll_profit,
        "recorded_profit": recorded_profit,
        "known_profit_count": len(known_profits),
        "pending_stakes": pending_stakes,
    }


def ranking_by_field(bets, field_function):
    groups = {}

    for bet in bets:
        if not is_settled(bet):
            continue

        result = normalize_result(bet)

        if result not in {"Gagné", "Perdu"}:
            continue

        label = field_function(bet)

        if label not in groups:
            groups[label] = {"wins": 0, "losses": 0}

        if result == "Gagné":
            groups[label]["wins"] += 1
        else:
            groups[label]["losses"] += 1

    rows = []

    for label, stats in groups.items():
        total = stats["wins"] + stats["losses"]

        rows.append({
            "Catégorie": label,
            "Paris": total,
            "Gagnés": stats["wins"],
            "Perdus": stats["losses"],
            "Réussite (%)": round(stats["wins"] / total * 100, 1),
        })

    rows.sort(
        key=lambda row: (
            row["Réussite (%)"],
            row["Paris"],
        ),
        reverse=True,
    )

    return rows


# ============================================================
# HISTORIQUE DU CAPITAL
# ============================================================

def build_capital_history(data):
    """
    Utilise l'historique enregistré par bot.py.
    Si les entrées ne contiennent pas de capital exploitable,
    affiche un point de départ et le capital actuel.
    """
    history = data.get("history", [])
    rows = []

    for item in history:
        if not isinstance(item, dict):
            continue

        day = (
            item.get("day")
            or item.get("date")
            or item.get("created_day")
        )

        capital = None

        for key in ("bankroll", "capital", "balance"):
            if item.get(key) is not None:
                capital = to_float(item.get(key))
                break

        if day and capital is not None:
            rows.append({
                "Date": str(day)[:10],
                "Capital (€)": capital,
            })

    if rows:
        frame = pd.DataFrame(rows)
        frame = frame.drop_duplicates(subset=["Date"], keep="last")
        frame = frame.sort_values("Date")
        return frame

    starting = to_float(data.get("starting_bankroll"), 20.0)
    current = to_float(data.get("bankroll"), starting)

    today = str(date.today())

    if abs(current - starting) < 0.0001:
        return pd.DataFrame([
            {"Date": today, "Capital (€)": starting},
        ])

    return pd.DataFrame([
        {"Date": "Départ", "Capital (€)": starting},
        {"Date": today, "Capital (€)": current},
    ])


# ============================================================
# API FOOTBALL-DATA.ORG
# ============================================================

def get_api_key():
    try:
        key = st.secrets.get("FOOTBALL_DATA_API_KEY", "")
        if key:
            return str(key).strip()
    except Exception:
        pass

    return os.getenv("FOOTBALL_DATA_API_KEY", "").strip()


@st.cache_data(ttl=900, show_spinner=False)
def fetch_matches(api_key, date_from, date_to, competition_codes):
    if not api_key:
        return [], "Clé API manquante."

    headers = {"X-Auth-Token": api_key}
    all_matches = []
    errors = []

    for code in competition_codes:
        url = f"{API_BASE}/competitions/{code}/matches"

        try:
            response = requests.get(
                url,
                headers=headers,
                params={
                    "dateFrom": date_from,
                    "dateTo": date_to,
                },
                timeout=20,
            )

            if response.status_code == 429:
                return all_matches, (
                    "Limite de requêtes API atteinte. "
                    "Les données déjà récupérées sont conservées."
                )

            if response.status_code == 403:
                errors.append(
                    f"{COMPETITIONS.get(code, code)} : accès refusé par l'API."
                )
                continue

            response.raise_for_status()
            payload = response.json()

            for match in payload.get("matches", []):
                match["competition_code_local"] = code
                all_matches.append(match)

        except requests.RequestException as exc:
            errors.append(f"{code} : {exc}")

        except (ValueError, TypeError):
            errors.append(f"{code} : réponse API illisible.")

    all_matches.sort(
        key=lambda match: match.get("utcDate", "")
    )

    message = " ".join(errors) if errors else None
    return all_matches, message


def format_match_status(match):
    status = match.get("status", "UNKNOWN")

    translations = {
        "SCHEDULED": "À venir",
        "TIMED": "Programmé",
        "IN_PLAY": "En direct",
        "PAUSED": "Mi-temps",
        "FINISHED": "Terminé",
        "POSTPONED": "Reporté",
        "CANCELLED": "Annulé",
        "SUSPENDED": "Suspendu",
        "AWARDED": "Résultat attribué",
    }

    return translations.get(status, status)


def prepare_match_table(matches):
    rows = []

    for match in matches:
        home = match.get("homeTeam", {}).get("name", "Domicile")
        away = match.get("awayTeam", {}).get("name", "Extérieur")

        competition_code = match.get("competition_code_local", "")
        competition = COMPETITIONS.get(
            competition_code,
            match.get("competition", {}).get("name", "Compétition"),
        )

        utc_date = match.get("utcDate", "")
        local_date = utc_date

        if utc_date:
            try:
                dt = datetime.fromisoformat(
                    utc_date.replace("Z", "+00:00")
                )
                local_date = dt.strftime("%d/%m/%Y %H:%M")
            except ValueError:
                pass

        score = match.get("score", {}).get("fullTime", {})
        home_score = score.get("home")
        away_score = score.get("away")

        score_text = "-"

        if home_score is not None and away_score is not None:
            score_text = f"{home_score} - {away_score}"

        rows.append({
            "Date": local_date,
            "Compétition": competition,
            "Match": f"{home} - {away}",
            "Statut": format_match_status(match),
            "Score": score_text,
        })

    return pd.DataFrame(rows)


# ============================================================
# EN-TÊTE ET SIDEBAR
# ============================================================

st.markdown(
    '<div class="main-title">⚽ FOOT AI PRO</div>',
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="sub-title">'
    "Tableau de bord • Capital virtuel • Statistiques • Matchs"
    "</div>",
    unsafe_allow_html=True,
)

st.write("")

with st.sidebar:
    st.header("⚙️ Configuration")

    st.caption("Capital de départ prévu : 20 €")

    selected_competitions = st.multiselect(
        "Compétitions",
        options=list(COMPETITIONS.keys()),
        default=list(COMPETITIONS.keys()),
        format_func=lambda code: COMPETITIONS[code],
    )

    days_ahead = st.slider(
        "Matchs à venir",
        min_value=1,
        max_value=14,
        value=7,
    )

    days_back = st.slider(
        "Jours d'historique des matchs",
        min_value=1,
        max_value=14,
        value=3,
    )

    refresh = st.button(
        "🔄 Actualiser les données",
        use_container_width=True,
    )

    if refresh:
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.caption(
        "Les paris et le capital sont gérés par bot.py. "
        "Ce tableau de bord ne modifie pas le fichier de données."
    )


# ============================================================
# CHARGEMENT DES DONNÉES
# ============================================================

data, load_error = load_state()
stats = calculate_statistics(data)

if load_error:
    st.warning(load_error)

bets = data.get("bets", [])

api_key = get_api_key()

date_from = (date.today() - timedelta(days=days_back)).isoformat()
date_to = (date.today() + timedelta(days=days_ahead)).isoformat()

matches = []
api_message = None

if selected_competitions:
    with st.spinner("Chargement des rencontres..."):
        matches, api_message = fetch_matches(
            api_key,
            date_from,
            date_to,
            tuple(selected_competitions),
        )
else:
    api_message = "Sélectionne au moins une compétition."


# ============================================================
# INDICATEURS PRINCIPAUX
# ============================================================

st.subheader("📊 Vue d'ensemble")

col1, col2, col3, col4 = st.columns(4)

col1.metric(
    "💰 Capital virtuel",
    f"{stats['current_bankroll']:.2f} €",
)

col2.metric(
    "📈 Bénéfice / perte",
    f"{stats['bankroll_profit']:+.2f} €",
)

col3.metric(
    "✅ Paris gagnés",
    stats["wins"],
)

col4.metric(
    "🎯 Réussite réelle",
    f"{stats['win_rate']:.1f}%",
)

col5, col6, col7, col8 = st.columns(4)

col5.metric("❌ Paris perdus", stats["losses"])
col6.metric("⏳ Paris en attente", stats["pending"])
col7.metric("↩️ Paris annulés", stats["voids"])
col8.metric("💶 Mises en attente", f"{stats['pending_stakes']:.2f} €")

if stats["settled"] == 0:
    st.info(
        "Le bot n'a pas encore enregistré de pari terminé. "
        "Le taux de réussite sera calculé lorsque les premiers résultats "
        "seront disponibles."
    )

if stats["known_profit_count"] < stats["settled"]:
    st.caption(
        "Certains paris anciens ne possèdent pas de bénéfice individuel "
        "enregistré. Le bénéfice global affiché est calculé à partir du "
        "capital actuel moins le capital de départ."
    )


# ============================================================
# ONGLETS
# ============================================================

tab_dashboard, tab_bets, tab_matches, tab_rankings = st.tabs([
    "🏠 Tableau de bord",
    "🎯 Mes paris",
    "⚽ Matchs",
    "🏆 Classements",
])


# ============================================================
# ONGLET TABLEAU DE BORD
# ============================================================

with tab_dashboard:
    st.subheader("📈 Évolution du capital")

    capital_frame = build_capital_history(data)

    if not capital_frame.empty:
        st.line_chart(
            capital_frame.set_index("Date")["Capital (€)"],
            use_container_width=True,
        )
    else:
        st.info("L'historique du capital apparaîtra ici.")

    st.subheader("🧾 Derniers paris")

    if bets:
        recent_bets = sorted(
            bets,
            key=lambda bet: (
                get_bet_date(bet),
                str(bet.get("settled_at", "")),
            ),
            reverse=True,
        )[:10]

        recent_rows = []

        for bet in recent_bets:
            profit = bet_profit(bet)

            recent_rows.append({
                "Date": get_bet_date(bet),
                "Match": get_match_name(bet),
                "Compétition": get_competition_name(bet),
                "Pronostic": get_market_name(bet),
                "Mise (€)": round(to_float(bet.get("stake", 0)), 2),
                "Cote": bet.get("virtual_odds", "-"),
                "Statut": get_bet_status(bet),
                "Bénéfice (€)": (
                    round(profit, 2)
                    if profit is not None
                    else "-"
                ),
            })

        st.dataframe(
            pd.DataFrame(recent_rows),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(
            "Aucun pari enregistré pour le moment. "
            "Le bot pourra ajouter des paris lors de ses prochaines exécutions."
        )

    st.subheader("🤖 État du bot")

    message = data.get("message", "")

    if message:
        st.write(str(message))
    else:
        st.write("Aucun message récent enregistré par le bot.")


# ============================================================
# ONGLET PARIS
# ============================================================

with tab_bets:
    st.subheader("⏳ Paris en attente")

    pending_bets = [
        bet for bet in bets
        if not is_settled(bet)
    ]

    if pending_bets:
        rows = []

        for bet in sorted(
            pending_bets,
            key=lambda item: get_bet_date(item),
            reverse=True,
        ):
            rows.append({
                "Date": get_bet_date(bet),
                "Match": get_match_name(bet),
                "Compétition": get_competition_name(bet),
                "Pronostic": get_market_name(bet),
                "Probabilité (%)": round(
                    to_float(bet.get("probability", 0)) * (
                        100 if to_float(bet.get("probability", 0)) <= 1
                        else 1
                    ),
                    1,
                ),
                "Mise (€)": round(to_float(bet.get("stake", 0)), 2),
                "Cote virtuelle": bet.get("virtual_odds", "-"),
            })

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.success("Aucun pari en attente.")

    st.subheader("📚 Historique des paris terminés")

    settled_bets = [
        bet for bet in bets
        if is_settled(bet)
    ]

    if settled_bets:
        rows = []

        for bet in sorted(
            settled_bets,
            key=lambda item: (
                get_bet_date(item),
                str(item.get("settled_at", "")),
            ),
            reverse=True,
        ):
            profit = bet_profit(bet)

            rows.append({
                "Date": get_bet_date(bet),
                "Match": get_match_name(bet),
                "Compétition": get_competition_name(bet),
                "Pronostic": get_market_name(bet),
                "Statut": get_bet_status(bet),
                "Score réel": bet.get("actual_score", "-"),
                "Cote": bet.get("virtual_odds", "-"),
                "Mise (€)": round(to_float(bet.get("stake", 0)), 2),
                "Bénéfice (€)": (
                    round(profit, 2)
                    if profit is not None
                    else "Non enregistré"
                ),
            })

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Les paris terminés apparaîtront ici.")


# ============================================================
# ONGLET MATCHS
# ============================================================

with tab_matches:
    st.subheader("⚽ Rencontres")

    if api_message:
        st.warning(api_message)

    if matches:
        match_frame = prepare_match_table(matches)

        if not match_frame.empty:
            st.dataframe(
                match_frame,
                use_container_width=True,
                hide_index=True,
            )
    elif not api_message:
        st.info(
            "Aucune rencontre trouvée sur cette période "
            "pour les compétitions sélectionnées."
        )

    st.caption(
        "Les rencontres proviennent de football-data.org. "
        "La disponibilité dépend de ton abonnement API."
    )


# ============================================================
# ONGLET CLASSEMENTS
# ============================================================

with tab_rankings:
    st.subheader("🏆 Performances par compétition")

    league_rows = ranking_by_field(
        bets,
        get_competition_name,
    )

    if league_rows:
        st.dataframe(
            pd.DataFrame(league_rows),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(
            "Le classement des compétitions apparaîtra après "
            "l'enregistrement de paris gagnés ou perdus."
        )

    st.subheader("🎯 Performances par marché")

    market_rows = ranking_by_field(
        bets,
        get_market_name,
    )

    if market_rows:
        st.dataframe(
            pd.DataFrame(market_rows),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(
            "Le classement des marchés apparaîtra après "
            "l'enregistrement de paris terminés."
        )

    st.caption(
        "Les classements utilisent uniquement les paris terminés "
        "et classés comme gagnés ou perdus. Les paris annulés "
        "ne sont pas inclus dans le taux de réussite."
    )


# ============================================================
# PIED DE PAGE
# ============================================================

st.divider()

st.caption(
    "FOOT AI PRO • Statistiques de simulation uniquement. "
    "Les probabilités et résultats ne garantissent aucun gain. "
    "Le tableau de bord ne passe aucun pari réel."
)