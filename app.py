import streamlit as st
import requests
import math
from datetime import date, timedelta

# ==========================================
# FOOT AI PRO V6 ULTIMATE
# ==========================================

st.set_page_config(
    page_title="FOOT AI PRO V6",
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
    "Ligue des Champions ⭐": "CL",
}

st.markdown("""
<style>
.main {
    background-color: #0b1220;
}
h1 {
    color: #00e676;
}
h2, h3 {
    color: #ffffff;
}
div.stButton > button {
    width: 100%;
    border-radius: 10px;
    font-weight: bold;
}
</style>
""", unsafe_allow_html=True)


def obtenir_cle():
    try:
        return st.secrets["FOOTBALL_API_KEY"]
    except Exception:
        return ""


def appel_api(endpoint, params=None):
    cle = obtenir_cle()

    if not cle:
        return None, (
            "Clé API absente. Vérifie les Secrets de ton application "
            "Streamlit."
        )

    try:
        reponse = requests.get(
            f"{API_URL}{endpoint}",
            headers={"X-Auth-Token": cle},
            params=params,
            timeout=20
        )

        if reponse.status_code == 200:
            return reponse.json(), None

        if reponse.status_code == 403:
            return None, (
                "Accès refusé par l'API. Cette compétition ou cette "
                "fonctionnalité n'est peut-être pas incluse dans ton forfait."
            )

        if reponse.status_code == 429:
            return None, (
                "Trop de demandes à l'API. Attends un peu avant de réessayer."
            )

        return None, f"Erreur API : HTTP {reponse.status_code}"

    except requests.RequestException:
        return None, (
            "Impossible de joindre le service des matchs. Réessaie plus tard."
        )


@st.cache_data(ttl=300)
def charger_matchs(competition, date_debut, date_fin):
    return appel_api(
        f"/competitions/{competition}/matches",
        {
            "dateFrom": date_debut,
            "dateTo": date_fin
        }
    )


@st.cache_data(ttl=900)
def derniers_matchs(equipe_id):
    return appel_api(
        f"/teams/{equipe_id}/matches",
        {
            "status": "FINISHED",
            "limit": 5
        }
    )


def calculer_moyennes(matchs, equipe_id):
    buts_marques = []
    buts_encaisses = []

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
            buts_marques.append(buts_dom)
            buts_encaisses.append(buts_ext)

        elif exterieur == equipe_id:
            buts_marques.append(buts_ext)
            buts_encaisses.append(buts_dom)

    if not buts_marques:
        return None

    return {
        "marques": sum(buts_marques) / len(buts_marques),
        "encaisses": sum(buts_encaisses) / len(buts_encaisses),
        "nombre": len(buts_marques)
    }


def loi_poisson(moyenne, buts):
    if moyenne <= 0:
        return 1.0 if buts == 0 else 0.0

    return (
        math.exp(-moyenne)
        * moyenne ** buts
        / math.factorial(buts)
    )


def calculer_pronostic(moyenne_dom, moyenne_ext):
    scores = {}

    for buts_dom in range(8):
        for buts_ext in range(8):
            probabilite = (
                loi_poisson(moyenne_dom, buts_dom)
                * loi_poisson(moyenne_ext, buts_ext)
            )
            scores[(buts_dom, buts_ext)] = probabilite

    total = sum(scores.values())

    if total <= 0:
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

    les_deux = sum(
        p for (d, e), p in scores.items() if d >= 1 and e >= 1
    ) / total

    meilleurs_scores = sorted(
        scores.items(),
        key=lambda item: item[1],
        reverse=True
    )[:5]

    return {
        "dom": victoire_dom,
        "nul": nul,
        "ext": victoire_ext,
        "plus15": plus_15,
        "plus25": plus_25,
        "deux": les_deux,
        "scores": meilleurs_scores
    }


