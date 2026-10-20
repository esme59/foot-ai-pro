import math
import os
from datetime import date, timedelta

import pandas as pd
import requests
import streamlit as st


# ============================================================
# CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="FOOT AI PRO",
    page_icon="⚽",
    layout="wide",
)

API_URL = "https://api.football-data.org/v4"

CHAMPIONNATS = {
    "France - Ligue 1": "FL1",
    "Angleterre - Premier League": "PL",
    "Espagne - Liga": "PD",
    "Allemagne - Bundesliga": "BL1",
    "Italie - Serie A": "SA",
    "Ligue des champions": "CL",
}

st.markdown(
    """
    <style>
    .main {
        background-color: #0e1117;
    }
    .stMetric {
        background-color: #19212c;
        padding: 12px;
        border-radius: 10px;
    }
    div[data-testid="stTabs"] button {
        font-size: 15px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# API FOOTBALL-DATA.ORG
# ============================================================

def obtenir_cle_api():
    try:
        cle = st.secrets.get("FOOTBALL_API_KEY", "")
        if cle:
            return cle
    except Exception:
        pass

    return os.environ.get("FOOTBALL_API_KEY", "")


def appel_api(endpoint, params=None):
    cle = obtenir_cle_api()

    if not cle:
        return {
            "_erreur": (
                "Clé API manquante. Ajoute FOOTBALL_API_KEY "
                "dans les Secrets de ton application Streamlit."
            )
        }

    try:
        reponse = requests.get(
            f"{API_URL}{endpoint}",
            headers={"X-Auth-Token": cle},
            params=params or {},
            timeout=20,
        )

        if reponse.status_code == 200:
            return reponse.json()

        if reponse.status_code == 401:
            return {
                "_erreur": (
                    "Clé API invalide. Vérifie FOOTBALL_API_KEY "
                    "dans les Secrets Streamlit."
                )
            }

        if reponse.status_code == 403:
            return {
                "_erreur": (
                    "Accès refusé par football-data.org. "
                    "Ton abonnement API ne permet peut-être pas "
                    "d'accéder à cette compétition ou à ces données."
                )
            }

        if reponse.status_code == 404:
            return {
                "_erreur": "Données introuvables pour cette demande."
            }

        if reponse.status_code == 429:
            return {
                "_erreur": (
                    "Limite de requêtes API atteinte. "
                    "Attends un peu avant de recommencer."
                )
            }

        return {
            "_erreur": (
                f"Erreur API HTTP {reponse.status_code} : "
                f"{reponse.text[:250]}"
            )
        }

    except requests.exceptions.Timeout:
        return {"_erreur": "Le serveur API met trop de temps à répondre."}

    except requests.exceptions.RequestException as erreur:
        return {"_erreur": f"Erreur de connexion : {erreur}"}


def verifier_erreur(donnees):
    if isinstance(donnees, dict):
        return donnees.get("_erreur")
    return None


# ============================================================
# RÉCUPÉRATION DES MATCHS
# ============================================================

@st.cache_data(ttl=300)
def charger_matchs(code, date_debut, date_fin):
    donnees = appel_api(
        f"/competitions/{code}/matches",
        {
            "dateFrom": date_debut,
            "dateTo": date_fin,
        },
    )

    if verifier_erreur(donnees):
        return {"_erreur": verifier_erreur(donnees)}

    return donnees.get("matches", [])


def nom_equipe(match, domicile=True):
    cle = "homeTeam" if domicile else "awayTeam"
    equipe = match.get(cle, {})
    return equipe.get("name") or equipe.get("shortName") or "Équipe inconnue"


def identifiant_equipe(match, domicile=True):
    cle = "homeTeam" if domicile else "awayTeam"
    return match.get(cle, {}).get("id")


def formater_match(match):
    domicile = nom_equipe(match, True)
    exterieur = nom_equipe(match, False)

    score = match.get("score", {}).get("fullTime", {})
    buts_dom = score.get("home")
    buts_ext = score.get("away")

    if buts_dom is not None and buts_ext is not None:
        resultat = f"{buts_dom} - {buts_ext}"
    else:
        resultat = "À jouer"

    date_match = match.get("utcDate", "")
    if date_match:
        date_match = date_match.replace("T", " ")[:16]
    else:
        date_match = "Date inconnue"

    return {
        "Date": date_match,
        "Compétition": match.get("competition", {}).get("name", ""),
        "Domicile": domicile,
        "Score": resultat,
        "Extérieur": exterieur,
        "Statut": match.get("status", ""),
        "ID": match.get("id"),
    }


# ============================================================
# HISTORIQUE DES ÉQUIPES
# ============================================================

@st.cache_data(ttl=900)
def derniers_matchs_equipe(equipe_id, date_reference):
    if not equipe_id:
        return []

    try:
        reference = date.fromisoformat(str(date_reference)[:10])
    except ValueError:
        reference = date.today()

    # On s'arrête la veille du match cible afin d'éviter
    # d'utiliser le résultat du match à pronostiquer.
    date_fin = reference - timedelta(days=1)
    date_debut = date_fin - timedelta(days=365)

    if date_fin < date_debut:
        return []

    donnees = appel_api(
        f"/teams/{equipe_id}/matches",
        {
            "dateFrom": date_debut.isoformat(),
            "dateTo": date_fin.isoformat(),
            "status": "FINISHED",
            "limit": 100,
        },
    )

    if verifier_erreur(donnees):
        return {"_erreur": verifier_erreur(donnees)}

    matchs = donnees.get("matches", [])

    matchs_valides = []

    for match in matchs:
        if match.get("status") != "FINISHED":
            continue

        score = match.get("score", {}).get("fullTime", {})

        if score.get("home") is None or score.get("away") is None:
            continue

        matchs_valides.append(match)

    matchs_valides.sort(
        key=lambda m: m.get("utcDate", ""),
        reverse=True,
    )

    return matchs_valides[:5]


def statistiques_equipe(equipe_id, nom, date_reference):
    matchs = derniers_matchs_equipe(equipe_id, date_reference)

    if isinstance(matchs, dict) and matchs.get("_erreur"):
        return {
            "nom": nom,
            "matchs": [],
            "erreur": matchs["_erreur"],
            "buts_marques": 1.2,
            "buts_encaisses": 1.2,
            "victoires": 0,
            "nuls": 0,
            "defaites": 0,
            "forme": "Indisponible",
        }

    if not matchs:
        return {
            "nom": nom,
            "matchs": [],
            "erreur": None,
            "buts_marques": 1.2,
            "buts_encaisses": 1.2,
            "victoires": 0,
            "nuls": 0,
            "defaites": 0,
            "forme": "Inconnue",
        }

    marques = []
    encaisses = []
    victoires = 0
    nuls = 0
    defaites = 0
    forme = []

    for match in matchs:
        domicile = match.get("homeTeam", {})
        exterieur = match.get("awayTeam", {})

        score = match.get("score", {}).get("fullTime", {})
        buts_dom = score.get("home")
        buts_ext = score.get("away")

        if buts_dom is None or buts_ext is None:
            continue

        if domicile.get("id") == equipe_id:
            buts_pour = buts_dom
            buts_contre = buts_ext
        elif exterieur.get("id") == equipe_id:
            buts_pour = buts_ext
            buts_contre = buts_dom
        else:
            continue

        marques.append(buts_pour)
        encaisses.append(buts_contre)

        if buts_pour > buts_contre:
            victoires += 1
            forme.append("V")
        elif buts_pour == buts_contre:
            nuls += 1
            forme.append("N")
        else:
            defaites += 1
            forme.append("D")

    if not marques:
        moyenne_marques = 1.2
        moyenne_encaisses = 1.2
    else:
        moyenne_marques = sum(marques) / len(marques)
        moyenne_encaisses = sum(encaisses) / len(encaisses)

    return {
        "nom": nom,
        "matchs": matchs,
        "erreur": None,
        "buts_marques": moyenne_marques,
        "buts_encaisses": moyenne_encaisses,
        "victoires": victoires,
        "nuls": nuls,
        "defaites": defaites,
        "forme": " - ".join(forme) if forme else "Inconnue",
    }


# ============================================================
# MODÈLE STATISTIQUE DE POISSON
# ============================================================

def probabilite_poisson(k, moyenne):
    if moyenne <= 0:
        return 0.0

    return (
        math.exp(-moyenne)
        * (moyenne ** k)
        / math.factorial(k)
    )


def analyser_match(match):
    domicile = nom_equipe(match, True)
    exterieur = nom_equipe(match, False)

    id_dom = identifiant_equipe(match, True)
    id_ext = identifiant_equipe(match, False)

    date_match = match.get("utcDate", "")[:10]

    stats_dom = statistiques_equipe(id_dom, domicile, date_match)
    stats_ext = statistiques_equipe(id_ext, exterieur, date_match)

    # Estimation des buts attendus à partir des 5 derniers matchs.
    moyenne_dom = (
        stats_dom["buts_marques"] + stats_ext["buts_encaisses"]
    ) / 2

    moyenne_ext = (
        stats_ext["buts_marques"] + stats_dom["buts_encaisses"]
    ) / 2

    moyenne_dom = max(0.15, min(moyenne_dom, 5.0))
    moyenne_ext = max(0.15, min(moyenne_ext, 5.0))

    probabilites_scores = {}

    for buts_dom in range(8):
        for buts_ext in range(8):
            probabilites_scores[(buts_dom, buts_ext)] = (
                probabilite_poisson(buts_dom, moyenne_dom)
                * probabilite_poisson(buts_ext, moyenne_ext)
            )

    total = sum(probabilites_scores.values())

    if total <= 0:
        total = 1

    probabilites_scores = {
        score: proba / total
        for score, proba in probabilites_scores.items()
    }

    p1 = sum(
        proba
        for (buts_dom, buts_ext), proba in probabilites_scores.items()
        if buts_dom > buts_ext
    )

    pn = sum(
        proba
        for (buts_dom, buts_ext), proba in probabilites_scores.items()
        if buts_dom == buts_ext
    )

    p2 = sum(
        proba
        for (buts_dom, buts_ext), proba in probabilites_scores.items()
        if buts_dom < buts_ext
    )

    over15 = sum(
        proba
        for (buts_dom, buts_ext), proba in probabilites_scores.items()
        if buts_dom + buts_ext >= 2
    )

    over25 = sum(
        proba
        for (buts_dom, buts_ext), proba in probabilites_scores.items()
        if buts_dom + buts_ext >= 3
    )

    btts = sum(
        proba
        for (buts_dom, buts_ext), proba in probabilites_scores.items()
        if buts_dom >= 1 and buts_ext >= 1
    )

    scores_tries = sorted(
        probabilites_scores.items(),
        key=lambda element: element[1],
        reverse=True,
    )

    meilleur_score = scores_tries[0]

    if p1 >= pn and p1 >= p2:
        resultat_probable = "Victoire domicile"
    elif pn >= p1 and pn >= p2:
        resultat_probable = "Match nul"
    else:
        resultat_probable = "Victoire extérieur"

    return {
        "match": match,
        "domicile": domicile,
        "exterieur": exterieur,
        "stats_dom": stats_dom,
        "stats_ext": stats_ext,
        "moyenne_dom": moyenne_dom,
        "moyenne_ext": moyenne_ext,
        "p1": p1,
        "pn": pn,
        "p2": p2,
        "over15": over15,
        "over25": over25,
        "btts": btts,
        "scores": scores_tries[:5],
        "meilleur_score": meilleur_score,
        "resultat_probable": resultat_probable,
    }


# ============================================================
# PRONOSTIC PRINCIPAL
# ============================================================

def generer_pronostic_principal(analyse):
    choix = [
        ("Plus de 1,5 but", analyse["over15"]),
        ("Double chance 1N", analyse["p1"] + analyse["pn"]),
        ("Double chance N2", analyse["pn"] + analyse["p2"]),
        ("Moins de 3,5 buts", 1 - analyse["over25"]),
    ]

    # On retient le marché avec la meilleure probabilité parmi
    # les options prévues par ce modèle simplifié.
    nom, probabilite = max(choix, key=lambda element: element[1])

    return {
        "choix": nom,
        "probabilite": probabilite,
    }


def afficher_analyse(analyse):
    st.subheader(
        f"⚽ {analyse['domicile']} - {analyse['exterieur']}"
    )

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Victoire domicile",
        f"{analyse['p1'] * 100:.1f} %",
    )

    col2.metric(
        "Match nul",
        f"{analyse['pn'] * 100:.1f} %",
    )

    col3.metric(
        "Victoire extérieur",
        f"{analyse['p2'] * 100:.1f} %",
    )

    st.markdown("### 📊 Probabilités de buts")

    a, b, c = st.columns(3)

    a.metric(
        "Plus de 1,5 but",
        f"{analyse['over15'] * 100:.1f} %",
    )

    b.metric(
        "Plus de 2,5 buts",
        f"{analyse['over25'] * 100:.1f} %",
    )

    c.metric(
        "Les deux équipes marquent",
        f"{analyse['btts'] * 100:.1f} %",
    )

    st.markdown("### 🎯 Pronostic IA principal")

    principal = generer_pronostic_principal(analyse)

    st.success(
        f"{principal['choix']} — "
        f"{principal['probabilite'] * 100:.1f} %"
    )

    score = analyse["meilleur_score"]

    st.markdown(
        f"**Score exact le plus probable :** "
        f"{score[0][0]} - {score[0][1]} "
        f"({score[1] * 100:.1f} %)"
    )

    st.markdown("### 📈 Forme récente")

    col1, col2 = st.columns(2)

    with col1:
        st.write(f"**{analyse['domicile']}**")
        st.write(f"Forme : {analyse['stats_dom']['forme']}")
        st.write(
            "Buts marqués en moyenne : "
            f"{analyse['stats_dom']['buts_marques']:.2f}"
        )
        st.write(
            "Buts encaissés en moyenne : "
            f"{analyse['stats_dom']['buts_encaisses']:.2f}"
        )

    with col2:
        st.write(f"**{analyse['exterieur']}**")
        st.write(f"Forme : {analyse['stats_ext']['forme']}")
        st.write(
            "Buts marqués en moyenne : "
            f"{analyse['stats_ext']['buts_marques']:.2f}"
        )
        st.write(
            "Buts encaissés en moyenne : "
            f"{analyse['stats_ext']['buts_encaisses']:.2f}"
        )

    st.markdown("### 🔢 Les 5 scores exacts les plus probables")

    lignes = []

    for (buts_dom, buts_ext), proba in analyse["scores"]:
        lignes.append({
            "Score": f"{buts_dom} - {buts_ext}",
            "Probabilité estimée": f"{proba * 100:.1f} %",
        })

    st.dataframe(
        pd.DataFrame(lignes),
        use_container_width=True,
        hide_index=True,
    )

    erreurs = [
        analyse["stats_dom"].get("erreur"),
        analyse["stats_ext"].get("erreur"),
    ]

    erreurs = [erreur for erreur in erreurs if erreur]

    if erreurs:
        st.warning(
            "Certaines statistiques historiques n'ont pas pu être "
            "récupérées. Les estimations peuvent donc être moins fiables."
        )


# ============================================================
# COMBINÉ SAFE IA
# ============================================================

def candidats_pronostics(analyse):
    """
    Produit les options statistiques admissibles pour le combiné.
    Les seuils sont des filtres, pas une garantie de résultat.
    """
    candidats = []

    options = [
        ("Plus de 1,5 but", analyse["over15"]),
        ("Double chance 1N", analyse["p1"] + analyse["pn"]),
        ("Double chance N2", analyse["pn"] + analyse["p2"]),
        ("Moins de 3,5 buts", 1 - analyse["over25"]),
    ]

    for nom, probabilite in options:
        if probabilite >= 0.75:
            candidats.append({
                "match": (
                    f"{analyse['domicile']} - {analyse['exterieur']}"
                ),
                "pronostic": nom,
                "probabilite": probabilite,
                "analyse": analyse,
            })

    candidats.sort(
        key=lambda element: element["probabilite"],
        reverse=True,
    )

    return candidats


def est_match_a_venir(match):
    statut = match.get("status", "")

    if statut not in ("SCHEDULED", "TIMED"):
        return False

    date_utc = match.get("utcDate", "")

    if not date_utc:
        return False

    # Le calendrier utilise des dates sans décalage horaire.
    # La comparaison de la date ISO suffit ici à exclure les matchs
    # dont la date est déjà passée.
    return date_utc[:10] >= date.today().isoformat()


def analyser_matchs_pour_combine(matchs, limite=8):
    matchs_a_venir = [
        match for match in matchs
        if est_match_a_venir(match)
    ]

    # Évite de déclencher trop de requêtes API en une seule fois.
    matchs_a_venir = matchs_a_venir[:limite]

    resultats = []
    erreurs = []

    barre = st.progress(0)
    statut = st.empty()

    total = len(matchs_a_venir)

    if total == 0:
        barre.empty()
        statut.empty()
        return [], []

    for index, match in enumerate(matchs_a_venir, start=1):
        statut.write(
            f"Analyse du match {index}/{total} : "
            f"{nom_equipe(match, True)} - {nom_equipe(match, False)}"
        )

        try:
            analyse = analyser_match(match)

            if (
                analyse["stats_dom"].get("erreur")
                or analyse["stats_ext"].get("erreur")
            ):
                erreurs.append(
                    f"{analyse['domicile']} - {analyse['exterieur']}"
                )
            else:
                resultats.append(analyse)

        except Exception:
            erreurs.append(
                f"{nom_equipe(match, True)} - "
                f"{nom_equipe(match, False)}"
            )

        barre.progress(index / total)

    barre.empty()
    statut.empty()

    return resultats, erreurs


def afficher_combine_ia():
    st.subheader("🧠 Combiné SAFE IA — 2 matchs")

    st.info(
        "Le système recherche deux matchs à venir avec des probabilités "
        "élevées selon le modèle. Aucun pronostic n'est garanti."
    )

    matchs = st.session_state.get("matchs_recherches", [])

    matchs_a_venir = [
        match for match in matchs
        if est_match_a_venir(match)
    ]

    if len(matchs_a_venir) < 2:
        st.warning(
            "Il faut au moins 2 matchs programmés dans les résultats. "
            "Choisis une période future et plusieurs championnats."
        )
        return

    if st.button(
        "🔎 Analyser les matchs pour trouver le combiné",
        key="bouton_combine",
    ):
        analyses, erreurs = analyser_matchs_pour_combine(
            matchs_a_venir,
            limite=8,
        )

        tous_candidats = []

        for analyse in analyses:
            tous_candidats.extend(candidats_pronostics(analyse))

        # Un seul pronostic par match dans le combiné.
        meilleurs_par_match = {}

        for candidat in tous_candidats:
            cle = candidat["match"]

            if (
                cle not in meilleurs_par_match
                or candidat["probabilite"]
                > meilleurs_par_match[cle]["probabilite"]
            ):
                meilleurs_par_match[cle] = candidat

        classement = sorted(
            meilleurs_par_match.values(),
            key=lambda element: element["probabilite"],
            reverse=True,
        )

        st.session_state["analyses_combine"] = analyses
        st.session_state["classement_ia"] = classement
        st.session_state["erreurs_combine"] = erreurs

    analyses = st.session_state.get("analyses_combine", [])
    classement = st.session_state.get("classement_ia", [])

    if analyses:
        st.markdown("### 🏆 Classement des meilleurs pronostics")

        if classement:
            tableau = []

            for rang, candidat in enumerate(classement, start=1):
                tableau.append({
                    "Rang": rang,
                    "Match": candidat["match"],
                    "Pronostic": candidat["pronostic"],
                    "Probabilité estimée": (
                        f"{candidat['probabilite'] * 100:.1f} %"
                    ),
                })

            st.dataframe(
                pd.DataFrame(tableau),
                use_container_width=True,
                hide_index=True,
            )

            if len(classement) >= 2:
                premier = classement[0]
                deuxieme = next(
                    (
                        candidat for candidat in classement[1:]
                        if candidat["match"] != premier["match"]
                    ),
                    None,
                )

                if deuxieme:
                    st.markdown("### 🎯 Ton combiné IA")

                    st.success(
                        f"1️⃣ {premier['match']} : "
                        f"{premier['pronostic']} "
                        f"({premier['probabilite'] * 100:.1f} %)"
                    )

                    st.success(
                        f"2️⃣ {deuxieme['match']} : "
                        f"{deuxieme['pronostic']} "
                        f"({deuxieme['probabilite'] * 100:.1f} %)"
                    )

                    probabilite_combinee = (
                        premier["probabilite"]
                        * deuxieme["probabilite"]
                    )

                    st.metric(
                        "Probabilité combinée indicative",
                        f"{probabilite_combinee * 100:.1f} %",
                    )

                    st.caption(
                        "Cette estimation multiplie les probabilités "
                        "individuelles et suppose leur indépendance. "
                        "Elle peut différer des probabilités réelles "
                        "et ne tient pas compte des cotes du bookmaker."
                    )
                else:
                    st.warning(
                        "Le système n'a pas trouvé deux matchs distincts "
                        "avec des options dépassant le seuil retenu."
                    )
            else:
                st.warning(
                    "Pas assez de pronostics au-dessus du seuil de 75 % "
                    "pour constituer un combiné de deux matchs."
                )
        else:
            st.warning(
                "Aucun pronostic n'a atteint le seuil statistique de 75 %. "
                "Élargis la période ou réessaie plus tard."
            )

        erreurs = st.session_state.get("erreurs_combine", [])

        if erreurs:
            st.caption(
                "Historique indisponible pour certains matchs : "
                + ", ".join(erreurs)
            )


# ============================================================
# INTERFACE
# ============================================================

st.title("⚽ FOOT AI PRO")
st.caption(
    "Analyse statistique des matchs réels — "
    "Ligue 1, Premier League, Liga, Bundesliga, Serie A et Ligue des champions"
)

if not obtenir_cle_api():
    st.error(
        "La clé API football-data.org est absente. "
        "Ajoute FOOTBALL_API_KEY dans les Secrets de Streamlit."
    )

onglets = st.tabs([
    "🏠 Accueil",
    "📅 Matchs réels",
    "🧠 Pronostic IA",
    "🎯 Combiné SAFE IA",
    "📊 Classement IA",
])


# ============================================================
# ONGLET ACCUEIL
# ============================================================

with onglets[0]:
    st.header("Bienvenue sur FOOT AI PRO")

    st.write(
        "Cette application analyse les matchs de football à partir "
        "des résultats et des statistiques disponibles sur l'API."
    )

    st.markdown(
        """
        **Fonctionnalités :**
        - Calendrier de matchs passés et futurs.
        - Analyse des cinq derniers matchs disponibles.
        - Probabilités 1N2 et marchés de buts.
        - Pronostic principal calculé par le modèle.
        - Classement des meilleures options statistiques.
        - Combiné de deux matchs à venir.
        """
    )

    st.warning(
        "Les probabilités sont des estimations. Vérifie les compositions, "
        "les blessures et les informations de dernière minute avant "
        "toute décision. Aucun pari n'est sans risque."
    )


# ============================================================
# ONGLET MATCHS RÉELS
# ============================================================

with onglets[1]:
    st.header("📅 Calendrier des matchs")

    col1, col2 = st.columns(2)

    with col1:
        date_debut = st.date_input(
            "Date de début",
            value=date.today(),
            key="date_debut",
        )

    with col2:
        date_fin = st.date_input(
            "Date de fin",
            value=date.today() + timedelta(days=7),
            key="date_fin",
        )

    competitions_selectionnees = st.multiselect(
        "Choisir les championnats",
        options=list(CHAMPIONNATS.keys()),
        default=list(CHAMPIONNATS.keys()),
    )

    if date_fin < date_debut:
        st.error("La date de fin doit être après la date de début.")

    elif st.button("🔍 Rechercher les matchs", key="rechercher_matchs"):
        if not competitions_selectionnees:
            st.warning("Choisis au moins un championnat.")
        else:
            matchs_trouves = []
            erreurs = []

            barre = st.progress(0)

            total = len(competitions_selectionnees)

            for index, competition in enumerate(
                competitions_selectionnees,
                start=1,
            ):
                code = CHAMPIONNATS[competition]

                resultat = charger_matchs(
                    code,
                    date_debut.isoformat(),
                    date_fin.isoformat(),
                )

                if isinstance(resultat, dict) and resultat.get("_erreur"):
                    erreurs.append(
                        f"{competition} : {resultat['_erreur']}"
                    )
                else:
                    matchs_trouves.extend(resultat)

                barre.progress(index / total)

            barre.empty()

            # Évite les doublons entre compétitions.
            uniques = {}

            for match in matchs_trouves:
                uniques[match.get("id")] = match

            matchs_trouves = list(uniques.values())
            matchs_trouves.sort(
                key=lambda match: match.get("utcDate", "")
            )

            st.session_state["matchs_recherches"] = matchs_trouves
            st.session_state["analyses_combine"] = []
            st.session_state["classement_ia"] = []
            st.session_state["erreurs_combine"] = []

            if erreurs:
                for erreur in erreurs:
                    st.warning(erreur)

            st.success(
                f"{len(matchs_trouves)} match(s) trouvé(s)."
            )

    matchs = st.session_state.get("matchs_recherches", [])

    if matchs:
        st.markdown("### Résultats du calendrier")

        tableau = pd.DataFrame(
            [formater_match(match) for match in matchs]
        )

        st.dataframe(
            tableau.drop(columns=["ID"]),
            use_container_width=True,
            hide_index=True,
        )

        options_matchs = {
            (
                f"{match.get('utcDate', '')[:16]} | "
                f"{nom_equipe(match, True)} - "
                f"{nom_equipe(match, False)}"
            ): match.get("id")
            for match in matchs
        }

        choix_match = st.selectbox(
            "Choisir un match à analyser",
            options=list(options_matchs.keys()),
            key="choix_match",
        )

        if st.button("🧠 Analyser ce match", key="analyser_un_match"):
            id_choisi = options_matchs[choix_match]

            match_choisi = next(
                (
                    match for match in matchs
                    if match.get("id") == id_choisi
                ),
                None,
            )

            if match_choisi:
                with st.spinner("Analyse des statistiques en cours..."):
                    try:
                        analyse = analyser_match(match_choisi)
                        st.session_state["derniere_analyse"] = analyse
                    except Exception as erreur:
                        st.error(f"Impossible d'analyser ce match : {erreur}")

        derniere_analyse = st.session_state.get("derniere_analyse")

        if derniere_analyse:
            st.divider()
            afficher_analyse(derniere_analyse)


# ============================================================
# ONGLET PRONOSTIC IA
# ============================================================

with onglets[2]:
    st.header("🧠 Pronostic IA")

    derniere_analyse = st.session_state.get("derniere_analyse")

    if derniere_analyse:
        afficher_analyse(derniere_analyse)
    else:
        st.info(
            "Va dans « Matchs réels », recherche les matchs, "
            "puis sélectionne un match et appuie sur « Analyser ce match »."
        )


# ============================================================
# ONGLET COMBINÉ SAFE IA
# ============================================================

with onglets[3]:
    afficher_combine_ia()


# ============================================================
# ONGLET CLASSEMENT IA
# ============================================================

with onglets[4]:
    st.header("📊 Classement IA")

    classement = st.session_state.get("classement_ia", [])

    if classement:
        tableau = []

        for rang, candidat in enumerate(classement, start=1):
            tableau.append({
                "Rang": rang,
                "Match": candidat["match"],
                "Pronostic": candidat["pronostic"],
                "Probabilité": (
                    f"{candidat['probabilite'] * 100:.1f} %"
                ),
            })

        st.dataframe(
            pd.DataFrame(tableau),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(
            "Pour remplir le classement, ouvre « Combiné SAFE IA » "
            "et lance l'analyse des matchs à venir."
        )