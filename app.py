import math
from datetime import date, timedelta

import requests
import streamlit as st


# ==========================================
# CONFIGURATION
# ==========================================

st.set_page_config(
    page_title="FOOT AI PRO",
    page_icon="⚽",
    layout="wide"
)

API_URL = "https://api.football-data.org/v4"

COMPETITIONS = {
    "🇫🇷 Ligue 1": "FL1",
    "🏴 Premier League": "PL",
    "🇪🇸 Liga": "PD",
    "🇩🇪 Bundesliga": "BL1",
    "🇮🇹 Serie A": "SA",
    "🏆 Ligue des champions": "CL",
}


# ==========================================
# MEMOIRE DE L'APPLICATION
# ==========================================

def initialiser(cle, valeur):
    if cle not in st.session_state:
        st.session_state[cle] = valeur


initialiser("matchs_charges", [])
initialiser("match_selectionne", None)
initialiser("resultat_analyse", None)
initialiser("erreur_analyse", None)
initialiser("buteurs_analyse", None)
initialiser("erreur_buteurs", None)
initialiser("classement", [])


# ==========================================
# STYLE
# ==========================================

st.markdown(
    """
    <style>
    .stApp {
        background-color: #0b1020;
        color: white;
    }

    h1, h2, h3 {
        color: #43e97b;
    }

    div[data-testid="stMetric"] {
        background-color: #151d32;
        padding: 15px;
        border-radius: 12px;
    }

    div.stButton > button {
        border-radius: 10px;
        font-weight: bold;
        min-height: 42px;
    }
    </style>
    """,
    unsafe_allow_html=True
)


# ==========================================
# TITRE
# ==========================================

st.title("⚽ FOOT AI PRO")

st.caption(
    "Analyse des matchs, statistiques et buteurs probables."
)


# ==========================================
# CONNEXION API
# ==========================================

def get_api_key():
    try:
        key = st.secrets.get("FOOTBALL_API_KEY", "")
        if key:
            return key

        key = st.secrets.get("FOOTBALL_DATA_TOKEN", "")
        if key:
            return key

    except Exception:
        return ""

    return ""


def api_get(endpoint, params=None):

    api_key = get_api_key()

    if not api_key:
        return None, (
            "Clé API introuvable. Vérifie dans Streamlit Cloud "
            "que ta clé est enregistrée dans Secrets sous "
            "FOOTBALL_API_KEY ou FOOTBALL_DATA_TOKEN."
        )

    headers = {
        "X-Auth-Token": api_key
    }

    try:
        response = requests.get(
            API_URL + endpoint,
            headers=headers,
            params=params,
            timeout=20
        )

        if response.status_code == 401:
            return None, (
                "Clé API invalide. Vérifie tes Secrets Streamlit."
            )

        if response.status_code == 403:
            return None, (
                "Accès refusé par l'API. Cette compétition ou "
                "cette fonctionnalité n'est peut-être pas incluse "
                "dans ton forfait."
            )

        if response.status_code == 429:
            return None, (
                "Trop de requêtes API. Attends un peu puis réessaie."
            )

        if response.status_code == 404:
            return None, "Données introuvables pour cette demande."

        response.raise_for_status()

        return response.json(), None

    except requests.exceptions.Timeout:
        return None, (
            "Le serveur met trop de temps à répondre. Réessaie."
        )

    except requests.exceptions.RequestException as erreur:
        return None, f"Erreur de connexion à l'API : {erreur}"

    except ValueError:
        return None, "La réponse de l'API est illisible."


# ==========================================
# CHARGEMENT DES MATCHS
# ==========================================

def charger_matchs(competition, debut, fin):

    donnees, erreur = api_get(
        f"/competitions/{competition}/matches",
        {
            "dateFrom": debut,
            "dateTo": fin
        }
    )

    if erreur:
        return None, erreur

    return donnees, None


# ==========================================
# DERNIERS MATCHS D'UNE EQUIPE
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
# STATISTIQUES D'UNE EQUIPE
# ==========================================

