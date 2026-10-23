import os
import math
import sqlite3
from datetime import date, datetime, timedelta
from itertools import combinations

import requests
import streamlit as st

# ============================================================
# FOOT AI PRO V5+ — base V5 conservée + nouvelles fonctions
# API : football-data.org v4
# ============================================================

st.set_page_config(
    page_title="FOOT AI PRO V5+",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_BASE = "https://api.football-data.org/v4"
DB_PATH = "foot_ai_pro_history.db"

COMPETITIONS = {
    "Ligue 1": "FL1",
    "Premier League": "PL",
    "Liga": "PD",
    "Bundesliga": "BL1",
    "Serie A": "SA",
    "Ligue des Champions": "CL",
}

STATUSES_LIVE = {"IN_PLAY", "PAUSED", "LIVE"}
STATUSES_FINISHED = {"FINISHED"}
MAX_GOALS = 7


def get_api_key():
    try:
        key = st.secrets.get("FOOTBALL_DATA_API_KEY", "")
        if key:
            return str(key).strip()
    except Exception:
        pass
    return os.getenv("FOOTBALL_DATA_API_KEY", "").strip()


API_KEY = get_api_key()


@st.cache_data(ttl=300, show_spinner=False)
def api_get(endpoint, params=None):
    """Appel API avec cache court et messages d'erreur lisibles."""
    if not API_KEY:
        return None, (
            "Clé API manquante. Dans Streamlit, ouvre "
            "Settings / Secrets et ajoute FOOTBALL_DATA_API_KEY."
        )
    try:
        response = requests.get(
            f"{API_BASE}/{endpoint}",
            headers={"X-Auth-Token": API_KEY},
            params=params or {},
            timeout=20,
        )
        if response.status_code == 200:
            return response.json(), None
        if response.status_code == 401:
            return None, "Clé API invalide. Vérifie FOOTBALL_DATA_API_KEY dans Secrets."
        if response.status_code == 403:
            return None, (
                "Accès refusé par football-data.org. Ton offre API ne permet peut-être "
                "pas cette compétition ou cette saison."
            )
        if response.status_code == 429:
            return None, (
                "Limite de requêtes API atteinte. Attends un peu puis réessaie. "
                "Le cache aide à réduire les appels."
            )
        return None, f"Erreur API {response.status_code} : {response.text[:250]}"
    except requests.RequestException as exc:
        return None, f"Erreur de connexion : {exc}"


def poisson(lam, k):
    if lam < 0:
        return 0.0
    try:
        return math.exp(-lam) * (lam ** k) / math.factorial(k)
    except (OverflowError, ValueError):
        return 0.0


def score_probabilities(home_lambda, away_lambda):
    matrix = {}
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            matrix[(h, a)] = poisson(home_lambda, h) * poisson(away_lambda, a)
    total = sum(matrix.values())
    if total > 0:
        matrix = {score: prob / total for score, prob in matrix.items()}
    return matrix


def get_score_probabilities(match):
    score = match.get("score", {}).get("fullTime", {})
    home = score.get("home")
    away = score.get("away")
    if home is None or away is None:
        return "—"
    return f"{home} - {away}"


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS predictions (
                match_id INTEGER PRIMARY KEY,
                match_date TEXT,
                competition TEXT,
                home_team TEXT,
                away_team TEXT,
                market TEXT,
                predicted_probability REAL,
                predicted_pick TEXT,
                actual_home INTEGER,
                actual_away INTEGER,
                settled INTEGER DEFAULT 0,
                created_at TEXT
            )
            """
        )
        conn.commit()


def save_prediction(match, competition_name, market, probability, pick):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO predictions
            (match_id, match_date, competition, home_team, away_team,
             market, predicted_probability, predicted_pick, settled, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                match.get("id"),
                match.get("utcDate", ""),
                competition_name,
                match.get("homeTeam", {}).get("name", "Domicile"),
                match.get("awayTeam", {}).get("name", "Extérieur"),
                market,
                float(probability),
                pick,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()


def load_history(limit=300):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM predictions ORDER BY match_date DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def settle_history(competition_codes):
    """Actualise les résultats des pronostics sauvegardés, avec peu d'appels."""
    history = load_history(500)
    pending = [row for row in history if not row.get("settled")]
    if not pending:
        return 0, None

    # Les résultats sont récupérés par compétition et par plage de dates,
    # au lieu de faire un appel par match.
    updated = 0
    errors = []
    grouped = {}
    for row in pending:
        grouped.setdefault(row["competition"], []).append(row)

    for comp_name, rows in grouped.items():
        comp_code = COMPETITIONS.get(comp_name)
        if not comp_code or comp_code not in competition_codes:
            continue
        dates = []
        for row in rows:
            try:
                dates.append(datetime.fromisoformat(row["match_date"].replace("Z", "+00:00")).date())
            except Exception:
                pass
        if not dates:
            continue
        start = max(min(dates), date.today() - timedelta(days=45))
        end = min(max(dates), date.today())
        if start > end:
            continue
        data, err = api_get(
            f"competitions/{comp_code}/matches",
            {"dateFrom": start.isoformat(), "dateTo": end.isoformat()},
        )
        if err:
            errors.append(err)
            continue
        actual_matches = {m.get("id"): m for m in data.get("matches", [])}
        with sqlite3.connect(DB_PATH) as conn:
            for row in rows:
                match = actual_matches.get(row["match_id"])
                if not match or match.get("status") != "FINISHED":
                    continue
                full = match.get("score", {}).get("fullTime", {})
                h, a = full.get("home"), full.get("away")
                if h is None or a is None:
                    continue
                conn.execute(
                    "UPDATE predictions SET actual_home=?, actual_away=?, settled=1 WHERE match_id=?",
                    (int(h), int(a), row["match_id"]),
                )
                updated += 1
            conn.commit()
    return updated, (errors[0] if errors else None)


@st.cache_data(ttl=21600, show_spinner=False)
def get_team_stats(team_id, before_date):
    """Forme récente : jusqu'à 10 matchs terminés dans les 180 jours précédents."""
    end_date = date.fromisoformat(before_date)
    start_date = end_date - timedelta(days=180)
    data, error = api_get(
        f"teams/{team_id}/matches",
        {
            "dateFrom": start_date.isoformat(),
            "dateTo": end_date.isoformat(),
            "status": "FINISHED",
            "limit": 10,
        },
    )
    if error or not data:
        return {
            "goals_for": 1.25,
            "goals_against": 1.25,
            "points": 0,
            "form": "Données insuffisantes",
            "matches": 0,
            "warning": error or "Historique indisponible",
        }

    matches = data.get("matches", [])[-10:]
    goals_for = goals_against = points = played = 0
    form = []
    for item in matches:
        home_id = item.get("homeTeam", {}).get("id")
        away_id = item.get("awayTeam", {}).get("id")
        full = item.get("score", {}).get("fullTime", {})
        hg, ag = full.get("home"), full.get("away")
        if hg is None or ag is None:
            continue
        if team_id == home_id:
            gf, ga = hg, ag
        elif team_id == away_id:
            gf, ga = ag, hg
        else:
            continue
        goals_for += gf
        goals_against += ga
        played += 1
        if gf > ga:
            points += 3
            form.append("V")
        elif gf == ga:
            points += 1
            form.append("N")
        else:
            form.append("D")

    if played == 0:
        return {
            "goals_for": 1.25,
            "goals_against": 1.25,
            "points": 0,
            "form": "Données insuffisantes",
            "matches": 0,
            "warning": "Aucun match récent exploitable",
        }
    return {
        "goals_for": goals_for / played,
        "goals_against": goals_against / played,
        "points": points,
        "form": " ".join(form[-5:]),
        "matches": played,
        "warning": None,
    }


def calculate_predictions(home_stats, away_stats):
    # Mélange attaque propre et défense adverse, puis correction domicile.
    home_attack = home_stats["goals_for"]
    away_defence = away_stats["goals_against"]
    away_attack = away_stats["goals_for"]
    home_defence = home_stats["goals_against"]

    home_lambda = max(0.15, min(4.2, 0.58 * home_attack + 0.42 * away_defence + 0.18))
    away_lambda = max(0.15, min(4.2, 0.58 * away_attack + 0.42 * home_defence))
    matrix = score_probabilities(home_lambda, away_lambda)

    home_win = sum(p for (h, a), p in matrix.items() if h > a)
    draw = sum(p for (h, a), p in matrix.items() if h == a)
    away_win = sum(p for (h, a), p in matrix.items() if h < a)
    total_goals = lambda predicate: sum(
        p for (h, a), p in matrix.items() if predicate(h + a)
    )
    btts_yes = sum(p for (h, a), p in matrix.items() if h > 0 and a > 0)

    markets = {
        "Victoire domicile": home_win,
        "Match nul": draw,
        "Victoire extérieur": away_win,
        "1X (domicile ou nul)": home_win + draw,
        "X2 (extérieur ou nul)": away_win + draw,
        "+0.5 but": total_goals(lambda g: g > 0),
        "+1.5 buts": total_goals(lambda g: g > 1),
        "+2.5 buts": total_goals(lambda g: g > 2),
        "+3.5 buts": total_goals(lambda g: g > 3),
        "-2.5 buts": total_goals(lambda g: g < 3),
        "-3.5 buts": total_goals(lambda g: g < 4),
        "Les deux marquent : OUI": btts_yes,
        "Les deux marquent : NON": 1 - btts_yes,
    }
    top_scores = sorted(matrix.items(), key=lambda item: item[1], reverse=True)[:5]
    return {
        "home_lambda": home_lambda,
        "away_lambda": away_lambda,
        "home_win": home_win,
        "draw": draw,
        "away_win": away_win,
        "markets": markets,
        "top_scores": top_scores,
        "matrix": matrix,
    }


def pct(value):
    return f"{max(0, min(1, value)) * 100:.1f} %"


def match_date_local(raw):
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%d/%m/%Y %H:%M")
    except Exception:
        return raw or "Date inconnue"


def get_market_pick(predictions):
    # Choix automatique du marché le plus probable, parmi les marchés affichés.
    markets = predictions["markets"]
    market = max(markets, key=markets.get)
    return market, markets[market]


def risk_label(probability):
    if probability >= 0.70:
        return "Plutôt faible"
    if probability >= 0.55:
        return "Modéré"
    if probability >= 0.40:
        return "Élevé"
    return "Très élevé"


def settle_pick(row):
    h, a = row.get("actual_home"), row.get("actual_away")
    market, pick = row.get("market", ""), row.get("predicted_pick", "")
    if h is None or a is None:
        return None
    if market == "Victoire domicile":
        return h > a
    if market == "Match nul":
        return h == a
    if market == "Victoire extérieur":
        return h < a
    if market == "1X (domicile ou nul)":
        return h >= a
    if market == "X2 (extérieur ou nul)":
        return h <= a
    goals = h + a
    if market == "+0.5 but":
        return goals > 0
    if market == "+1.5 buts":
        return goals > 1
    if market == "+2.5 buts":
        return goals > 2
    if market == "+3.5 buts":
        return goals > 3
    if market == "-2.5 buts":
        return goals < 3
    if market == "-3.5 buts":
        return goals < 4
    if market == "Les deux marquent : OUI":
        return h > 0 and a > 0
    if market == "Les deux marquent : NON":
        return h == 0 or a == 0
    return None


init_db()

st.title("⚽ FOOT AI PRO")
st.caption("Version basée sur ton ancienne V5 : mêmes championnats et même clé API, avec classement, combinés et historique.")

with st.sidebar:
    st.header("⚙️ Paramètres")
    selected_competitions = st.multiselect(
        "Championnats",
        options=list(COMPETITIONS.keys()),
        default=list(COMPETITIONS.keys()),
    )
    selected_date = st.date_input("Date des matchs", value=date.today())
    max_matches = st.slider(
        "Nombre maximum de matchs à analyser",
        min_value=2,
        max_value=20,
        value=10,
        help="Réduit les appels à l'API. Les statistiques d'équipes sont mises en cache.",
    )
    st.info("Pour économiser ta limite API, l'analyse détaillée se lance uniquement quand tu appuies sur le bouton.")
    if st.button("🔄 Vider le cache API"):
        api_get.clear()
        get_team_stats.clear()
        st.success("Cache vidé. Les prochains chargements feront de nouveaux appels API.")

if not API_KEY:
    st.error("🔑 Clé API manquante.")
    st.markdown(
        "Dans les Secrets de ton application Streamlit, ajoute exactement :\n\n"
        "```toml\nFOOTBALL_DATA_API_KEY = \"TA_CLE_API\"\n```"
    )
    st.stop()

if not selected_competitions:
    st.warning("Choisis au moins un championnat dans le menu à gauche.")
    st.stop()

tab_matches, tab_analysis, tab_combos, tab_history = st.tabs(
    ["📅 Matchs", "🤖 Analyse IA & classement", "🎯 Combinés", "📈 Historique"]
)

# Chargement léger : seulement la liste des matchs, sans statistiques des équipes.
all_matches = []
api_errors = []
with st.spinner("Récupération des matchs..."):
    for comp_name in selected_competitions:
        comp_code = COMPETITIONS[comp_name]
        data, error = api_get(
            f"competitions/{comp_code}/matches",
            {
                "dateFrom": selected_date.isoformat(),
                "dateTo": selected_date.isoformat(),
            },
        )
        if error:
            api_errors.append(f"{comp_name} : {error}")
            continue
        for match in data.get("matches", []):
            match["_competition_name"] = comp_name
            all_matches.append(match)

all_matches.sort(key=lambda m: m.get("utcDate", ""))

with tab_matches:
    st.subheader(f"Matchs du {selected_date.strftime('%d/%m/%Y')}")
    if api_errors:
        for error in api_errors:
            st.warning(error)
    if not all_matches:
        st.info(
            "Aucun match trouvé pour cette date dans les compétitions accessibles par ta clé API. "
            "Essaie une autre date ou vérifie les compétitions autorisées par ton offre."
        )
    else:
        st.caption(f"{len(all_matches)} match(s) récupéré(s).")
        for match in all_matches:
            home = match.get("homeTeam", {}).get("name", "Domicile")
            away = match.get("awayTeam", {}).get("name", "Extérieur")
            status = match.get("status", "SCHEDULED")
            score = get_score_probabilities(match)
            comp = match.get("_competition_name", "")
            with st.container(border=True):
                col1, col2, col3 = st.columns([3, 2, 2])
                with col1:
                    st.markdown(f"**{home} — {away}**")
                    st.caption(f"{comp} • {match_date_local(match.get('utcDate', ''))}")
                with col2:
                    st.write(f"Statut : {status}")
                with col3:
                    st.write(f"Score : {score}")

    st.divider()
    st.caption("L'analyse détaillée et les prédictions se trouvent dans l'onglet « Analyse IA & classement ».")

with tab_analysis:
    st.subheader("Analyse détaillée des matchs")
    st.write(
        "Probabilités estimées à partir des derniers résultats disponibles. "
        "Ce sont des estimations statistiques, pas des garanties."
    )
    eligible_matches = [
        m for m in all_matches
        if m.get("status") not in STATUSES_FINISHED
        and m.get("homeTeam", {}).get("id")
        and m.get("awayTeam", {}).get("id")
    ]
    if len(eligible_matches) > max_matches:
        st.info(
            f"{len(eligible_matches)} matchs disponibles. Pour limiter les appels, "
            f"seuls les {max_matches} premiers seront analysés."
        )
    matches_to_analyze = eligible_matches[:max_matches]
    run_analysis = st.button("🚀 Analyser les matchs", type="primary")
    if run_analysis:
        results = []
        with st.spinner("Analyse des équipes et calcul des probabilités..."):
            for match in matches_to_analyze:
                home_team = match.get("homeTeam", {})
                away_team = match.get("awayTeam", {})
                raw_date = match.get("utcDate", "")[:10]
                try:
                    match_day = date.fromisoformat(raw_date)
                except Exception:
                    match_day = selected_date
                before = match_day.isoformat()
                home_stats = get_team_stats(home_team["id"], before)
                away_stats = get_team_stats(away_team["id"], before)
                prediction = calculate_predictions(home_stats, away_stats)
                best_market, best_probability = get_market_pick(prediction)
                best_pick = best_market
                save_prediction(
                    match,
                    match.get("_competition_name", ""),
                    best_market,
                    best_probability,
                    best_pick,
                )
                results.append({
                    "match": match,
                    "home_stats": home_stats,
                    "away_stats": away_stats,
                    "prediction": prediction,
                    "best_market": best_market,
                    "best_probability": best_probability,
                })
        st.session_state["foot_ai_results"] = results

    results = st.session_state.get("foot_ai_results", [])
    if results:
        ranked = sorted(results, key=lambda r: r["best_probability"], reverse=True)
        st.markdown("### 🏆 Classement des pronostics automatiques")
        for index, item in enumerate(ranked, start=1):
            match = item["match"]
            pred = item["prediction"]
            home = match.get("homeTeam", {}).get("name", "Domicile")
            away = match.get("awayTeam", {}).get("name", "Extérieur")
            with st.container(border=True):
                st.markdown(f"**#{index} — {home} vs {away}**")
                st.caption(
                    f"{match.get('_competition_name', '')} • "
                    f"{match_date_local(match.get('utcDate', ''))}"
                )
                c1, c2, c3 = st.columns(3)
                c1.metric("Victoire domicile", pct(pred["home_win"]))
                c2.metric("Match nul", pct(pred["draw"]))
                c3.metric("Victoire extérieur", pct(pred["away_win"]))
                st.markdown(
                    f"**Choix automatique : {item['best_market']} — "
                    f"{pct(item['best_probability'])}**"
                )
                st.caption(f"Niveau de risque indicatif : {risk_label(item['best_probability'])}")

                markets = pred["markets"]
                market_cols = st.columns(3)
                for i, (market, probability) in enumerate(markets.items()):
                    market_cols[i % 3].write(f"**{market}** : {pct(probability)}")

                scores = [
                    (f"{h}-{a}", p) for (h, a), p in pred["top_scores"]
                ]
                st.write("**Scores exacts les plus probables :** " + " • ".join(
                    f"{score} ({pct(prob)})" for score, prob in scores
                ))
                st.write(
                    f"**Buts attendus (modèle) :** {pred['home_lambda']:.2f} - "
                    f"{pred['away_lambda']:.2f}"
                )
                form_col1, form_col2 = st.columns(2)
                form_col1.write(
                    f"Forme {home} : {item['home_stats']['form']} "
                    f"({item['home_stats']['matches']} matchs)"
                )
                form_col2.write(
                    f"Forme {away} : {item['away_stats']['form']} "
                    f"({item['away_stats']['matches']} matchs)"
                )
                if item["home_stats"].get("warning") or item["away_stats"].get("warning"):
                    st.warning(
                        "Données historiques limitées pour au moins une équipe : "
                        "la prédiction est moins fiable."
                    )
    else:
        st.info("Appuie sur « Analyser les matchs » pour lancer les calculs et afficher le classement.")

with tab_combos:
    st.subheader("Combinaisons automatiques")
    st.write(
        "Les combinés sont construits avec les choix les plus probables des matchs analysés. "
        "La probabilité combinée est une approximation par multiplication des probabilités."
    )
    results = st.session_state.get("foot_ai_results", [])
    legs = st.selectbox("Nombre de matchs dans le combiné", [2, 3, 4], index=0)
    max_combos = st.slider("Nombre de propositions", 1, 10, 5)
    if len(results) < legs:
        st.info(
            f"Il faut analyser au moins {legs} matchs dans l'onglet « Analyse IA & classement » "
            "pour construire ce type de combiné."
        )
    else:
        ranked = sorted(results, key=lambda r: r["best_probability"], reverse=True)
        # Limiter le nombre de candidats pour ne pas afficher des milliers de combinaisons.
        candidates = ranked[:min(len(ranked), 12)]
        combo_rows = []
        for combo in combinations(candidates, legs):
            probability = 1.0
            selections = []
            for item in combo:
                probability *= item["best_probability"]
                match = item["match"]
                selections.append(
                    f"{match.get('homeTeam', {}).get('name', 'Domicile')} vs "
                    f"{match.get('awayTeam', {}).get('name', 'Extérieur')} — "
                    f"{item['best_market']} ({pct(item['best_probability'])})"
                )
            combo_rows.append((probability, selections))
        combo_rows.sort(key=lambda row: row[0], reverse=True)
        if not combo_rows:
            st.info("Aucune combinaison disponible.")
        else:
            for idx, (probability, selections) in enumerate(combo_rows[:max_combos], start=1):
                with st.container(border=True):
                    st.markdown(f"**Combiné #{idx} — probabilité estimée : {pct(probability)}**")
                    st.caption(f"Risque indicatif : {risk_label(probability)}")
                    for selection in selections:
                        st.write("• " + selection)
            st.warning(
                "Une probabilité combinée faible est normale quand plusieurs matchs sont assemblés. "
                "Les résultats sportifs restent incertains ; ne considère pas ces calculs comme une garantie."
            )

with tab_history:
    st.subheader("Historique et résultats réels")
    col_sync, col_reload = st.columns([2, 1])
    with col_sync:
        sync_button = st.button("🔄 Vérifier les résultats des pronostics enregistrés")
    with col_reload:
        reload_button = st.button("Actualiser l'historique")
    if sync_button:
        with st.spinner("Vérification des résultats..."):
            updated, sync_error = settle_history(set(COMPETITIONS[c] for c in selected_competitions))
        if updated:
            st.success(f"{updated} résultat(s) actualisé(s).")
        else:
            st.info("Aucun nouveau résultat terminé trouvé dans les compétitions sélectionnées.")
        if sync_error:
            st.warning(sync_error)

    history = load_history()
    settled = [row for row in history if row.get("settled")]
    if settled:
        hits = sum(1 for row in settled if settle_pick(row) is True)
        hit_rate = hits / len(settled)
        m1, m2, m3 = st.columns(3)
        m1.metric("Pronostics évalués", len(settled))
        m2.metric("Pronostics corrects", hits)
        m3.metric("Taux de réussite", pct(hit_rate))
    else:
        st.info(
            "Pas encore de pronostics évalués. Analyse des matchs, puis reviens ici après "
            "les rencontres et appuie sur « Vérifier les résultats »."
        )

    if history:
        display_rows = []
        for row in history:
            result = "En attente"
            correct = None
            if row.get("settled"):
                correct = settle_pick(row)
                result = f"{row['actual_home']} - {row['actual_away']}"
            display_rows.append({
                "Date": match_date_local(row.get("match_date", "")),
                "Championnat": row.get("competition", ""),
                "Match": f"{row.get('home_team', '')} vs {row.get('away_team', '')}",
                "Pronostic enregistré": row.get("market", ""),
                "Probabilité au moment du choix": pct(row.get("predicted_probability") or 0),
                "Score réel": result,
                "Correct ?": ("Oui" if correct else "Non") if correct is not None else "—",
            })
        st.dataframe(display_rows, use_container_width=True, hide_index=True)
    else:
        st.caption("L'historique apparaîtra après le premier lancement d'analyse.")

st.divider()
st.caption()
    "FOOT AI PRO V5+ • Modèle Poisson simplifié. Les probabilités sont indicatives et "
    "dépendent des données accessibles via football-data.org. L'historique SQLite est local "
    "à l'instance Streamlit ; selon l'hébergement, il peut ne pas être conservé après un redéploiement."