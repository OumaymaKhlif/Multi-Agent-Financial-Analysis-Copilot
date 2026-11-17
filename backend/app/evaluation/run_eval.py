# il crée le dataset de 3 questions dans LangSmith
# exécute le workflow sur chacune (une à la fois, pour respecter la limite Groq) 
# applique les 4 contrôles.

import asyncio
from uuid import uuid4
from langsmith import Client
import time

from app.graph.workflow import build_workflow
from app.evaluation.evaluators import (
    numbers_match, report_not_empty, no_forbidden_words, no_unneeded_review,
)

DATASET = "financial-copilot-eval"
QUESTIONS = [
    "Analyze Microsoft's FY2026 revenue growth vs FY2025 using only PostgreSQL data.",
    "Analyze Microsoft's FY2026 profitability (margins, ROA, ROE) using only PostgreSQL data.",
    "Analyze Microsoft's FY2026 equity ratio and liabilities using only PostgreSQL data.",
]


# Exécuter le workflow pour une question et renvoyer ce qu'on veut évaluer
async def _run(question):
    wf = await build_workflow()
    res = await wf.ainvoke({"question": question},
                           {"configurable": {"thread_id": str(uuid4())}})
    return {
        "report": res.get("report", ""),
        "kpi_calc": res.get("kpi_calc", ""),
        "needs_review": "__interrupt__" in res,
    }


# Fonction appelée par LangSmith pour chaque exemple (pause pour la limite Groq)
def target(inputs):
    time.sleep(60)
    return asyncio.run(_run(inputs["question"]))


if __name__ == "__main__":
    client = Client()
    # Créer le dataset une seule fois
    if not client.has_dataset(dataset_name=DATASET):
        ds = client.create_dataset(DATASET)
        client.create_examples(dataset_id=ds.id,
                               inputs=[{"question": q} for q in QUESTIONS])
    client.evaluate(
        target,
        data=DATASET,
        evaluators=[numbers_match, report_not_empty, no_forbidden_words, no_unneeded_review],
        experiment_prefix="copilot",
        max_concurrency=1,
    )