def calculer_moyennes(matchs, equipe_id):

    buts_marques = []
    buts_encaisses = []

    victoires = 0
    nuls = 0
    defaites = 0

    for match in matchs:

        score = match.get("score", {}).get("fullTime", {})

        buts_dom = score.get("home")
        buts_ext = score.get("away")

        if buts_dom is None or buts_ext is None:
            continue

        equipe_dom = match.get("homeTeam", {}).get("id")
        equipe_ext = match.get("awayTeam", {}).get("id")

        if equipe_dom == equipe_id:
            marques = buts_dom
            encaisses = buts_ext

        elif equipe_ext == equipe_id:
            marques = buts_ext
            encaisses = buts_dom

        else:
            continue

        buts_marques.append(marques)
        buts_encaisses.append(encaisses)

        if marques > encaisses:
            victoires += 1
        elif marques == encaisses:
            nuls += 1
        else:
            defaites += 1

    nombre = len(buts_marques)

    if nombre == 0:
        return None

    return {
        "nombre_matchs": nombre,
        "buts_marques": sum(buts_marques) / nombre,
        "buts_encaisses": sum(buts_encaisses) / nombre,
        "victoires": victoires,
        "nuls": nuls,
        "defaites": defaites
    }


# ==========================================
# MODELE DE POISSON
# ==========================================

def poisson(moyenne, buts):

    if moyenne < 0:
        return 0

    return (
        math.exp(-moyenne)
        * moyenne ** buts
        / math.factorial(buts)
    )


# ==========================================
# ANALYSE DU MATCH
# ==========================================

def analyser(match):

    equipe_dom = match.get("homeTeam", {})
    equipe_ext = match.get("awayTeam", {})

    id_dom = equipe_dom.get("id")
    id_ext = equipe_ext.get("id")

    nom_dom = equipe_dom.get("name", "Domicile")
    nom_ext = equipe_ext.get("name", "Extérieur")

    if not id_dom or not id_ext:
        return None, "Identifiants des équipes indisponibles."

    matchs_dom, erreur = derniers_matchs(id_dom)

    if erreur:
        return None, (
            f"Impossible de récupérer les matchs de {nom_dom}. "
            f"{erreur}"
        )

    matchs_ext, erreur = derniers_matchs(id_ext)

    if erreur:
        return None, (
            f"Impossible de récupérer les matchs de {nom_ext}. "
            f"{erreur}"
        )

    stats_dom = calculer_moyennes(matchs_dom, id_dom)
    stats_ext = calculer_moyennes(matchs_ext, id_ext)

    if stats_dom is None or stats_ext is None:
        return None, (
            "Pas assez de résultats terminés pour analyser "
            "les deux équipes."
        )

    moyenne_dom = (
        stats_dom["buts_marques"]
        + stats_ext["buts_encaisses"]
    ) / 2

    moyenne_ext = (
        stats_ext["buts_marques"]
        + stats_dom["buts_encaisses"]
    ) / 2

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
        "nom_dom": nom_dom,
        "nom_ext": nom_ext,
        "stats_dom": stats_dom,
        "stats_ext": stats_ext,
        "moyenne_dom": moyenne_dom,
        "moyenne_ext": moyenne_ext,
        "victoire_dom": victoire_dom,
        "nul": nul,
        "victoire_ext": victoire_ext,
        "plus_25": plus_25,
        "moins_25": 1 - plus_25,
        "deux_marquent": deux_marquent,
        "scores": scores[:5]
    }, None


# ==========================================
# ANALYSE DES BUTEURS
# ==========================================

def analyser_buteurs(match):

    equipe_dom = match.get("homeTeam", {})
    equipe_ext = match.get("awayTeam", {})

    id_dom = equipe_dom.get("id")
    id_ext = equipe_ext.get("id")

    competition = match.get("competition", {}).get("code")

    if not competition or not id_dom or not id_ext:
        return None, (
            "Les informations nécessaires sur les équipes "
            "ou la compétition sont indisponibles."
        )

    donnees, erreur = api_get(
        f"/competitions/{competition}/scorers",
        {"limit": 100}
    )

    if erreur:
        return None, (
            "Impossible de récupérer les statistiques des buteurs. "
            + erreur
        )

    liste_buteurs = donnees.get("scorers", [])

    resultat = {
        "domicile": [],
        "exterieur": []
    }

    for buteur in liste_buteurs:

        joueur = buteur.get("player", {})
        equipe = buteur.get("team", {})

        id_equipe = equipe.get("id")

        buts = buteur.get("goals") or 0
        matchs_joues = buteur.get("playedMatches") or 0

        if matchs_joues <= 0 or buts <= 0:
            continue

        # Moyenne de buts par apparition.
        moyenne_buts = buts / matchs_joues

        # Approximation statistique du risque de marquer
        # au moins un but, selon une loi de Poisson.
        probabilite = (
            1 - math.exp(-moyenne_buts)
        ) * 100

        information = {
            "nom": joueur.get("name", "Joueur inconnu"),
            "equipe": equipe.get("name", ""),
            "buts": buts,
            "matchs": matchs_joues,
            "moyenne": moyenne_buts,
            "probabilite": probabilite
        }

        if id_equipe == id_dom:
            resultat["domicile"].append(information)

        elif id_equipe == id_ext:
            resultat["exterieur"].append(information)

    for cote in ["domicile", "exterieur"]:

        resultat[cote].sort(
            key=lambda joueur: joueur["probabilite"],
            reverse=True
        )

    return resultat, None


