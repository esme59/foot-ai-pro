import streamlit as st

st.set_page_config(
page_title="IA Pronostics Football",
page_icon="⚽",
layout="wide"
)

st.title("⚽ IA de Pronostics Football")
st.write("Bienvenue dans notre IA de pronostics football !")

st.subheader("📊 Analyser un match")

equipe1 = st.text_input("Équipe à domicile","Paris Saint-Germain")
equipe2 = st.text_input("Équipe à l’extérieur", "Olympique de Marseille")

if st.button(“Analyser le match”):
st.subheader(f”{equipe1} vs {equipe2}”)
st.info(“Notre système de calcul des probabilités sera ajouté à la prochaine étape.”)
st.write(“🏠 Victoire domicile : à calculer”)
st.write(“🤝 Match nul : à calculer”)
st.write(“✈️ Victoire extérieur : à calculer”)

st.caption(“Version 1.0 — Projet IA Football”)
