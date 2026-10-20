import streamlit as st
import requests
import math
from datetime import date, timedelta

# ==========================================
# FOOT AI PRO V7 ULTIMATE
# ==========================================

st.set_page_config(
    page_title="FOOT AI PRO V7",
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
# MEMOIRE DE L'APPLICATION
# ==========================================

for cle, valeur in {
    "match_selectionne": None,
    "competition_selectionnee": "FL1",
    "resultat_analyse": None,
    "erreur_analyse": None,
    "classement": []
}.items():
    if cle not in st.session_state:
        st.session_state[cle] = valeur

# ==========================================
# CONNEXION API
# ==========================================

def obtenir_cle():
    try:
        return st.secrets["FOOTBALL_API_KEY"]
    except Exception:
        return None


def appel_api(endpoint, params=None):
    cle = obtenir_cle()

    if not cle:
        return None, (
            "Clé API introuvable. Vérifie les Secrets "
            "de ton application Streamlit."
        )

    try:
        reponse = requests.get(
            API_URL + endpoint,
            headers={"X-Auth-Token": cle},
            params=params,
            timeout=20
        )

        if reponse.status_code == 200:
            return reponse.json(), None

        if reponse.status_code == 403:
            return None, (
                "Accès refusé par l'API. Cette fonctionnalité "
                "n'est peut-être pas disponible avec ton forfait."
            )

        if reponse.status_code == 429:
            return None, (
                "Limite de requêtes atteinte. Attends quelques "
                "minutes avant de réessayer."
            )

        return None, f"Erreur API HTTP {reponse.status_code}"

    except requests.RequestException:
        return None, "Erreur de connexion à l'API."


# ==========================================
# CHARGEMENT DES MATCHS
# ==========================================

@st.cache_data(ttl=300)
def charger_matchs(competition, debut, fin):
    return appel_api(
        f"/competitions/{competition}/matches",
        {
            "dateFrom": debut,
            "dateTo": fin
        }
    )


@st.cache_data(ttl=900)
def charger_historique(equipe_id):
    return appel_api(
        f"/teams/{equipe_id}/matches",
        {
            "status": "FINISHED",
            "limit": 5
        }
    )


# ==========================================
# STATISTIQUES DES EQUIPES
# ==========================================

def statistiques_equipe(matchs, equipe_id):
    marques = []
    encaisses = []

    for match in matchs:
        if match.get("status") != "FINISHED":
            continue

        domicile = match.get("homeTeam", {}).get("id")
        exterieur = match.get("awayTeam", {}).get("id")

        score = match.get("score", {}).get("fullTime", {})
        buts_dom = score.get("home")
        buts_ext = score.get("away")

        if buts_dom is None or buts_ext is None:
            continue

        if domicile == equipe_id:
            marques.append(buts_dom)
            encaisses.append(buts_ext)

        elif exterieur == equipe_id:
            marques.append(buts_ext)
            encaisses.append(buts_dom)

    if not marques:
        return None

    return {
        "marques": sum(marques) / len(marques),
        "encaisses": sum(encaisses) / len(encaisses),
        "nombre": len(marques)
    }


# ==========================================
# CALCUL DES PROBABILITES
# ==========================================

def poisson(moyenne, buts):
    if moyenne <= 0:
        return 1.0 if buts == 0 else 0.0

    return (
        math.exp(-moyenne)
        * moyenne ** buts
        / math.factorial(buts)
    )


def calculer_probabilites(moyenne_dom, moyenne_ext):
    scores = {}

    for dom in range(9):
        for ext in range(9):
            scores[(dom, ext)] = (
                poisson(moyenne_dom, dom)
                * poisson(moyenne_ext, ext)
            )

    total = sum(scores.values())

    if total == 0:
        return None

    victoire_dom = sum(
        p for (d, e), p in scores.items() if d > e
    ) / total

    nul = sum(
        p for (d, e), p in scores.items() if d == e
    ) / total

    victoire_ext = sum(
        p for (d, e), p in scores.items() if d < e
    ) / total

    plus_15 = sum(
        p for (d, e), p in scores.items() if d + e >= 2
    ) / total

    plus_25 = sum(
        p for (d, e), p in scores.items() if d + e >= 3
    ) / total

    deux_marquent = sum(
        p for (d, e), p in scores.items()
        if d >= 1 and e >= 1
    ) / total

    scores_tries = sorted(
        scores.items(),
        key=lambda element: element[1],
        reverse=True
    )

    return {
        "dom": victoire_dom,
        "nul": nul,
        "ext": victoire_ext,
        "plus15": plus_15,
        "plus25": plus_25,
        "deux": deux_marquent,
        "scores": scores_tries[:5]
    }


# ==========================================
# BUTEURS DE LA COMPETITION
# ==========================================

@st.cache_data(ttl=1800)
def charger_buteurs(competition):
    return appel_api(
        f"/competitions/{competition}/scorers",
        {"limit": 20}
    )


def afficher_buteurs(competition, id_dom, id_ext):
    st.markdown("## ⚽ Buteurs à surveiller")

    donnees, erreur = charger_buteurs(competition)

    if erreur:
        st.warning(
            "Les statistiques des buteurs ne sont pas accessibles "
            "pour cette compétition avec l'API actuelle."
        )
        return

    buteurs = donnees.get("scorers", [])

    if not buteurs:
        st.info("Aucune statistique de buteur disponible.")
        return

    joueurs_match = []

    for element in buteurs:
        joueur = element.get("player", {})
        equipe = element.get("team", {})

        equipe_id = equipe.get("id")

        if equipe_id not in (id_dom, id_ext):
            continue

        buts = element.get("goals")

        if buts is None:
            continue

        apparitions = element.get("playedMatches") or 0

        joueurs_match.append({
            "nom": joueur.get("name", "Joueur inconnu"),
            "equipe": equipe.get("name", "Équipe inconnue"),
            "buts": buts,
            "matchs": apparitions,
            "passes": element.get("assists") or 0,
            "equipe_id": equipe_id
        })

    if not joueurs_match:
        st.info(
            "Aucun joueur de ces deux équipes ne figure dans "
            "le classement des buteurs accessible."
        )

        st.caption(
            "Cela ne signifie pas que les équipes n'ont pas de "
            "buteurs : l'API ne fournit ici que les joueurs présents "
            "dans son classement."
        )
        return

    joueurs_match.sort(
        key=lambda joueur: joueur["buts"],
        reverse=True
    )

    st.caption(
        "Classement disponible des buteurs de la compétition. "
        "Il ne confirme pas que les joueurs seront titulaires."
    )

    for joueur in joueurs_match:
        if joueur["matchs"] > 0:
            moyenne = joueur["buts"] / joueur["matchs"]
            taux = 100 * (1 - math.exp(-moyenne))
        else:
            moyenne = 0
            taux = 0

        st.markdown(
            f"### 🥅 {joueur['nom']}"
        )

        c1, c2, c3 = st.columns(3)

        c1.metric("Buts", joueur["buts"])
        c2.metric("Matchs", joueur["matchs"])
        c3.metric("Passes décisives", joueur["passes"])

        st.write(f"**Équipe :** {joueur['equipe']}")
        st.write(
            f"Buts par match : {moyenne:.2f}"
        )

        st.caption(
            f"Indicateur statistique approximatif de but : "
            f"{taux:.1f} %. Ce chiffre n'est pas une probabilité "
            f"validée que le joueur marque lors du prochain match."
        )

        st.divider()


# ==========================================
# ANALYSE COMPLETE DU MATCH
# ==========================================

def analyser_match(match):
    equipe_dom = match.get("homeTeam", {})
    equipe_ext = match.get("awayTeam", {})

    id_dom = equipe_dom.get("id")
    id_ext = equipe_ext.get("id")

    if not id_dom or not id_ext:
        return None, "Informations des équipes incomplètes."

    historique_dom, erreur = charger_historique(id_dom)

    if erreur:
        return None, f"Historique domicile : {erreur}"

    historique_ext, erreur = charger_historique(id_ext)

    if erreur:
        return None, f"Historique extérieur : {erreur}"

    stats_dom = statistiques_equipe(
        historique_dom.get("matches", []),
        id_dom
    )

    stats_ext = statistiques_equipe(
        historique_ext.get("matches", []),
        id_ext
    )

    if not stats_dom or not stats_ext:
        return None, (
            "Pas assez de résultats récents disponibles "
            "pour analyser ce match."
        )

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

    if not probabilites:
        return None, "Impossible de calculer les probabilités."

    return {
        "nom_dom": equipe_dom.get("name", "Domicile"),
        "nom_ext": equipe_ext.get("name", "Extérieur"),
        "id_dom": id_dom,
        "id_ext": id_ext,
        "stats_dom": stats_dom,
        "stats_ext": stats_ext,
        "probabilites": probabilites
    }, None


# ==========================================
# AFFICHAGE DE L'ANALYSE
# ==========================================

def afficher_analyse(resultat, competition):
    p = resultat["probabilites"]

    st.success("Analyse terminée !")

    st.subheader(
        f"{resultat['nom_dom']} vs {resultat['nom_ext']}"
    )

    st.markdown("## 📊 Statistiques des équipes")

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

        st.caption(
            f"{resultat['stats_dom']['nombre']} matchs analysés"
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

        st.caption(
            f"{resultat['stats_ext']['nombre']} matchs analysés"
        )

    st.markdown("## 🎯 Résultat probable")

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

    c1.metric("Plus de 1,5 but", f"{p['plus15'] * 100:.1f} %")
    c2.metric("Plus de 2,5 buts", f"{p['plus25'] * 100:.1f} %")
    c3.metric("Les deux marquent", f"{p['deux'] * 100:.1f} %")

    st.markdown("## 🥅 Scores les plus probables")

    for (dom, ext), proba in p["scores"]:
        st.write(
            f"**{resultat['nom_dom']} {dom} - {ext} "
            f"{resultat['nom_ext']}** — {proba * 100:.1f} %"
        )

    # Nouvelle fonctionnalité : buteurs
    afficher_buteurs(
        competition,
        resultat["id_dom"],
        resultat["id_ext"]
    )

    st.warning(
        "Les estimations ne garantissent pas le résultat du match. "
        "Les buteurs affichés dépendent des données disponibles et "
        "ne sont pas nécessairement titulaires."
    )


# ==========================================
# INTERFACE
# ==========================================

st.title("⚽ FOOT AI PRO V7 ULTIMATE")

st.caption(
    "Matchs réels • Pronostics • Statistiques • Buteurs"
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
    st.header("Bienvenue sur FOOT AI PRO V7")

    st.write(
        "Choisis un match, analyse les performances des équipes "
        "et consulte les statistiques disponibles des buteurs."
    )

    st.markdown("""
    - ⚽ Matchs disponibles
    - 📊 Statistiques des équipes
    - 🎯 Probabilités de résultats
    - 🥅 Scores estimés
    - 🔥 Buteurs et statistiques individuelles
    """)

    st.info(
        "Les statistiques des buteurs dépendent des données "
        "accessibles avec ton API."
    )

# ==========================================
# MATCHS REELS
# ==========================================

elif page == "🌍 Matchs réels":
    st.header("🌍 Matchs disponibles")

    competition_nom = st.selectbox(
        "Compétition",
        list(COMPETITIONS.keys())
    )

    competition = COMPETITIONS[competition_nom]

    debut = st.date_input(
        "Date de début",
        value=date.today()
    )

    fin = st.date_input(
        "Date de fin",
        value=date.today() + timedelta(days=7)
    )

    if fin < debut:
        st.error("La date de fin doit suivre la date de début.")

    elif st.button("🔎 AFFICHER LES MATCHS"):
        with st.spinner("Chargement des matchs..."):
            donnees, erreur = charger_matchs(
                competition,
                debut.isoformat(),
                fin.isoformat()
            )

        if erreur:
            st.error(erreur)

        elif donnees is not None:
            matchs = donnees.get("matches", [])

            if not matchs:
                st.info("Aucun match trouvé pour cette période.")

            for match in matchs:
                dom = match.get("homeTeam", {}).get(
                    "name", "Domicile"
                )

                ext = match.get("awayTeam", {}).get(
                    "name", "Extérieur"
                )

                with st.container(border=True):
                    st.subheader(f"{dom} vs {ext}")

                    st.write(
                        "Date UTC : "
                        + match.get("utcDate", "").replace("T", " ")[:16]
                    )

                    st.write(
                        f"Statut : {match.get('status', 'Inconnu')}"
                    )

                    if st.button(
                        "🤖 ANALYSER CE MATCH",
                        key=f"match_{match.get('id')}"
                    ):
                        st.session_state.match_selectionne = match
                        st.session_state.competition_selectionnee = competition
                        st.session_state.resultat_analyse = None
                        st.session_state.erreur_analyse = None

                        st.success(
                            "Match sélectionné ! Ouvre l'onglet Analyse IA."
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
        dom = match.get("homeTeam", {}).get("name", "Domicile")
        ext = match.get("awayTeam", {}).get("name", "Extérieur")

        st.subheader(f"{dom} vs {ext}")

        if st.button(
            "📊 LANCER L'ANALYSE",
            key="lancer_analyse"
        ):
            st.session_state.resultat_analyse = None
            st.session_state.erreur_analyse = None

            with st.spinner(
                "Analyse des équipes et recherche des buteurs..."
            ):
                resultat, erreur = analyser_match(match)

            if erreur:
                st.session_state.erreur_analyse = erreur
            else:
                st.session_state.resultat_analyse = resultat

                score = resultat["probabilites"]["scores"][0][0]

                entree = {
                    "match_id": str(match.get("id")),
                    "match": f"{dom} - {ext}",
                    "score": f"{score[0]} - {score[1]}",
                    "confiance": round(
                        max(
                            resultat["probabilites"]["dom"],
                            resultat["probabilites"]["nul"],
                            resultat["probabilites"]["ext"]
                        ) * 100,
                        1
                    )
                }

                st.session_state.classement = [
                    item for item in st.session_state.classement
                    if item["match_id"] != entree["match_id"]
                ]

                st.session_state.classement.append(entree)

        # Affichage persistant après le clic
        if st.session_state.erreur_analyse:
            st.error(st.session_state.erreur_analyse)

        if st.session_state.resultat_analyse:
            afficher_analyse(
                st.session_state.resultat_analyse,
                st.session_state.competition_selectionnee
            )

# ==========================================
# CLASSEMENT
# ==========================================

elif page == "🏆 Classement":
    st.header("🏆 Classement des pronostics")

    classement = st.session_state.classement

    if not classement:
        st.info(
            "Aucun pronostic pour le moment. Analyse un match d'abord."
        )

    else:
        for numero, entree in enumerate(
            reversed(classement),
            start=1
        ):
            st.markdown(f"### {numero}. {entree['match']}")

            st.write(f"Score estimé : {entree['score']}")

            st.write(
                f"Probabilité la plus élevée parmi 1/N/2 : "
                f"{entree['confiance']} %"
            )

            st.divider()

        if st.button("🗑️ EFFACER LE CLASSEMENT"):
            st.session_state.classement = []
            st.rerun()