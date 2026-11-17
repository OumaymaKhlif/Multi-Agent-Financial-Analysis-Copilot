import os
import json
from typing import TypedDict

from langchain_groq import ChatGroq
from langchain.mcp import MCPAdapter
from langgraph.graph import StateGraph, START, END

import re
from langgraph.types import interrupt, Command
from langgraph.checkpoint.memory import MemorySaver


class CopilotState(TypedDict, total=False):
    question: str
    plan: str
    research: str
    kpis: str          # KPI bruts PostgreSQL (source de vérité)
    kpi_calc: str      # ratios calculés en Python (pas par le LLM)
    analysis: str
    risk_review: str
    supervisor_decision: str
    report: str
    human_decision: str
    human_comment: str


def get_text(response):
    c = response.content
    return c if isinstance(c, str) else str(c)


def tool_text(result):
    """Normalise la sortie d'un outil MCP en texte."""
    if isinstance(result, list):
        return "".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in result
        )
    return str(result)


def compute_kpis(kpis_text: str) -> str:
    """Calcule les ratios en Python pour éviter les erreurs du LLM."""
    try:
        rows = json.loads(kpis_text)
    except Exception:
        return "Data not available"

    out = []
    for r in rows:  # FY2026 puis FY2025
        rev, ni = float(r["revenue"]), float(r["net_income"])
        op, a, e = float(r["operating_income"]), float(r["assets"]), float(r["equity"])
        out.append(
            f"{r['end_date']} (FY{r['fiscal_year']}, USD): "
            f"revenue={rev:,.0f}; net_income={ni:,.0f}; operating_income={op:,.0f}; "
            f"assets={a:,.0f}; equity={e:,.0f}; "
            f"total_liabilities(assets-equity)={a - e:,.0f}; "
            f"net_margin={ni / rev * 100:.2f}% (net_income/revenue); "
            f"operating_margin={op / rev * 100:.2f}% (operating_income/revenue); "
            f"ROA={ni / a * 100:.2f}% (net_income/assets, year-end); "
            f"ROE={ni / e * 100:.2f}% (net_income/equity, year-end); "
            f"equity_ratio={e / a * 100:.2f}% (equity/assets)"
        )
    if len(rows) >= 2:
        r0, r1 = float(rows[0]["revenue"]), float(rows[1]["revenue"])
        out.append(f"revenue_growth={(r0 - r1) / r1 * 100:.2f}% ((rev_FY_n - rev_FY_n-1)/rev_FY_n-1)")
        # Croissances calculées en Python (le LLM ne doit rien calculer)
    if len(rows) >= 2:
        for k in ("net_income", "operating_income"):
            n, p = float(rows[0][k]), float(rows[1][k])
            out.append(f"{k}_growth={(n - p) / p * 100:.2f}% (FY{rows[1]['fiscal_year']} -> FY{rows[0]['fiscal_year']})")

    return "\n".join(out)


SOURCE_RULE = (
    "RÈGLE : les données PostgreSQL fournies sont la SEULE source de vérité. "
    "N'utilise AUCUNE connaissance externe sur Microsoft et ne conteste pas ces chiffres. "
    "Réponse concise (max 250 mots).\n"
)