def afficher_analyse(match):
    domicile = match.get("homeTeam", {})
    exterieur = match.get("awayTeam", {})

    nom_dom = domicile.get("name", "Domicile")
    nom_ext = exterieur.get("name", "Extérieur")

    id_dom = domicile.get("id")
    id_ext = exterieur.get("id")

    if not id_dom or not id_ext:
        st.error("Les informations des équipes sont incomplètes.")
        return

    st.subheader(f"⚽ {nom_dom} — {nom_ext}")

    with st.spinner("Analyse des derniers matchs en cours..."):
        historique_dom, erreur_dom = derniers_matchs(id_dom)
        historique_ext, erreur_ext = derniers_matchs(id_ext)

    if erreur_dom:
        st.error(f"Historique de {nom_dom} : {erreur_dom}")
        return

    if erreur_ext:
        st.error(f"Historique de {nom_ext} : {erreur_ext}")
        return

    stats_dom = calculer_moyennes(
        historique_dom.get("matches", []),
        id_dom
    )

    stats_ext = calculer_moyennes(
        historique_ext.get("matches", []),
        id_ext
    )

    if not stats_dom or not stats_ext:
        st.warning(
            "Pas assez de résultats récents disponibles pour calculer "
            "un pronostic fiable."
        )
        return

    st.markdown("### 📊 Comparaison des équipes")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown(f"#### 🏠 {nom_dom}")
        st.metric(
            "Buts marqués par match",
            f"{stats_dom['marques']:.2f}"
        )
        st.metric(
            "Buts encaissés par match",
            f"{stats_dom['encaisses']:.2f}"
        )
        st.caption(
            f"Basé sur {stats_dom['nombre']} match(s) disponible(s)"
        )

    with col2:
        st.markdown(f"#### ✈️ {nom_ext}")
        st.metric(
            "Buts marqués par match",
            f"{stats_ext['marques']:.2f}"
        )
        st.metric(
            "Buts encaissés par match",
            f"{stats_ext['encaisses']:.2f}"
        )
        st.caption(
            f"Basé sur {stats_ext['nombre']} match(s) disponible(s)"
        )

    # Estimation simple combinant attaque et défense.
    moyenne_dom = (
        stats_dom["marques"] + stats_ext["encaisses"]
    ) / 2

    moyenne_ext = (
        stats_ext["marques"] + stats_dom["encaisses"]
    ) / 2

    pronostic = calculer_pronostic(moyenne_dom, moyenne_ext)

    if not pronostic:
        st.error("Impossible de calculer les probabilités.")
        return

    st.markdown("### 🎯 Probabilités du match")

    c1, c2, c3 = st.columns(3)

    with c1:
        st.metric(
            f"Victoire {nom_dom}",
            f"{pronostic['dom'] * 100:.1f} %"
        )

    with c2:
        st.metric(
            "Match nul",
            f"{pronostic['nul'] * 100:.1f} %"
        )

    with c3:
        st.metric(
            f"Victoire {nom_ext}",
            f"{pronostic['ext'] * 100:.1f} %"
        )

    st.markdown("### ⚽ Probabilités de buts")

    c1, c2, c3 = st.columns(3)

    c1.metric(
        "Plus de 1,5 but",
        f"{pronostic['plus15'] * 100:.1f} %"
    )

    c2.metric(
        "Plus de 2,5 buts",
        f"{pronostic['plus25'] * 100:.1f} %"
    )

    c3.metric(
        "Les deux équipes marquent",
        f"{pronostic['deux'] * 100:.1f} %"
    )

    st.markdown("### 🥅 Scores les plus probables")

    for (buts_dom, buts_ext), probabilite in pronostic["scores"]:
        st.write(
            f"**{nom_dom} {buts_dom} - {buts_ext} {nom_ext}** "
            f"— {probabilite * 100:.1f} %"
        )

    # Enregistrer les analyses dans le classement de la session.
    if "classement" not in st.session_state:
        st.session_state.classement = []

    cle_match = f"{match.get('id')}"

    entree = {
        "match_id": cle_match,
        "match": f"{nom_dom} - {nom_ext}",
        "score": (
            f"{pronostic['scores'][0][0][0]} - "
            f"{pronostic['scores'][0][0][1]}"
        ),
        "confiance": round(
            max(
                pronostic["dom"],
                pronostic["nul"],
                pronostic["ext"]
            ) * 100,
            1
        )
    }

    # Éviter les doublons lors d'une nouvelle analyse.
    st.session_state.classement = [
        x for x in st.session_state.classement
        if x["match_id"] != cle_match
    ]

    st.session_state.classement.append(entree)

    st.info(
        "Ces chiffres sont des estimations statistiques fondées sur les "
        "résultats disponibles, et non des certitudes."
    )


