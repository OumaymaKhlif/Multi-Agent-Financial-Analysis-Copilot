import os
import json
from typing import TypedDict

from langchain_groq import ChatGroq
from langchain.mcp import MCPAdapter
from langgraph.graph import StateGraph, START, END

import re
from langgraph.types import interrupt, Command
from langgraph.checkpoint.memory import MemorySaver

# Récupérer les résultats SQL sous forme de dictionnaires ({"id": 1}) plutôt que de tuples. C'est le format attendu par le checkpointer.
from psycopg.rows import dict_row                                  
from psycopg_pool import AsyncConnectionPool                       # pool de connexions asynchrones (éviter d'ouvrir une nouvelle connexion à chaque opération)
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver   # checkpointer PostgreSQL asynchrone

from app.services.financial_metrics import build_kpi_report

from app.services.prompt_safety import UNTRUSTED_RULE, filter_passages, wrap_untrusted, wrap_text

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

# Appeller le module financial_metrics.py pour calculer les indicateurs et ratios financiers
def compute_kpis(kpis_text: str) -> str:
    """Calcule les ratios en Python (module financial_metrics) pour éviter les erreurs du LLM."""
    return build_kpi_report(kpis_text)


SOURCE_RULE = (
    "RÈGLE : les données PostgreSQL fournies sont la SEULE source de vérité. "
    "N'utilise AUCUNE connaissance externe sur Microsoft et ne conteste pas ces chiffres. "
    "Réponse concise (max 250 mots).\n"
)

# envoyer vers l’humain si le Supervisor répond HUMAN_REVIEW_REQUIRED, sinon directement au rapport.
def after_supervisor(state):
    decision = state.get("supervisor_decision", "")
    # Seule une approbation explicite évite la validation humaine : tout autre texte va à l'humain
    if re.search(r"DECISION:\s*\**\s*APPROVED_FOR_DRAFT", decision):
        return "report_generator"
    return "human_review" 

# Fusionne les résultats de plusieurs recherches sans doublons (même document + même chunk)
def merge_passages(batches):
    seen, merged = set(), []
    for batch in batches:                          # un lot de passages par requête
        for p in batch:
            key = (p["source"], p["chunk_index"])  # identifiant unique d'un passage
            if key not in seen:
                seen.add(key)
                merged.append(p)
    return merged

# ------------------------------------------------------------------
# TRACING LANGSMITH : lecture d'une trace
# Activé par LANGSMITH_TRACING, LANGSMITH_API_KEY et LANGSMITH_PROJECT
# (docker-compose.yml). Chaque analyse = une trace dans le projet.
#
# Arbre d'une trace (un nœud par agent) :
#   planner            -> plan en 5 puces (1 appel LLM)
#   researcher         -> 3 appels search_financial_documents (outil MCP),
#                         puis 1 appel LLM qui résume les passages
#   analyst            -> get_financial_kpis (outil MCP) + 1 appel LLM
#   verifier           -> compare l'analyse aux KPI calculés
#   supervisor         -> décision APPROVED_FOR_DRAFT ou HUMAN_REVIEW_REQUIRED
#   human_review       -> présent seulement si validation humaine (pause)
#   report_generator   -> rapport final
#
# Pour chaque nœud, LangSmith affiche : Input, Output, durée, tokens, erreurs.
# thread_id = identifiant de l'analyse (le même que dans les emails).
# ------------------------------------------------------------------

