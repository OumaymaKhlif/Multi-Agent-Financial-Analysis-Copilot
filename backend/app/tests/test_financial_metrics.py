import json
import pytest
from app.services.financial_metrics import build_kpi_report, growth_pct, ratio_pct

# FY2026 puis FY2025 (mêmes valeurs que PostgreSQL)
ROWS = [
    {"fiscal_year": 2026, "end_date": "2026-06-30", "revenue": 331839000000,
     "net_income": 133749000000, "operating_income": 155237000000,
     "assets": 758376000000, "equity": 442387000000},
    {"fiscal_year": 2025, "end_date": "2025-06-30", "revenue": 281724000000,
     "net_income": 101832000000, "operating_income": 128528000000,
     "assets": 619003000000, "equity": 343479000000},
]


def report(rows):
    return build_kpi_report(json.dumps(rows))


# Ratios sur moyennes : 133749 / ((758376 + 619003) / 2) = 19,42 %
def test_average_based_ratios():
    out = report(ROWS)
    assert "ROA_avg=19.42%" in out and "ROE_avg=34.04%" in out


# Valeur manquante (NULL en base) : pas de crash, ratio marqué "Data not available"
def test_missing_value_does_not_crash():
    out = report([dict(ROWS[0], net_income=None), ROWS[1]])
    assert "net_margin=Data not available" in out


# Chiffre d'affaires nul : pas de division par zéro
def test_zero_revenue():
    out = report([dict(ROWS[0], revenue=0), ROWS[1]])
    assert "net_margin=Data not available" in out


# Capitaux propres négatifs : ROE non significatif et alerte qualité
def test_negative_equity():
    out = report([dict(ROWS[0], equity=-100), ROWS[1]])
    assert "ROE=Data not available" in out and "data_quality_warnings" in out


# Incohérence comptable : capitaux propres supérieurs aux actifs
def test_equity_greater_than_assets():
    out = report([dict(ROWS[0], equity=900000000000), ROWS[1]])
    assert "equity > assets" in out


# Croissance : pas de calcul sur une base nulle ou négative
def test_growth_with_non_positive_base():
    assert growth_pct(100, 0) is None
    assert growth_pct(100, -5) is None
    assert growth_pct(110, 100) == pytest.approx(10.0)


# Dénominateur nul ou valeur absente : None
def test_ratio_guards():
    assert ratio_pct(10, 0) is None
    assert ratio_pct(None, 10) is None


# Entrée invalide ou vide
def test_invalid_input():
    assert build_kpi_report("not json") == "Data not available"
    assert build_kpi_report("[]") == "Data not available"