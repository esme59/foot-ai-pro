import math
import os
from datetime import date, timedelta

import pandas as pd
import requests
import streamlit as st


# =========================================================
# CONFIGURATION
# =========================================================

st.set_page_config(
    page_title="FOOT AI PRO",
    page_icon="⚽",
    layout="wide"
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
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 3rem;
    }
    div[data-testid="stMetric"] {
        border: 1px solid #30363d;
        padding: 12px;
        border-radius: 10px;
    }
    </style>
    """,
    unsafe_allow_html=True
)


# =========================================================
# API FOOTBALL
# =========================================================

def obtenir_cle_api():
    try:
        cle = st.secrets.get("FOOTBALL_API_KEY", "")
        if cle:
            return cle
    except Exception:
        pass

    return os.getenv("FOOTBALL_API_KEY", "")


def appel_api(endpoint, params=None):
    cle = obtenir_cle_api()

    if not cle:
        st.error(
            "Clé API manquante. Ajoute FOOTBALL_API_KEY "
            "dans les Secrets de Streamlit."
        )
        return None

    try:
        reponse = requests.get(
            f"{API_URL}{endpoint}",
            headers={"X-Auth-Token": cle},
            params=params or {},
            timeout=25
        )

        if reponse.status_code == 429:
            st.warning(
                "Limite de requêtes API atteinte. "
                "Attends un peu avant de recommencer."
            )
            return None

        if reponse.status_code == 403:
            st.error(
                "Accès refusé par l'API. "
                "Vérifie ton abonnement et les compétitions autorisées."
            )
            return None

        if reponse.status_code == 404:
            return None

        if reponse.status_code != 200:
            st.error(
                f"Erreur API : HTTP {reponse.status_code}. "
                "Réessaie plus tard."
            )
            return None

        return reponse.json()

    except requests.RequestException as erreur:
        st.error(f"Erreur de connexion : {erreur}")
        return None


# =========================================================
# RECHERCHE DES MATCHS PAR DATES
# =========================================================

@st.cache_data(ttl=300, show_spinner=False)
def charger_matchs(code, date_debut, date_fin):
    resultat = appel_api(
        f"/competitions/{code}/matches",
        {
            "dateFrom": date_debut,
            "dateTo": date_fin,
        }
    )

    if not resultat:
        return []

    return resultat.get("matches", [])


def afficher_nom_equipe(match, domicile=True):
    equipe = (
        match.get("homeTeam", {})
        if domicile
        else match.get("awayTeam", {})
    )

    return (
        equipe.get("shortName")
        or equipe.get("name")
        or "Équipe inconnue"
    )


def formater_match(match):
    score = match.get("score", {})
    temps = score.get("fullTime", {})

    buts_dom = temps.get("home")
    buts_ext = temps.get("away")

    statut = match.get("status", "INCONNU")

    if statut == "FINISHED":
        score_txt = (
            f"{buts_dom} - {buts_ext}"
            if buts_dom is not None and buts_ext is not None
            else "Terminé"
        )
    elif statut in ("IN_PLAY", "PAUSED", "LIVE"):
        score_txt = (
            f"{buts_dom} - {buts_ext}"
            if buts_dom is not None and buts_ext is not None
            else "En direct"
        )
    else:
        score_txt = "À jouer"

    return {
        "id": match.get("id"),
        "date": match.get("utcDate", ""),
        "domicile": afficher_nom_equipe(match, True),
        "extérieur": afficher_nom_equipe(match, False),
        "score": score_txt,
        "statut": statut,
        "buts_dom": buts_dom,
        "buts_ext": buts_ext,
        "equipe_dom_id": match.get("homeTeam", {}).get("id"),
        "equipe_ext_id": match.get("awayTeam", {}).get("id"),
        "compétition": match.get("competition", {}).get(
            "name", "Championnat"
        ),
    }


# =========================================================
# HISTORIQUE DES ÉQUIPES
# =========================================================

@st.cache_data(ttl=900, show_spinner=False)
def derniers_matchs_equipe(equipe_id, date_reference):
    if not equipe_id:
        return []

    # Recherche jusqu'à un an avant la date du match analysé.
    # Pour un match futur, on utilise les dernières rencontres terminées.
    fin = date.fromisoformat(date_reference[:10])
    debut = fin - timedelta(days=365)

    resultat = appel_api(
        f"/teams/{equipe_id}/matches",
        {
            "dateFrom": debut.isoformat(),
            "dateTo": fin.isoformat(),
            "status": "FINISHED",
            "limit": 100,
        }
    )

    if not resultat:
        return []

    matchs = resultat.get("matches", [])

    matchs = [
        m for m in matchs
        if m.get("status") == "FINISHED"
        and m.get("score", {}).get("fullTime", {}).get("home")
        is not None
        and m.get("score", {}).get("fullTime", {}).get("away")
        is not None
    ]

    matchs.sort(
        key=lambda m: m.get("utcDate", ""),
        reverse=True
    )

    return matchs[:5]


def statistiques_equipe(equipe_id, nom_equipe, date_reference):
    matchs = derniers_matchs_equipe(
        equipe_id,
        date_reference
    )

    if not matchs:
        return None

    buts_marques = []
    buts_encaisses = []
    victoires = 0
    nuls = 0
    defaites = 0

    for match in matchs:
        domicile = match.get("homeTeam", {})
        score = match.get("score", {}).get("fullTime", {})

        bd = score.get("home")
        be = score.get("away")

        if bd is None or be is None:
            continue

        est_domicile = domicile.get("id") == equipe_id

        marques = bd if est_domicile else be
        encaisses = be if est_domicile else bd

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
        "nom": nom_equipe,
        "matchs": nombre,
        "buts_marques": sum(buts_marques) / nombre,
        "buts_encaisses": sum(buts_encaisses) / nombre,
        "victoires": victoires,
        "nuls": nuls,
        "defaites": defaites,
        "forme": f"{victoires}V {nuls}N {defaites}D",
    }


# =========================================================
# MODÈLE DE POISSON
# =========================================================

def probabilite_poisson(nombre_buts, moyenne):
    if moyenne <= 0:
        return 1.0 if nombre_buts == 0 else 0.0

    return (
        math.exp(-moyenne)
        * moyenne ** nombre_buts
        / math.factorial(nombre_buts)
    )


def analyser_match(match):
    match_info = formater_match(match)

    date_reference = match_info["date"]

    stats_dom = statistiques_equipe(
        match_info["equipe_dom_id"],
        match_info["domicile"],
        date_reference
    )

    stats_ext = statistiques_equipe(
        match_info["equipe_ext_id"],
        match_info["extérieur"],
        date_reference
    )

    if not stats_dom or not stats_ext:
        return {
            "match": match_info,
            "erreur": (
                "Historique insuffisant pour analyser "
                "correctement ce match."
            ),
        }

    # Estimations simplifiées à partir des cinq derniers matchs.
    moyenne_dom = (
        stats_dom["buts_marques"]
        + stats_ext["buts_encaisses"]
    ) / 2

    moyenne_ext = (
        stats_ext["buts_marques"]
        + stats_dom["buts_encaisses"]
    ) / 2

    moyenne_dom = max(0.15, min(moyenne_dom, 5.0))
    moyenne_ext = max(0.15, min(moyenne_ext, 5.0))

    # Distribution des scores de 0 à 7 buts par équipe.
    scores = []

    for bd in range(8):
        for be in range(8):
            p = (
                probabilite_poisson(bd, moyenne_dom)
                * probabilite_poisson(be, moyenne_ext)
            )

            scores.append({
                "dom": bd,
                "ext": be,
                "p": p,
            })

    total = sum(s["p"] for s in scores)

    for s in scores:
        s["p"] /= total

    p1 = sum(s["p"] for s in scores if s["dom"] > s["ext"])
    pn = sum(s["p"] for s in scores if s["dom"] == s["ext"])
    p2 = sum(s["p"] for s in scores if s["dom"] < s["ext"])

    p15 = sum(
        s["p"] for s in scores
        if s["dom"] + s["ext"] >= 2
    )

    p25 = sum(
        s["p"] for s in scores
        if s["dom"] + s["ext"] >= 3
    )

    btts = sum(
        s["p"] for s in scores
        if s["dom"] >= 1 and s["ext"] >= 1
    )

    scores_tries = sorted(
        scores,
        key=lambda s: s["p"],
        reverse=True
    )[:5]

    meilleur_score = scores_tries[0]

    probabilites = {
        "Victoire domicile": p1,
        "Match nul": pn,
        "Victoire extérieur": p2,
    }

    meilleur_resultat = max(
        probabilites,
        key=probabilites.get
    )

    return {
        "match": match_info,
        "stats_dom": stats_dom,
        "stats_ext": stats_ext,
        "moyenne_dom": moyenne_dom,
        "moyenne_ext": moyenne_ext,
        "p1": p1,
        "pn": pn,
        "p2": p2,
        "p15": p15,
        "p25": p25,
        "btts": btts,
        "scores": scores_tries,
        "score_principal": (
            f"{meilleur_score['dom']} - {meilleur_score['ext']}"
        ),
        "resultat": meilleur_resultat,
        "confiance": probabilites[meilleur_resultat],
    }


# =========================================================
# AFFICHAGE D'UNE ANALYSE
# =========================================================

def afficher_analyse(analyse):
    if analyse.get("erreur"):
        st.warning(analyse["erreur"])
        return

    match = analyse["match"]

    st.subheader(
        f"{match['domicile']} - {match['extérieur']}"
    )

    c1, c2, c3 = st.columns(3)

    c1.metric(
        "Victoire domicile",
        f"{analyse['p1'] * 100:.1f}%"
    )

    c2.metric(
        "Match nul",
        f"{analyse['pn'] * 100:.1f}%"
    )

    c3.metric(
        "Victoire extérieur",
        f"{analyse['p2'] * 100:.1f}%"
    )

    st.write(
        f"**Score exact principal estimé :** "
        f"{analyse['score_principal']}"
    )

    st.write(
        f"**Plus de 1,5 but :** "
        f"{analyse['p15'] * 100:.1f}%"
    )

    st.write(
        f"**Plus de 2,5 buts :** "
        f"{analyse['p25'] * 100:.1f}%"
    )

    st.write(
        f"**Les deux équipes marquent :** "
        f"{analyse['btts'] * 100:.1f}%"
    )

    st.write(
        f"**Forme récente - {match['domicile']} :** "
        f"{analyse['stats_dom']['forme']}"
    )

    st.write(
        f"**Forme récente - {match['extérieur']} :** "
        f"{analyse['stats_ext']['forme']}"
    )

    st.caption(
        "Estimations statistiques simplifiées, non garanties. "
        "Elles ne constituent pas une certitude de résultat."
    )

    with st.expander("Voir les 5 scores les plus probables"):
        lignes = []

        for score in analyse["scores"]:
            lignes.append({
                "Score": f"{score['dom']} - {score['ext']}",
                "Probabilité": f"{score['p'] * 100:.2f}%",
            })

        st.dataframe(
            pd.DataFrame(lignes),
            hide_index=True,
            use_container_width=True
        )


# =========================================================
# INTERFACE PRINCIPALE
# =========================================================

st.title("⚽ FOOT AI PRO")
st.caption(
    "Analyse footballistique basée sur les résultats "
    "et les statistiques disponibles."
)

onglets = st.tabs([
    "🏠 Accueil",
    "📅 Matchs réels",
    "🎯 Analyse personnalisée",
    "🏆 Classement IA",
])

# ---------------------------------------------------------
# ONGLET ACCUEIL
# ---------------------------------------------------------

with onglets[0]:
    st.header("Bienvenue sur FOOT AI PRO")

    st.write(
        "Choisis une période, consulte les matchs réels "
        "et lance une analyse statistique."
    )

    st.info(
        "La période peut être passée, actuelle ou future. "
        "La disponibilité des données dépend de l'API."
    )

    st.markdown(
        """
        **Fonctionnalités :**
        - Calendrier personnalisable.
        - Historique des rencontres.
        - Estimations de scores.
        - Probabilités 1N2.
        - Marchés de buts.
        - Classement des matchs analysés.
        """
    )


# ---------------------------------------------------------
# ONGLET MATCHS RÉELS
# ---------------------------------------------------------

with onglets[1]:
    st.header("📅 Calendrier des matchs")

    aujourd_hui = date.today()

    col1, col2 = st.columns(2)

    with col1:
        date_debut = st.date_input(
            "Date de début",
            value=aujourd_hui,
            key="date_debut",
            format="DD/MM/YYYY",
        )

    with col2:
        date_fin = st.date_input(
            "Date de fin",
            value=aujourd_hui + timedelta(days=7),
            key="date_fin",
            format="DD/MM/YYYY",
        )

    if date_debut > date_fin:
        st.error(
            "La date de début doit être antérieure "
            "ou égale à la date de fin."
        )
    else:
        championnats_choisis = st.multiselect(
            "Championnats à afficher",
            options=list(CHAMPIONNATS.keys()),
            default=list(CHAMPIONNATS.keys()),
        )

        if st.button(
            "🔎 Rechercher les matchs",
            use_container_width=True
        ):
            tous_matchs = []

            with st.spinner("Recherche des rencontres..."):
                for nom, code in CHAMPIONNATS.items():
                    if nom not in championnats_choisis:
                        continue

                    rencontres = charger_matchs(
                        code,
                        date_debut.isoformat(),
                        date_fin.isoformat()
                    )

                    for rencontre in rencontres:
                        ligne = formater_match(rencontre)
                        ligne["championnat"] = nom
                        ligne["match_original"] = rencontre
                        tous_matchs.append(ligne)

            tous_matchs.sort(key=lambda m: m["date"])

            st.session_state["matchs_recherches"] = tous_matchs
            st.session_state["periode_recherchee"] = (
                date_debut.isoformat(),
                date_fin.isoformat()
            )

        matchs = st.session_state.get(
            "matchs_recherches",
            []
        )

        if matchs:
            st.success(
                f"{len(matchs)} rencontre(s) trouvée(s)."
            )

            tableau = []

            for m in matchs:
                tableau.append({
                    "Date UTC": m["date"].replace("T", " ")[:16],
                    "Championnat": m.get("championnat", ""),
                    "Domicile": m["domicile"],
                    "Extérieur": m["extérieur"],
                    "Score / statut": m["score"],
                    "Statut": m["statut"],
                })

            st.dataframe(
                pd.DataFrame(tableau),
                hide_index=True,
                use_container_width=True
            )

            options_matchs = {
                (
                    f"{m['date'][:16]} | "
                    f"{m['domicile']} - {m['extérieur']} "
                    f"({m.get('championnat', '')})"
                ): m
                for m in matchs
            }

            choix = st.selectbox(
                "Choisir un match à analyser",
                list(options_matchs.keys())
            )

            match_selectionne = options_matchs[choix]

            if st.button(
                "⚽ Analyser ce match",
                use_container_width=True
            ):
                with st.spinner("Analyse statistique en cours..."):
                    analyse = analyser_match(
                        match_selectionne["match_original"]
                    )

                st.session_state["derniere_analyse"] = analyse

            derniere_analyse = st.session_state.get(
                "derniere_analyse"
            )

            if derniere_analyse:
                afficher_analyse(derniere_analyse)

        elif "matchs_recherches" in st.session_state:
            st.info(
                "Aucun match trouvé pour cette période "
                "et ces compétitions, ou données indisponibles."
            )


# ---------------------------------------------------------
# ONGLET ANALYSE PERSONNALISÉE
# ---------------------------------------------------------

with onglets[2]:
    st.header("🎯 Analyse personnalisée")

    st.write(
        "Cette section permet d'estimer un match à partir "
        "des équipes disponibles dans l'API."
    )

    equipe_dom = st.text_input(
        "Équipe à domicile",
        placeholder="Exemple : Paris Saint-Germain",
    )

    equipe_ext = st.text_input(
        "Équipe à l'extérieur",
        placeholder="Exemple : Marseille",
    )

    date_match_perso = st.date_input(
        "Date de référence des statistiques",
        value=date.today(),
        key="date_match_perso",
        format="DD/MM/YYYY",
    )

    if st.button(
        "Analyser le match personnalisé",
        use_container_width=True
    ):
        st.info(
            "L'analyse personnalisée par noms d'équipes "
            "nécessite une recherche des identifiants officiels "
            "des équipes dans l'API. Utilise pour le moment "
            "l'onglet « Matchs réels » pour obtenir une analyse "
            "complète à partir d'une rencontre officielle."
        )


# ---------------------------------------------------------
# ONGLET CLASSEMENT IA
# ---------------------------------------------------------

with onglets[3]:
    st.header("🏆 Classement des matchs analysés")

    derniere_analyse = st.session_state.get(
        "derniere_analyse"
    )

    if derniere_analyse and not derniere_analyse.get("erreur"):
        match = derniere_analyse["match"]

        st.write(
            f"**Dernier match analysé :** "
            f"{match['domicile']} - {match['extérieur']}"
        )

        classement = pd.DataFrame([
            {
                "Marché": "Victoire domicile",
                "Probabilité": derniere_analyse["p1"] * 100,
            },
            {
                "Marché": "Match nul",
                "Probabilité": derniere_analyse["pn"] * 100,
            },
            {
                "Marché": "Victoire extérieur",
                "Probabilité": derniere_analyse["p2"] * 100,
            },
            {
                "Marché": "Plus de 1,5 but",
                "Probabilité": derniere_analyse["p15"] * 100,
            },
            {
                "Marché": "Plus de 2,5 buts",
                "Probabilité": derniere_analyse["p25"] * 100,
            },
            {
                "Marché": "Les deux équipes marquent",
                "Probabilité": derniere_analyse["btts"] * 100,
            },
        ])

        classement = classement.sort_values(
            "Probabilité",
            ascending=False
        )

        classement["Probabilité"] = classement[
            "Probabilité"
        ].map(lambda x: f"{x:.1f}%")

        st.dataframe(
            classement,
            hide_index=True,
            use_container_width=True
        )

    else:
        st.info(
            "Analyse d'abord un match dans l'onglet "
            "« Matchs réels » pour afficher le classement."
        )


st.divider()

st.caption(
    "FOOT AI PRO — Les probabilités sont des estimations "
    "et ne garantissent aucun résultat sportif."
)