# ==========================================
# AFFICHAGE DE L'ANALYSE DU MATCH
# ==========================================

def afficher_analyse(resultat):

    st.subheader(
        f"{resultat['nom_dom']} - {resultat['nom_ext']}"
    )

    st.caption(
        "Estimations mathématiques fondées sur les résultats récents. "
        "Elles ne garantissent pas le résultat du match."
    )

    st.markdown("### 📊 Probabilités du match")

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Victoire domicile",
        f"{resultat['victoire_dom'] * 100:.1f} %"
    )

    col2.metric(
        "Match nul",
        f"{resultat['nul'] * 100:.1f} %"
    )

    col3.metric(
        "Victoire extérieur",
        f"{resultat['victoire_ext'] * 100:.1f} %"
    )

    st.markdown("### ⚽ Buts estimés")

    col1, col2 = st.columns(2)

    col1.metric(
        resultat["nom_dom"],
        f"{resultat['moyenne_dom']:.2f} buts"
    )

    col2.metric(
        resultat["nom_ext"],
        f"{resultat['moyenne_ext']:.2f} buts"
    )

    st.markdown("### 🔥 Plus ou moins de 2,5 buts")

    col1, col2 = st.columns(2)

    col1.metric(
        "Plus de 2,5 buts",
        f"{resultat['plus_25'] * 100:.1f} %"
    )

    col2.metric(
        "Moins de 2,5 buts",
        f"{resultat['moins_25'] * 100:.1f} %"
    )

    st.markdown("### 🎯 Les deux équipes marquent")

    st.metric(
        "Probabilité estimée",
        f"{resultat['deux_marquent'] * 100:.1f} %"
    )

    st.markdown("### 🥅 Les 5 scores les plus probables")

    for numero, element in enumerate(
        resultat["scores"],
        start=1
    ):

        score, probabilite = element

        st.write(
            f"**{numero}. {score[0]} - {score[1]}** "
            f"— {probabilite * 100:.2f} %"
        )

    st.markdown("### 📈 Forme récente")

    col1, col2 = st.columns(2)

    for colonne, nom, cle in [
        (col1, resultat["nom_dom"], "stats_dom"),
        (col2, resultat["nom_ext"], "stats_ext")
    ]:

        stats = resultat[cle]

        with colonne:

            st.write(f"**{nom}**")

            st.write(
                f"Matchs analysés : {stats['nombre_matchs']}"
            )

            st.write(
                f"Buts marqués par match : "
                f"{stats['buts_marques']:.2f}"
            )

            st.write(
                f"Buts encaissés par match : "
                f"{stats['buts_encaisses']:.2f}"
            )

            st.write(f"Victoires : {stats['victoires']}")
            st.write(f"Nuls : {stats['nuls']}")
            st.write(f"Défaites : {stats['defaites']}")


# ==========================================
# AFFICHAGE DES BUTEURS
# ==========================================

