import streamlit as st
import requests
from datetime import date, timedelta

st.set_page_config(
    page_title="Foot AI Pro",
    page_icon="⚽",
    layout="wide"
)

API_URL = "https://api.football-data.org/v4"

COMPETITIONS = {
    "Ligue 1 🇫🇷": "FL1",
    "Premier League 🏴": "PL",
    "Liga 🇪🇸": "PD",
    "Serie A 🇮🇹": "SA",
    "Bundesliga 🇩🇪": "BL1",
}

st.title("⚽ Foot AI Pro")
st.subheader("🤖 Analyse et pronostics de football")

st.caption(
    "Matchs et classements issus de Football-Data.org. "
    "Les estimations ne garantissent aucun résultat."
)

try:
    token = st.secrets["FOOTBALL_DATA_TOKEN"]
except Exception:
    st.error(
        "Clé API introuvable. Configure FOOTBALL_DATA_TOKEN "
        "dans les Secrets de Streamlit."
    )
    st.stop()


def api_get(endpoint, params=None):
    headers = {"X-Auth-Token": token}

    response = requests.get(
        f"{API_URL}/{endpoint}",
        headers=headers,
        params=params,
        timeout=20
    )

    if response.status_code == 429:
        st.error("Limite de requêtes atteinte. Réessaie plus tard.")
        return None

    if response.status_code != 200:
        st.error(
            f"Erreur API : {response.status_code}. "
            "Vérifie ton accès et la compétition choisie."
        )
        return None

    return response.json()


@st.cache_data(ttl=900)
def get_matches(code, date_from, date_to):
    return api_get(
        f"competitions/{code}/matches",
        {
            "dateFrom": date_from,
            "dateTo": date_to,
            "status": "SCHEDULED"
        }
    )


@st.cache_data(ttl=900)
def get_standings(code):
    return api_get(f"competitions/{code}/standings")


competition = st.selectbox(
    "🏆 Choisis un championnat",
    list(COMPETITIONS.keys())
)

jours = st.selectbox(
    "📅 Période des matchs",
    [7, 14, 30],
    format_func=lambda x: f"Prochains {x} jours"
)

if st.button("🔎 Charger les matchs", type="primary"):
    code = COMPETITIONS[competition]

    with st.spinner("Récupération des matchs..."):
        data = get_matches(
            code,
            date.today().isoformat(),
            (date.today() + timedelta(days=jours)).isoformat()
        )

    if data is not None:
        matches = data.get("matches", [])

        if not matches:
            st.info(
                "Aucun match programmé trouvé pour cette période "
                "ou cette compétition."
            )
        else:
            st.success(f"{len(matches)} match(s) trouvé(s).")

            for match in matches:
                home = match["homeTeam"].get("name", "Domicile")
                away = match["awayTeam"].get("name", "Extérieur")
                match_date = match.get("utcDate", "")[:16].replace("T", " ")

                with st.expander(f"⚽ {home} - {away} | {match_date}"):
                    st.write(f"**Compétition :** {competition}")

                    if st.button(
                        "📊 Analyser cette rencontre",
                        key=f"analyse_{match['id']}"
                    ):
                        table = get_standings(code)

                        if table is None:
                            st.warning(
                                "Classement indisponible. "
                                "Impossible de calculer cette estimation."
                            )
                        else:
                            standings = table.get("standings", [])
                            rows = (
                                standings[0].get("table", [])
                                if standings else []
                            )

                            home_row = next(
                                (
                                    r for r in rows
                                    if r["team"]["id"]
                                    == match["homeTeam"]["id"]
                                ),
                                None
                            )

                            away_row = next(
                                (
                                    r for r in rows
                                    if r["team"]["id"]
                                    == match["awayTeam"]["id"]
                                ),
                                None
                            )

                            if not home_row or not away_row:
                                st.warning(
                                    "Les deux équipes ne figurent pas "
                                    "dans le classement disponible."
                                )
                            else:
                                home_points = home_row["points"]
                                away_points = away_row["points"]

                                home_played = max(
                                    home_row["playedGames"], 1
                                )
                                away_played = max(
                                    away_row["playedGames"], 1
                                )

                                home_strength = (
                                    home_points / home_played + 0.25
                                )
                                away_strength = (
                                    away_points / away_played
                                )

                                total = home_strength + away_strength

                                home_prob = (
                                    home_strength / total * 100
                                )
                                away_prob = (
                                    away_strength / total * 100
                                )

                                draw_prob = 25.0

                                home_prob = (
                                    home_prob * 0.75
                                )
                                away_prob = (
                                    away_prob * 0.75
                                )

                                st.subheader(
                                    f"{home} contre {away}"
                                )

                                c1, c2, c3 = st.columns(3)

                                c1.metric(
                                    "Victoire domicile",
                                    f"{home_prob:.1f} %"
                                )
                                c2.metric(
                                    "Match nul",
                                    f"{draw_prob:.1f} %"
                                )
                                c3.metric(
                                    "Victoire extérieur",
                                    f"{away_prob:.1f} %"
                                )

                                st.info(
                                    "Estimation expérimentale fondée "
                                    "sur les points par match et "
                                    "un avantage théorique à domicile. "
                                    "Ce n'est pas un modèle prédictif "
                                    "validé, et les probabilités "
                                    "ne sont pas calibrées."
                                )

st.divider()
st.caption("Foot AI Pro — Version expérimentale")