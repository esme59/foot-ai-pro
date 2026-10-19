import streamlit as st
import requests
import math
from datetime import date, timedelta

st.set_page_config(
    page_title="FOOT AI PRO V4",
    page_icon="⚽",
    layout="wide"
)

st.markdown("""
<style>
.stApp {
    background: linear-gradient(135deg, #071b16, #102b23);
}
h1, h2, h3 {
    color: #00e676;
}
div.stButton > button {
    background-color: #00c853;
    color: white;
    border-radius: 10px;
    font-weight: bold;
    width: 100%;
}
</style>
""", unsafe_allow_html=True)

st.title("⚽ FOOT AI PRO V4")
st.subheader("👑 ULTIMATE — Football Analytics")
st.caption("Données réelles disponibles + analyses statistiques.")

st.divider()

# CONFIGURATION API
API_URL = "https://api.football-data.org/v4"

competitions = {
    "Premier League 🇬🇧": "PL",
    "Ligue 1 🇫🇷": "FL1",
    "Liga 🇪🇸": "PD",
    "Bundesliga 🇩🇪": "BL1",
    "Serie A 🇮🇹": "SA",
    "Ligue des Champions 🏆": "CL",
}

def get_api_key():
    try:
        return st.secrets["FOOTBALL_API_KEY"]
    except Exception:
        return ""

def api_get(endpoint, params=None):
    key = get_api_key()

    if not key:
        return None, "Clé API absente dans les Secrets Streamlit."

    headers = {"X-Auth-Token": key}

    try:
        response = requests.get(
            f"{API_URL}{endpoint}",
            headers=headers,
            params=params,
            timeout=20
        )

        if response.status_code == 200:
            return response.json(), None

        if response.status_code == 401:
            return None, "Clé API invalide ou non reconnue."

        if response.status_code == 403:
            return None, (
                "Cette compétition ou cette donnée n'est pas "
                "accessible avec ton abonnement API."
            )

        if response.status_code == 429:
            return None, (
                "Limite de requêtes atteinte. Réessaie plus tard."
            )

        return None, f"Erreur API : HTTP {response.status_code}"

    except requests.exceptions.Timeout:
        return None, "Le serveur met trop de temps à répondre."

    except requests.exceptions.RequestException:
        return None, "Impossible de contacter le serveur football."


# MENU
page = st.radio(
    "Navigation",
    [
        "🏠 Accueil",
        "🌍 Matchs réels",
        "🤖 Analyse personnalisée"
    ],
    horizontal=True
)

st.divider()

# PAGE ACCUEIL
if page == "🏠 Accueil":

    st.header("Bienvenue sur Foot AI PRO V4")

    col1, col2, col3 = st.columns(3)

    col1.metric("Version", "V4 Ultimate")
    col2.metric("Données", "API Football")
    col3.metric("Analyse", "Statistique")

    st.info(
        "Choisis Matchs réels pour consulter les rencontres "
        "disponibles ou Analyse personnalisée pour estimer "
        "les probabilités d'un match."
    )

    if get_api_key():
        st.success("Configuration API détectée.")
    else:
        st.error(
            "Clé API manquante. Configure FOOTBALL_API_KEY "
            "dans les Secrets de Streamlit."
        )

    st.caption(
        "Les probabilités sont des estimations et ne garantissent "
        "jamais le résultat d'un match."
    )


# PAGE MATCHS REELS
elif page == "🌍 Matchs réels":

    st.header("🌍 Calendrier des matchs")

    nom_competition = st.selectbox(
        "Choisir une compétition",
        list(competitions.keys())
    )

    code = competitions[nom_competition]

    aujourd_hui = date.today()
    date_fin = aujourd_hui + timedelta(days=7)

    st.write(
        f"Du {aujourd_hui.strftime('%d/%m/%Y')} "
        f"au {date_fin.strftime('%d/%m/%Y')}"
    )

    if st.button("🔄 CHARGER LES MATCHS"):

        with st.spinner("Recherche des matchs en cours..."):

            donnees, erreur = api_get(
                f"/competitions/{code}/matches",
                {
                    "dateFrom": aujourd_hui.isoformat(),
                    "dateTo": date_fin.isoformat()
                }
            )

        if erreur:
            st.error(erreur)

        else:
            matchs = donnees.get("matches", [])

            if not matchs:
                st.warning(
                    "Aucun match trouvé pour cette compétition "
                    "sur cette période."
                )

            else:
                st.success(f"{len(matchs)} match(s) trouvé(s).")

                for match in matchs:

                    domicile = match.get(
                        "homeTeam", {}
                    ).get("name", "Équipe domicile")

                    exterieur = match.get(
                        "awayTeam", {}
                    ).get("name", "Équipe extérieur")

                    date_match = match.get("utcDate", "")
                    statut = match.get("status", "Inconnu")

                    score = match.get("score", {})
                    resultat = score.get("fullTime", {})

                    buts_dom = resultat.get("home")
                    buts_ext = resultat.get("away")

                    if buts_dom is not None and buts_ext is not None:
                        score_texte = f"{buts_dom} - {buts_ext}"
                    else:
                        score_texte = "À jouer"

                    with st.container(border=True):

                        st.subheader(
                            f"⚽ {domicile} - {exterieur}"
                        )

                        st.write(f"📅 {date_match}")
                        st.write(f"📌 Statut : {statut}")
                        st.write(f"🎯 Score : {score_texte}")


