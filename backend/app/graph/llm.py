import os
from langchain_groq import ChatGroq


# Initialiser le modèle LLM depuis les variables d'environnement
llm = ChatGroq(
    model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
    temperature=0,
    api_key=os.getenv("GROQ_API_KEY"),
    timeout=90,        # abandonne un appel bloqué après 90 secondes
    max_retries=3      # nouvelles tentatives en cas d'erreur réseau ou de limite de débit
)