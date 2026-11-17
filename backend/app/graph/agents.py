# Importer le modèle LLM configuré avec Groq
from app.graph.llm import llm

# Importer la structure de l'état partagé entre les agents
from app.graph.state import FinancialAnalysisState


# Agent 1 : Planner — prépare le plan d'analyse financière
def planner_agent(state: FinancialAnalysisState):

    # Envoyer la question au LLM pour générer un plan d'analyse
    response = llm.invoke(
        f"Create a financial analysis plan for Microsoft. Question: {state['question']}"
    )

    # Retourner le plan pour le partager avec les autres agents
    return {"plan": response.content}


# Agent 2 : Researcher — recherche les informations financières
def researcher_agent(state: FinancialAnalysisState):

    # Retourner un résultat temporaire en attendant la connexion MCP
    return {"research": "Research agent: MCP integration pending."}


# Agent 3 : Financial Analyst — analyse les données collectées
def analyst_agent(state: FinancialAnalysisState):

    # Demander au LLM d'analyser les informations de recherche
    response = llm.invoke(
        f"Analyze these financial findings: {state['research']}"
    )

    # Retourner le résultat de l'analyse financière
    return {"analysis": response.content}


# Agent 4 : Risk Verifier — vérifie la fiabilité de l'analyse
def risk_verifier_agent(state: FinancialAnalysisState):

    # Demander au LLM d'identifier les incohérences et les risques
    response = llm.invoke(
        f"Verify the reliability and risks of this analysis: {state['analysis']}"
    )

    # Retourner le rapport de vérification
    return {"risk_review": response.content}


# Agent 5 : Supervisor — prend une décision de supervision
def supervisor_agent(state: FinancialAnalysisState):

    # Demander au LLM si une validation humaine est nécessaire
    response = llm.invoke(
        f"Review this analysis and decide whether human approval is needed: "
        f"{state['risk_review']}"
    )

    # Retourner la décision du superviseur
    return {"supervisor_decision": response.content}


# Agent 6 : Report Generator — génère le rapport financier final
def report_generator_agent(state: FinancialAnalysisState):

    # Demander au LLM de rédiger un rapport structuré
    response = llm.invoke(
        f"Generate a structured financial report for Microsoft using: "
        f"{state['analysis']} and {state['risk_review']}"
    )

    # Retourner le rapport généré
    return {"report": response.content}