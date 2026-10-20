import streamlit as st
import requests
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# =====================================================
# CONFIGURATION
# =====================================================

st.set_page_config(
    page_title="Foot AI PRO",
    page_icon="⚽",
    layout="wide"
)

PARIS = ZoneInfo("Europe/Paris")

API_URL = "https://api.football-data.org/v4"

# Championnats de première division uniquement
COMPETITIONS = {
    "Ligue 1": "FL1",
    "Premier League": "PL",
    "Liga": "PD",
    "Bundesliga": "BL1",
    "Serie A": "SA",
    "Primeira Liga": "PPL",
    "Eredivisie": "DED",
    "Jupiler Pro League": "BJL",
    "Süper Lig": "TSL",
    "Ligue des champions": "CL",
    "Ligue Europa": "EL",
}

# =====================================================
# STYLE
# =====================================================

st.markdown("""
<style>
.stApp {
    background-color: #101820;
    color: white;
}
h1, h2, h3 {
    color: #00E676;
}
div[data-testid="stMetric"] {
    background-color: #1d2b36;
    padding: 15px;
    border-radius: 10px;
}
</style>
""", unsafe_allow_html=True)

st.title("⚽ FOOT AI PRO")
st.caption("Analyse statistique des matchs de football du jour")

# =====================================================
# DATE DU JOUR
# =====================================================

def maintenant_paris():
    return datetime.now(PARIS)


def date_paris():
    return maintenant_paris().date()


# =====================================================
# API FOOTBALL-DATA.ORG
# =====================================================

def obtenir_cle_api():
    try:
        return st.secrets["FOOTBALL_API_KEY"]
    except Exception:
        return None


def appel_api(endpoint, params=None):
    cle = obtenir_cle_api()

    if not cle:
        return None, "Clé API manquante"

    headers = {
        "X-Auth-Token": cle
    }

    try:
        reponse = requests.get(
            f"{API_URL}/{endpoint}",
            headers=headers,
            params=params,
            timeout=25
        )

        if reponse.status_code == 200:
            return reponse.json(), None

        if reponse.status_code == 401:
            return None, "401 : clé API invalide ou non reconnue."

        if reponse.status_code == 403:
            return None, (
                "403 : accès refusé à cette ressource ou "
                "à certaines compétitions avec cette clé API."
            )

        if reponse.status_code == 429:
            return None, (
                "429 : limite de requêtes atteinte. "
                "Attends un peu avant de réessayer."
            )

        return None, (
            f"Erreur API {reponse.status_code} : "
            f"{reponse.text[:250]}"
        )

    except requests.exceptions.Timeout:
        return None, "Délai dépassé lors de la connexion à l'API."

    except requests.exceptions.RequestException as erreur:
        return None, f"Erreur de connexion : {erreur}"


# =====================================================
# RÉCUPÉRATION DES MATCHS DU JOUR
# Une seule requête pour le calendrier
# =====================================================

@st.cache_data(ttl=300)
def charger_matchs_du_jour(date_cible):
    debut = f"{date_cible}T00:00:00"
    fin = f"{date_cible}T23:59:59"

    donnees, erreur = appel_api(
        "matches",
        {
            "dateFrom": date_cible,
            "dateTo": date_cible
        }
    )

    if erreur:
        return [], [erreur]

    matchs = donnees.get("matches", [])
    codes_autorises = set(COMPETITIONS.values())

    resultat = []
    maintenant = maintenant_paris()

    for match in matchs:
        competition = match.get("competition", {})
        code = competition.get("code")

        if code not in codes_autorises:
            continue

        statut = match.get("status")

        # On ne garde que les matchs pas encore commencés
        if statut not in ["SCHEDULED", "TIMED"]:
            continue

        coup_envoi = match.get("utcDate")

        if not coup_envoi:
            continue

        try:
            date_match = datetime.fromisoformat(
                coup_envoi.replace("Z", "+00:00")
            ).astimezone(PARIS)
        except (ValueError, TypeError):
            continue

        # Match du jour en heure française et encore à venir
        if date_match.date() != date_cible:
            continue

        if date_match <= maintenant:
            continue

        match["heure_paris"] = date_match.strftime("%H:%M")
        resultat.append(match)

    resultat.sort(key=lambda m: m["utcDate"])

    return resultat, []


# =====================================================
# RÉCUPÉRATION DES RÉSULTATS RÉCENTS
# Une seule requête pour les statistiques
# =====================================================

