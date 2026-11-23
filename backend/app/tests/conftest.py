import pytest
from app.main import app
from app.services.security import require_api_key


# Pour tous les tests : désactiver la vérification de clé (sauf dans le test dédié)
@pytest.fixture(autouse=True)
def bypass_api_key():
    app.dependency_overrides[require_api_key] = lambda: None
    yield
    app.dependency_overrides.clear()

import os
import uuid
from pathlib import Path

import psycopg

# Script SQL du projet (monté en lecture seule dans le conteneur backend)
INIT_SQL = Path(os.getenv("INIT_SQL", "/app/infrastructure/postgres/init.sql"))


# Paramètres de connexion PostgreSQL (mêmes variables que le backend)
def db_params(dbname: str) -> dict:
    return dict(
        host=os.getenv("DB_HOST", "database"), port=os.getenv("DB_PORT", "5432"),
        dbname=dbname, user=os.getenv("DB_USER", "copilot_user"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )


# Base de test temporaire : créée avec le vrai schéma, supprimée à la fin
@pytest.fixture(scope="session")
def test_db():
    if not INIT_SQL.exists():
        pytest.skip("init.sql introuvable (volume non monté)")
    try:
        admin = psycopg.connect(**db_params("postgres"), autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL indisponible")
    name = f"copilot_test_{uuid.uuid4().hex[:8]}"
    admin.execute(f'CREATE DATABASE "{name}"')
    with psycopg.connect(**db_params(name), autocommit=True) as conn:
        conn.execute(INIT_SQL.read_text(encoding="utf-8"))   # tables, vues, contraintes
    yield name
    admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
    admin.close()


# Connexion propre à chaque test : tables vidées avant utilisation
@pytest.fixture
def db(test_db):
    with psycopg.connect(**db_params(test_db), autocommit=True) as conn:
        conn.execute("TRUNCATE sec_raw_data, financial_indicators, analysis_decisions RESTART IDENTITY")
        yield conn