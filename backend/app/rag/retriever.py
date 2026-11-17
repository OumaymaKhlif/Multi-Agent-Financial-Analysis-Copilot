
import os
import psycopg
from pgvector import Vector

from langchain_huggingface import HuggingFaceEmbeddings
from pgvector.psycopg import register_vector

# Charger Qwen sur le GPU une seule fois
embeddings_model = HuggingFaceEmbeddings(
    model_name="Qwen/Qwen3-Embedding-0.6B",
    model_kwargs={"device": "cuda"},
    encode_kwargs={"normalize_embeddings": True}
)

print("Device:", embeddings_model._client.device)

# Définir la connexion PostgreSQL
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "database"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "financial_copilot"),
    "user": os.getenv("DB_USER", "copilot_user"),
    "password": os.getenv("POSTGRES_PASSWORD")
}

# Rechercher les passages les plus pertinents
def search_documents(query: str, top_k: int = 5):

    # Ajouter l'instruction recommandée pour Qwen
    query_text = (
        "Instruct: Given a question, retrieve relevant passages "
        "that answer the question\nQuery: " + query
    )

    # Transformer la question en vecteur
    query_embedding = embeddings_model.embed_query(query_text)

    # Ouvrir la connexion à PostgreSQL
    with psycopg.connect(**DB_CONFIG) as connection:

        # Enregistrer le type vector
        register_vector(connection)

        # Rechercher les chunks par similarité cosinus
        results = connection.execute(
            """
            SELECT
                source_title,
                source_url,
                chunk_index,
                content,
                1 - (embedding <=> %s) AS similarity
            FROM document_chunks
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> %s
            LIMIT %s;
            """,
            (Vector(query_embedding), Vector(query_embedding), top_k)
        ).fetchall()

    # Retourner les passages retrouvés
    return [
        {
            "title": row[0],
            "source": row[1],
            "chunk_index": row[2],
            "content": row[3],
            "similarity": float(row[4])
        }
        for row in results
    ]
# Exécuter un test lorsque le fichier est lancé directement
if __name__ == "__main__":

    # Poser une question financière
    question = "What are Microsoft's main sources of revenue?"

    # Effectuer une recherche des 5 passages les plus pertinents
    results = search_documents(question, top_k=5)

    # Afficher les résultats
    for result in results:
        print("\nSimilarity:", round(result["similarity"], 4))
        print("Source:", result["title"])
        print("Content:", result["content"][:500])