@st.cache_data(ttl=1800)
def charger_resultats():
    aujourd_hui = date_paris()
    debut = aujourd_hui - timedelta(days=90)

    donnees, erreur = appel_api(
        "matches",
        {
            "dateFrom": debut.isoformat(),
            "dateTo": aujourd_hui.isoformat(),
            "status": "FINISHED"
        }
    )

    if erreur:
        return [], [erreur]

    codes_autorises = set(COMPETITIONS.values())
    resultats = []

    for match in donnees.get("matches", []):
        code = match.get("competition", {}).get("code")

        if code not in codes_autorises:
            continue

        score = match.get("score", {}).get("fullTime", {})
        domicile = score.get("home")
        exterieur = score.get("away")

        if domicile is None or exterieur is None:
            continue

        match["buts_domicile"] = domicile
        match["buts_exterieur"] = exterieur

        resultats.append(match)

    return resultats, []


# =====================================================
# STATISTIQUES DES ÉQUIPES
# =====================================================

def statistiques_equipe(team_id, resultats, domicile=None):
    matchs_equipe = []

    for match in resultats:
        home_id = match.get("homeTeam", {}).get("id")
        away_id = match.get("awayTeam", {}).get("id")

        if domicile is True:
            if home_id != team_id:
                continue

        elif domicile is False:
            if away_id != team_id:
                continue

        else:
            if team_id not in [home_id, away_id]:
                continue

        matchs_equipe.append(match)

    matchs_equipe.sort(
        key=lambda m: m.get("utcDate", ""),
        reverse=True
    )

    matchs_equipe = matchs_equipe[:5]

    if not matchs_equipe:
        return {
            "joues": 0,
            "victoires": 0,
            "nuls": 0,
            "defaites": 0,
            "buts_marques": 1.2,
            "buts_encaisses": 1.2,
            "forme": "Inconnue"
        }

    victoires = 0
    nuls = 0
    defaites = 0
    buts_marques = 0
    buts_encaisses = 0
    forme = []

    for match in matchs_equipe:
        home_id = match.get("homeTeam", {}).get("id")

        if home_id == team_id:
            marques = match["buts_domicile"]
            encaisses = match["buts_exterieur"]
        else:
            marques = match["buts_exterieur"]
            encaisses = match["buts_domicile"]

        buts_marques += marques
        buts_encaisses += encaisses

        if marques > encaisses:
            victoires += 1
            forme.append("V")
        elif marques == encaisses:
            nuls += 1
            forme.append("N")
        else:
            defaites += 1
            forme.append("D")

    nombre = len(matchs_equipe)

    return {
        "joues": nombre,
        "victoires": victoires,
        "nuls": nuls,
        "defaites": defaites,
        "buts_marques": buts_marques / nombre,
        "buts_encaisses": buts_encaisses / nombre,
        "forme": " - ".join(forme)
    }


# =====================================================
# MODÈLE DE POISSON
# =====================================================

def probabilite_poisson(k, moyenne):
    if moyenne <= 0:
        return 1.0 if k == 0 else 0.0

    return (
        math.exp(-moyenne)
        * moyenne ** k
        / math.factorial(k)
    )


def analyser_match(match, resultats):
    domicile = match.get("homeTeam", {})
    exterieur = match.get("awayTeam", {})

    id_domicile = domicile.get("id")
    id_exterieur = exterieur.get("id")

    stats_dom = statistiques_equipe(
        id_domicile,
        resultats
    )

    stats_ext = statistiques_equipe(
        id_exterieur,
        resultats
    )

    # Estimation simple à partir des cinq derniers matchs.
    # Avantage domicile inclus dans l'estimation.
    moyenne_dom = (
        stats_dom["buts_marques"]
        + stats_ext["buts_encaisses"]
    ) / 2

    moyenne_ext = (
        stats_ext["buts_marques"]
        + stats_dom["buts_encaisses"]
    ) / 2

    moyenne_dom = max(0.15, min(4.0, moyenne_dom * 1.12))
    moyenne_ext = max(0.15, min(4.0, moyenne_ext * 0.92))

    proba_dom = 0
    proba_nul = 0
    proba_ext = 0
    proba_plus_15 = 0
    proba_plus_25 = 0
    proba_btts = 0

    for buts_dom in range(11):
        for buts_ext in range(11):
            p = (
                probabilite_poisson(buts_dom, moyenne_dom)
                * probabilite_poisson(buts_ext, moyenne_ext)
            )

            if buts_dom > buts_ext:
                proba_dom += p
            elif buts_dom == buts_ext:
                proba_nul += p
            else:
                proba_ext += p

            total = buts_dom + buts_ext

            if total >= 2:
                proba_plus_15 += p

            if total >= 3:
                proba_plus_25 += p

            if buts_dom >= 1 and buts_ext >= 1:
                proba_btts += p

    probabilites = {
        "Victoire domicile": proba_dom,
        "Match nul": proba_nul,
        "Victoire extérieur": proba_ext,
        "Plus de 1,5 but": proba_plus_15,
        "Plus de 2,5 buts": proba_plus_25,
        "Les deux équipes marquent": proba_btts
    }

    meilleur = max(
        probabilites.items(),
        key=lambda item: item[1]
    )

    return {
        "domicile": domicile.get("name", "Domicile"),
        "exterieur": exterieur.get("name", "Extérieur"),
        "heure": match.get("heure_paris", "--:--"),
        "competition": match.get("competition", {}).get(
            "name", "Compétition"
        ),
        "moyenne_dom": moyenne_dom,
        "moyenne_ext": moyenne_ext,
        "stats_dom": stats_dom,
        "stats_ext": stats_ext,
        "probabilites": probabilites,
        "meilleur_marche": meilleur[0],
        "meilleure_proba": meilleur[1]
    }


