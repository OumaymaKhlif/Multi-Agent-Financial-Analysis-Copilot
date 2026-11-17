
# Importer la bibliothèque requests pour effectuer des requêtes HTTP
import requests

# Importer les URLs et le User-Agent depuis le fichier de configuration
from sec_config import (
    SUBMISSIONS_URL,     # URL des déclarations réglementaires de Microsoft
    COMPANY_FACTS_URL,   # URL des données financières XBRL de Microsoft
    USER_AGENT           # Identification de notre application auprès de la SEC
)

# Définir les en-têtes HTTP de la requête
HEADERS = {"User-Agent": USER_AGENT}


# Fonction qui récupère les données depuis une URL
def fetch_sec_data(url):

    # Envoyer une requête HTTP GET à la SEC
    response = requests.get(
        url,
        headers=HEADERS,  # Envoyer le User-Agent
        timeout=30        # Attendre au maximum 30 secondes
    )

    # Vérifier si la requête a réussi (sinon déclencher une erreur)
    response.raise_for_status()

    # Convertir la réponse JSON en dictionnaire Python
    return response.json()


# Fonction principale pour collecter les données de Microsoft
def collect_microsoft_data():

    # Récupérer les déclarations réglementaires (10-K, 10-Q, 8-K...)
    submissions = fetch_sec_data(SUBMISSIONS_URL)

    # Récupérer les données financières structurées (XBRL)
    company_facts = fetch_sec_data(COMPANY_FACTS_URL)

    # Organiser les données récupérées dans un dictionnaire Python
    return {
        "company": submissions["name"],           # Nom de l'entreprise
        "ticker": submissions["tickers"][0],      # Symbole boursier
        "submissions": submissions,                # Déclarations réglementaires
        "financial_facts": company_facts           # Données financières XBRL
    }


# Vérifier si ce fichier est exécuté directement
if __name__ == "__main__":

    # Lancer la collecte des données de Microsoft
    data = collect_microsoft_data()

    # Afficher le nom de l'entreprise
    print("Company:", data["company"])

    # Afficher son symbole boursier
    print("Ticker:", data["ticker"])

    # Afficher les catégories de données financières disponibles
    print(
        "Financial categories:",
        list(data["financial_facts"]["facts"].keys())
    )

    # Confirmer que la collecte a réussi
    print("SEC collection successful!")



