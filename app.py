import math
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="Foot AI Pro V2",
    page_icon="⚽",
    layout="wide"
)

API_URL = "https://api.football-data.org/v4"
DB_PATH = "foot_ai_pro.db"

COMPETITIONS = {
    "Ligue 1 🇫🇷": "FL1",
    "Premier League 🏴": "PL",
    "Liga 🇪🇸": "PD",
    "Serie A 🇮🇹": "SA",
    "Bundesliga 🇩🇪": "BL1",
}

st.title("⚽ FOOT AI PRO")
st.subheader("🤖 Football Analytics — Version 2")
st.caption(
    "Matchs, forme récente, probabilités et scores estimés."
)


# --------------------------------------------------
# BASE DE DONNÉES
# --------------------------------------------------

def initialiser_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pronostics (
                match_id INTEGER PRIMARY KEY,
                competition TEXT,
                date_match TEXT,
                domicile TEXT,
                exterieur TEXT,
                proba_domicile REAL,
                proba_nul REAL,
                proba_exterieur REAL,
                score_prevu TEXT,
                cree_le TEXT
            )
        """)


def sauvegarder_pronostic(match, analyse):
    score = analyse["scores"][0]
    score_prevu = (
        f"{score['domicile']}-{score['exterieur']}"
    )

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO pronostics (
                match_id, competition, date_match,
                domicile, exterieur,
                proba_domicile, proba_nul,
                proba_exterieur, score_prevu, cree_le
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            match["id"],
            match["competition"],
            match["date"],
            match["domicile"],
            match["exterieur"],
            analyse["domicile"] * 100,
            analyse["nul"] * 100,
            analyse["exterieur"] * 100,
            score_prevu,
            datetime.now().isoformat(timespec="seconds")
        ))


def lire_historique():
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(
            "SELECT * FROM pronostics ORDER BY date_match DESC",
            conn
        )


initialiser_db()


# --------------------------------------------------
# API FOOTBALL-DATA
# --------------------------------------------------

try:
    TOKEN = st.secrets["FOOTBALL_DATA_TOKEN"]
except Exception:
    st.error(
        "Clé API absente. Ajoute FOOTBALL_DATA_TOKEN "
        "dans les Secrets de Streamlit."
    )
    st.stop()


def api_get(endpoint, params=None):
    try:
        response = requests.get(
            f"{API_URL}/{endpoint}",
            headers={"X-Auth-Token": TOKEN},
            params=params,
            timeout=20
        )

        if response.status_code == 429:
            st.warning(
                "Limite de requêtes API atteinte. "
                "Attends un peu avant de recommencer."
            )
            return None

        if response.status_code != 200:
            st.warning(
                f"API : erreur HTTP {response.status_code}. "
                "La compétition ou les données demandées "
                "ne sont peut-être pas accessibles avec ton offre."
            )
            return None

        return response.json()

    except requests.RequestException:
        st.warning("Impossible de joindre l'API football.")
        return None


@st.cache_data(ttl=900)
def charger_matchs(code, debut, fin, statut):
    return api_get(
        f"competitions/{code}/matches",
        {
            "dateFrom": debut,
            "dateTo": fin,
            "status": statut
        }
    )


@st.cache_data(ttl=1800)
def charger_classement(code):
    return api_get(f"competitions/{code}/standings")


# --------------------------------------------------
# HISTORIQUE DES MATCHS ET FORME RÉCENTE
# --------------------------------------------------

def resultat_match(match):
    score = match.get("score", {}).get("fullTime", {})

    domicile = score.get("home")
    exterieur = score.get("away")

    if domicile is None or exterieur is None:
        return None

    return domicile, exterieur


def calculer_forme(equipe_id, matchs_termines):
    rencontres = []

    for match in matchs_termines:
        home_id = match.get("homeTeam", {}).get("id")
        away_id = match.get("awayTeam", {}).get("id")

        if equipe_id not in (home_id, away_id):
            continue

        score = resultat_match(match)

        if score is None:
            continue

        buts_d, buts_e = score

        if home_id == equipe_id:
            marques, encaisses = buts_d, buts_e
        else:
            marques, encaisses = buts_e, buts_d

        if marques > encaisses:
            resultat = "V"
        elif marques == encaisses:
            resultat = "N"
        else:
            resultat = "D"

        rencontres.append({
            "date": match.get("utcDate", ""),
            "buts_marques": marques,
            "buts_encaisses": encaisses,
            "resultat": resultat
        })

    rencontres.sort(
        key=lambda x: x["date"],
        reverse=True
    )

    cinq = rencontres[:5]

    if not cinq:
        return {
            "matchs": 0,
            "forme": "Indisponible",
            "buts_marques": 1.25,
            "buts_encaisses": 1.25
        }

    return {
        "matchs": len(cinq),
        "forme": " ".join(x["resultat"] for x in cinq),
        "buts_marques": (
            sum(x["buts_marques"] for x in cinq) / len(cinq)
        ),
        "buts_encaisses": (
            sum(x["buts_encaisses"] for x in cinq) / len(cinq)
        )
    }


# --------------------------------------------------
# MODÈLE DE POISSON
# --------------------------------------------------

def poisson(lam, buts):
    return (
        math.exp(-lam)
        * (lam ** buts)
        / math.factorial(buts)
    )


def analyser_match(equipe_d, equipe_e, forme_d, forme_e):
    # Mélange des buts récents avec une moyenne générale.
    # Si les cinq derniers matchs sont indisponibles,
    # les valeurs de repli sont utilisées.

    attaque_d = (
        0.65 * forme_d["buts_marques"]
        + 0.35 * 1.35
    )

    defense_d = (
        0.65 * forme_d["buts_encaisses"]
        + 0.35 * 1.25
    )

    attaque_e = (
        0.65 * forme_e["buts_marques"]
        + 0.35 * 1.20
    )

    defense_e = (
        0.65 * forme_e["buts_encaisses"]
        + 0.35 * 1.30
    )

    lambda_d = max(
        0.15,
        min(4.5, (attaque_d + defense_e) / 2 * 1.10)
    )

    lambda_e = max(
        0.15,
        min(4.5, (attaque_e + defense_d) / 2 * 0.95)
    )

    scores = []

    for buts_d in range(8):
        for buts_e in range(8):
            probabilite = (
                poisson(lambda_d, buts_d)
                * poisson(lambda_e, buts_e)
            )

            scores.append({
                "domicile": buts_d,
                "exterieur": buts_e,
                "probabilite": probabilite
            })

    total = sum(s["probabilite"] for s in scores)

    if total <= 0:
        return None

    for score in scores:
        score["probabilite"] /= total

    p_d = sum(
        s["probabilite"] for s in scores
        if s["domicile"] > s["exterieur"]
    )

    p_n = sum(
        s["probabilite"] for s in scores
        if s["domicile"] == s["exterieur"]
    )

    p_e = sum(
        s["probabilite"] for s in scores
        if s["domicile"] < s["exterieur"]
    )

    scores.sort(
        key=lambda s: s["probabilite"],
        reverse=True
    )

    return {
        "domicile": p_d,
        "nul": p_n,
        "exterieur": p_e,
        "scores": scores[:5],
        "buts_d": lambda_d,
        "buts_e": lambda_e,
        "favori": max(p_d, p_n, p_e)
    }


# --------------------------------------------------
# NAVIGATION
# --------------------------------------------------

page = st.sidebar.radio(
    "Navigation",
    [
        "🏠 Accueil",
        "⚽ Matchs et pronostics",
        "📊 Analyse détaillée",
        "📚 Historique"
    ]
)


# --------------------------------------------------
# ACCUEIL
# --------------------------------------------------

if page == "🏠 Accueil":
    st.header("Bienvenue sur Foot AI Pro")

    st.write(
        "Analyse les matchs à venir, compare la forme récente "
        "des équipes et examine les scores les plus probables."
    )

    st.info(
        "Ouvre Matchs et pronostics pour charger les rencontres "
        "des sept prochains jours."
    )

    st.warning(
        "Les probabilités sont des estimations expérimentales. "
        "Elles ne garantissent aucun résultat."
    )


# --------------------------------------------------
# MATCHS ET PRONOSTICS
# --------------------------------------------------

elif page == "⚽ Matchs et pronostics":
    competition_nom = st.selectbox(
        "Championnat",
        list(COMPETITIONS.keys())
    )

    code = COMPETITIONS[competition_nom]

    if st.button("🔄 Charger les matchs des 7 prochains jours"):
        debut = date.today()
        fin = debut + timedelta(days=7)

        debut_historique = debut - timedelta(days=90)

        with st.spinner("Récupération des matchs et résultats..."):
            futurs = charger_matchs(
                code,
                debut.isoformat(),
                fin.isoformat(),
                "SCHEDULED"
            )

            passes = charger_matchs(
                code,
                debut_historique.isoformat(),
                debut.isoformat(),
                "FINISHED"
            )

        if futurs is None:
            st.error(
                "Impossible de récupérer les prochains matchs."
            )

        else:
            matchs_passes = (
                passes.get("matches", [])
                if passes else []
            )

            matchs_futurs = futurs.get("matches", [])

            resultats = []

            barre = st.progress(0)

            for index, match in enumerate(matchs_futurs):
                id_d = match.get("homeTeam", {}).get("id")
                id_e = match.get("awayTeam", {}).get("id")

                forme_d = calculer_forme(
                    id_d, matchs_passes
                )

                forme_e = calculer_forme(
                    id_e, matchs_passes
                )

                analyse = analyser_match(
                    id_d,
                    id_e,
                    forme_d,
                    forme_e
                )

                if analyse is None:
                    continue

                resultats.append({
                    "id": match["id"],
                    "competition": competition_nom,
                    "date": match.get("utcDate", ""),
                    "domicile": match["homeTeam"].get("name", ""),
                    "exterieur": match["awayTeam"].get("name", ""),
                    "forme_d": forme_d,
                    "forme_e": forme_e,
                    "analyse": analyse
                })

                barre.progress(
                    (index + 1) / max(len(matchs_futurs), 1)
                )

            resultats.sort(
                key=lambda x: x["analyse"]["favori"],
                reverse=True
            )

            st.session_state["matchs"] = resultats

            st.success(
                f"{len(resultats)} match(s) analysé(s)."
            )

    matchs = st.session_state.get("matchs", [])

    if matchs:
        st.subheader("🏆 Classement des rencontres")

        for numero, match in enumerate(matchs, start=1):
            a = match["analyse"]

            with st.expander(
                f"#{numero} — {match['domicile']} "
                f"contre {match['exterieur']}"
            ):
                st.write(f"Date : {match['date']}")

                c1, c2, c3 = st.columns(3)

                c1.metric(
                    "Victoire domicile",
                    f"{a['domicile'] * 100:.1f} %"
                )

                c2.metric(
                    "Match nul",
                    f"{a['nul'] * 100:.1f} %"
                )

                c3.metric(
                    "Victoire extérieur",
                    f"{a['exterieur'] * 100:.1f} %"
                )

                st.write("### 📊 Forme récente")

                c1, c2 = st.columns(2)

                with c1:
                    st.write(f"**{match['domicile']}**")
                    st.write(
                        f"Résultats : {match['forme_d']['forme']}"
                    )
                    st.write(
                        "Buts marqués par match : "
                        f"{match['forme_d']['buts_marques']:.2f}"
                    )

                with c2:
                    st.write(f"**{match['exterieur']}**")
                    st.write(
                        f"Résultats : {match['forme_e']['forme']}"
                    )
                    st.write(
                        "Buts marqués par match : "
                        f"{match['forme_e']['buts_marques']:.2f}"
                    )

                st.write("### 🎯 Top 5 des scores probables")

                for score in a["scores"]:
                    st.write(
                        f"⚽ {score['domicile']}-"
                        f"{score['exterieur']} : "
                        f"{score['probabilite'] * 100:.2f} %"
                    )

                st.caption(
                    "Le classement trie les matchs selon la "
                    "probabilité du résultat individuel le plus "
                    "probable. Cela ne mesure pas la probabilité "
                    "de gagner un pari."
                )

                if st.button(
                    "💾 Enregistrer le pronostic",
                    key=f"save_{match['id']}"
                ):
                    sauvegarder_pronostic(match, a)
                    st.success("Pronostic enregistré dans l'historique.")


# --------------------------------------------------
# ANALYSE DETAILLEE
# --------------------------------------------------

elif page == "📊 Analyse détaillée":
    matchs = st.session_state.get("matchs", [])

    if not matchs:
        st.info(
            "Charge d'abord les matchs dans la section "
            "Matchs et pronostics."
        )

    else:
        choix = st.selectbox(
            "Choisir une rencontre",
            [
                f"{m['domicile']} - {m['exterieur']}"
                for m in matchs
            ]
        )

        match = next(
            m for m in matchs
            if f"{m['domicile']} - {m['exterieur']}" == choix
        )

        a = match["analyse"]

        st.header(choix)

        st.write("### Probabilités du modèle")

        st.progress(
            a["domicile"],
            text=f"Victoire à domicile : {a['domicile'] * 100:.1f} %"
        )

        st.progress(
            a["nul"],
            text=f"Match nul : {a['nul'] * 100:.1f} %"
        )

        st.progress(
            a["exterieur"],
            text=f"Victoire à l'extérieur : {a['exterieur'] * 100:.1f} %"
        )

        st.write("### Buts moyens estimés")

        c1, c2 = st.columns(2)

        c1.metric(match["domicile"], f"{a['buts_d']:.2f}")
        c2.metric(match["exterieur"], f"{a['buts_e']:.2f}")

        st.write("### Scores les plus probables")

        st.dataframe(
            pd.DataFrame([
                {
                    "Score": (
                        f"{s['domicile']}-{s['exterieur']}"
                    ),
                    "Probabilité": (
                        f"{s['probabilite'] * 100:.2f} %"
                    )
                }
                for s in a["scores"]
            ]),
            use_container_width=True
        )


# --------------------------------------------------
# HISTORIQUE
# --------------------------------------------------

elif page == "📚 Historique":
    st.header("📚 Historique des pronostics")

    try:
        historique = lire_historique()

        if historique.empty:
            st.info("Aucun pronostic enregistré pour le moment.")

        else:
            st.dataframe(
                historique,
                use_container_width=True
            )

            csv = historique.to_csv(
                index=False
            ).encode("utf-8")

            st.download_button(
                "📥 Télécharger l'historique CSV",
                csv,
                file_name="historique_foot_ai_pro.csv",
                mime="text/csv"
            )

    except sqlite3.Error:
        st.error("Impossible de lire l'historique.")

st.divider()

st.caption(
    "Foot AI Pro V2 — Outil expérimental d'analyse statistique. "
    "Les probabilités ne garantissent aucun résultat sportif."
)