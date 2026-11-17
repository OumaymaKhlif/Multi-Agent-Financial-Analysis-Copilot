# teste les routes de l’API. Le workflow est remplacé par de fausses réponses (monkeypatch), donc aucun appel au LLM, y compris pour le HITL.

from fastapi.testclient import TestClient
from app.main import app
import app.api.analysis as analysis_api

client = TestClient(app)


# Objet imitant l'interruption renvoyée par LangGraph
class FakeInterrupt:
    def __init__(self, value):
        self.value = value


# La route PostgreSQL doit renvoyer les exercices FY2025 et FY2026
def test_financial_analysis_endpoint():
    r = client.get("/financial-analysis")
    assert r.status_code == 200
    years = [row["fiscal_year"] for row in r.json()["financial_analysis"]]
    assert 2026 in years and 2025 in years


# La route PDF doit renvoyer un vrai fichier PDF
def test_pdf_endpoint():
    r = client.post("/analysis/pdf", json={"report": "**Test** rapport"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


# Analyse terminée : statut COMPLETED avec le rapport
def test_analysis_completed(monkeypatch):
    async def fake(question, thread_id):
        return {"report": "Rapport", "supervisor_decision": "DECISION: APPROVED_FOR_DRAFT"}
    monkeypatch.setattr(analysis_api, "run_financial_analysis", fake)
    data = client.post("/analysis/", json={"question": "test"}).json()
    assert data["status"] == "COMPLETED" and data["report"] == "Rapport"


# Validation humaine requise : statut PENDING_HUMAN_REVIEW
def test_analysis_pending_review(monkeypatch):
    async def fake(question, thread_id):
        return {"__interrupt__": [FakeInterrupt({"supervisor_decision": "HUMAN_REVIEW_REQUIRED"})]}
    monkeypatch.setattr(analysis_api, "run_financial_analysis", fake)
    data = client.post("/analysis/", json={"question": "test"}).json()
    assert data["status"] == "PENDING_HUMAN_REVIEW"
    assert data["review_data"]["supervisor_decision"] == "HUMAN_REVIEW_REQUIRED"


# Approbation humaine : le rapport est généré
def test_review_approve(monkeypatch):
    async def fake(thread_id, action, comment=""):
        assert action == "approve"
        return {"report": "Rapport final", "supervisor_decision": "OK"}
    monkeypatch.setattr(analysis_api, "resume_analysis", fake)
    data = client.post("/analysis/abc/review", json={"action": "approve", "comment": "OK"}).json()
    assert data["status"] == "COMPLETED" and data["report"] == "Rapport final"


# Rejet humain : aucun rapport n'est produit
def test_review_reject(monkeypatch):
    async def fake(thread_id, action, comment=""):
        return {"supervisor_decision": "HUMAN_REVIEW_REQUIRED"}
    monkeypatch.setattr(analysis_api, "resume_analysis", fake)
    data = client.post("/analysis/abc/review", json={"action": "reject"}).json()
    assert data["status"] == "COMPLETED" and data["report"] == ""


# Une requête sans question doit être refusée (erreur 422)
def test_invalid_request():
    assert client.post("/analysis/", json={}).status_code == 422