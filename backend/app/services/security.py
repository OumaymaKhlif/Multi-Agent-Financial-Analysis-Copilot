import os, secrets
from fastapi import Header, HTTPException

API_KEY = os.getenv("API_KEY", "")   # clé lue depuis l'environnement


# Dépendance FastAPI : refuse la requête si l'en-tête X-API-Key est absent ou faux
def require_api_key(x_api_key: str = Header(default="")):
    # compare_digest : comparaison à temps constant (évite les attaques par chronométrage)
    if not API_KEY or not secrets.compare_digest(x_api_key.encode(), API_KEY.encode()):
        raise HTTPException(401, "Clé API invalide")