def afficher_buteurs(buteurs):

    col1, col2 = st.columns(2)

    equipes = [
        (col1, "domicile", "🏠 Équipe à domicile"),
        (col2, "exterieur", "✈️ Équipe à l'extérieur")
    ]

    for colonne, cote, titre in equipes:

        with colonne:

            st.markdown(f"### {titre}")

            liste = buteurs.get(cote, [])

            if not liste:

                st.info(
                    "Aucun buteur disponible pour cette équipe "
                    "dans les données reçues."
                )

                continue

            for numero, joueur in enumerate(liste[:3], start=1):

                st.markdown(
                    f"**{numero}. ⚽ {joueur['nom']}**"
                )

                st.write(
                    f"Buts cette saison : {joueur['buts']}"
                )

                st.write(
                    f"Matchs joués : {joueur['matchs']}"
                )

                st.write(
                    f"Moyenne : {joueur['moyenne']:.2f} "
                    "but par match"
                )

                st.write(
                    "Estimation statistique : "
                    f"{joueur['probabilite']:.1f} %"
                )

                st.progress(
                    min(
                        max(
                            int(joueur["probabilite"]),
                            0
                        ),
                        100
                    )
                )

                st.divider()

    st.caption(
        "Important : les probabilités des buteurs sont des "
        "approximations fondées sur leurs buts et leurs matchs "
        "joués dans les statistiques disponibles. Elles ne prennent "
        "pas nécessairement en compte les blessures, les titulaires "
        "annoncés, le temps de jeu prévu ou la forme récente. "
        "Elles ne garantissent pas qu'un joueur marquera."
    )


# ==========================================
# NAVIGATION
# ==========================================

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

    st.header("Bienvenue sur FOOT AI PRO")

    st.write(
        "Ton assistant d'analyse des matchs de football."
    )

    st.markdown(
        """
        ### Fonctionnalités

        - 🌍 Matchs réels et compétitions.
        - 📊 Analyse des derniers résultats des équipes.
        - 🎯 Probabilités de victoire, de nul et de buts.
        - 🥅 Analyse statistique des meilleurs buteurs disponibles.
        - 🏆 Classements des compétitions.

        ### Comment utiliser l'application ?

        1. Ouvre « Matchs réels ».
        2. Choisis une compétition et les dates.
        3. Appuie sur « AFFICHER LES MATCHS ».
        4. Sélectionne un match.
        5. Ouvre « Analyse IA ».
        6. Lance l'analyse du match.
        7. Lance ensuite l'analyse des buteurs.
        """
    )


# ==========================================
# MATCHS REELS
# ==========================================

elif page == "🌍 Matchs réels":

    st.header("🌍 Matchs réels")

    nom_competition = st.selectbox(
        "Choisir une compétition",
        list(COMPETITIONS.keys())
    )

    competition = COMPETITIONS[nom_competition]

    aujourd_hui = date.today()

    col1, col2 = st.columns(2)

    with col1:

        debut = st.date_input(
            "Date de début",
            value=aujourd_hui
        )

    with col2:

        fin = st.date_input(
            "Date de fin",
            value=aujourd_hui + timedelta(days=7)
        )

    if st.button(
        "🔎 AFFICHER LES MATCHS",
        use_container_width=True
    ):

        if fin < debut:

            st.error(
                "La date de fin doit être après la date de début."
            )

        else:

            with st.spinner("Chargement des matchs..."):

                donnees, erreur = charger_matchs(
                    competition,
                    debut.isoformat(),
                    fin.isoformat()
                )

            if erreur:

                st.session_state.matchs_charges = []
                st.error(erreur)

            else:

                st.session_state.matchs_charges = (
                    donnees.get("matches", [])
                )

                st.session_state.match_selectionne = None
                st.session_state.resultat_analyse = None
                st.session_state.erreur_analyse = None
                st.session_state.buteurs_analyse = None
                st.session_state.erreur_buteurs = None

    # Les matchs restent affichés après les clics.

    matchs = st.session_state.matchs_charges

    if not matchs:

        st.info(
            "Choisis une compétition et une période, "
            "puis appuie sur « AFFICHER LES MATCHS »."
        )

    else:

        st.success(f"{len(matchs)} match(s) chargé(s).")

        for match in matchs:

            equipe_dom = match.get("homeTeam", {})
            equipe_ext = match.get("awayTeam", {})

            dom = equipe_dom.get("name", "Domicile")
            ext = equipe_ext.get("name", "Extérieur")

            identifiant = match.get("id")

            with st.container(border=True):

                st.subheader(f"{dom} vs {ext}")

                date_match = match.get("utcDate", "")

                if date_match:

                    st.write(
                        "Date : "
                        + date_match.replace("T", " ")[:16]
                        + " UTC"
                    )

                st.write(
                    f"Statut : {match.get('status', 'Inconnu')}"
                )

                score = match.get("score", {}).get("fullTime", {})

                if (
                    score.get("home") is not None
                    and score.get("away") is not None
                ):

                    st.write(
                        f"Score : {score['home']} - {score['away']}"
                    )

                if st.button(
                    "🤖 Sélectionner ce match",
                    key=f"match_{identifiant}",
                    use_container_width=True
                ):

                    st.session_state.match_selectionne = match
                    st.session_state.resultat_analyse = None
                    st.session_state.erreur_analyse = None
                    st.session_state.buteurs_analyse = None
                    st.session_state.erreur_buteurs = None

                    st.success(
                        "Match sélectionné ! "
                        "Ouvre maintenant l'onglet Analyse IA."
                    )


