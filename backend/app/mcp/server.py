
import os
import json
import psycopg

from psycopg.rows import dict_row
from mcp.server import MCPServer
from pgvector import Vector

from app.rag.retriever import search_documents


# Initialisation du MCP Server
mcp = MCPServer("Financial Analysis Copilot")

# Similarité minimale (0 à 1) : en dessous, le passage est jugé hors sujet
MIN_SIMILARITY = float(os.getenv("MIN_SIMILARITY", "0.30"))


# Connexion à PostgreSQL
def get_connection():
    return psycopg.connect(
        host=os.getenv("DB_HOST", "database"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "financial_copilot"),
        user=os.getenv("DB_USER", "copilot_user"),
        password=os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD"),
        row_factory=dict_row
    )


# TOOL 1 : Recherche sémantique dans les documents financiers
@mcp.tool()
def search_financial_documents(query: str, top_k: int = 3) -> str:
    """Search Microsoft financial documents using the RAG system."""
    # On cherche plus large puis on retire les chunks trop courts (sommaire, titres)
    results = search_documents(query, top_k * 4)
    results = [r for r in results
        if len(r["content"]) >= 300 and r["similarity"] >= MIN_SIMILARITY][:top_k]
    for r in results:
        r["content"] = r["content"][:600]
    return json.dumps(results, default=str)


# TOOL 2 : Récupération des derniers indicateurs financiers
@mcp.tool()
def get_financial_kpis() -> str:
    """Retrieve Microsoft's two latest annual financial KPIs."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT fiscal_year, end_date, revenue, net_income,
                   operating_income, assets, equity
            FROM financial_analysis_annual
            ORDER BY end_date DESC
            LIMIT 2;
        """).fetchall()
    return json.dumps(rows, default=str)


# TOOL 3 : Historique d'un indicateur financier
@mcp.tool()
def get_financial_history(concept: str, limit: int = 10) -> str:
    """Retrieve Microsoft's historical values for a financial indicator."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT concept, label, value, unit, end_date,
                   fiscal_year, fiscal_period, form, filed
            FROM financial_indicators
            WHERE concept ILIKE %s
            ORDER BY end_date DESC
            LIMIT %s;
        """, (f"%{concept}%", limit)).fetchall()

    return json.dumps(rows, default=str)


# Démarrage du serveur MCP en HTTP
if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8001)
