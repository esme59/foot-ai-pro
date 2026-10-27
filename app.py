import os
import json
import math
import unicodedata
from datetime import date, datetime, timedelta, timezone

import requests
import streamlit as st

# ============================================================
# FOOT AI PRO — résultats automatiques des pronostics du bot
# API : football-data.org v4
# Lit data/bankroll.json et met à jour le statut des paris terminés.
# Le capital et les mises ne sont pas recalculés par cette page.
# ============================================================

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
DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "bankroll.json")

st.markdown("""
<style>
/* FOOT AI PRO — interface premium, fond stade sombre */
:root { color-scheme: dark; }
.stApp {
    background-color: #06100e;
    background-image:
        linear-gradient(90deg, rgba(3,10,12,.94) 0%, rgba(3,10,12,.80) 55%, rgba(3,10,12,.70) 100%),
        linear-gradient(0deg, rgba(2,8,10,.94) 0%, rgba(2,8,10,.35) 100%),
        url("https://images.unsplash.com/photo-1522778119026-d647f0596c20?auto=format&fit=crop&w=2000&q=85");
    background-position: center, center, center;
    background-size: cover, cover, cover;
    background-attachment: fixed;
    color: #f4f8f6;
}
[data-testid="stHeader"] { background: rgba(3,10,12,.72); }
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, rgba(5,20,17,.98), rgba(7,16,28,.98));
    border-right: 1px solid rgba(67,255,157,.22);
}
[data-testid="stSidebar"] * { color: #eefbf4; }
.block-container { padding-top: 1.6rem; padding-bottom: 3rem; }
h1, h2, h3 { letter-spacing: -.025em; }
h1 { text-shadow: 0 0 24px rgba(47,255,143,.18); }
/* Cartes vitrées et métriques */
div[data-testid="stMetric"] {
    background: linear-gradient(145deg, rgba(12,37,32,.94), rgba(10,23,34,.94));
    padding: 16px 18px; border-radius: 16px;
    border: 1px solid rgba(69,255,161,.28);
    box-shadow: 0 8px 28px rgba(0,0,0,.22);
}
div[data-testid="stMetricLabel"] { color: #b8d8c8; }
div[data-testid="stMetricValue"] { color: #54ffa1; font-weight: 800; }
[data-testid="stVerticalBlockBorderWrapper"] {
    border-color: rgba(85,255,165,.18) !important;
    border-radius: 16px !important;
}
.stButton > button, .stDownloadButton > button {
    border-radius: 11px; border: 1px solid #39e98c;
    background: linear-gradient(120deg, #0c6b43, #0a453b);
    color: white; font-weight: 700; transition: .18s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover {
    border-color: #8affbd; color: white;
    box-shadow: 0 0 18px rgba(57,233,140,.24);
}
[data-baseweb="tab-list"] { gap: 7px; }
[data-baseweb="tab"] {
    background: rgba(10,30,28,.78); border-radius: 10px 10px 0 0;
    padding: 8px 14px;
}
[data-baseweb="tab"][aria-selected="true"] {
    background: rgba(14,90,58,.88); border-bottom: 2px solid #54ffa1;
}
[data-testid="stDataFrame"] { border: 1px solid rgba(69,255,161,.20); border-radius: 12px; }
input, textarea, [data-baseweb="select"] > div {
    background-color: rgba(8,24,25,.92) !important;
    border-color: rgba(69,255,161,.22) !important;
}
hr { border-color: rgba(69,255,161,.20); }
small, .stCaption { color: #b2c7c0 !important; }
@media (max-width: 700px) {
    .block-container { padding-left: 1rem; padding-right: 1rem; }
    .stApp { background-attachment: scroll; }
}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div style="padding:18px 22px;margin:0 0 20px;border-radius:18px;
background:linear-gradient(105deg,rgba(5,42,29,.92),rgba(7,22,32,.80));
border:1px solid rgba(75,255,159,.35);box-shadow:0 12px 36px rgba(0,0,0,.22)">
  <div style="font-size:12px;letter-spacing:3px;color:#62ffa8;font-weight:800">FOOTBALL ANALYTICS</div>
  <div style="font-size:clamp(25px,4vw,38px);font-weight:900;line-height:1.15;color:#f5fff9;margin-top:5px">FOOT AI <span style="color:#54ffa1">PRO</span></div>
  <div style="font-size:14px;color:#c1d8ce;margin-top:7px">Les matchs, les statistiques et les pronostics réunis au même endroit.</div>
</div>
""", unsafe_allow_html=True)