# ==========================================
# ANALYSE IA ET BUTEURS
# ==========================================

elif page == "🤖 Analyse IA":

    st.header("🤖 Analyse du match")

    match = st.session_state.match_selectionne

    if match is None:

        st.warning(
            "Va dans « Matchs réels » et sélectionne d'abord "
            "un match."
        )

    else:

        nom_dom = match.get(
            "homeTeam", {}
        ).get("name", "Domicile")

        nom_ext = match.get(
            "awayTeam", {}
        ).get("name", "Extérieur")

        st.info(
            f"Match sélectionné : {nom_dom} - {nom_ext}"
        )

        if st.button(
            "🚀 LANCER L'ANALYSE DU MATCH",
            use_container_width=True
        ):

            with st.spinner(
                "Analyse des résultats récents des équipes..."
            ):

                resultat, erreur = analyser(match)

            st.session_state.resultat_analyse = resultat
            st.session_state.erreur_analyse = erreur

        if st.session_state.erreur_analyse:

            st.error(st.session_state.erreur_analyse)

        if st.session_state.resultat_analyse:

            afficher_analyse(
                st.session_state.resultat_analyse
            )

            st.divider()

            st.subheader("🥅 Les buteurs les plus probables")

            st.write(
                "Recherche les meilleurs buteurs disponibles "
                "pour chacune des deux équipes."
            )

            if st.button(
                "🎯 ANALYSER LES BUTEURS",
                use_container_width=True
            ):

                with st.spinner(
                    "Chargement des statistiques des buteurs..."
                ):

                    buteurs, erreur = analyser_buteurs(match)

                st.session_state.buteurs_analyse = buteurs
                st.session_state.erreur_buteurs = erreur

            if st.session_state.erreur_buteurs:

                st.warning(
                    st.session_state.erreur_buteurs
                )

            if st.session_state.buteurs_analyse:

                afficher_buteurs(
                    st.session_state.buteurs_analyse
                )


# ==========================================
# CLASSEMENT
# ==========================================

elif page == "🏆 Classement":

    st.header("🏆 Classement")

    nom_competition = st.selectbox(
        "Choisir une compétition",
        list(COMPETITIONS.keys()),
        key="competition_classement"
    )

    competition = COMPETITIONS[nom_competition]

    if st.button(
        "📊 AFFICHER LE CLASSEMENT",
        use_container_width=True
    ):

        with st.spinner("Chargement du classement..."):

            donnees, erreur = api_get(
                f"/competitions/{competition}/standings"
            )

        if erreur:

            st.session_state.classement = []
            st.error(erreur)

        else:

            tableaux = donnees.get("standings", [])
            classement = []

            for tableau in tableaux:

                if tableau.get("type") == "TOTAL":

                    classement = tableau.get("table", [])
                    break

            st.session_state.classement = classement

            if not classement:

                st.warning(
                    "Aucun classement disponible pour cette "
                    "compétition avec ton accès API."
                )

    classement = st.session_state.classement

    if classement:

        st.dataframe(
            [
                {
                    "Position": equipe.get("position"),
                    "Équipe": equipe.get("team", {}).get("name"),
                    "Matchs": equipe.get("playedGames"),
                    "Victoires": equipe.get("won"),
                    "Nuls": equipe.get("draw"),
                    "Défaites": equipe.get("lost"),
                    "Buts marqués": equipe.get("goalsFor"),
                    "Buts encaissés": equipe.get("goalsAgainst"),
                    "Différence": equipe.get("goalDifference"),
                    "Points": equipe.get("points")
                }
                for equipe in classement
            ],
            use_container_width=True,
            hide_index=True
        )


# ==========================================
# AVERTISSEMENT FINAL
# ==========================================

st.divider()

st.caption(
    "FOOT AI PRO fournit des estimations statistiques et non "
    "des certitudes. Les données disponibles dépendent de l'API "
    "et de ton accès. Aucun pronostic ne garantit un résultat."
)