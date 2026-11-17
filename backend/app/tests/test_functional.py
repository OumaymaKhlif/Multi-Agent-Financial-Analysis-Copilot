# teste le calcul des KPI, le PDF et les évaluateurs.

import json
from app.services.pdf_report import report_to_pdf
from app.evaluation.evaluators import numbers_match, no_forbidden_words

# Données de test : mêmes valeurs que PostgreSQL (FY2026 puis FY2025)
ROWS = [
    {"fiscal_year": 2026, "end_date": "2026-06-30", "revenue": 331839000000,
     "net_income": 133749000000, "operating_income": 155237000000,
     "assets": 758376000000, "equity": 442387000000},
    {"fiscal_year": 2025, "end_date": "2025-06-30", "revenue": 281724000000,
     "net_income": 101832000000, "operating_income": 128528000000,
     "assets": 619003000000, "equity": 343479000000},
]


def kpis():
    from app.graph.workflow import compute_kpis
    return compute_kpis(json.dumps(ROWS))


# Les ratios calculés en Python doivent correspondre aux valeurs attendues
def test_kpi_ratios():
    out = kpis()
    for expected in ["net_margin=40.31%", "operating_margin=46.78%", "ROA=17.64%",
                     "ROE=30.23%", "equity_ratio=58.33%", "revenue_growth=17.79%",
                     "net_income_growth=31.34%", "operating_income_growth=20.78%",
                     "total_liabilities(assets-equity)=315,989,000,000"]:
        assert expected in out


# Sans données, le calcul doit renvoyer "Data not available"
def test_kpi_no_data():
    from app.graph.workflow import compute_kpis
    assert compute_kpis("not json") == "Data not available"


# Le PDF doit être valide, même avec des caractères spéciaux
def test_pdf_generation():
    pdf = report_to_pdf("**Titre**\n- Net‑income growth : 31,34 % → FY2026 ≠ FY2025")
    assert pdf.startswith(b"%PDF")


# Un chiffre faux dans le rapport doit être détecté
def test_evaluator_detects_wrong_number():
    out = {"kpi_calc": kpis(), "report": "Croissance 17,80 %."}
    assert numbers_match(out)["score"] == 0.0


# Un rapport correct doit être validé
def test_evaluator_accepts_correct_number():
    out = {"kpi_calc": kpis(), "report": "Croissance 17,79 %. Revenu 331 839 M USD."}
    assert numbers_match(out)["score"] == 1.0


# Les mots interdits doivent être détectés
def test_forbidden_words():
    assert no_forbidden_words({"report": "croissance robuste"})["score"] == 0.0