import streamlit as st
import math
st.set_page_config(
    page_title="Foot AI Pro",
    page_icon="⚽",
    layout="centered"
)
st.title("⚽ Foot AI Pro")
st.subheader("Analyse et pronostics de football")
st.write("Compare deux équipes et obtiens une estimation indicative du résultat.")
st.divider()
equipe1 = st.text_input("Équipe à domicile", "Paris Saint-Germain")
equipe2 = st.text_input("Équipe à l'extérieur", "Olympique de Marseille")
st.subheader("📊 Statistiques des équipes")
col1, col2 = st.columns(2)
with col1:
    st.write("Équipe à domicile")
    buts1 = st.number_input("Buts marqués par match", 0.0, 10.0, 1.8, 0.1, key="b1")
    encaisses1 = st.number_input("Buts encaissés par match", 0.0, 10.0, 1.0, 0.1, key="e1")
with col2:
    st.write("Équipe à l'extérieur")
    buts2 = st.number_input("Buts marqués par match", 0.0, 10.0, 1.3, 0.1, key="b2")
    encaisses2 = st.number_input("Buts encaissés par match", 0.0, 10.0, 1.4, 0.1, key="e2")
if st.button("🔎 Analyser le match", type="primary"):
    if not equipe1.strip() or not equipe2.strip():
        st.error("Entre le nom des deux équipes.")
    else:
        force1 = (buts1 + encaisses2) / 2 + 0.25
        force2 = (buts2 + encaisses1) / 2
        total = force1 + force2
        proba1 = force1 / total * 100 if total else 0
        proba2 = force2 / total * 100 if total else 0
        st.divider()
        st.header(f"⚽ {equipe1} vs {equipe2}")
        st.write("### 📈 Estimation indicative")
        c1, c2 = st.columns(2)
        c1.metric(f"Victoire {equipe1}", f"{proba1:.1f} %")
        c2.metric(f"Victoire {equipe2}", f"{proba2:.1f} %")
        nul = max(0, 100 - proba1 - proba2)
        st.write(f"Match nul : **{nul:.1f} %**")
        st.info(
            "Ces chiffres sont une estimation simplifiée basée uniquement "
            "sur les statistiques saisies. Ce ne sont pas des probabilités "
            "issues de données en direct."
        )
        if force1 > force2:
            st.success(f"Pronostic indicatif : avantage {equipe1}.")
        elif force2 > force1:
            st.success(f"Pronostic indicatif : avantage {equipe2}.")
        else:
            st.success("Pronostic indicatif : match équilibré.")
        st.caption("Foot AI Pro — Outil d'aide à l'analyse, sans garantie de résultat.")