# Utiliser Python 3.12 comme image de base
FROM python:3.12-slim

# Définir le répertoire de travail du conteneur
WORKDIR /app

# Couche lourde : ne change presque jamais
COPY requirements-heavy.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements-heavy.txt

# Couche légère : peut changer sans retélécharger torch
# Copier le fichier des dépendances
COPY requirements.txt .
# Installer les dépendances Python (avec cache pip permanent)
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

# Copier le code de l'application
# Utilisateur non root : un conteneur compromis n'a pas les droits administrateur
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /hf_cache \
    && chown appuser:appuser /app /hf_cache

# Cache des modèles Hugging Face (monté en volume)
ENV HF_HOME=/hf_cache

# Copier le code avec les bons droits
COPY --chown=appuser:appuser app ./app

# Tout ce qui suit s'exécute sans droits root
USER appuser

# Démarrer le serveur FastAPI
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]