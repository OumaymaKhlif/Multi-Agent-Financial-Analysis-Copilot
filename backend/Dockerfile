# Utiliser Python 3.12 comme image de base
FROM python:3.12-slim

# Définir le répertoire de travail du conteneur
WORKDIR /app

# Copier le fichier des dépendances
COPY requirements.txt .

# Installer les dépendances Python (avec cache pip permanent)
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

# Copier le code de l'application
COPY app ./app

# Démarrer le serveur FastAPI
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]