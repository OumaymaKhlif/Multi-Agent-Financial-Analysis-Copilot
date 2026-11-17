-- ============================================================
-- Financial Analysis Copilot : schéma PostgreSQL + pgvector
-- À exécuter dans pgAdmin (Query Tool) ou via psql
-- ============================================================

-- Activer l'extension pgvector (stockage des embeddings)
CREATE EXTENSION IF NOT EXISTS vector;

-- 1) Données brutes SEC (JSON) alimentées par n8n
CREATE TABLE IF NOT EXISTS sec_raw_data (
    id BIGSERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,          -- submissions ou companyfacts
    company VARCHAR(100) NOT NULL,
    ticker VARCHAR(10) NOT NULL,
    payload JSONB NOT NULL,               -- réponse JSON brute de la SEC
    collected_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sec_source ON sec_raw_data(source);

-- 2) Indicateurs financiers XBRL structurés
CREATE TABLE IF NOT EXISTS financial_indicators (
    id BIGSERIAL PRIMARY KEY,
    company VARCHAR(100),
    ticker VARCHAR(10),
    concept VARCHAR(150),                 -- nom technique XBRL
    label TEXT,
    value NUMERIC,
    unit VARCHAR(30),
    start_date DATE,
    end_date DATE,
    form VARCHAR(10),                     -- 10-K, 10-Q...
    filed DATE,
    fiscal_year INTEGER,
    fiscal_period VARCHAR(10),            -- FY, Q1, Q2...
    accession_number VARCHAR(30)
);

-- 3) Extraction des indicateurs depuis le JSON brut companyfacts
INSERT INTO financial_indicators (
    company, ticker, concept, label, value, unit,
    start_date, end_date, form, filed,
    fiscal_year, fiscal_period, accession_number
)
WITH facts AS (
    SELECT payload->'facts'->'us-gaap' AS data
    FROM sec_raw_data
    WHERE source = 'companyfacts'
),
concepts AS (
    SELECT key AS concept, value AS details
    FROM facts, LATERAL jsonb_each(data)
),
units AS (
    SELECT concept, details->>'label' AS label, unit_key AS unit, unit_values
    FROM concepts, LATERAL jsonb_each(details->'units') AS u(unit_key, unit_values)
),
records AS (
    SELECT concept, label, unit, jsonb_array_elements(unit_values) AS observation
    FROM units
    WHERE concept IN (
        'Revenues',
        'RevenueFromContractWithCustomerExcludingAssessedTax',
        'NetIncomeLoss',
        'Assets',
        'OperatingIncomeLoss',
        'StockholdersEquity'
    )
)
SELECT
    'MICROSOFT CORP', 'MSFT', concept, label,
    (observation->>'val')::NUMERIC, unit,
    NULLIF(observation->>'start', '')::DATE,
    (observation->>'end')::DATE,
    observation->>'form',
    NULLIF(observation->>'filed', '')::DATE,
    NULLIF(observation->>'fy', '')::INTEGER,
    observation->>'fp',
    observation->>'accn'
FROM records;

-- 4) Vue nettoyée : une seule observation par indicateur et période
CREATE OR REPLACE VIEW financial_indicators_clean AS
SELECT DISTINCT ON (concept, unit, start_date, end_date) *
FROM financial_indicators
ORDER BY concept, unit, start_date, end_date, filed DESC NULLS LAST, id DESC;

-- 5) Vue des KPI annuels (croissance, marges, ROA, ROE)
CREATE OR REPLACE VIEW financial_analysis_annual AS
WITH annual_data AS (
    SELECT
        fiscal_year,
        end_date,
        MAX(value) FILTER (WHERE concept = 'RevenueFromContractWithCustomerExcludingAssessedTax') AS revenue,
        MAX(value) FILTER (WHERE concept = 'NetIncomeLoss') AS net_income,
        MAX(value) FILTER (WHERE concept = 'OperatingIncomeLoss') AS operating_income,
        MAX(value) FILTER (WHERE concept = 'Assets') AS assets,
        MAX(value) FILTER (WHERE concept = 'StockholdersEquity') AS equity
    FROM financial_indicators
    WHERE form IN ('10-K', '10-K/A') AND fiscal_period = 'FY' AND unit = 'USD'
    GROUP BY fiscal_year, end_date
),
kpi AS (
    SELECT *, LAG(revenue) OVER (ORDER BY end_date) AS previous_revenue
    FROM annual_data
)
SELECT *,
    ROUND(((revenue - previous_revenue) / NULLIF(previous_revenue, 0) * 100)::NUMERIC, 2) AS revenue_growth_pct,
    ROUND((net_income / NULLIF(revenue, 0) * 100)::NUMERIC, 2) AS net_profit_margin_pct,
    ROUND((operating_income / NULLIF(revenue, 0) * 100)::NUMERIC, 2) AS operating_margin_pct,
    ROUND((net_income / NULLIF(assets, 0) * 100)::NUMERIC, 2) AS roa_pct,
    ROUND((net_income / NULLIF(equity, 0) * 100)::NUMERIC, 2) AS roe_pct
FROM kpi;

-- 6) Table RAG : chunks du rapport annuel + embeddings (Qwen3-Embedding-0.6B = 1024 dim.)
CREATE TABLE IF NOT EXISTS document_chunks (
    id BIGSERIAL PRIMARY KEY,
    source_title TEXT NOT NULL,
    source_url TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding VECTOR(1024),
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source_url, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_document_embedding
ON document_chunks USING hnsw (embedding vector_cosine_ops);
