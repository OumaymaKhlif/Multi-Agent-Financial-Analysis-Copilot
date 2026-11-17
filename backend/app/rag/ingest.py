# Le fichier permet de :
    # télécharger le rapport annuel 10-K
    # extraire son texte
    # le découper
    # calculer les embeddings Qwen
    # les enregistrer dans PostgreSQL

# PyTorch : framework Python pour exécuter des modèles d'IA et effectuer des calculs tensoriels.
# CUDA : plateforme NVIDIA permettant d'exécuter ces calculs sur le GPU.

# Importer les bibliothèques nécessaires
import os                          # Lire les variables d'environnement
import requests                    # Envoyer des requêtes HTTP
import psycopg                      # Se connecter à PostgreSQL

from bs4 import BeautifulSoup       # Extraire le texte du HTML
from langchain_text_splitters import RecursiveCharacterTextSplitter  # Découper le texte
from langchain_huggingface import HuggingFaceEmbeddings  # Générer des embeddings
from pgvector.psycopg import register_vector  # Activer le support vector dans PostgreSQL
from psycopg.types.json import Jsonb  # Stocker les métadonnées au format JSONB


# URL officielle du rapport annuel 2026 de Microsoft
SOURCE_URL = "https://www.sec.gov/Archives/edgar/data/789019/000119312526323660/msft-20260630.htm"

# Nom du document qui sera enregistré dans PostgreSQL
SOURCE_TITLE = "Microsoft Annual Report 2026 - Form 10-K"

# Nom du modèle qui transforme le texte en vecteurs
MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"


# Informations nécessaires pour se connecter à PostgreSQL
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "database"),  # Adresse du serveur PostgreSQL
    "port": os.getenv("DB_PORT", "5432"),      # Port de connexion
    "dbname": os.getenv("DB_NAME", "financial_copilot"),  # Nom de la base
    "user": os.getenv("DB_USER", "copilot_user"),          # Nom utilisateur
    "password": os.getenv("POSTGRES_PASSWORD"),            # Mot de passe
}


# Télécharger le rapport financier depuis le site de la SEC
response = requests.get(
    SOURCE_URL,
    headers={"User-Agent": "FinancialAnalysisCopilot khlif.oumayma30@gmail.com"},  # Identifier notre application
    timeout=60  # Attendre au maximum 60 secondes
)

# Vérifier si le téléchargement a réussi
response.raise_for_status()


# Analyser le contenu HTML du rapport
soup = BeautifulSoup(response.text, "html.parser")

# Supprimer les scripts et les styles inutiles
for tag in soup(["script", "style"]):
    tag.decompose()


# Extraire le contenu HTML sous forme de texte brut
document_text = soup.get_text(separator="\n", strip=True)


# Créer un découpeur pour diviser le document en morceaux
splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,       # Taille maximale de chaque morceau
    chunk_overlap=150,     # Partie répétée entre deux morceaux
    add_start_index=True   # Conserver la position de chaque morceau
)

# Découper le document en plusieurs chunks
chunks = splitter.create_documents([document_text])


# Charger le modèle Qwen3 pour générer les embeddings sur le CPU
embeddings_model = HuggingFaceEmbeddings(
    model_name=MODEL_NAME,  # Modèle d'embeddings utilisé
    model_kwargs={"device": "cuda"},  # Exécuter le modèle sur le gpu
    encode_kwargs={
        "normalize_embeddings": True,  # Normaliser les vecteurs
        "batch_size": 8                # Traiter 8 textes à la fois
    }
)


# Extraire le texte de chaque chunk
texts = [chunk.page_content for chunk in chunks]

# Transformer chaque chunk en vecteur numérique (embedding)
vectors = embeddings_model.embed_documents(texts)


# Ouvrir une connexion avec PostgreSQL
with psycopg.connect(**DB_CONFIG) as connection:

    # Enregistrer le type vector pour permettre son utilisation avec pgvector
    register_vector(connection)

    # Parcourir les chunks et leurs embeddings simultanément
    for index, (chunk, vector) in enumerate(zip(chunks, vectors)):

        # Préparer les informations supplémentaires du chunk
        metadata = {
            "company": "Microsoft",  # Nom de l'entreprise
            "ticker": "MSFT",        # Symbole boursier
            "filing": "10-K",        # Type de rapport
            "fiscal_year": 2026,     # Année fiscale
            "start_index": chunk.metadata["start_index"]  # Position dans le document
        }

        # Insérer le chunk et son embedding dans PostgreSQL
        connection.execute(
            """
            INSERT INTO document_chunks
                (source_title, source_url, chunk_index, content, embedding, metadata)
            VALUES (%s, %s, %s, %s, %s, %s)

            -- Éviter les doublons pour une même URL et un même index
            ON CONFLICT (source_url, chunk_index)

            -- Mettre à jour les informations si le chunk existe déjà
            DO UPDATE SET
                content = EXCLUDED.content,
                embedding = EXCLUDED.embedding,
                metadata = EXCLUDED.metadata
            """,
            (
                SOURCE_TITLE,       # Nom du document
                SOURCE_URL,         # URL du rapport
                index,              # Numéro du chunk
                chunk.page_content, # Texte du chunk
                vector,             # Embedding du chunk
                Jsonb(metadata)     # Métadonnées au format JSONB
            )
        )

# Afficher le nombre de chunks enregistrés
print(f"Document ingéré avec succès : {len(chunks)} chunks")

# Afficher le modèle d'embeddings utilisé
print(f"Modèle utilisé : {MODEL_NAME}")
