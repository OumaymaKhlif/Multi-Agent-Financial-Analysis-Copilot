# Le fichier permet de :
    # télécharger le rapport annuel 10-K
    # extraire son texte
    # le découper
    # calculer les embeddings Qwen
    # les enregistrer dans PostgreSQL

# PyTorch : framework Python pour exécuter des modèles d'IA et effectuer des calculs tensoriels.
# CUDA : plateforme NVIDIA permettant d'exécuter ces calculs sur le GPU.

# Importer les bibliothèques nécessaires
# Ingestion d'un dépôt SEC : téléchargement, découpage, embeddings, stockage pgvector.
# Usage : python -m app.rag.ingest [--cik 0000789019] [--form 10-K] [--force]
import os
import argparse
import requests
import psycopg
import torch                                                   # détecter la présence d'un GPU
from bs4 import BeautifulSoup                                  # extraire le texte du HTML
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B")   # modèle d'embeddings
CHUNK_SIZE, CHUNK_OVERLAP = 1000, 150                                    # stratégie de découpage
HEADERS = {"User-Agent": os.getenv("SEC_USER_AGENT", "FinancialAnalysisCopilot contact@example.com")}
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "database"), "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "financial_copilot"), "user": os.getenv("DB_USER", "copilot_user"),
    "password": os.getenv("POSTGRES_PASSWORD"),
}


# Trouve le dépôt le plus récent d'un type donné (10-K, 10-Q, 8-K) via l'API SEC
def latest_filing(cik: str, form: str = "10-K") -> dict:
    r = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=HEADERS, timeout=30)
    r.raise_for_status()                              # erreur si la SEC refuse la requête
    data = r.json()
    recent = data["filings"]["recent"]                # dépôts récents, du plus récent au plus ancien
    for i, f in enumerate(recent["form"]):
        if f == form:                                 # premier = le plus récent
            acc = recent["accessionNumber"][i]
            return {
                "accession": acc,                                     # identifiant du dépôt
                "filing_date": recent["filingDate"][i],               # date de dépôt
                "report_date": recent["reportDate"][i],               # date de clôture de la période
                "url": (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                        f"{acc.replace('-', '')}/{recent['primaryDocument'][i]}"),
                "company": data.get("name", ""),
                "ticker": (data.get("tickers") or [""])[0],
            }
    raise ValueError(f"Aucun dépôt {form} trouvé pour le CIK {cik}")


# Télécharge le document HTML et en extrait le texte brut
def download_text(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style"]):             # retirer le code inutile
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


# Ingestion complète d'un dépôt
def ingest(cik: str, form: str = "10-K", force: bool = False):
    filing = latest_filing(cik, form)
    with psycopg.connect(**DB_CONFIG) as conn:
        register_vector(conn)
        exists = conn.execute("SELECT 1 FROM document_chunks WHERE source_url = %s LIMIT 1",
                              (filing["url"],)).fetchone()
        if exists and not force:                      # déjà ingéré : ne rien recalculer
            print(f"Déjà ingéré, ignoré : {filing['url']} (utiliser --force pour refaire)")
            return
        if exists:                                    # --force : repartir de zéro (évite les chunks orphelins)
            conn.execute("DELETE FROM document_chunks WHERE source_url = %s", (filing["url"],))

        text = download_text(filing["url"])
        chunks = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP, add_start_index=True
        ).create_documents([text])

        device = "cuda" if torch.cuda.is_available() else "cpu"   # GPU si disponible, sinon CPU
        model = HuggingFaceEmbeddings(
            model_name=MODEL_NAME, model_kwargs={"device": device},
            encode_kwargs={"normalize_embeddings": True, "batch_size": 8},
        )
        vectors = model.embed_documents([c.page_content for c in chunks])

        title = f"{filing['company']} - Form {form} ({filing['report_date']})"
        for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
            metadata = {                                          # traçabilité complète du chunk
                "company": filing["company"], "ticker": filing["ticker"], "filing": form,
                "accession_number": filing["accession"], "filing_date": filing["filing_date"],
                "report_date": filing["report_date"], "fiscal_year": int(filing["report_date"][:4]),
                "embedding_model": MODEL_NAME, "chunk_size": CHUNK_SIZE, "chunk_overlap": CHUNK_OVERLAP,
                "start_index": chunk.metadata["start_index"],
            }
            conn.execute(
                "INSERT INTO document_chunks (source_title, source_url, chunk_index, content, embedding, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (source_url, chunk_index) DO UPDATE SET "
                "content = EXCLUDED.content, embedding = EXCLUDED.embedding, metadata = EXCLUDED.metadata",
                (title, filing["url"], i, chunk.page_content, vec, Jsonb(metadata)),
            )
    print(f"Ingéré : {title} ({len(chunks)} chunks, device={device}, modèle={MODEL_NAME})")


# Point d'entrée en ligne de commande
def main():
    p = argparse.ArgumentParser(description="Ingestion d'un dépôt SEC dans pgvector")
    p.add_argument("--cik", default="0000789019", help="CIK de la société (défaut : Microsoft)")
    p.add_argument("--form", default="10-K", help="Type de dépôt : 10-K, 10-Q, 8-K")
    p.add_argument("--force", action="store_true", help="Réingérer même si déjà présent")
    a = p.parse_args()
    ingest(a.cik.zfill(10), a.form, a.force)       # zfill : le CIK doit avoir 10 chiffres


if __name__ == "__main__":
    main()