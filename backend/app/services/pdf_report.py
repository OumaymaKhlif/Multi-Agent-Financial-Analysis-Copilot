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