# =====================================================
# CHARGEMENT DES DONNÉES
# =====================================================

if not obtenir_cle_api():
    st.error(
        "Clé API absente. Dans Streamlit, ouvre "
        "Settings > Secrets et vérifie la présence de "
        "FOOTBALL_API_KEY."
    )
    st.stop()

aujourd_hui = date_paris()

st.info(
    f"📅 Matchs du {aujourd_hui.strftime('%d/%m/%Y')} "
    "— heure française"
)

with st.spinner("Chargement des matchs du jour..."):
    matchs, erreurs_matchs = charger_matchs_du_jour(
        aujourd_hui.isoformat()
    )

with st.spinner("Chargement des derniers résultats..."):
    resultats, erreurs_resultats = charger_resultats()

# =====================================================
# ONGLETS
# =====================================================

tab_accueil, tab_matchs, tab_combine, tab_stats = st.tabs([
    "🏠 Accueil",
    "⚽ Matchs du jour",
    "🧠 Combiné IA",
    "📊 Statistiques"
])

# =====================================================
# ACCUEIL
# =====================================================

with tab_accueil:
    st.subheader("Bienvenue sur Foot AI PRO")

    c1, c2, c3 = st.columns(3)

    c1.metric("Matchs à venir", len(matchs))
    c2.metric("Résultats chargés", len(resultats))
    c3.metric("Championnats", len(COMPETITIONS))

    st.write(
        "L'application utilise les résultats récents "
        "pour estimer les probabilités des matchs."
    )

    st.warning(
        "Les probabilités sont des estimations statistiques, "
        "pas des garanties. Les cotes des bookmakers ne sont "
        "pas fournies par cette API."
    )

# =====================================================
# MATCHS DU JOUR
# =====================================================

with tab_matchs:
    st.subheader("Les matchs qui restent à jouer")

    if erreurs_matchs:
        for erreur in erreurs_matchs:
            st.error(erreur)

    elif not matchs:
        st.warning(
            "Aucun match à venir n'a été trouvé aujourd'hui "
            "dans les compétitions sélectionnées."
        )

        st.write(
            "Vérifie l'onglet Statistiques si tu penses "
            "qu'il devrait y avoir des matchs."
        )

    else:
        for match in matchs:
            analyse = analyser_match(match, resultats)

            with st.container(border=True):
                st.markdown(
                    f"### {analyse['domicile']} "
                    f"vs {analyse['exterieur']}"
                )

                st.caption(
                    f"{analyse['competition']} "
                    f"— Coup d'envoi à {analyse['heure']}"
                )

                col1, col2, col3 = st.columns(3)

                col1.metric(
                    "Victoire domicile",
                    f"{analyse['probabilites']['Victoire domicile'] * 100:.1f}%"
                )

                col2.metric(
                    "Match nul",
                    f"{analyse['probabilites']['Match nul'] * 100:.1f}%"
                )

                col3.metric(
                    "Victoire extérieur",
                    f"{analyse['probabilites']['Victoire extérieur'] * 100:.1f}%"
                )

                st.write(
                    "**Plus de 1,5 but :** "
                    f"{analyse['probabilites']['Plus de 1,5 but'] * 100:.1f}%"
                )

                st.write(
                    "**Plus de 2,5 buts :** "
                    f"{analyse['probabilites']['Plus de 2,5 buts'] * 100:.1f}%"
                )

                st.write(
                    "**Les deux équipes marquent :** "
                    f"{analyse['probabilites']['Les deux équipes marquent'] * 100:.1f}%"
                )

                st.success(
                    f"Marché le plus probable selon le modèle : "
                    f"{analyse['meilleur_marche']} "
                    f"({analyse['meilleure_proba'] * 100:.1f}%)"
                )

                with st.expander("Voir la forme des équipes"):
                    st.write(
                        f"**{analyse['domicile']} :** "
                        f"{analyse['stats_dom']['forme']}"
                    )

                    st.write(
                        f"**{analyse['exterieur']} :** "
                        f"{analyse['stats_ext']['forme']}"
                    )

                    st.write(
                        f"Buts moyens estimés : "
                        f"{analyse['moyenne_dom']:.2f} - "
                        f"{analyse['moyenne_ext']:.2f}"
                    )

