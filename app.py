import math
import requests
import streamlit as st
import pandas as pd

from datetime import date, timedelta

st.set_page_config(
    page_title="Foot AI Pro",
    page_icon="⚽",
    layout="wide"
)

API_URL = "https://api.football-data.org/v4"

COMPETITIONS = {
    "Ligue 1 🇫🇷": "FL1",
    "Premier League 🏴": "PL",
    "Liga 🇪🇸": "PD",
    "Serie A 🇮🇹": "SA",
    "Bundesliga 🇩🇪": "BL1",
}

st.title("⚽ FOOT AI PRO")
st.subheader("🤖 Intelligence artificielle et pronostics")
st.caption("Analyse statistique expérimentale du football")

try:
    TOKEN = st.secrets["FOOTBALL_DATA_TOKEN"]
except Exception:
    st.error("Clé API manquante dans les Secrets de Streamlit.")
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
            st.error("Limite API atteinte. Réessaie plus tard.")
            return None

        if response.status_code != 200:
            st.error(
                f"Erreur API {response.status_code}. "
                "Vérifie les compétitions accessibles avec ton compte."
            )
            return None

        return response.json()

    except requests.RequestException:
        st.error("Impossible de contacter le service des matchs.")
        return None


@st.cache_data(ttl=900)
def charger_matchs(competition, debut, fin):
    return api_get(
        f"competitions/{competition}/matches",
        {
            "dateFrom": debut,
            "dateTo": fin,
            "status": "SCHEDULED"
        }
    )


@st.cache_data(ttl=900)
def charger_classement(competition):
    return api_get(f"competitions/{competition}/standings")


def poisson(lam, buts):
    return math.exp(-lam) * (lam ** buts) / math.factorial(buts)


def analyser_match(domicile, exterieur, classement):
    equipe_d = classement.get(domicile)
    equipe_e = classement.get(exterieur)

    if not equipe_d or not equipe_e:
        return None

    matchs_d = max(equipe_d["playedGames"], 1)
    matchs_e = max(equipe_e["playedGames"], 1)

    attaque_d = equipe_d["goalsFor"] / matchs_d
    defense_d = equipe_d["goalsAgainst"] / matchs_d

    attaque_e = equipe_e["goalsFor"] / matchs_e
    defense_e = equipe_e["goalsAgainst"] / matchs_e

    moyenne_d = (attaque_d + defense_e) / 2
    moyenne_e = (attaque_e + defense_d) / 2

    # Avantage théorique du terrain
    lambda_d = max(0.15, moyenne_d * 1.12)
    lambda_e = max(0.15, moyenne_e * 0.90)

    scores = []

    for buts_d in range(8):
        for buts_e in range(8):
            proba = (
                poisson(lambda_d, buts_d)
                * poisson(lambda_e, buts_e)
            )

            scores.append({
                "domicile": buts_d,
                "exterieur": buts_e,
                "probabilite": proba
            })

    total = sum(s["probabilite"] for s in scores)

    if total == 0:
        return None

    for score in scores:
        score["probabilite"] /= total

    p_domicile = sum(
        s["probabilite"] for s in scores
        if s["domicile"] > s["exterieur"]
    )

    p_nul = sum(
        s["probabilite"] for s in scores
        if s["domicile"] == s["exterieur"]
    )

    p_exterieur = sum(
        s["probabilite"] for s in scores
        if s["domicile"] < s["exterieur"]
    )

    scores.sort(
        key=lambda s: s["probabilite"],
        reverse=True
    )

    return {
        "domicile": p_domicile,
        "nul": p_nul,
        "exterieur": p_exterieur,
        "scores": scores[:5],
        "lambda_d": lambda_d,
        "lambda_e": lambda_e,
        "rang": max(p_domicile, p_nul, p_exterieur)
    }


# Navigation
page = st.sidebar.radio(
    "Navigation",
    [
        "🏠 Accueil",
        "⚽ Matchs et pronostics",
        "📊 Analyse détaillée",
        "📚 Historique"
    ]
)

if "historique" not in st.session_state:
    st.session_state.historique = []

if page == "🏠 Accueil":
    st.markdown("## Bienvenue sur Foot AI Pro")

    c1, c2, c3 = st.columns(3)

    c1.metric("Champion­nats", len(COMPETITIONS))
    c2.metric("Scores analysés", "0 à 7 buts")
    c3.metric("Modèle", "Poisson")

    st.info(
        "Choisis un championnat dans la section Matchs et pronostics "
        "pour commencer."
    )

    st.warning(
        "Les probabilités sont expérimentales et reposent sur les "
        "buts et classements disponibles. Elles ne garantissent "
        "aucun résultat."
    )