# ==========================================
# INTERFACE
# ==========================================

st.title("⚽ FOOT AI PRO V6")
st.caption("Matchs réels • Statistiques • Probabilités")

if "classement" not in st.session_state:
    st.session_state.classement = []

if "match_selectionne" not in st.session_state:
    st.session_state.match_selectionne = None

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

if page == "🏠 Accueil":
    st.markdown("## Bienvenue sur FOOT AI PRO V6")
    st.write(
        "Consulte les matchs disponibles, compare les équipes et "
        "analyse les probabilités statistiques."
    )

    st.warning(
        "Les pronostics ne garantissent aucun résultat. "
        "Ne mise jamais de l'argent que tu ne peux pas te permettre de perdre."
    )

elif page == "🌍 Matchs réels":
    st.subheader("🌍 Matchs disponibles")

    competition_nom = st.selectbox(
        "Choisir une compétition",
        list(COMPETITIONS.keys())
    )

    aujourd_hui = date.today()

    col1, col2 = st.columns(2)

    with col1:
        date_debut = st.date_input(
            "Date de début",
            aujourd_hui
        )

    with col2:
        date_fin = st.date_input(
            "Date de fin",
            aujourd_hui + timedelta(days=7)
        )

    if date_fin < date_debut:
        st.error("La date de fin doit être après la date de début.")

    elif st.button("🔎 Afficher les matchs"):
        with st.spinner("Chargement des matchs..."):
            resultat, erreur = charger_matchs(
                COMPETITIONS[competition_nom],
                date_debut.isoformat(),
                date_fin.isoformat()
            )

        if erreur:
            st.error(erreur)

        elif resultat is not None:
            matchs = resultat.get("matches", [])

            if not matchs:
                st.info("Aucun match disponible pour cette période.")

            for match in matchs:
                domicile = match.get("homeTeam", {}).get(
                    "name", "Domicile"
                )
                exterieur = match.get("awayTeam", {}).get(
                    "name", "Extérieur"
                )

                statut = match.get("status", "Inconnu")
                date_match = match.get("utcDate", "")[:16].replace("T", " ")

                with st.container(border=True):
                    st.markdown(f"### {domicile} vs {exterieur}")
                    st.write(f"📅 {date_match} UTC")
                    st.write(f"Statut : {statut}")

                    score = match.get("score", {}).get("fullTime", {})
                    if score.get("home") is not None:
                        st.write(
                            f"Score : {score['home']} - {score['away']}"
                        )

                    if st.button(
                        "🤖 Analyser cette rencontre",
                        key=f"analyser_{match.get('id')}"
                    ):
                        st.session_state.match_selectionne = match
                        st.success(
                            "Match sélectionné ! Va dans l'onglet "
                            "🤖 Analyse IA pour lancer l'analyse."
                        )

elif page == "🤖 Analyse IA":
    st.subheader("🤖 Analyse statistique")

    match = st.session_state.match_selectionne

    if match is None:
        st.info(
            "Va dans 🌍 Matchs réels et sélectionne une rencontre "
            "pour commencer."
        )
    else:
        st.write(
            f"{match.get('homeTeam', {}).get('name', '')} "
            f"vs "
            f"{match.get('awayTeam', {}).get('name', '')}"
        )

        if st.button("📊 LANCER L'ANALYSE"):
            afficher_analyse(match)

elif page == "🏆 Classement":
    st.subheader("🏆 Pronostics analysés")

    classement = st.session_state.classement

    if not classement:
        st.info(
            "Aucune analyse dans cette session. Analyse un match pour "
            "le voir apparaître ici."
        )
    else:
        for numero, entree in enumerate(
            reversed(classement),
            start=1
        ):
            st.markdown(
                f"**{numero}. {entree['match']}**  \n"
                f"Score estimé : {entree['score']}  \n"
                f"Probabilité la plus élevée parmi 1/N/2 : "
                f"{entree['confiance']} %"
            )
            st.divider()

        if st.button("🗑️ Effacer le classement"):
            st.session_state.classement = []
            st.rerun()