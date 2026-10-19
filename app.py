import streamlit as st
import requests
import math
from datetime import date, timedelta

st.set_page_config(
    page_title="FOOT AI PRO V5",
    page_icon="⚽",
    layout="wide"
)

API_URL = "https://api.football-data.org/v4"

COMPETITIONS = {
    "Ligue 1 🇫🇷": "FL1",
    "Premier League 🇬🇧": "PL",
    "Liga 🇪🇸": "PD",
    "Bundesliga 🇩🇪": "BL1",
    "Serie A 🇮🇹": "SA",
    "Ligue des Champions 🏆": "CL",
}

st.markdown("""
<style>
.stApp {
    background: linear-gradient(135deg, #071b16, #102b23);
}
h1, h2, h3 {
    color: #00e676 !important;
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


def get_api_key():
    try:
        return st.secrets["FOOTBALL_API_KEY"]
    except Exception:
        return ""


def api_get(endpoint, params=None):
    key = get_api_key()

    if not key:
        return None, "Clé API absente dans les Secrets Streamlit."

    try:
        response = requests.get(
            API_URL + endpoint,
            headers={"X-Auth-Token": key},
            params=params,
            timeout=20
        )

        if response.status_code == 200:
            return response.json(), None

        if response.status_code == 401:
            return None, "Clé API invalide."

        if response.status_code == 403:
            return None, "Accès refusé pour cette donnée avec ton offre API."

        if response.status_code == 429:
            return None, "Limite de requêtes atteinte. Réessaie plus tard."

        return None, f"Erreur API : {response.status_code}"

    except requests.exceptions.RequestException:
        return None, "Connexion au service football impossible."


@st.cache_data(ttl=300)
def charger_matchs(competition, debut, fin):
    data, error = api_get(
        f"/competitions/{competition}/matches",
        {"dateFrom": debut, "dateTo": fin}
    )
    if error:
        return None, error
    return data.get("matches", []), None


@st.cache_data(ttl=900)
def derniers_matchs(team_id):
    data, error = api_get(
        f"/teams/{team_id}/matches",
        {"status": "FINISHED", "limit": 5}
    )
    if error:
        return None, error
    return data.get("matches", []), None


def nom_equipe(match, cote):
    return match.get(cote, {}).get("name", "Équipe inconnue")


def date_fr(texte):
    if not texte:
        return "Date inconnue"
    return texte.replace("T", " ")[:16] + " UTC"


def calculer_moyennes(matchs, team_id):
    """
    Calcule les buts marqués et encaissés par match
    à partir des résultats terminés récupérés par l'API.
    """
    if not matchs:
        return None

    marques = []
    encaisses = []

    for match in matchs:
        if match.get("status") != "FINISHED":
            continue

        domicile_id = match.get("homeTeam", {}).get("id")
        exterieur_id = match.get("awayTeam", {}).get("id")

        score = match.get("score", {}).get("fullTime", {})
        buts_dom = score.get("home")
        buts_ext = score.get("away")

        if buts_dom is None or buts_ext is None:
            continue

        if domicile_id == team_id:
            marques.append(buts_dom)
            encaisses.append(buts_ext)
        elif exterieur_id == team_id:
            marques.append(buts_ext)
            encaisses.append(buts_dom)

    if not marques:
        return None

    return {
        "marques": sum(marques) / len(marques),
        "encaisses": sum(encaisses) / len(encaisses),
        "nombre": len(marques),
    }


def poisson(moyenne, maximum=10):
    return [
        math.exp(-moyenne) * moyenne**i / math.factorial(i)
        for i in range(maximum + 1)
    ]


def analyser(moyenne_dom, moyenne_ext):
    p_dom = poisson(moyenne_dom)
    p_ext = poisson(moyenne_ext)

    victoire_dom = 0.0
    nul = 0.0
    victoire_ext = 0.0
    deux_marquent = 0.0
    plus_25 = 0.0
    scores = []

    for buts_dom, prob_dom in enumerate(p_dom):
        for buts_ext, prob_ext in enumerate(p_ext):
            probabilite = prob_dom * prob_ext
            scores.append((probabilite, buts_dom, buts_ext))

            if buts_dom > buts_ext:
                victoire_dom += probabilite
            elif buts_dom == buts_ext:
                nul += probabilite
            else:
                victoire_ext += probabilite

            if buts_dom > 0 and buts_ext > 0:
                deux_marquent += probabilite

            if buts_dom + buts_ext >= 3:
                plus_25 += probabilite

    scores.sort(reverse=True)

    return {
        "dom": victoire_dom,
        "nul": nul,
        "ext": victoire_ext,
        "scores": scores[:5],
        "btts": deux_marquent,
        "over25": plus_25,
    }


def afficher_analyse(match):
    domicile = match.get("homeTeam", {})
    exterieur = match.get("awayTeam", {})

    nom_dom = domicile.get("name", "Domicile")
    nom_ext = exterieur.get("name", "Extérieur")

    id_dom = domicile.get("id")
    id_ext = exterieur.get("id")

    if not id_dom or not id_ext:
        st.error("Les identifiants des équipes sont indisponibles.")
        return None

    with st.spinner("Analyse des derniers résultats..."):
        matchs_dom, erreur_dom = derniers_matchs(id_dom)
        matchs_ext, erreur_ext = derniers_matchs(id_ext)

    if erreur_dom or erreur_ext:
        st.warning(
            "Impossible de récupérer tous les derniers matchs. "
            "Vérifie les accès autorisés par ton API."
        )
        if erreur_dom:
            st.caption(f"Équipe à domicile : {erreur_dom}")
        if erreur_ext:
            st.caption(f"Équipe à l'extérieur : {erreur_ext}")
        return None

    stats_dom = calculer_moyennes(matchs_dom, id_dom)
    stats_ext = calculer_moyennes(matchs_ext, id_ext)

    if not stats_dom or not stats_ext:
        st.warning("Pas assez de résultats terminés pour cette analyse.")
        return None

    # Estimation à partir des moyennes récentes.
    buts_attendus_dom = (
        stats_dom["marques"] + stats_ext["encaisses"]
    ) / 2

    buts_attendus_ext = (
        stats_ext["marques"] + stats_dom["encaisses"]
    ) / 2

    resultat = analyser(buts_attendus_dom, buts_attendus_ext)

    st.subheader(f"⚽ {nom_dom} — {nom_ext}")

    c1, c2, c3 = st.columns(3)
    c1.metric("Victoire domicile", f"{resultat['dom'] * 100:.1f} %")
    c2.metric("Match nul", f"{resultat['nul'] * 100:.1f} %")
    c3.metric("Victoire extérieur", f"{resultat['ext'] * 100:.1f} %")

    st.markdown("### 📊 Forme récente")

    c4, c5 = st.columns(2)

    with c4:
        st.write(f"**{nom_dom}**")
        st.write(f"Matchs analysés : {stats_dom['nombre']}")
        st.write(f"Buts marqués / match : {stats_dom['marques']:.2f}")
        st.write(f"Buts encaissés / match : {stats_dom['encaisses']:.2f}")

    with c5:
        st.write(f"**{nom_ext}**")
        st.write(f"Matchs analysés : {stats_ext['nombre']}")
        st.write(f"Buts marqués / match : {stats_ext['marques']:.2f}")
        st.write(f"Buts encaissés / match : {stats_ext['encaisses']:.2f}")

    st.markdown("### 🎯 Les 5 scores les plus probables")

    for probabilite, buts_dom, buts_ext in resultat["scores"]:
        st.write(
            f"**{nom_dom} {buts_dom} - {buts_ext} {nom_ext}** "
            f"— {probabilite * 100:.1f} %"
        )

    c6, c7 = st.columns(2)
    c6.metric("Plus de 2,5 buts", f"{resultat['over25'] * 100:.1f} %")
    c7.metric("Moins de 2,5 buts", f"{(1-resultat['over25']) * 100:.1f} %")

    c8, c9 = st.columns(2)
    c8.metric("Les deux marquent : oui", f"{resultat['btts'] * 100:.1f} %")
    c9.metric("Les deux marquent : non", f"{(1-resultat['btts']) * 100:.1f} %")

    choix = {
        f"Victoire {nom_dom}": resultat["dom"],
        "Match nul": resultat["nul"],
        f"Victoire {nom_ext}": resultat["ext"],
    }

    meilleur = max(choix, key=choix.get)

    st.success(
        f"🏆 Pronostic principal : {meilleur} "
        f"({choix[meilleur] * 100:.1f} %)"
    )

    st.caption(
        "Estimation statistique basée sur les derniers résultats disponibles. "
        "Ce modèle simplifié ne tient pas compte de toutes les variables "
        "sportives et ne garantit aucun résultat."
    )

    return {
        "match": f"{nom_dom} — {nom_ext}",
        "pronostic": meilleur,
        "probabilite": max(choix.values()),
    }


st.title("⚽ FOOT AI PRO V5")
st.subheader("👑 ULTIMATE — Analyse statistique du football")

st.caption(
    "Matchs réels, forme récente et probabilités estimées."
)

if not get_api_key():
    st.error(
        "Clé API absente. Configure FOOTBALL_API_KEY dans "
        "les Secrets de Streamlit."
    )
    st.stop()

page = st.radio(
    "Navigation",
    [
        "🏠 Accueil",
        "🌍 Matchs réels",
        "🤖 Analyse IA",
        "🏆 Classement des pronostics",
    ],
    horizontal=True,
)

if "matchs_charges" not in st.session_state:
    st.session_state.matchs_charges = []

if "classement" not in st.session_state:
    st.session_state.classement = []


if page == "🏠 Accueil":
    st.markdown("### Bienvenue sur Foot AI PRO V5")

    st.write(
        "Consulte les rencontres disponibles, sélectionne un match "
        "et lance une analyse statistique à partir des résultats récents."
    )

    st.info(
        "Les compétitions et les statistiques accessibles dépendent "
        "des autorisations de ta clé API."
    )


elif page == "🌍 Matchs réels":
    st.header("🌍 Calendrier des matchs")

    competition_nom = st.selectbox(
        "Compétition",
        list(COMPETITIONS.keys()),
    )

    code = COMPETITIONS[competition_nom]

    debut = st.date_input("Date de début", date.today())
    fin = st.date_input(
        "Date de fin",
        date.today() + timedelta(days=7),
    )

    if fin < debut:
        st.error("La date de fin doit être après la date de début.")
        st.stop()

    if st.button("🔄 CHARGER LES MATCHS"):
        with st.spinner("Récupération du calendrier..."):
            matchs, erreur = charger_matchs(
                code,
                debut.isoformat(),
                fin.isoformat(),
            )

        if erreur:
            st.error(erreur)
        elif not matchs:
            st.warning("Aucun match trouvé sur cette période.")
            st.session_state.matchs_charges = []
        else:
            st.session_state.matchs_charges = matchs
            st.success(f"{len(matchs)} rencontre(s) trouvée(s).")

    for index, match in enumerate(st.session_state.matchs_charges):
        nom_dom = nom_equipe(match, "homeTeam")
        nom_ext = nom_equipe(match, "awayTeam")

        with st.container(border=True):
            st.subheader(f"⚽ {nom_dom} — {nom_ext}")
            st.write(f"📅 {date_fr(match.get('utcDate'))}")
            st.write(f"Statut : {match.get('status', 'Inconnu')}")

            score = match.get("score", {}).get("fullTime", {})
            if score.get("home") is not None:
                st.write(f"Score : {score['home']} - {score['away']}")

            if match.get("status") == "FINISHED":
                st.caption("Cette rencontre est déjà terminée.")

            if st.button("🤖 Analyser cette rencontre", key=f"match_{index}"):
                st.session_state.match_a_analyser = match
                st.session_state.page_analyse = True
                st.rerun()


elif page == "🤖 Analyse IA":
    st.header("🤖 Analyse IA")

    match_selectionne = st.session_state.get("match_a_analyser")

    if match_selectionne:
        st.info(
            "Une rencontre a été sélectionnée depuis le calendrier. "
            "Tu peux lancer son analyse ci-dessous."
        )

        if st.button("📊 LANCER L'ANALYSE"):
            resultat = afficher_analyse(match_selectionne)

            if resultat:
                st.session_state.classement.append(resultat)

    else:
        st.write(
            "Pour analyser un match réel, ouvre « Matchs réels » "
            "et sélectionne une rencontre."
        )


elif page == "🏆 Classement des pronostics":
    st.header("🏆 Classement des analyses réalisées")

    classement = st.session_state.classement

    if not classement:
        st.info(
            "Aucune analyse enregistrée pour le moment. "
            "Lance une analyse depuis la page Analyse IA."
        )
    else:
        classement_trie = sorted(
            classement,
            key=lambda item: item["probabilite"],
            reverse=True,
        )

        for numero, resultat in enumerate(classement_trie, start=1):
            st.write(
                f"**{numero}. {resultat['match']}** — "
                f"{resultat['pronostic']} — "
                f"{resultat['probabilite'] * 100:.1f} %"
            )

st.divider()
st.caption(
    "FOOT AI PRO V5 ULTIMATE — Les probabilités sont indicatives. "
    "Un classement par probabilité ne signifie pas qu'un pari est sûr."
)