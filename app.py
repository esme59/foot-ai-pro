import os
import math
from datetime import date, datetime, timedelta, timezone

import requests
import streamlit as st

# =========================================================
# FOOT AI PRO — FOOTBALL LIVE
# Compatible avec football-data.org v4
# =========================================================

st.set_page_config(
    page_title="FOOT AI PRO | Football Live",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_BASE = "https://api.football-data.org/v4"
COMPETITIONS = {
    "🇫🇷 Ligue 1": "FL1",
    "🏴 Premier League": "PL",
    "🇪🇸 Liga": "PD",
    "🇩🇪 Bundesliga": "BL1",
    "🇮🇹 Serie A": "SA",
    "🏆 Ligue des Champions": "CL",
}
LIVE_STATUSES = {"IN_PLAY", "PAUSED", "EXTRA_TIME", "PENALTY_SHOOTOUT"}
UPCOMING_STATUSES = {"SCHEDULED", "TIMED"}
FINISHED_STATUSES = {"FINISHED"}
MARKET_GROUPS = {
    "Résultat": ["Victoire domicile", "Match nul", "Victoire extérieur", "Double chance 1X", "Double chance X2"],
    "Buts": ["Plus de 0,5 but", "Plus de 1,5 but", "Plus de 2,5 buts", "Plus de 3,5 buts", "Moins de 2,5 buts", "Moins de 3,5 buts"],
    "BTTS": ["Les deux équipes marquent — Oui", "Les deux équipes marquent — Non"],
}

# ----------------------------- STYLE -----------------------------
st.markdown("""
<style>
:root { color-scheme: dark; }
.stApp {
    background:
      radial-gradient(ellipse at 15% 0%, rgba(24, 110, 77, .20), transparent 35%),
      linear-gradient(145deg, #08121b 0%, #0b1721 55%, #071018 100%);
}
.block-container { padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1500px; }
[data-testid="stSidebar"] { background: #0b151e; border-right: 1px solid #20323d; }
.hero {
    padding: 1.4rem 1.6rem; border: 1px solid #23473b; border-radius: 22px;
    background: linear-gradient(115deg, rgba(17,72,51,.88), rgba(13,31,42,.95) 70%);
    margin-bottom: 1.2rem;
}
.hero-kicker { color:#70e5a2; font-size:.78rem; letter-spacing:.16em; font-weight:800; text-transform:uppercase; }
.hero-title { color:#f5fbf8; font-size:2.25rem; font-weight:850; line-height:1.1; margin:.35rem 0; }
.hero-sub { color:#b7c9c5; font-size:.98rem; }
.section-label { color:#72e3a2; text-transform:uppercase; letter-spacing:.12em; font-weight:800; font-size:.76rem; }
.match-card {
    border:1px solid #263d49; border-radius:18px; padding:1.05rem 1.15rem;
    background:linear-gradient(135deg, rgba(20,38,49,.96), rgba(12,25,35,.96));
    margin-bottom:.75rem;
}
.match-comp { color:#8da9b4; font-size:.78rem; text-transform:uppercase; letter-spacing:.07em; }
.match-teams { color:#f2f7fa; font-size:1.13rem; font-weight:800; margin:.35rem 0; }
.match-meta { color:#a4b8c0; font-size:.82rem; }
.pill {
    display:inline-block; padding:.25rem .55rem; border-radius:999px; font-size:.75rem;
    font-weight:750; background:#183d30; color:#8df0b3; border:1px solid #2d624a;
}
.small-note { color:#91a6b1; font-size:.8rem; }
div[data-testid="stMetric"] {
    background:rgba(18,37,48,.82); border:1px solid #263d49;
    padding:14px 16px; border-radius:16px;
}
div[data-testid="stMetricLabel"] { color:#a6bbc3; }
div[data-testid="stMetricValue"] { color:#f4faf7; }
.stButton > button {
    border-radius:11px; border:1px solid #2c6a4d; font-weight:750;
}
hr { border-color:#233844; }
</style>
""", unsafe_allow_html=True)


# ----------------------------- API -----------------------------
def get_api_key():
    try:
        key = st.secrets.get("FOOTBALL_DATA_API_KEY", "")
        if key:
            return str(key).strip()
    except Exception:
        pass
    return os.environ.get("FOOTBALL_DATA_API_KEY", "").strip()


def api_get(endpoint, params=None):
    key = get_api_key()
    if not key:
        raise RuntimeError(
            "Clé API absente. Dans Streamlit, ouvre Settings → Secrets et ajoute "
            'FOOTBALL_DATA_API_KEY = "ta_cle_api".'
        )
    try:
        response = requests.get(
            API_BASE + endpoint,
            headers={"X-Auth-Token": key},
            params=params,
            timeout=20,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Connexion impossible à football-data.org : {exc}") from exc

    if response.status_code == 429:
        raise RuntimeError("Limite de requêtes API atteinte. Attends quelques minutes avant de réessayer.")
    if response.status_code == 403:
        raise RuntimeError("Accès refusé pour cette compétition avec ta clé API ou ton abonnement.")
    if response.status_code == 401:
        raise RuntimeError("Clé API refusée. Vérifie FOOTBALL_DATA_API_KEY dans Streamlit Secrets.")
    if response.status_code != 200:
        raise RuntimeError(f"Erreur API {response.status_code} : {response.text[:180]}")
    return response.json()


@st.cache_data(ttl=300, show_spinner=False)
def load_matches(competition_code, date_from, date_to):
    return api_get(
        f"/competitions/{competition_code}/matches",
        {"dateFrom": date_from, "dateTo": date_to},
    ).get("matches", [])


@st.cache_data(ttl=180, show_spinner=False)
def load_live_matches(competition_code):
    return api_get(f"/competitions/{competition_code}/matches", {"status": "IN_PLAY"}).get("matches", [])


@st.cache_data(ttl=3600, show_spinner=False)
def load_team_history(team_id, before_date):
    return api_get(
        f"/teams/{team_id}/matches",
        {"status": "FINISHED", "dateTo": before_date, "limit": 10},
    ).get("matches", [])


# ----------------------------- STATS & MODEL -----------------------------
def team_statistics(team_id, before_date, venue=None):
    try:
        matches = load_team_history(team_id, before_date)
    except Exception:
        matches = []

    valid = []
    for match in matches:
        score = match.get("score", {}).get("fullTime", {})
        if score.get("home") is None or score.get("away") is None:
            continue
        if venue == "home" and match.get("homeTeam", {}).get("id") != team_id:
            continue
        if venue == "away" and match.get("awayTeam", {}).get("id") != team_id:
            continue
        valid.append(match)

    valid.sort(key=lambda m: m.get("utcDate", ""), reverse=True)
    valid = valid[:5]
    scored, conceded, points, form = [], [], [], []

    for match in valid:
        home_id = match.get("homeTeam", {}).get("id")
        away_id = match.get("awayTeam", {}).get("id")
        score = match["score"]["fullTime"]
        if team_id == home_id:
            gf, ga = score["home"], score["away"]
        elif team_id == away_id:
            gf, ga = score["away"], score["home"]
        else:
            continue
        scored.append(gf)
        conceded.append(ga)
        if gf > ga:
            points.append(3); form.append("V")
        elif gf == ga:
            points.append(1); form.append("N")
        else:
            points.append(0); form.append("D")

    if not scored:
        return {"scored": 1.25, "conceded": 1.25, "points": 1.0, "form": "Indisponible", "count": 0}

    return {
        "scored": sum(scored) / len(scored),
        "conceded": sum(conceded) / len(conceded),
        "points": sum(points) / len(points),
        "form": " · ".join(form),
        "count": len(scored),
    }


def poisson(k, expected):
    expected = max(0.01, expected)
    return math.exp(-expected) * expected**k / math.factorial(k)


def calculate_markets(expected_home, expected_away):
    max_goals = 10
    hp = [poisson(i, expected_home) for i in range(max_goals + 1)]
    ap = [poisson(i, expected_away) for i in range(max_goals + 1)]
    scores = []
    mass = home_win = draw = away_win = 0.0
    over05 = over15 = over25 = over35 = btts = 0.0

    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = hp[h] * ap[a]
            mass += p
            scores.append((h, a, p))
            if h > a: home_win += p
            elif h == a: draw += p
            else: away_win += p
            if h + a >= 1: over05 += p
            if h + a >= 2: over15 += p
            if h + a >= 3: over25 += p
            if h + a >= 4: over35 += p
            if h >= 1 and a >= 1: btts += p

    mass = mass or 1.0
    norm = lambda x: x / mass
    markets = {
        "Victoire domicile": norm(home_win),
        "Match nul": norm(draw),
        "Victoire extérieur": norm(away_win),
        "Double chance 1X": norm(home_win + draw),
        "Double chance X2": norm(away_win + draw),
        "Plus de 0,5 but": norm(over05),
        "Plus de 1,5 but": norm(over15),
        "Plus de 2,5 buts": norm(over25),
        "Plus de 3,5 buts": norm(over35),
        "Les deux équipes marquent — Oui": norm(btts),
        "Les deux équipes marquent — Non": norm(mass - btts),
        "Moins de 2,5 buts": norm(mass - over25),
        "Moins de 3,5 buts": norm(mass - over35),
    }
    top_scores = [
        {"score": f"{h} - {a}", "probability": norm(p)}
        for h, a, p in sorted(scores, key=lambda x: x[2], reverse=True)[:5]
    ]
    return markets, top_scores


def analyze_match(match):
    home = match.get("homeTeam", {})
    away = match.get("awayTeam", {})
    home_id, away_id = home.get("id"), away.get("id")
    if not home_id or not away_id:
        return None

    kickoff = match.get("utcDate", "")
    before = kickoff[:10] if kickoff else date.today().isoformat()

    # Recent form overall, plus venue-specific samples where available.
    hs = team_statistics(home_id, before)
    aws = team_statistics(away_id, before)
    home_venue = team_statistics(home_id, before, "home")
    away_venue = team_statistics(away_id, before, "away")

    # Blend overall recent form with venue-specific form when enough matches exist.
    home_scored = 0.65 * hs["scored"] + 0.35 * home_venue["scored"] if home_venue["count"] else hs["scored"]
    home_conceded = 0.65 * hs["conceded"] + 0.35 * home_venue["conceded"] if home_venue["count"] else hs["conceded"]
    away_scored = 0.65 * aws["scored"] + 0.35 * away_venue["scored"] if away_venue["count"] else aws["scored"]
    away_conceded = 0.65 * aws["conceded"] + 0.35 * away_venue["conceded"] if away_venue["count"] else aws["conceded"]

    eh = (0.55 * home_scored + 0.45 * away_conceded + 0.20) * (0.90 + hs["points"] * 0.07)
    ea = (0.55 * away_scored + 0.45 * home_conceded) * (0.90 + aws["points"] * 0.07)
    eh, ea = max(0.10, min(eh, 4.0)), max(0.10, min(ea, 4.0))
    markets, scores = calculate_markets(eh, ea)

    return {
        "id": match.get("id"),
        "home": home.get("name", "Domicile"),
        "away": away.get("name", "Extérieur"),
        "home_id": home_id,
        "away_id": away_id,
        "kickoff": kickoff,
        "status": match.get("status", ""),
        "score": match.get("score", {}),
        "competition": match.get("_competition_label") or match.get("competition", {}).get("name", ""),
        "home_stats": hs,
        "away_stats": aws,
        "home_venue": home_venue,
        "away_venue": away_venue,
        "expected_home": eh,
        "expected_away": ea,
        "markets": markets,
        "top_scores": scores,
    }


# ----------------------------- HELPERS -----------------------------
def pct(p):
    return f"{p * 100:.1f} %"


def prob_emoji(p):
    if p >= 0.75: return "🟢"
    if p >= 0.60: return "🟡"
    if p >= 0.45: return "🟠"
    return "⚪"


def kickoff_local(iso):
    if not iso:
        return "Horaire indisponible"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        # Display France local time (handles winter/summer time).
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo("Europe/Paris")).strftime("%H:%M")
    except Exception:
        return iso[11:16] + " UTC"


def score_text(analysis):
    score = analysis.get("score", {}).get("fullTime", {})
    h, a = score.get("home"), score.get("away")
    if h is None or a is None:
        score = analysis.get("score", {}).get("halfTime", {})
        h, a = score.get("home"), score.get("away")
    return f"{h} – {a}" if h is not None and a is not None else "VS"


def match_status_label(status):
    if status in LIVE_STATUSES: return "🔴 EN DIRECT"
    if status == "FINISHED": return "TERMINÉ"
    if status == "POSTPONED": return "REPORTÉ"
    if status == "CANCELLED": return "ANNULÉ"
    return "À VENIR"


def make_picks(analyses, profile, max_legs):
    """Build varied, non-duplicate market selections; probabilities are model estimates."""
    if profile == "Prudent":
        threshold, markets_allowed = 0.72, [
            "Double chance 1X", "Double chance X2", "Plus de 1,5 but",
            "Moins de 3,5 buts", "Les deux équipes marquent — Non",
            "Les deux équipes marquent — Oui",
        ]
    elif profile == "Équilibré":
        threshold, markets_allowed = 0.58, [
            "Victoire domicile", "Victoire extérieur", "Double chance 1X",
            "Double chance X2", "Plus de 1,5 but", "Plus de 2,5 buts",
            "Moins de 3,5 buts", "Les deux équipes marquent — Oui",
        ]
    else:
        threshold, markets_allowed = 0.42, [
            "Victoire domicile", "Match nul", "Victoire extérieur",
            "Plus de 2,5 buts", "Plus de 3,5 buts",
            "Les deux équipes marquent — Oui", "Moins de 2,5 buts",
        ]

    candidates = []
    for a in analyses:
        for market in markets_allowed:
            p = a["markets"].get(market, 0)
            if p >= threshold:
                candidates.append({
                    "match_id": a["id"], "fixture": f'{a["home"]} – {a["away"]}',
                    "market": market, "p": p, "kickoff": a["kickoff"],
                    "competition": a["competition"],
                })

    # Highest probability first; avoid using the same match twice in one combo.
    candidates.sort(key=lambda x: x["p"], reverse=True)
    picks, used = [], set()
    for item in candidates:
        if item["match_id"] in used:
            continue
        picks.append(item)
        used.add(item["match_id"])
        if len(picks) >= max_legs:
            break
    return picks


def combo_probability(picks):
    result = 1.0
    for pick in picks:
        result *= pick["p"]
    return result


def render_match_card(a, show_analysis_button=True):
    status = match_status_label(a.get("status", ""))
    score = score_text(a)
    st.markdown(
        f"""
        <div class="match-card">
          <div class="match-comp">{a['competition']} &nbsp;·&nbsp; {kickoff_local(a['kickoff'])} &nbsp;·&nbsp; <span class="pill">{status}</span></div>
          <div class="match-teams">{a['home']} &nbsp; <span style="color:#6fe3a0">{score}</span> &nbsp; {a['away']}</div>
          <div class="match-meta">Buts attendus : {a['expected_home']:.2f} – {a['expected_away']:.2f} &nbsp;·&nbsp; Forme récente disponible : {a['home_stats']['count']} / {a['away_stats']['count']} matchs</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    best = sorted(a["markets"].items(), key=lambda x: x[1], reverse=True)[:3]
    cols = st.columns(3)
    for col, (label, p) in zip(cols, best):
        with col:
            st.metric(label, pct(p))
    if show_analysis_button:
        with st.expander(f"📊 Analyse complète — {a['home']} / {a['away']}"):
            left, right = st.columns(2)
            with left:
                st.markdown(f"**{a['home']} — domicile**")
                st.write(f"Forme récente : {a['home_stats']['form']}")
                st.write(f"Buts marqués/match : {a['home_stats']['scored']:.2f}")
                st.write(f"Buts encaissés/match : {a['home_stats']['conceded']:.2f}")
                st.write(f"Échantillon domicile : {a['home_venue']['count']} match(s)")
            with right:
                st.markdown(f"**{a['away']} — extérieur**")
                st.write(f"Forme récente : {a['away_stats']['form']}")
                st.write(f"Buts marqués/match : {a['away_stats']['scored']:.2f}")
                st.write(f"Buts encaissés/match : {a['away_stats']['conceded']:.2f}")
                st.write(f"Échantillon extérieur : {a['away_venue']['count']} match(s)")
            st.markdown("##### Probabilités estimées par marché")
            sorted_markets = sorted(a["markets"].items(), key=lambda x: x[1], reverse=True)
            for start in range(0, len(sorted_markets), 2):
                cols = st.columns(2)
                for offset, col in enumerate(cols):
                    idx = start + offset
                    if idx >= len(sorted_markets):
                        continue
                    label, p = sorted_markets[idx]
                    with col:
                        st.write(f"{prob_emoji(p)} **{label}** · {pct(p)}")
                        st.progress(min(1.0, max(0.0, p)))
            with st.expander("🎯 Scores exacts théoriques"):
                for item in a["top_scores"]:
                    st.write(f"**{item['score']}** — {pct(item['probability'])}")
            st.caption("Modèle simplifié de Poisson : estimation indicative, non garantie et non calibrée sur plusieurs saisons.")


# ----------------------------- HEADER -----------------------------
st.markdown("""
<div class="hero">
  <div class="hero-kicker">Football analytics · Live dashboard</div>
  <div class="hero-title">⚽ FOOT AI PRO</div>
  <div class="hero-sub">Matchs, statistiques et probabilités dans une interface claire — pensée pour mobile.</div>
</div>
""", unsafe_allow_html=True)

if not get_api_key():
    st.error("La clé API football-data.org n'a pas été trouvée.")
    st.code('FOOTBALL_DATA_API_KEY = "TA_CLE_API"', language="toml")
    st.info("Sur Streamlit Cloud : ouvre ton application → Settings → Secrets, puis ajoute la clé sans la partager publiquement.")
    st.stop()

# ----------------------------- SIDEBAR -----------------------------
with st.sidebar:
    st.markdown("## ⚽ FOOT AI PRO")
    st.caption("CENTRE DE CONTRÔLE")
    page = st.radio(
        "Navigation",
        ["🏠 Tableau de bord", "🔴 Football Live", "🧠 Analyses IA", "🎯 Combinés IA", "📈 Historique"],
        label_visibility="collapsed",
    )
    st.divider()
    selected_date = st.date_input("Date des matchs", value=date.today())
    selected_competitions = st.multiselect(
        "Championnats",
        options=list(COMPETITIONS.keys()),
        default=list(COMPETITIONS.keys()),
    )
    days_ahead = st.slider("Fenêtre de recherche (jours)", 0, 7, 0)
    refresh = st.button("↻ Actualiser les données", use_container_width=True)
    st.caption("Les données dépendent des droits et limites de ton abonnement API.")

if refresh:
    load_matches.clear()
    load_live_matches.clear()
    load_team_history.clear()
    st.session_state.pop("analyses", None)
    st.session_state.pop("all_fixtures", None)
    st.session_state.pop("live_analyses", None)

if "analyses" not in st.session_state or refresh or st.session_state.get("loaded_filter") != (
    selected_date.isoformat(), tuple(selected_competitions), days_ahead
):
    all_fixtures, errors = [], []
    end_date = selected_date + timedelta(days=days_ahead)
    if not selected_competitions:
        st.session_state["analyses"] = []
        st.session_state["all_fixtures"] = []
        st.session_state["errors"] = ["Sélectionne au moins un championnat."]
    else:
        with st.spinner("Récupération des matchs et analyse statistique…"):
            for comp_name in selected_competitions:
                try:
                    fixtures = load_matches(COMPETITIONS[comp_name], selected_date.isoformat(), end_date.isoformat())
                    for fixture in fixtures:
                        fixture["_competition_label"] = comp_name
                    all_fixtures.extend(fixtures)
                except Exception as exc:
                    errors.append(f"{comp_name} : {exc}")

            unique = {m.get("id"): m for m in all_fixtures if m.get("id") is not None}
            all_fixtures = sorted(unique.values(), key=lambda m: m.get("utcDate", ""))
            analyses = []
            for fixture in all_fixtures:
                # Analyze scheduled/timed and finished matches; live scores shown in Live page too.
                if fixture.get("status") not in UPCOMING_STATUSES | LIVE_STATUSES | FINISHED_STATUSES:
                    continue
                try:
                    a = analyze_match(fixture)
                    if a:
                        a["competition"] = fixture.get("_competition_label") or a["competition"]
                        analyses.append(a)
                except Exception as exc:
                    errors.append(f"{fixture.get('homeTeam', {}).get('name', '?')} – {fixture.get('awayTeam', {}).get('name', '?')} : {exc}")
            st.session_state["analyses"] = analyses
            st.session_state["all_fixtures"] = all_fixtures
            st.session_state["errors"] = errors
            st.session_state["loaded_filter"] = (selected_date.isoformat(), tuple(selected_competitions), days_ahead)

analyses = st.session_state.get("analyses", [])
all_fixtures = st.session_state.get("all_fixtures", [])
errors = st.session_state.get("errors", [])

for err in errors:
    st.warning(err)

live_analyses = [a for a in analyses if a.get("status") in LIVE_STATUSES]
upcoming_analyses = [a for a in analyses if a.get("status") in UPCOMING_STATUSES]
finished_analyses = [a for a in analyses if a.get("status") in FINISHED_STATUSES]

# ----------------------------- DASHBOARD -----------------------------
if page == "🏠 Tableau de bord":
    st.markdown('<div class="section-label">Vue d’ensemble</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Matchs trouvés", len(all_fixtures))
    c2.metric("À venir", len(upcoming_analyses))
    c3.metric("En direct", len(live_analyses))
    c4.metric("Terminés", len(finished_analyses))

    st.markdown("### ⭐ Meilleures probabilités estimées")
    if analyses:
        rows = []
        for a in analyses:
            for market, p in a["markets"].items():
                if market in ("Victoire domicile", "Victoire extérieur", "Plus de 1,5 but", "Plus de 2,5 buts", "Double chance 1X", "Double chance X2", "Les deux équipes marquent — Oui"):
                    rows.append({"Match": f'{a["home"]} – {a["away"]}', "Championnat": a["competition"], "Marché": market, "Probabilité estimée": p})
        rows.sort(key=lambda x: x["Probabilité estimée"], reverse=True)
        if rows:
            for row in rows[:8]:
                with st.container(border=True):
                    left, right = st.columns([4, 1])
                    left.markdown(f"**{row['Match']}**")
                    left.caption(f"{row['Championnat']} · {row['Marché']}")
                    right.metric("Estimation", pct(row["Probabilité estimée"]))
    else:
        st.info("Aucun match analysable pour les filtres sélectionnés. Essaie une autre date ou un autre championnat.")

    st.caption(f"Date sélectionnée : {selected_date.strftime('%d/%m/%Y')} · Horaires affichés en heure française.")

# ----------------------------- LIVE -----------------------------
elif page == "🔴 Football Live":
    st.markdown('<div class="section-label">Scores en direct</div>', unsafe_allow_html=True)
    st.caption("Le direct dépend de la disponibilité des matchs dans ton offre football-data.org.")
    if live_analyses:
        st.success(f"{len(live_analyses)} rencontre(s) en direct ou en pause.")
        for a in live_analyses:
            render_match_card(a)
    else:
        st.info("Aucun match en direct dans les compétitions et la période chargées.")
        st.markdown("### Prochains matchs")
        for a in upcoming_analyses[:10]:
            render_match_card(a, show_analysis_button=False)

# ----------------------------- AI ANALYSIS -----------------------------
elif page == "🧠 Analyses IA":
    st.markdown('<div class="section-label">Laboratoire de pronostics</div>', unsafe_allow_html=True)
    search = st.text_input("Rechercher une équipe", placeholder="Ex. : Paris, Lille, Arsenal…")
    status_filter = st.selectbox("Type de rencontre", ["Toutes", "À venir", "En direct", "Terminées"])
    shown = analyses
    if search.strip():
        q = search.strip().lower()
        shown = [a for a in shown if q in a["home"].lower() or q in a["away"].lower()]
    if status_filter == "À venir": shown = [a for a in shown if a["status"] in UPCOMING_STATUSES]
    elif status_filter == "En direct": shown = [a for a in shown if a["status"] in LIVE_STATUSES]
    elif status_filter == "Terminées": shown = [a for a in shown if a["status"] in FINISHED_STATUSES]
    if not shown:
        st.info("Aucune rencontre ne correspond à ta recherche.")
    else:
        st.write(f"**{len(shown)} rencontre(s)**")
        for a in shown:
            render_match_card(a)

# ----------------------------- COMBINATIONS -----------------------------
elif page == "🎯 Combinés IA":
    st.markdown('<div class="section-label">Générateur de combinés</div>', unsafe_allow_html=True)
    st.warning("Les combinés multiplient le risque : même une sélection individuellement probable peut faire perdre le ticket. Les probabilités sont des estimations du modèle, pas des garanties.")
    source = st.radio("Rencontres à utiliser", ["Matchs à venir uniquement", "Tous les matchs analysés"], horizontal=True)
    pool = upcoming_analyses if source == "Matchs à venir uniquement" else analyses
    c1, c2 = st.columns(2)
    with c1:
        profile = st.selectbox("Profil du combiné", ["Prudent", "Équilibré", "Audacieux"])
    with c2:
        legs = st.slider("Nombre de sélections maximum", 2, 4, 3)
    if st.button("✨ Générer les combinés", type="primary", use_container_width=True):
        combos = {}
        for level in ["Prudent", "Équilibré", "Audacieux"]:
            picks = make_picks(pool, level, legs)
            combos[level] = picks
        st.session_state["last_combos"] = combos
        st.session_state["last_combo_date"] = selected_date.isoformat()

    combos = st.session_state.get("last_combos", {})
    if combos:
        for level in ["Prudent", "Équilibré", "Audacieux"]:
            picks = combos.get(level, [])
            if level != profile:
                continue
            st.markdown(f"### {level}")
            if len(picks) < 2:
                st.info("Pas assez de sélections distinctes avec les seuils actuels. Essaie une autre date, plus de championnats ou un autre profil.")
            else:
                for i, pick in enumerate(picks, 1):
                    with st.container(border=True):
                        left, right = st.columns([4, 1])
                        left.markdown(f"**{i}. {pick['fixture']}**")
                        left.caption(f"{pick['competition']} · {pick['market']}")
                        right.metric("Probabilité estimée", pct(pick["p"]))
                st.divider()
                st.metric("Probabilité théorique que toutes passent", pct(combo_probability(picks)))
                st.caption("Calcul simplifié supposant les sélections indépendantes. Le résultat réel peut différer et cette valeur n'est pas une garantie.")
    else:
        st.info("Choisis un profil puis clique sur « Générer les combinés ».")

# ----------------------------- HISTORY -----------------------------
elif page == "📈 Historique":
    st.markdown('<div class="section-label">Résultats et suivi</div>', unsafe_allow_html=True)
    st.caption("Cette page montre les matchs terminés accessibles pour la période sélectionnée. Elle ne prétend pas suivre des paris qui n'ont pas été enregistrés.")
    if finished_analyses:
        rows = []
        for a in finished_analyses:
            rows.append({
                "Date": a["kickoff"][:10] if a["kickoff"] else "—",
                "Championnat": a["competition"],
                "Match": f'{a["home"]} – {a["away"]}',
                "Score": score_text(a),
                "Probabilité la plus élevée": max(a["markets"].items(), key=lambda x: x[1])[0],
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("Aucun match terminé trouvé pour la période sélectionnée. Choisis une date passée dans la barre latérale pour consulter les résultats disponibles.")

st.divider()
st.markdown(
    '<div class="small-note">FOOT AI PRO · Estimations statistiques issues d’un modèle simplifié de Poisson. '
    'Cette version n’intègre pas automatiquement les blessures, les compositions probables ni les nouvelles de dernière minute. '
    'Les résultats passés ne garantissent pas les résultats futurs.</div>',
    unsafe_allow_html=True,
)