async def build_workflow():
    llm = ChatGroq(
        model=os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.1,
        max_tokens=4096,
        reasoning_effort="low",
        max_retries=8,
    )

    async with MCPAdapter("http://mcp-server:8001/mcp") as mcp_client:
        tools = await mcp_client.list_tools()
    tool_map = {t.name: t for t in tools}

    async def planner(state):
        r = await llm.ainvoke(
            "Tu es le Planner Agent. Liste en 5 puces max les étapes pour répondre : "
            + state["question"]
        )
        return {"plan": get_text(r)}

    async def researcher(state):
        # Requête courte et ciblée (pas la question entière)
        docs = await tool_map["search_financial_documents"].ainvoke({
            "query": "Microsoft revenue increased operating income net income risk factors",
            "top_k": 3,
        })
        r = await llm.ainvoke(
            "Tu es un Research Agent. Résume les passages ci-dessous en gardant "
            "titre, source et chiffres exacts. Max 200 mots. "
            "Si un passage ne contient aucun chiffre, dis-le.\n" + tool_text(docs)
        )
        return {"research": get_text(r)}

    async def analyst(state):
        kpis = tool_text(await tool_map["get_financial_kpis"].ainvoke({}))
        kpi_calc = compute_kpis(kpis)
        r = await llm.ainvoke(
            "Tu es un Financial Analyst. " + SOURCE_RULE +
            "Les ratios ci-dessous sont DÉJÀ calculés : recopie-les sans les recalculer.\n"
            "Ne confonds pas passifs et dette financière. Aucune comparaison sectorielle. "
            "Distingue faits et interprétations. Écris 'Data not available' si absent.\n"
            "Format : 1. Indicateurs 2. Calculs et formules 3. Limites\n\n"
            "KPI CALCULÉS :\n" + kpi_calc +
            "\n\nRECHERCHE DOCUMENTAIRE :\n" + state.get("research", "")
        )
        return {"kpis": kpis, "kpi_calc": kpi_calc, "analysis": get_text(r)}

    async def verifier(state):
        r = await llm.ainvoke(
            "Tu es le Risk Verifier. " + SOURCE_RULE +
            "Compare l'ANALYSE aux KPI CALCULÉS : signale uniquement les écarts de chiffres, "
            "d'unités ou de périodes. Une source sans chiffre = limite, pas erreur.\n\n"
            "KPI CALCULÉS :\n" + state["kpi_calc"] +
            "\n\nANALYSE :\n" + state["analysis"]
        )
        return {"risk_review": get_text(r)}

    async def supervisor(state):
        r = await llm.ainvoke(
            "Tu es le Supervisor. " + SOURCE_RULE +
            "Décide :\n"
            "- APPROVED_FOR_DRAFT si l'analyse correspond aux KPI CALCULÉS "
            "(même si des données manquent : elles sont alors signalées comme limites).\n"
            "- HUMAN_REVIEW_REQUIRED SEULEMENT si un chiffre de l'analyse contredit les KPI "
            "calculés ou si une conclusion n'est pas justifiée par les données.\n"
            "Ne compare jamais avec tes connaissances externes. "
            "Ne prétends pas avoir vérifié une URL.\n"
            "Format :\nDECISION: ...\nJUSTIFICATION: ...\nLIMITATIONS: ...\n\n"
            "KPI CALCULÉS :\n" + state["kpi_calc"] +
            "\n\nANALYSE :\n" + state["analysis"] +
            "\n\nVÉRIFICATION :\n" + (state.get("risk_review") or "Vérification vide")
        )
        return {"supervisor_decision": get_text(r)}

    async def report_generator(state):
        r = await llm.ainvoke(
            "Tu es un analyste financier senior. Rédige en français un brouillon "
            "(pas un conseil financier). " + SOURCE_RULE +
            "Structure : 1. Résumé exécutif 2. Performance et croissance "
            "3. Rentabilité 4. Ratios 5. Risques et limites 6. Conclusion.\n"
            "Règles : recopie exactement les chiffres, unités et périodes des KPI CALCULÉS ; "
            "ne recalcule rien ; passifs ≠ dette financière ; pas de comparaison sectorielle ; "
            "ROA/ROE sur soldes de fin d'exercice ; faits et interprétations séparés ; "
            "'Donnée non disponible' si absent.\n\n"
            "INTERDIT : citer des segments (cloud, services…), des causes, une maîtrise des coûts "
            "ou une amélioration non chiffrée. Une interprétation = une seule phrase comparant "
            "uniquement les chiffres fournis.\n\n"
            "Ne calcule JAMAIS toi-même : utilise uniquement les croissances et variations fournies. "
            "Toujours écrire les périodes dans l'ordre FY2025 -> FY2026. "
            "Pas de section 'Interprétations' séparée, pas de mots 'solide' ou 'robuste'.\n\n"
            "KPI CALCULÉS :\n" + state["kpi_calc"] +
            "\n\nANALYSE :\n" + state["analysis"] +
            "\n\nRECHERCHE :\n" + state["research"] +
            "\n\nVÉRIFICATION :\n" + state["risk_review"] +
            "\n\nDÉCISION SUPERVISOR :\n" + state["supervisor_decision"]
        )
        # Si le modèle n'a rien écrit, on le signale au lieu de renvoyer un texte vide
        report = get_text(r).strip() or "ERREUR : rapport vide (tokens épuisés), relancer."
        return {"report": report}
    
    # mettre le workflow en pause et attendre la réponse de l’humain.
    async def human_review(state):
        answer = interrupt({
            "supervisor_decision": state["supervisor_decision"],
            "kpi_calc": state["kpi_calc"],
            "analysis": state["analysis"],
        })
        return {"human_decision": answer.get("action", "reject"),
                "human_comment": answer.get("comment", "")}

    # envoyer vers l’humain si le Supervisor répond HUMAN_REVIEW_REQUIRED, sinon directement au rapport.
    def after_supervisor(state):
        """if re.search(r"DECISION:\s*\**\s*HUMAN_REVIEW_REQUIRED", state["supervisor_decision"]):
            return "human_review"""
        if True:  # TEST : force la validation humaine
            return "human_review"
        return "report_generator"

    # générer le rapport si l’humain approuve, sinon arrêter.
    def after_human(state):
        return "report_generator" if state.get("human_decision") == "approve" else END

    
    g = StateGraph(CopilotState)
    for name, fn in [
        ("planner", planner), ("researcher", researcher), ("analyst", analyst),
        ("verifier", verifier), ("supervisor", supervisor),
        ("human_review", human_review), ("report_generator", report_generator),
    ]:
        g.add_node(name, fn)

    g.add_edge(START, "planner")
    g.add_edge("planner", "researcher")
    g.add_edge("researcher", "analyst")
    g.add_edge("analyst", "verifier")
    g.add_edge("verifier", "supervisor")
    g.add_conditional_edges("supervisor", after_supervisor, ["human_review", "report_generator"])
    g.add_conditional_edges("human_review", after_human, ["report_generator", END])
    g.add_edge("report_generator", END)
    # sauvegarder l’état du graphe pour pouvoir le reprendre.
    return g.compile(checkpointer=MemorySaver())


_workflow = None

async def get_workflow():
    global _workflow
    if _workflow is None:
        _workflow = await build_workflow()
    return _workflow

async def run_financial_analysis(question: str, thread_id: str):
    wf = await get_workflow()
    return await wf.ainvoke({"question": question},
                            {"configurable": {"thread_id": thread_id}})

async def resume_analysis(thread_id: str, action: str, comment: str = ""):
    wf = await get_workflow()
    return await wf.ainvoke(Command(resume={"action": action, "comment": comment}),
                            {"configurable": {"thread_id": thread_id}})