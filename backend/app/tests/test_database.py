import asyncio
from typing import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.tests.conftest import db_params

REVENUE = "RevenueFromContractWithCustomerExcludingAssessedTax"


# Insère une observation financière (ON CONFLICT : même comportement que l'extraction)
def add_obs(db, concept, value, start, end, form, filed, accn, fp="FY"):
    db.execute(
        "INSERT INTO financial_indicators (company, ticker, concept, value, unit, start_date, end_date, "
        "form, filed, fiscal_year, fiscal_period, accession_number) "
        "VALUES ('M', 'MSFT', %s, %s, 'USD', %s, %s, %s, %s, 2026, %s, %s) ON CONFLICT DO NOTHING",
        (concept, value, start, end, form, filed, fp, accn),
    )


# Le même JSON brut inséré deux fois ne crée qu'une ligne (ingestion n8n quotidienne)
def test_raw_payload_not_duplicated(db):
    sql = ("INSERT INTO sec_raw_data (source, company, ticker, payload) "
           "VALUES ('companyfacts', 'M', 'MSFT', %s::jsonb) ON CONFLICT DO NOTHING")
    db.execute(sql, ('{"a": 1}',))
    db.execute(sql, ('{"a":1}',))      # même contenu, mise en forme différente
    db.execute(sql, ('{"a": 2}',))     # contenu modifié : nouvelle ligne
    assert db.execute("SELECT COUNT(*) FROM sec_raw_data").fetchone()[0] == 2


# Une observation identique (start_date NULL compris) n'est stockée qu'une fois
def test_observation_not_duplicated(db):
    for _ in range(3):
        add_obs(db, "Assets", 758376, None, "2026-06-30", "10-K", "2026-07-29", "A26")
    assert db.execute("SELECT COUNT(*) FROM financial_indicators").fetchone()[0] == 1


# La vue annuelle utilise le 10-K annuel : ni un trimestre, ni un 10-Q ultérieur ne la faussent
def test_annual_view_uses_10k_and_full_year(db):
    add_obs(db, REVENUE, 281724, "2024-07-01", "2025-06-30", "10-K", "2025-07-30", "A25")
    add_obs(db, REVENUE, 331839, "2025-07-01", "2026-06-30", "10-K", "2026-07-29", "A26")
    add_obs(db, REVENUE, 90000, "2026-04-01", "2026-06-30", "10-K", "2026-07-29", "A26")   # trimestre : exclu
    add_obs(db, "Assets", 758376, None, "2026-06-30", "10-K", "2026-07-29", "A26")
    add_obs(db, "Assets", 999999, None, "2026-06-30", "10-Q", "2026-10-28", "Q1", fp="Q1")  # 10-Q : ignoré
    row = db.execute(
        "SELECT fiscal_year, revenue, assets, revenue_growth_pct "
        "FROM financial_analysis_annual WHERE fiscal_year = 2026"
    ).fetchone()
    assert row[0] == 2026 and row[1] == 331839 and row[2] == 758376
    assert float(row[3]) == 17.79


# Une décision humaine ne peut être enregistrée qu'une fois (lien à usage unique)
def test_decision_single_use(db, test_db, monkeypatch):
    monkeypatch.setenv("DB_NAME", test_db)
    from app.services.decisions import record_decision, release_decision
    assert record_decision("t1", "approve", "reviewer") is True
    assert record_decision("t1", "reject", "autre") is False      # lien déjà utilisé
    release_decision("t1")                                         # libération après un échec
    assert record_decision("t1", "approve", "reviewer") is True


class S(TypedDict, total=False):
    answer: str


# Mini-graphe avec une pause humaine, compilé avec le checkpointer fourni
def build_graph(saver):
    async def ask(state):
        return {"answer": interrupt("validation ?")}
    g = StateGraph(S)
    g.add_node("ask", ask)
    g.add_edge(START, "ask")
    g.add_edge("ask", END)
    return g.compile(checkpointer=saver)


# Ouvre un pool PostgreSQL et un checkpointer (même configuration que get_workflow)
async def open_saver(conninfo):
    pool = AsyncConnectionPool(
        conninfo=conninfo, min_size=1, max_size=2, open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open()
    saver = AsyncPostgresSaver(pool)
    await saver.setup()
    return pool, saver


async def pause_then_restart_then_resume(conninfo):
    config = {"configurable": {"thread_id": "thread-restart"}}
    pool, saver = await open_saver(conninfo)
    first = await build_graph(saver).ainvoke({"answer": ""}, config)
    assert "__interrupt__" in first                       # analyse en pause
    await pool.close()                                    # simule l'arrêt du backend
    pool2, saver2 = await open_saver(conninfo)            # nouveau démarrage : nouveau graphe
    second = await build_graph(saver2).ainvoke(Command(resume="approve"), config)
    await pool2.close()
    return second


# Une analyse en pause survit à un redémarrage et reprend après la décision humaine
def test_hitl_survives_restart(test_db):
    p = db_params(test_db)
    conninfo = " ".join(f"{k}={v}" for k, v in p.items())
    result = asyncio.run(pause_then_restart_then_resume(conninfo))
    assert result["answer"] == "approve"