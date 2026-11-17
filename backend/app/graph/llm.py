import os
from langchain_groq import ChatGroq


# Initialiser le modèle LLM depuis les variables d'environnement
llm = ChatGroq(
    model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
    temperature=0,
    api_key=os.getenv("GROQ_API_KEY")
)