async def build_workflow(checkpointer=None):
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
        # Dans LangSmith, chaque appel search_financial_documents montre :
        #   Input  : query (une des 3 requêtes) et top_k
        #   Output : liste de passages {title, source, chunk_index, content, similarity}
        #            similarity : 0 à 1 (1 = très proche de la requête)


        question = state["question"][:500]   # limiter la taille pour l'embedding
        # 3 angles de recherche construits à partir de la question de l'utilisateur
        # 1. La question telle quelle.
        # 2. La question + financial metrics revenue operating income net income : pour retrouver les chiffres liés.
        # 3. La question + risks and limitations : pour retrouver les passages sur les risques.
        queries = [
            question,
            f"{question} financial metrics revenue operating income net income",
            f"{question} risks and limitations",
        ]

        # Chaque requête ramène 2 passages, puis les doublons sont retirés
        # la base calcule pour chaque passage un score entre 0 et 1 qui mesure à quel point son sens est proche de la question. 
        # Le système classe toujours des passages, même hors sujet, donc on retire ceux dont le score est sous le seuil
        batches = []
        for q in queries:
            raw = await tool_map["search_financial_documents"].ainvoke({"query": q, "top_k": 2}) 
            try:
                batches.append(json.loads(tool_text(raw)))   # liste de passages
            except ValueError:                               # réponse non JSON : ignorer
                batches.append([])
        
        passages = merge_passages(batches)[:5]
        passages, blocked = filter_passages(passages)      # écarter les passages suspects
        if not passages:
            return {"research": "Data not available : aucun passage documentaire fiable ou pertinent trouvé."}
        r = await llm.ainvoke(
            "Tu es un Research Agent. " + UNTRUSTED_RULE +
            "Résume les passages ci-dessous en gardant titre, source et chiffres exacts. Max 200 mots. "
            "Si un passage ne contient aucun chiffre, dis-le.\n" + wrap_untrusted(passages)
        )
        # Signaler à la suite du workflow (et à l'humain) qu'un passage a été écarté
        note = f"\n[{blocked} passage(s) écarté(s) : instructions suspectes]" if blocked else ""
        return {"research": get_text(r) + note}

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
            "\n\n" + UNTRUSTED_RULE + "RECHERCHE DOCUMENTAIRE :\n" + wrap_text(state.get("research", ""))
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
            "ROA/ROE sur soldes de fin d'exercice ; ROA_avg/ROE_avg sont des compléments "
            "sur soldes moyens, à citer à part avec leur libellé ; faits et interprétations séparés ; "
            "'Donnée non disponible' si absent.\n\n"
            "INTERDIT : citer des segments (cloud, services…), des causes, une maîtrise des coûts "
            "ou une amélioration non chiffrée. Une interprétation = une seule phrase comparant "
            "uniquement les chiffres fournis.\n\n"
            "Ne calcule JAMAIS toi-même : utilise uniquement les croissances et variations fournies. "
            "Toujours écrire les périodes dans l'ordre FY2025 -> FY2026. "
            "Pas de section 'Interprétations' séparée, pas de mots 'solide' ou 'robuste'.\n\n"
            "KPI CALCULÉS :\n" + state["kpi_calc"] +
            "\n\nANALYSE :\n" + state["analysis"] +
            "\n\n" + UNTRUSTED_RULE + "RECHERCHE :\n" + wrap_text(state["research"]) +
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
    return g.compile(checkpointer=checkpointer or MemorySaver())


_workflow = None   # workflow unique, construit une seule fois
_pool = None       # pool PostgreSQL gardé ouvert pendant toute la vie du backend


async def get_workflow():
    global _workflow, _pool
    if _workflow is None:
        # Paramètres de connexion lus depuis les variables Docker
        conninfo = (
            f"host={os.getenv('DB_HOST', 'database')} "
            f"port={os.getenv('DB_PORT', '5432')} "
            f"dbname={os.getenv('DB_NAME', 'financial_copilot')} "
            f"user={os.getenv('DB_USER', 'copilot_user')} "
            f"password={os.getenv('POSTGRES_PASSWORD')}"
        )
        # Pool de connexions avec les options requises par le checkpointer
        _pool = AsyncConnectionPool(
            conninfo=conninfo,
            max_size=5,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            open=False,
        )
        await _pool.open()                      # ouvrir le pool
        saver = AsyncPostgresSaver(_pool)       # checkpointer branché sur PostgreSQL
        await saver.setup()                     # créer les tables checkpoints si absentes
        _workflow = await build_workflow(saver) # construire le graphe avec ce checkpointer
    return _workflow

async def run_financial_analysis(question: str, thread_id: str):
    wf = await get_workflow()
    return await wf.ainvoke({"question": question},
                            {"configurable": {"thread_id": thread_id}})

async def resume_analysis(thread_id: str, action: str, comment: str = ""):
    wf = await get_workflow()
    return await wf.ainvoke(Command(resume={"action": action, "comment": comment}),
                            {"configurable": {"thread_id": thread_id}})

# Lit l'analyse en pause (motif + analyse) sans la reprendre
async def get_pending_review(thread_id: str):
    wf = await get_workflow()
    # Récupérer l'état sauvegardé dans PostgreSQL
    state = await wf.aget_state({"configurable": {"thread_id": thread_id}})
    for task in state.tasks:
        if task.interrupts:                      # tâche en attente de l'humain
            return task.interrupts[0].value      # contenu envoyé à interrupt()
    return None                                  # rien en attente