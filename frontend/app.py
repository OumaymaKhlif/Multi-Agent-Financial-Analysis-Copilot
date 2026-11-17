import os
import requests
import streamlit as st

import re
import markdown
from fpdf import FPDF

import re
import markdown
from fpdf import FPDF


# Remplacer les caractères non supportés par la police PDF standard
def clean(text):
    for a, b in {"’": "'", "‘": "'", "“": '"', "”": '"', "→": "->", "≠": "!=",
                 "–": "-", "—": "-", "‑": "-", "‐": "-", "‒": "-", "−": "-",
                 "…": "...", "\u202f": " ", "\u00a0": " "}.items():
        text = text.replace(a, b)
    return text.encode("latin-1", "replace").decode("latin-1")


# Convertir le rapport markdown en fichier PDF
def report_to_pdf(md_text):
    md_text = re.sub(r"([^\n])\n([-*] )", r"\1\n\n\2", clean(md_text))
    html = markdown.markdown(md_text, extensions=["tables"])
    html = html.replace("<strong>", "<b>").replace("</strong>", "</b>")
    pdf = FPDF()
    pdf.set_margins(20, 20, 20)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Financial Analysis Report - Microsoft", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(91, 103, 120)
    pdf.cell(0, 6, "Brouillon d'analyse - ne constitue pas un conseil financier",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_text_color(15, 27, 45)
    pdf.set_font("Helvetica", "", 10.5)
    pdf.write_html(html)
    return bytes(pdf.output())

# Adresse du backend FastAPI (nom du service Docker)
API_URL = os.getenv("API_URL", "http://backend:8000")

st.set_page_config(page_title="Financial Analysis Copilot", layout="wide")

# Style global : police, couleurs, boutons, cartes et en-tête
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&display=swap');
html, body, .stApp, .stMarkdown, button, textarea, input {
    font-family: 'IBM Plex Sans', sans-serif !important;
}
#MainMenu, footer, header { visibility: hidden; }
.block-container { max-width: 960px; padding-top: 3rem; }

.brand { font-size: 1.6rem; font-weight: 600; color: #0F1B2D; letter-spacing: -0.01em; }
.tagline { color: #5B6778; font-size: 0.95rem; margin: 0.2rem 0 1.2rem 0; }
.rule { border: 0; border-top: 1px solid #E3E7ED; margin: 0 0 1.8rem 0; }

textarea { background: #FFFFFF !important; border: 1px solid #CBD3DD !important;
           border-radius: 4px !important; font-size: 0.95rem !important; }
label p { font-weight: 500; color: #0F1B2D; }

.stButton > button, .stDownloadButton > button {
    border-radius: 4px; border: 1px solid #1F4E8C; background: #FFFFFF;
    color: #1F4E8C; font-weight: 500; padding: 0.45rem 1.3rem; box-shadow: none;
}
.stButton > button[kind="primary"] { background: #1F4E8C; color: #FFFFFF; }
.stButton > button:hover, .stDownloadButton > button:hover {
    border-color: #163A68; background: #163A68; color: #FFFFFF;
}

[data-testid="stVerticalBlockBorderWrapper"] {
    background: #FFFFFF; border: 1px solid #E3E7ED; border-radius: 6px;
}
[data-testid="stAlert"] {
    background: #FFFFFF; border: 1px solid #E3E7ED; border-left: 4px solid #1F4E8C;
    border-radius: 4px; color: #0F1B2D;
}
h2, h3 { color: #0F1B2D; font-weight: 600; letter-spacing: -0.01em; }
table { font-size: 0.9rem; }
</style>
<div class="brand">Financial Analysis Copilot</div>
<div class="tagline">Analyse financière multi-agents de Microsoft, basée sur les dépôts SEC.</div>
<hr class="rule">
""", unsafe_allow_html=True)

# Mémoriser le résultat entre les clics (Streamlit relance le script à chaque action)
if "result" not in st.session_state:
    st.session_state.result = None

# Question par défaut
DEFAULT_Q = (
    "Analyze Microsoft's FY2026 financial performance using only PostgreSQL data "
    "and RAG documents: revenue growth vs FY2025, profitability, ROA, ROE, equity "
    "ratio, and risks. Keep figures, units and periods exact, show formulas, "
    "separate facts from interpretations, and write 'Data not available' when "
    "data is missing."
)


# Appeler l'API et gérer les erreurs (timeout long : 6 agents)
def call_api(path, payload):
    try:
        r = requests.post(f"{API_URL}{path}", json=payload, timeout=300)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Erreur API : {e}")
        return None


# Zone de saisie de la question
question = st.text_area("Question financière", DEFAULT_Q, height=150)

# Lancer l'analyse
if st.button("Lancer l'analyse", type="primary"):
    with st.spinner("Les agents analysent les données..."):
        st.session_state.result = call_api("/analysis/", {"question": question})

result = st.session_state.result

if result:
    # Cas 1 : le Supervisor demande une validation humaine
    if result["status"] == "PENDING_HUMAN_REVIEW":
        st.warning("Validation humaine requise")
        data = result["review_data"]
        st.subheader("Décision du Supervisor")
        st.write(data["supervisor_decision"])
        with st.expander("KPI calculés"):
            st.code(data["kpi_calc"])
        with st.expander("Analyse"):
            st.write(data["analysis"])

        comment = st.text_input("Commentaire (optionnel)")
        col1, col2, _ = st.columns([1, 1, 4])
        # Approuver : le rapport est généré
        if col1.button("Approuver"):
            with st.spinner("Génération du rapport..."):
                st.session_state.result = call_api(
                    f"/analysis/{result['thread_id']}/review",
                    {"action": "approve", "comment": comment},
                )
            st.rerun()
        # Rejeter : le workflow s'arrête
        if col2.button("Rejeter"):
            st.session_state.result = call_api(
                f"/analysis/{result['thread_id']}/review",
                {"action": "reject", "comment": comment},
            )
            st.rerun()

    # Cas 2 : analyse terminée
    elif result["status"] == "COMPLETED":
        if result.get("report"):
            # Rapport dans une carte blanche
            with st.container(border=True):
                st.markdown(result["report"])
            st.download_button("Télécharger le rapport (PDF)", report_to_pdf(result["report"]),
                               file_name="rapport_microsoft.pdf", mime="application/pdf")
        else:
            st.info("Analyse rejetée : aucun rapport généré.")
        with st.expander("Décision du Supervisor"):
            st.write(result["supervisor_decision"])