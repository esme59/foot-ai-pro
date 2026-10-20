import streamlit as st
import requests
import math
from datetime import date, timedelta

# ==========================================
# CONFIGURATION
# ==========================================

st.set_page_config(
    page_title="FOOT AI PRO V5",
    page_icon="⚽",
    layout="wide"
)

API_URL = "https://api.football-data.org/v4"

COMPETITIONS = {
    "Ligue 1 🇫🇷": "FL1",
    "Premier League 🏴": "PL",
    "Liga 🇪🇸": "PD",
    "Bundesliga 🇩🇪": "BL1",
    "Serie A 🇮🇹": "SA",
    "Ligue des Champions ⭐": "CL"
}


# ==========================================
# INITIALISATION
# ==========================================

if "match_selectionne" not in st.session_state:
    st.session_state.match_selectionne = None
if "matchs_charges" not in st.session_state:
    st.session_state.matchs_charges = []
if "resultat_analyse" not in st.session_state:
    st.session_state.resultat_analyse = None

if "erreur_analyse" not in st.session_state:
    st.session_state.erreur_analyse = None

if "classement" not in st.session_state:
    st.session_state.classement = []


# ==========================================
# API FOOTBALL
# ==========================================

def get_api_key():
    try:
        return st.secrets["FOOTBALL_API_KEY"]
    except Exception:
        return None


def api_get(endpoint, params=None):
    cle = get_api_key()

    if not cle:
        return None, (
            "Clé API manquante. Vérifie les Secrets "
            "de ton application Streamlit."
        )

    headers = {
        "X-Auth-Token": cle
    }

    try:
        reponse = requests.get(
            f"{API_URL}{endpoint}",
            headers=headers,
            params=params,
            timeout=20
        )

        if reponse.status_code == 403:
            return None, (
                "Accès refusé par l'API. "
                "Vérifie les droits de ton compte."
            )

        if reponse.status_code == 429:
            return None, (
                "Trop de requêtes. Attends une minute "
                "avant de réessayer."
            )

        if reponse.status_code != 200:
            return None, (
                f"Erreur API : HTTP {reponse.status_code}. "
                f"{reponse.text[:200]}"
            )

        return reponse.json(), None

    except requests.exceptions.Timeout:
        return None, "Le serveur met trop de temps à répondre."

    except requests.exceptions.RequestException as erreur:
        return None, f"Erreur de connexion : {erreur}"


# ==========================================
# CHARGER LES MATCHS
# ==========================================

def charger_matchs(competition, debut, fin):
    return api_get(
        f"/competitions/{competition}/matches",
        {
            "dateFrom": debut,
            "dateTo": fin
        }
    )


# ==========================================
# DERNIERS MATCHS D'UNE ÉQUIPE
# ==========================================

def derniers_matchs(equipe_id):
    donnees, erreur = api_get(
        f"/teams/{equipe_id}/matches",
        {
            "status": "FINISHED",
            "limit": 5
        }
    )

    if erreur:
        return None, erreur

    return donnees.get("matches", []), None


# ==========================================
# STATISTIQUES D'UNE ÉQUIPE
# ==========================================

def calculer_moyennes(matchs, equipe_id):
    buts_marques = 0
    buts_encaisses = 0
    victoires = 0
    nuls = 0
    defaites = 0
    nombre = 0

    for match in matchs:
        domicile = match.get("homeTeam", {})
        exterieur = match.get("awayTeam", {})
        score = match.get("score", {}).get("fullTime", {})

        buts_dom = score.get("home")
        buts_ext = score.get("away")

        if buts_dom is None or buts_ext is None:
            continue

        if domicile.get("id") == equipe_id:
            marques = buts_dom
            encaisses = buts_ext
        elif exterieur.get("id") == equipe_id:
            marques = buts_ext
            encaisses = buts_dom
        else:
            continue

        buts_marques += marques
        buts_encaisses += encaisses
        nombre += 1

        if marques > encaisses:
            victoires += 1
        elif marques == encaisses:
            nuls += 1
        else:
            defaites += 1

    if nombre == 0:
        return None

    return {
        "marques": buts_marques / nombre,
        "encaisses": buts_encaisses / nombre,
        "victoires": victoires,
        "nuls": nuls,
        "defaites": defaites,
        "nombre": nombre
    }


# ==========================================
# CALCUL DE POISSON
# ==========================================

def poisson(moyenne, buts):
    if moyenne < 0:
        return 0

    return (
        math.exp(-moyenne)
        * moyenne ** buts
        / math.factorial(buts)
    )


