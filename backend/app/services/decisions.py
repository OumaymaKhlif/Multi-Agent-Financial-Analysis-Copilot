import os
import psycopg


# Connexion PostgreSQL avec les variables Docker
def _conn():
    return psycopg.connect(
        host=os.getenv("DB_HOST", "database"), port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "financial_copilot"),
        user=os.getenv("DB_USER", "copilot_user"), password=os.getenv("POSTGRES_PASSWORD"),
    )


# Enregistre la décision. Renvoie False si l'analyse a déjà été décidée (lien déjà utilisé)
def record_decision(thread_id: str, action: str, reviewer: str) -> bool:
    with _conn() as c:
        row = c.execute(
            "INSERT INTO analysis_decisions (thread_id, action, reviewer) VALUES (%s, %s, %s) "
            "ON CONFLICT (thread_id) DO NOTHING RETURNING thread_id",   # ignore si déjà présent
            (thread_id, action, reviewer),
        ).fetchone()
    return row is not None   # None = conflit = déjà décidé


# Annule l'enregistrement si la reprise du workflow a échoué (permet de réessayer)
def release_decision(thread_id: str):
    with _conn() as c:
        c.execute("DELETE FROM analysis_decisions WHERE thread_id = %s", (thread_id,))