# Importer les fonctions nécessaires
import os
import psycopg

# Importer FastAPI et le format de résultat PostgreSQL
from fastapi import FastAPI
from psycopg.rows import dict_row

# Importer le routeur du système multi-agents
from app.api.analysis import router as analysis_router

# Créer l'application API
app = FastAPI(title="Microsoft Financial Analysis API")

# Enregistrer le routeur du système multi-agents
app.include_router(analysis_router)


# Définir une route pour récupérer les analyses financières
@app.get("/financial-analysis")
def get_financial_analysis():

    # Se connecter à PostgreSQL avec les variables Docker
    with psycopg.connect(
        host=os.getenv("DB_HOST", "database"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "financial_copilot"),
        user=os.getenv("DB_USER", "copilot_user"),
        password=os.getenv("POSTGRES_PASSWORD"),
        row_factory=dict_row
    ) as connection:

        # Lire les KPI calculés dans la vue PostgreSQL
        result = connection.execute("""
            SELECT
                fiscal_year,
                end_date,
                revenue,
                net_income,
                operating_income,
                assets,
                equity,
                revenue_growth_pct,
                net_profit_margin_pct,
                operating_margin_pct,
                roa_pct,
                roe_pct
            FROM financial_analysis_annual
            ORDER BY end_date DESC;
        """).fetchall()

    # Retourner les résultats au format JSON
    return {
        "company": "MICROSOFT CORP",
        "ticker": "MSFT",
        "financial_analysis": result
    }