def calculer_probabilites(moyenne_dom, moyenne_ext):
    scores = []

    victoire_dom = 0
    nul = 0
    victoire_ext = 0
    plus_25 = 0
    deux_marquent = 0

    for buts_dom in range(7):
        for buts_ext in range(7):

            p_dom = poisson(moyenne_dom, buts_dom)
            p_ext = poisson(moyenne_ext, buts_ext)

            probabilite = p_dom * p_ext

            scores.append(
                ((buts_dom, buts_ext), probabilite)
            )

            if buts_dom > buts_ext:
                victoire_dom += probabilite
            elif buts_dom == buts_ext:
                nul += probabilite
            else:
                victoire_ext += probabilite

            if buts_dom + buts_ext >= 3:
                plus_25 += probabilite

            if buts_dom > 0 and buts_ext > 0:
                deux_marquent += probabilite

    scores.sort(
        key=lambda element: element[1],
        reverse=True
    )

    return {
        "dom": victoire_dom,
        "nul": nul,
        "ext": victoire_ext,
        "plus25": plus_25,
        "moins25": 1 - plus_25,
        "deux": deux_marquent,
        "scores": scores[:5]
    }


# ==========================================
# ANALYSE DU MATCH
# ==========================================

def analyser(match):
    equipe_dom = match.get("homeTeam", {})
    equipe_ext = match.get("awayTeam", {})

    id_dom = equipe_dom.get("id")
    id_ext = equipe_ext.get("id")

    if not id_dom or not id_ext:
        return None, "Les informations des équipes sont incomplètes."

    matchs_dom, erreur = derniers_matchs(id_dom)

    if erreur:
        return None, f"Équipe à domicile : {erreur}"

    matchs_ext, erreur = derniers_matchs(id_ext)

    if erreur:
        return None, f"Équipe à l'extérieur : {erreur}"

    stats_dom = calculer_moyennes(matchs_dom, id_dom)
    stats_ext = calculer_moyennes(matchs_ext, id_ext)

    if not stats_dom or not stats_ext:
        return None, "Pas assez de résultats récents disponibles."

    moyenne_dom = (
        stats_dom["marques"] + stats_ext["encaisses"]
    ) / 2

    moyenne_ext = (
        stats_ext["marques"] + stats_dom["encaisses"]
    ) / 2

    probabilites = calculer_probabilites(
        moyenne_dom,
        moyenne_ext
    )

    return {
        "nom_dom": equipe_dom.get("name", "Domicile"),
        "nom_ext": equipe_ext.get("name", "Extérieur"),
        "stats_dom": stats_dom,
        "stats_ext": stats_ext,
        "probabilites": probabilites
    }, None


# ==========================================
# AFFICHER L'ANALYSE
# ==========================================

def afficher_analyse(resultat):
    p = resultat["probabilites"]

    st.success("Analyse terminée !")

    st.subheader(
        f"{resultat['nom_dom']} contre {resultat['nom_ext']}"
    )

    st.markdown("## 📊 Forme récente")

    c1, c2 = st.columns(2)

    with c1:
        st.markdown(f"### 🏠 {resultat['nom_dom']}")

        st.metric(
            "Buts marqués par match",
            f"{resultat['stats_dom']['marques']:.2f}"
        )

        st.metric(
            "Buts encaissés par match",
            f"{resultat['stats_dom']['encaisses']:.2f}"
        )

        st.write(
            f"Victoires : {resultat['stats_dom']['victoires']}"
        )

        st.write(
            f"Nuls : {resultat['stats_dom']['nuls']}"
        )

        st.write(
            f"Défaites : {resultat['stats_dom']['defaites']}"
        )

    with c2:
        st.markdown(f"### ✈️ {resultat['nom_ext']}")

        st.metric(
            "Buts marqués par match",
            f"{resultat['stats_ext']['marques']:.2f}"
        )

        st.metric(
            "Buts encaissés par match",
            f"{resultat['stats_ext']['encaisses']:.2f}"
        )

        st.write(
            f"Victoires : {resultat['stats_ext']['victoires']}"
        )

        st.write(
            f"Nuls : {resultat['stats_ext']['nuls']}"
        )

        st.write(
            f"Défaites : {resultat['stats_ext']['defaites']}"
        )

    st.markdown("## 🎯 Probabilités du match")

    c1, c2, c3 = st.columns(3)

    c1.metric(
        f"Victoire {resultat['nom_dom']}",
        f"{p['dom'] * 100:.1f} %"
    )

    c2.metric(
        "Match nul",
        f"{p['nul'] * 100:.1f} %"
    )

    c3.metric(
        f"Victoire {resultat['nom_ext']}",
        f"{p['ext'] * 100:.1f} %"
    )

    st.markdown("## ⚽ Probabilités de buts")

    c1, c2, c3 = st.columns(3)

    c1.metric(
        "Plus de 2,5 buts",
        f"{p['plus25'] * 100:.1f} %"
    )

    c2.metric(
        "Moins de 2,5 buts",
        f"{p['moins25'] * 100:.1f} %"
    )

    c3.metric(
        "Les deux équipes marquent",
        f"{p['deux'] * 100:.1f} %"
    )

    st.markdown("## 🥅 Scores les plus probables")

    for score, probabilite in p["scores"]:
        st.write(
            f"**{score[0]} - {score[1]}** "
            f"— {probabilite * 100:.1f} %"
        )

    choix = max(
        [
            ("Victoire domicile", p["dom"]),
            ("Match nul", p["nul"]),
            ("Victoire extérieur", p["ext"])
        ],
        key=lambda element: element[1]
    )

    st.markdown("## 🤖 Pronostic principal")

    st.info(
        f"{choix[0]} — probabilité estimée : "
        f"{choix[1] * 100:.1f} %"
    )

    st.warning(
        "Ces probabilités sont des estimations statistiques, "
        "pas des garanties du résultat réel."
    )