def norm(value):
    value = str(value or "").lower().strip()
    value = unicodedata.normalize("NFKD", value)
    return " ".join("".join(c for c in value if not unicodedata.combining(c)).split())


def num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def api_key():
    try:
        key = st.secrets.get("FOOTBALL_DATA_API_KEY", "")
        if key:
            return str(key).strip()
    except Exception:
        pass
    return os.environ.get("FOOTBALL_DATA_API_KEY", "").strip()


def load_data():
    default = {
        "starting_bankroll": 20.0, "bankroll": 20.0, "bets": [],
        "history": [], "stats": {}, "message": ""
    }
    try:
        if os.path.isfile(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                default.update(loaded)
    except Exception as exc:
        st.error(f"Lecture de bankroll.json impossible : {exc}")
    if not isinstance(default.get("bets"), list):
        default["bets"] = []
    return default


def save_data(data):
    """Écriture atomique pour éviter de laisser un JSON incomplet."""
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    temp_file = DATA_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(temp_file, DATA_FILE)


def bet_teams(bet):
    home = bet.get("home_team") or bet.get("home") or bet.get("homeTeam") or ""
    away = bet.get("away_team") or bet.get("away") or bet.get("awayTeam") or ""
    return str(home), str(away)


def bet_pick(bet):
    return str(bet.get("pick") or bet.get("market") or bet.get("prediction") or "")


def bet_status(bet):
    status = norm(bet.get("result") or bet.get("status") or "En attente")
    if status in ("gagne", "gagnee", "win", "won"):
        return "Gagné"
    if status in ("perdu", "perdue", "loss", "lost"):
        return "Perdu"
    if status in ("annule", "annulee", "void"):
        return "Annulé"
    return "En attente"


def bet_probability(bet):
    value = num(bet.get("probability", bet.get("confidence", 0)))
    return value * 100 if 0 < value <= 1 else value


def bet_probability(bet):
    value = num(bet.get("probability", bet.get("confidence", 0)))
    return value * 100 if 0 < value <= 1 else value


def evaluate_market(pick, home_goals, away_goals):
    """Retourne Gagné/Perdu pour les marchés connus, sinon None."""
    if home_goals is None or away_goals is None:
        return None
    text = norm(pick)
    total = home_goals + away_goals

    # Totaux de buts : le seuil exact est testé avant tout autre marché.
    patterns_over = [
        ("plus de 0,5", 0.5), ("plus de 0.5", 0.5), ("over 0.5", 0.5),
        ("plus de 1,5", 1.5), ("plus de 1.5", 1.5), ("over 1.5", 1.5),
        ("plus de 2,5", 2.5), ("plus de 2.5", 2.5), ("over 2.5", 2.5),
        ("plus de 3,5", 3.5), ("plus de 3.5", 3.5), ("over 3.5", 3.5),
    ]
    patterns_under = [
        ("moins de 0,5", 0.5), ("moins de 0.5", 0.5), ("under 0.5", 0.5),
        ("moins de 1,5", 1.5), ("moins de 1.5", 1.5), ("under 1.5", 1.5),
        ("moins de 2,5", 2.5), ("moins de 2.5", 2.5), ("under 2.5", 2.5),
        ("moins de 3,5", 3.5), ("moins de 3.5", 3.5), ("under 3.5", 3.5),
    ]
    for pattern, threshold in patterns_over:
        if pattern in text:
            return "Gagné" if total > threshold else "Perdu"
    for pattern, threshold in patterns_under:
        if pattern in text:
            return "Gagné" if total < threshold else "Perdu"

    if "btts" in text or "deux equipes marquent" in text:
        both = home_goals > 0 and away_goals > 0
        if "non" in text or "no" in text:
            return "Gagné" if not both else "Perdu"
        return "Gagné" if both else "Perdu"

    if "double chance 1x" in text or text.strip() == "1x":
        return "Gagné" if home_goals >= away_goals else "Perdu"
    if "double chance x2" in text or text.strip() == "x2":
        return "Gagné" if away_goals >= home_goals else "Perdu"
    if "victoire domicile" in text or "home win" in text or text.strip() in ("1", "1 gagnant"):
        return "Gagné" if home_goals > away_goals else "Perdu"
    if "victoire exterieur" in text or "away win" in text or text.strip() in ("2", "2 gagnant"):
        return "Gagné" if away_goals > home_goals else "Perdu"
    if "match nul" in text or text.strip() in ("x", "nul", "draw"):
        return "Gagné" if home_goals == away_goals else "Perdu"
    return None


@st.cache_data(ttl=900, show_spinner=False)
def fetch_competition_matches(code, date_from, date_to, key):
    url = f"{API_BASE}/competitions/{code}/matches"
    try:
        response = requests.get(
            url,
            headers={"X-Auth-Token": key},
            params={"dateFrom": date_from, "dateTo": date_to},
            timeout=20,
        )
        if response.status_code == 200:
            return {"ok": True, "matches": response.json().get("matches", []), "error": ""}
        if response.status_code == 429:
            return {"ok": False, "matches": [], "error": "Limite API atteinte (HTTP 429). Réessaie plus tard."}
        if response.status_code == 403:
            return {"ok": False, "matches": [], "error": f"Accès refusé à {code} (HTTP 403) : vérifie ton abonnement API."}
        return {"ok": False, "matches": [], "error": f"Erreur API HTTP {response.status_code} pour {code}."}
    except requests.RequestException as exc:
        return {"ok": False, "matches": [], "error": f"Connexion API impossible : {exc}"}


def score_of(match):
    score = (match.get("score") or {}).get("fullTime") or {}
    hg, ag = score.get("home"), score.get("away")
    if hg is None or ag is None:
        return None, None
    return int(hg), int(ag)


def match_date(match):
    value = match.get("utcDate", "")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except (ValueError, AttributeError):
        return str(value)[:10]


def settle_bets(data, matches):
    """Met à jour uniquement les paris dont le match est officiellement terminé."""
    bets = data.get("bets", [])
    by_id = {str(m.get("id")): m for m in matches if m.get("id") is not None}
    changed = 0
    unknown = 0

    for bet in bets:
        if bet_status(bet) in ("Gagné", "Perdu", "Annulé"):
            continue

        match = None
        bet_id = str(bet.get("match_id", "")).strip()
        if bet_id and bet_id in by_id:
            match = by_id[bet_id]

        if match is None:
            bh, ba = (norm(x) for x in bet_teams(bet))
            bd = str(bet.get("date") or bet.get("match_date") or "")[:10]
            for candidate in matches:
                ch = norm((candidate.get("homeTeam") or {}).get("name", ""))
                ca = norm((candidate.get("awayTeam") or {}).get("name", ""))
                if bh and ba and bh == ch and ba == ca and (not bd or bd == match_date(candidate)):
                    match = candidate
                    break

        if not match:
            continue

        status = match.get("status", "")
        if status in ("CANCELLED", "POSTPONED", "SUSPENDED"):
            # Ne pas régler un match reporté/suspendu/annulé automatiquement.
            continue
        if status not in ("FINISHED", "AWARDED"):
            continue

        hg, ag = score_of(match)
        if hg is None or ag is None:
            continue

        outcome = evaluate_market(bet_pick(bet), hg, ag)
        bet["actual_score"] = f"{hg}-{ag}"
        bet["match_status"] = status
        if outcome is None:
            bet["result"] = "Marché à vérifier"
            bet["settled"] = False
            unknown += 1
        else:
            bet["result"] = outcome
            bet["settled"] = True
            bet["settled_at"] = datetime.now(timezone.utc).isoformat()
            changed += 1

    if changed:
        # Ne modifie pas le capital, les mises ou les bénéfices ici.
        data["bets"] = bets
        save_data(data)
    return changed, unknown


# ---------------------- Chargement et statistiques ----------------------

state = load_data()
bets = state.get("bets", [])
key = api_key()
starting_bankroll = num(state.get("starting_bankroll", 20), 20)
bankroll = num(state.get("bankroll", starting_bankroll), starting_bankroll)

def status_counts(items):
    wins = sum(bet_status(b) == "Gagné" for b in items)
    losses = sum(bet_status(b) == "Perdu" for b in items)
    pending = sum(bet_status(b) == "En attente" for b in items)
    voids = sum(bet_status(b) == "Annulé" for b in items)
    return wins, losses, pending, voids

wins, losses, pending, voids = status_counts(bets)
settled = wins + losses
win_rate = 100 * wins / settled if settled else 0
open_stakes = sum(num(b.get("stake", 0)) for b in bets if bet_status(b) == "En attente")

st.title("⚽ FOOT AI PRO")
st.caption("Tableau de bord, pronostics du bot et résultats officiels des matchs.")

if not key:
    st.error("Clé API manquante. Dans Streamlit → Settings → Secrets, ajoute FOOTBALL_DATA_API_KEY.")

with st.sidebar:
    st.header("⚙️ Paramètres")
    selected_leagues = st.multiselect("Compétitions", list(COMPETITIONS.keys()), default=list(COMPETITIONS.keys()))
    st.divider()
    st.metric("Capital actuel", f"{bankroll:.2f} €")
    st.metric("Mises en attente", f"{open_stakes:.2f} €")
    st.caption("La vérification des résultats ne change pas automatiquement ton capital.")
    if st.button("🔄 Vider le cache API"):
        st.cache_data.clear()
        st.rerun()

tab_dashboard, tab_matches, tab_history = st.tabs(
    ["📊 Tableau de bord", "📅 Matchs et scores", "📚 Pronostics du bot"]
)

with tab_dashboard:
    st.subheader("Vue générale")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Capital", f"{bankroll:.2f} €")
    c2.metric("Pronostics enregistrés", len(bets))
    c3.metric("En attente", pending)
    c4.metric("Taux de réussite", f"{win_rate:.1f} %")
    c5, c6, c7 = st.columns(3)
    c5.metric("Gagnés", wins)
    c6.metric("Perdus", losses)
    c7.metric("Mises en attente", f"{open_stakes:.2f} €")
    st.info("Le taux de réussite est calculé uniquement sur les pronostics gagnés ou perdus.")
    if state.get("message"):
        st.caption(str(state["message"]))

    st.subheader("Derniers pronostics du bot")
    if not bets:
        st.info("Aucun pari trouvé dans data/bankroll.json.")
    else:
        rows = []
        for bet in bets[-10:][::-1]:
            home = bet.get("home") or bet.get("home_team") or ""
            away = bet.get("away") or bet.get("away_team") or ""
            rows.append({
                "Date": str(bet.get("date", ""))[:10] or "—",
                "Compétition": bet.get("league") or bet.get("competition") or "—",
                "Match": f"{home} - {away}",
                "Pronostic": bet_pick(bet) or "—",
                "Score réel": bet.get("actual_score") or "—",
                "Statut": bet_status(bet),
                "Mise (€)": round(num(bet.get("stake")), 2),
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)

with tab_matches:
    st.subheader("📅 Recherche de matchs et vérification des résultats")
    today = date.today()
    selected_date = st.date_input(
        "Date des matchs",
        value=today,
        min_value=date(2000, 1, 1),
        max_value=today + timedelta(days=365),
        format="DD/MM/YYYY",
    )
    if st.button("🔎 Rechercher les matchs", type="primary"):
        if not key:
            st.error("La clé API est manquante.")
        elif not selected_leagues:
            st.warning("Sélectionne au moins une compétition.")
        else:
            found, errors = [], []
            progress = st.progress(0)
            for i, league in enumerate(selected_leagues):
                result = fetch_competition_matches(
                    COMPETITIONS[league], selected_date.isoformat(),
                    selected_date.isoformat(), key
                )
                if result["ok"]:
                    for match in result["matches"]:
                        match["_league_name"] = league
                        found.append(match)
                elif result["error"]:
                    errors.append(result["error"])
                progress.progress((i + 1) / len(selected_leagues))
            progress.empty()
            st.session_state["calendar_matches"] = found
            st.session_state["calendar_date"] = selected_date.isoformat()
            st.session_state["calendar_errors"] = errors

    if st.session_state.get("calendar_date") == selected_date.isoformat():
        for error in st.session_state.get("calendar_errors", []):
            st.warning(error)
        matches = st.session_state.get("calendar_matches", [])
        if not matches:
            st.info("Aucun match trouvé pour cette date dans les compétitions accessibles.")
        for match in sorted(matches, key=lambda m: m.get("utcDate", "")):
            home = (match.get("homeTeam") or {}).get("name", "Domicile")
            away = (match.get("awayTeam") or {}).get("name", "Extérieur")
            hg, ag = score_of(match)
            status = match.get("status", "")
            st.markdown(f"### {home} — {away}")
            st.caption(f"{match.get('_league_name', '')} · {match.get('utcDate', '')[:16]} · {status}")
            if hg is not None and ag is not None:
                st.success(f"Score : {hg} - {ag}")
            elif status in ("IN_PLAY", "PAUSED"):
                st.info("Match en cours ; score final pas encore disponible.")
            else:
                st.caption("Pas encore de score final.")

            match_bets = []
            mid = str(match.get("id", ""))
            for bet in bets:
                same_id = mid and str(bet.get("match_id", "")) == mid
                bh, ba = (norm(x) for x in (bet.get("home") or bet.get("home_team") or "", bet.get("away") or bet.get("away_team") or ""))
                same_teams = bh == norm(home) and ba == norm(away)
                same_date = not bet.get("date") or str(bet.get("date"))[:10] == match_date(match)
                if same_id or (same_teams and same_date):
                    match_bets.append(bet)
            for bet in match_bets:
                st.write(f"Pronostic du bot : **{bet_pick(bet)}**")
                if status in ("FINISHED", "AWARDED") and hg is not None and ag is not None:
                    result = evaluate_market(bet_pick(bet), hg, ag)
                    if result == "Gagné":
                        st.success("Pronostic : GAGNÉ ✅")
                    elif result == "Perdu":
                        st.error("Pronostic : PERDU ❌")
                    else:
                        st.warning("Marché non reconnu : vérification manuelle nécessaire.")
                else:
                    st.info("Pronostic en attente du résultat final.")
            st.divider()

with tab_history:
    st.subheader("📚 Historique et règlement automatique des pronostics")
    st.write(
        "Le bouton ci-dessous recherche les matchs des 45 derniers jours "
        "dans les compétitions sélectionnées, puis inscrit le score réel et "
        "le statut Gagné/Perdu dans data/bankroll.json."
    )
    st.warning(
        "La vérification met à jour les champs de résultat des paris. "
        "Elle ne modifie pas le capital, les mises ni les bénéfices."
    )

    if st.button("🔄 Vérifier les résultats des 45 derniers jours", type="primary", use_container_width=True):
        if not key:
            st.error("Clé API manquante : impossible de vérifier les résultats.")
        elif not selected_leagues:
            st.warning("Sélectionne au moins une compétition dans la barre latérale.")
        else:
            end_day = date.today()
            start_day = end_day - timedelta(days=45)
            all_matches, errors = [], []
            progress = st.progress(0)
            for i, league in enumerate(selected_leagues):
                result = fetch_competition_matches(
                    COMPETITIONS[league], start_day.isoformat(), end_day.isoformat(), key
                )
                if result["ok"]:
                    all_matches.extend(result["matches"])
                else:
                    errors.append(result["error"])
                progress.progress((i + 1) / len(selected_leagues))
            progress.empty()
            changed, unknown = settle_bets(state, all_matches)
            st.session_state["settle_notice"] = (
                f"Vérification terminée : {changed} pronostic(s) réglé(s). "
                f"{unknown} marché(s) nécessitent une vérification manuelle."
            )
            st.session_state["settle_errors"] = errors
            st.rerun()

    if st.session_state.get("settle_notice"):
        st.success(st.session_state["settle_notice"])
    for error in st.session_state.get("settle_errors", []):
        st.warning(error)

    current_state = load_data()
    current_bets = current_state.get("bets", [])
    filter_status = st.selectbox("Filtrer les pronostics", ["Tous", "En attente", "Gagné", "Perdu", "Annulé", "Marché à vérifier"])
    rows = []
    for bet in current_bets[::-1]:
        status = bet_status(bet)
        if bet.get("result") == "Marché à vérifier":
            status = "Marché à vérifier"
        if filter_status != "Tous" and status != filter_status:
            continue
        home = bet.get("home") or bet.get("home_team") or ""
        away = bet.get("away") or bet.get("away_team") or ""
        rows.append({
            "Date": str(bet.get("date", ""))[:10] or "—",
            "Compétition": bet.get("league") or bet.get("competition") or "—",
            "Match": f"{home} - {away}",
            "Pronostic": bet_pick(bet) or "—",
            "Probabilité": f"{bet_probability(bet):.1f} %",
            "Score prédit": bet.get("score") or "—",
            "Score réel": bet.get("actual_score") or "—",
            "Mise (€)": round(num(bet.get("stake")), 2),
            "Statut": status,
        })
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("Aucun pronostic correspondant à ce filtre.")

st.divider()
st.caption(
    "FOOT AI PRO — les probabilités sont des estimations, pas des garanties. "
    "Les résultats sont récupérés depuis football-data.org selon les compétitions accessibles à ta clé API."
)