# PAGE ANALYSE PERSONNALISEE
elif page == "🤖 Analyse personnalisée":

    st.header("🤖 Analyse statistique d'un match")

    col1, col2 = st.columns(2)

    with col1:
        equipe1 = st.text_input(
            "🏠 Équipe à domicile",
            "Paris Saint-Germain"
        )

        buts1 = st.number_input(
            "Moyenne de buts marqués à domicile",
            0.0, 10.0, 1.8, 0.1
        )

        encaisses1 = st.number_input(
            "Moyenne de buts encaissés à domicile",
            0.0, 10.0, 1.0, 0.1
        )

    with col2:
        equipe2 = st.text_input(
            "✈️ Équipe à l'extérieur",
            "Olympique de Marseille"
        )

        buts2 = st.number_input(
            "Moyenne de buts marqués à l'extérieur",
            0.0, 10.0, 1.2, 0.1
        )

        encaisses2 = st.number_input(
            "Moyenne de buts encaissés à l'extérieur",
            0.0, 10.0, 1.4, 0.1
        )

    st.info(
        "Les moyennes doivent être saisies manuellement. "
        "Elles ne sont pas automatiquement récupérées depuis l'API."
    )

    def poisson(moyenne, maximum=10):
        return [
            math.exp(-moyenne) * moyenne**i / math.factorial(i)
            for i in range(maximum + 1)
        ]

    def analyser(m1, m2):
        p1 = poisson(m1)
        p2 = poisson(m2)

        domicile = 0.0
        nul = 0.0
        exterieur = 0.0
        deux_marquent = 0.0
        plus_25 = 0.0
        scores = []

        for i, pi in enumerate(p1):
            for j, pj in enumerate(p2):

                proba = pi * pj
                scores.append((proba, i, j))

                if i > j:
                    domicile += proba
                elif i == j:
                    nul += proba
                else:
                    exterieur += proba

                if i > 0 and j > 0:
                    deux_marquent += proba

                if i + j >= 3:
                    plus_25 += proba

        scores.sort(reverse=True)

        return (
            domicile,
            nul,
            exterieur,
            scores[:5],
            deux_marquent,
            plus_25
        )

    if st.button("🚀 ANALYSER LE MATCH"):

        if not equipe1.strip() or not equipe2.strip():

            st.error("Entre les deux noms d'équipes.")

        elif equipe1.strip().casefold() == equipe2.strip().casefold():

            st.error("Choisis deux équipes différentes.")

        else:

            m1 = (buts1 + encaisses2) / 2
            m2 = (buts2 + encaisses1) / 2

            dom, nul, ext, scores, btts, over = analyser(m1, m2)

            st.divider()
            st.subheader(f"{equipe1} vs {equipe2}")

            c1, c2, c3 = st.columns(3)

            c1.metric("Victoire domicile", f"{dom * 100:.1f} %")
            c2.metric("Match nul", f"{nul * 100:.1f} %")
            c3.metric("Victoire extérieur", f"{ext * 100:.1f} %")

            st.subheader("🎯 Les 5 scores les plus probables")

            for proba, i, j in scores:

                st.write(
                    f"**{equipe1} {i} - {j} {equipe2}** "
                    f"— {proba * 100:.1f} %"
                )

            c4, c5 = st.columns(2)

            c4.metric("Plus de 2,5 buts", f"{over * 100:.1f} %")
            c5.metric("Moins de 2,5 buts", f"{(1-over)*100:.1f} %")

            c6, c7 = st.columns(2)

            c6.metric("Les deux marquent : oui", f"{btts*100:.1f} %")
            c7.metric("Les deux marquent : non", f"{(1-btts)*100:.1f} %")

            resultats = {
                f"Victoire {equipe1}": dom,
                "Match nul": nul,
                f"Victoire {equipe2}": ext
            }

            meilleur = max(resultats, key=resultats.get)

            st.success(
                f"🏆 Résultat le plus probable : {meilleur} "
                f"({resultats[meilleur]*100:.1f} %)"
            )

            st.caption(
                "Modèle de Poisson simplifié. Les estimations "
                "dépendent des moyennes saisies et ne garantissent "
                "aucun résultat réel."
            )

st.divider()

st.caption(
    "FOOT AI PRO V4 ULTIMATE — "
    "Outil d'aide à l'analyse football."
)