elif page == "⚽ Matchs et pronostics":

    competition_nom = st.selectbox(
        "Choisir un championnat",
        list(COMPETITIONS.keys())
    )

    code = COMPETITIONS[competition_nom]

    nombre_jours = st.selectbox(
        "Période",
        [7, 14, 30],
        format_func=lambda n: f"Prochains {n} jours"
    )

    if st.button("🔎 Charger et analyser les matchs"):
        debut = date.today()
        fin = debut + timedelta(days=nombre_jours)

        with st.spinner("Chargement des données..."):
            donnees_matchs = charger_matchs(
                code,
                debut.isoformat(),
                fin.isoformat()
            )

            donnees_classement = charger_classement(code)

        if donnees_matchs is None or donnees_classement is None:
            st.error("Les données sont indisponibles pour le moment.")

        else:
            table = donnees_classement.get("standings", [])

            classement = {}

            for groupe in table:
                for equipe in groupe.get("table", []):
                    classement[equipe["team"]["id"]] = equipe

            resultats = []

            for match in donnees_matchs.get("matches", []):
                id_d = match["homeTeam"].get("id")
                id_e = match["awayTeam"].get("id")

                if id_d not in classement or id_e not in classement:
                    continue

                analyse = analyser_match(id_d, id_e, classement)

                if analyse is None:
                    continue

                resultats.append({
                    "id": match["id"],
                    "date": match.get("utcDate", ""),
                    "domicile": match["homeTeam"]["name"],
                    "exterieur": match["awayTeam"]["name"],
                    "analyse": analyse
                })

            resultats.sort(
                key=lambda m: m["analyse"]["rang"],
                reverse=True
            )

            st.session_state.matchs = resultats
            st.session_state.competition = competition_nom

            if not resultats:
                st.warning(
                    "Aucun match analysable trouvé. "
                    "Les classements ou les calendriers peuvent "
                    "être indisponibles pour cette période."
                )
            else:
                st.success(
                    f"{len(resultats)} match(s) analysé(s)."
                )

    for match in st.session_state.get("matchs", []):
        a = match["analyse"]

        with st.expander(
            f"⚽ {match['domicile']} - {match['exterieur']}"
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

            st.write("**🎯 Les 5 scores les plus probables**")

            for score in a["scores"]:
                st.write(
                    f"⚽ {match['domicile']} "
                    f"{score['domicile']} - {score['exterieur']} "
                    f"{match['exterieur']} — "
                    f"{score['probabilite'] * 100:.1f} %"
                )

            if st.button(
                "📚 Enregistrer dans l'historique",
                key=f"hist_{match['id']}"
            ):
                st.session_state.historique.append({
                    "match": (
                        f"{match['domicile']} - {match['exterieur']}"
                    ),
                    "date": match["date"],
                    "domicile": a["domicile"] * 100,
                    "nul": a["nul"] * 100,
                    "exterieur": a["exterieur"] * 100,
                    "score": (
                        f"{a['scores'][0]['domicile']}-"
                        f"{a['scores'][0]['exterieur']}"
                    )
                })

                st.success("Pronostic enregistré !")

elif page == "📊 Analyse détaillée":

    matchs = st.session_state.get("matchs", [])

    if not matchs:
        st.info(
            "Charge d'abord les matchs dans la section "
            "Matchs et pronostics."
        )

    else:
        noms = [
            f"{m['domicile']} - {m['exterieur']}"
            for m in matchs
        ]

        choix = st.selectbox("Choisir un match", noms)

        match = matchs[noms.index(choix)]
        a = match["analyse"]

        st.header(choix)

        st.subheader("Probabilités du résultat")

        st.progress(a["domicile"], text="Victoire à domicile")
        st.progress(a["nul"], text="Match nul")
        st.progress(a["exterieur"], text="Victoire à l'extérieur")

        st.subheader("Buts attendus par le modèle")

        c1, c2 = st.columns(2)

        c1.metric(
            match["domicile"],
            f"{a['lambda_d']:.2f}"
        )

        c2.metric(
            match["exterieur"],
            f"{a['lambda_e']:.2f}"
        )

        st.subheader("Scores les plus probables")

        tableau = pd.DataFrame([
            {
                "Score": (
                    f"{s['domicile']}-{s['exterieur']}"
                ),
                "Probabilité": (
                    f"{s['probabilite'] * 100:.2f} %"
                )
            }
            for s in a["scores"]
        ])

        st.dataframe(tableau, use_container_width=True)

        st.caption(
            "Le modèle utilise les moyennes de buts inscrits et "
            "encaissés. Il ne tient pas encore compte des blessures, "
            "des compositions, de la forme récente ou des cotes."
        )

elif page == "📚 Historique":

    st.header("📚 Historique des pronostics")

    historique = st.session_state.historique

    if not historique:
        st.info(
            "Aucun pronostic enregistré. "
            "Enregistre un pronostic depuis la liste des matchs."
        )

    else:
        st.dataframe(
            pd.DataFrame(historique),
            use_container_width=True
        )

        fichier = pd.DataFrame(historique).to_csv(
            index=False
        ).encode("utf-8")

        st.download_button(
            "📥 Télécharger l'historique CSV",
            fichier,
            file_name="historique_foot_ai_pro.csv",
            mime="text/csv"
        )

st.divider()

st.caption(
    "Foot AI Pro — Outil expérimental d'analyse statistique. "
    "Les estimations ne garantissent aucun résultat sportif."
)