# ==========================================
# INTERFACE
# ==========================================

st.title("⚽ FOOT AI PRO V5")

st.caption(
    "Matchs réels • Statistiques • Pronostics"
)

page = st.radio(
    "Navigation",
    [
        "🏠 Accueil",
        "🌍 Matchs réels",
        "🤖 Analyse IA",
        "🏆 Classement"
    ],
    horizontal=True
)


# ==========================================
# ACCUEIL
# ==========================================

if page == "🏠 Accueil":
    st.header("Bienvenue sur FOOT AI PRO V5")

    st.write(
        "Sélectionne un match réel et lance une analyse "
        "statistique des deux équipes."
    )

    st.markdown("""
    - ⚽ Calendrier des matchs
    - 📊 Forme récente des équipes
    - 🎯 Probabilités de victoire et de nul
    - 🥅 Scores les plus probables
    - 🤖 Pronostic principal
    """)


# ==========================================
# MATCHS REELS
# ==========================================

elif page == "🌍 Matchs réels":
    st.header("🌍 Matchs disponibles")

    nom_competition = st.selectbox(
        "Choisir une compétition",
        list(COMPETITIONS.keys())
    )

    competition = COMPETITIONS[nom_competition]

    debut = st.date_input(
        "Date de début",
        value=date.today()
    )

    fin = st.date_input(
        "Date de fin",
        value=date.today() + timedelta(days=7)
    )

    if fin < debut:
        st.error(
            "La date de fin doit être après la date de début."
        )

    elif st.button("🔎 AFFICHER LES MATCHS"):
        with st.spinner("Chargement des matchs..."):
            donnees, erreur = charger_matchs(
                competition,
                debut.isoformat(),
                fin.isoformat()
            )

        if erreur:
            st.error(erreur)

        else:
            matchs = donnees.get("matches", [])

            if not matchs:
                st.info(
                    "Aucun match trouvé pour cette période."
                )

            for match in matchs:
                dom = match.get(
                    "homeTeam", {}
                ).get("name", "Domicile")

                ext = match.get(
                    "awayTeam", {}
                ).get("name", "Extérieur")

                with st.container(border=True):
                    st.subheader(f"{dom} vs {ext}")

                    st.write(
                        "Date : "
                        + match.get("utcDate", "").replace("T", " ")[:16]
                    )

                    st.write(
                        f"Statut : {match.get('status', 'Inconnu')}"
                    )

                    if st.button(
                        "🤖 Sélectionner ce match",
                        key=f"match_{match.get('id')}"
                    ):
                        st.session_state.match_selectionne = match
                        st.session_state.resultat_analyse = None
                        st.session_state.erreur_analyse = None

                        st.success(
                            "Match sélectionné ! "
                            "Ouvre maintenant l'onglet Analyse IA."
                        )


# ==========================================
# ANALYSE IA
# ==========================================

elif page == "🤖 Analyse IA":
    st.header("🤖 Analyse du match")

    match = st.session_state.match_selectionne

    if match is None:
        st.info(
            "Va dans Matchs réels et sélectionne d'abord un match."
        )

    else:
        dom = match.get(
            "homeTeam", {}
        ).get("name", "Domicile")

        ext = match.get(
            "awayTeam", {}
        ).get("name", "Extérieur")

        st.subheader(f"{dom} vs {ext}")

        if st.button("📊 LANCER L'ANALYSE"):
            st.session_state.resultat_analyse = None
            st.session_state.erreur_analyse = None

            with st.spinner(
                "Analyse des derniers matchs des deux équipes..."
            ):
                resultat, erreur = analyser(match)

            if erreur:
                st.session_state.erreur_analyse = erreur
            else:
                st.session_state.resultat_analyse = resultat

        if st.session_state.erreur_analyse:
            st.error(st.session_state.erreur_analyse)

        if st.session_state.resultat_analyse:
            afficher_analyse(
                st.session_state.resultat_analyse
            )


# ==========================================
# CLASSEMENT
# ==========================================

elif page == "🏆 Classement":
    st.header("🏆 Classement des pronostics")

    st.info(
        "Cette version simplifiée ne conserve pas encore "
        "automatiquement un historique des pronostics."
    )