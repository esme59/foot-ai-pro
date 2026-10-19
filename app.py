import streamlit as st
import math

st.set_page_config(
    page_title="FOOT AI PRO V3",
    page_icon="⚽",
    layout="wide"
)

st.markdown("""
<style>
.stApp {
    background: linear-gradient(135deg, #071b16, #102b23);
    color: white;
}
h1, h2, h3, p, label {
    color: white !important;
}
div.stButton > button {
    background-color: #00c853;
    color: white;
    border-radius: 12px;
    font-weight: bold;
    width: 100%;
}
</style>
""", unsafe_allow_html=True)

st.title("⚽ FOOT AI PRO V3")
st.subheader("👑 PRO MAX — Analyse et pronostics football")
st.caption("Outil d'estimation statistique — aucun pronostic n'est garanti.")

st.divider()

st.header("📋 Informations du match")

col1, col2 = st.columns(2)

with col1:
    equipe1 = st.text_input("🏠 Équipe à domicile", "Paris Saint-Germain")
    buts1 = st.number_input(
        "Buts moyens marqués à domicile",
        min_value=0.0,
        max_value=10.0,
        value=1.8,
        step=0.1
    )
    encaisses1 = st.number_input(
        "Buts moyens encaissés à domicile",
        min_value=0.0,
        max_value=10.0,
        value=1.0,
        step=0.1
    )

with col2:
    equipe2 = st.text_input("✈️ Équipe à l'extérieur", "Olympique de Marseille")
    buts2 = st.number_input(
        "Buts moyens marqués à l'extérieur",
        min_value=0.0,
        max_value=10.0,
        value=1.2,
        step=0.1
    )
    encaisses2 = st.number_input(
        "Buts moyens encaissés à l'extérieur",
        min_value=0.0,
        max_value=10.0,
        value=1.4,
        step=0.1
    )

st.info(
    "Renseigne les moyennes réelles des équipes si tu les connais. "
    "Les valeurs proposées sont uniquement des exemples."
)

def probabilites_poisson(moyenne, maximum=10):
    probabilites = []
    for buts in range(maximum + 1):
        probabilite = (
            math.exp(-moyenne) * moyenne ** buts / math.factorial(buts)
        )
        probabilites.append(probabilite)
    return probabilites

def analyser_match(moyenne1, moyenne2):
    p1 = probabilites_poisson(moyenne1)
    p2 = probabilites_poisson(moyenne2)

    victoire1 = 0
    nul = 0
    victoire2 = 0
    scores = []
    les_deux_marquent = 0
    plus_25 = 0

    for i in range(len(p1)):
        for j in range(len(p2)):
            proba = p1[i] * p2[j]
            scores.append((proba, i, j))

            if i > j:
                victoire1 += proba
            elif i == j:
                nul += proba
            else:
                victoire2 += proba

            if i > 0 and j > 0:
                les_deux_marquent += proba

            if i + j >= 3:
                plus_25 += proba

    scores.sort(reverse=True)
    return victoire1, nul, victoire2, scores[0], les_deux_marquent, plus_25

if st.button("🚀 ANALYSER LE MATCH"):
    if not equipe1.strip() or not equipe2.strip():
        st.error("Entre le nom des deux équipes.")
    elif equipe1.strip().lower() == equipe2.strip().lower():
        st.error("Choisis deux équipes différentes.")
    else:
        moyenne1 = (buts1 + encaisses2) / 2
        moyenne2 = (buts2 + encaisses1) / 2

        v1, n, v2, meilleur_score, btts, over25 = analyser_match(
            moyenne1, moyenne2
        )

        st.divider()
        st.header(f"📊 {equipe1} — {equipe2}")

        c1, c2, c3 = st.columns(3)
        c1.metric(f"🏠 {equipe1}", f"{v1 * 100:.1f} %")
        c2.metric("🤝 Match nul", f"{n * 100:.1f} %")
        c3.metric(f"✈️ {equipe2}", f"{v2 * 100:.1f} %")

        st.subheader("🎯 Score exact le plus probable")
        _, score1, score2 = meilleur_score
        st.success(f"{equipe1} {score1} - {score2} {equipe2}")

        st.subheader("🥅 Total de buts")
        c4, c5 = st.columns(2)
        c4.metric("Plus de 2,5 buts", f"{over25 * 100:.1f} %")
        c5.metric("Moins de 2,5 buts", f"{(1 - over25) * 100:.1f} %")

        st.subheader("🔥 Les deux équipes marquent")
        c6, c7 = st.columns(2)
        c6.metric("Oui", f"{btts * 100:.1f} %")
        c7.metric("Non", f"{(1 - btts) * 100:.1f} %")

        resultats = {
            f"Victoire {equipe1}": v1,
            "Match nul": n,
            f"Victoire {equipe2}": v2
        }
        meilleur = max(resultats, key=resultats.get)

        st.subheader("🏆 Pronostic principal")
        st.success(f"{meilleur} — {resultats[meilleur] * 100:.1f} %")

        st.subheader("📈 Indice de confiance du modèle")
        confiance = max(v1, n, v2) * 100
        st.progress(int(confiance))
        st.write(
            f"Le résultat le plus probable représente {confiance:.1f} % "
            "selon ce modèle simplifié. Ce n'est pas une garantie."
        )

        st.caption(
            "Modèle de Poisson simplifié basé sur les moyennes saisies. "
            "Il n'utilise pas automatiquement les résultats récents, "
            "les compositions, les blessures ou les cotes."
        )

st.divider()
st.caption("FOOT AI PRO V3 © — Version PRO MAX")