# =====================================================
# COMBINÉ IA
# =====================================================

with tab_combine:
    st.subheader("Combiné de deux matchs")

    st.write(
        "L'application sélectionne les deux marchés ayant "
        "les probabilités estimées les plus élevées parmi "
        "les matchs du jour."
    )

    if erreurs_matchs:
        st.error(
            "Impossible de construire le combiné tant que "
            "le chargement des matchs rencontre une erreur."
        )

    elif erreurs_resultats:
        st.error(
            "Les résultats récents n'ont pas pu être chargés. "
            "Les analyses ne sont pas suffisamment disponibles."
        )

    else:
        candidats = []

        for match in matchs:
            analyse = analyser_match(match, resultats)

            candidats.append({
                "analyse": analyse,
                "probabilite": analyse["meilleure_proba"],
                "marche": analyse["meilleur_marche"]
            })

        candidats.sort(
            key=lambda item: item["probabilite"],
            reverse=True
        )

        if len(candidats) < 2:
            st.warning(
                "Il faut au moins deux matchs à venir "
                "pour proposer un combiné."
            )

        else:
            selection = candidats[:2]

            probabilite_combine = (
                selection[0]["probabilite"]
                * selection[1]["probabilite"]
            )

            for numero, candidat in enumerate(selection, start=1):
                a = candidat["analyse"]

                st.markdown(f"### Sélection {numero}")

                st.write(
                    f"**{a['domicile']} vs {a['exterieur']}**"
                )

                st.write(f"Marché : {candidat['marche']}")

                st.write(
                    "Probabilité estimée : "
                    f"{candidat['probabilite'] * 100:.1f}%"
                )

            st.divider()

            st.metric(
                "Probabilité théorique du combiné",
                f"{probabilite_combine * 100:.1f}%"
            )

            st.caption(
                "Cette estimation multiplie les probabilités "
                "des deux sélections en supposant leur indépendance. "
                "Cette hypothèse peut être imparfaite. Le modèle "
                "n'est pas calibré sur des performances garanties."
            )

            st.warning(
                "Une probabilité élevée ne signifie pas qu'un "
                "pari est sûr. Les cotes réelles ne sont pas "
                "disponibles via cette API."
            )

            st.write("### Cotes du bookmaker")

            cote1 = st.number_input(
                "Cote de la sélection 1",
                min_value=1.0,
                max_value=100.0,
                value=1.30,
                step=0.05
            )

            cote2 = st.number_input(
                "Cote de la sélection 2",
                min_value=1.0,
                max_value=100.0,
                value=1.30,
                step=0.05
            )

            cote_combine = cote1 * cote2

            st.metric(
                "Cote totale du combiné",
                f"{cote_combine:.2f}"
            )

            if 1.50 <= cote_combine <= 2.00:
                st.success(
                    "La cote totale se situe entre 1,50 et 2,00."
                )
            else:
                st.info(
                    "La cote totale est en dehors de la plage "
                    "1,50–2,00. Ajuste les cotes saisies si "
                    "elles correspondent à d'autres marchés."
                )

# =====================================================
# STATISTIQUES ET ERREURS
# =====================================================

with tab_stats:
    st.subheader("État de l'application")

    st.write("### Compétitions configurées")

    for nom, code in COMPETITIONS.items():
        st.write(f"- {nom} (`{code}`)")

    st.write("### Résultats de chargement")

    st.write(f"Matchs à venir trouvés : {len(matchs)}")
    st.write(f"Résultats récupérés : {len(resultats)}")

    if erreurs_matchs:
        st.error("Erreur lors du chargement des matchs")

        for erreur in erreurs_matchs:
            st.code(erreur)

    if erreurs_resultats:
        st.error("Erreur lors du chargement des résultats")

        for erreur in erreurs_resultats:
            st.code(erreur)

    if not erreurs_matchs and not erreurs_resultats:
        st.success("Les requêtes API ont fonctionné.")

    st.caption(
        "Les compétitions disponibles dépendent des droits "
        "associés à la clé football-data.org."
    )

    if st.button("🔄 Actualiser les données"):
        st.cache_data.clear()
        st.rerun()