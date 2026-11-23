import pytest
import requests
from fastapi.testclient import TestClient

from app.main import app
from app.api import analysis as analysis_api
from app.services import approval_token as at

client = TestClient(app)


# Secret de test pour signer les liens
@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setattr(at, "SECRET", "test-secret")


def token(action="approve", thread_id="abc"):
    return at.make_token(thread_id, action)


# Faux workflow : la reprise renvoie un rapport
async def fake_resume(thread_id, action):
    return {"report": "Rapport", "supervisor_decision": "DECISION: APPROVED_FOR_DRAFT"}


# Token invalide : refusé (page et décision)
def test_decision_invalid_token():
    body = {"action": "approve", "token": "bad"}
    assert client.post("/analysis/abc/decision", json=body).status_code == 403
    assert client.get("/analysis/abc/decision", params=body).status_code == 403


# Un token "approve" ne permet pas de rejeter
def test_decision_token_wrong_action():
    r = client.post("/analysis/abc/decision", json={"action": "reject", "token": token("approve")})
    assert r.status_code == 403


# Lien déjà utilisé : la première décision passe (200), la seconde est refusée (409)
def test_decision_single_use(monkeypatch):
    used = set()

    def fake_record(thread_id, action, reviewer):
        if thread_id in used:
            return False
        used.add(thread_id)
        return True

    monkeypatch.setattr(analysis_api, "record_decision", fake_record)
    monkeypatch.setattr(analysis_api, "resume_analysis", fake_resume)
    monkeypatch.setattr(analysis_api, "notify_n8n", lambda payload: None)
    body = {"action": "approve", "token": token()}
    assert client.post("/analysis/abc/decision", json=body).status_code == 200
    assert client.post("/analysis/abc/decision", json=body).status_code == 409


# Échec de la reprise (ex. LLM indisponible) : la décision est libérée pour pouvoir réessayer
def test_decision_released_on_failure(monkeypatch):
    released = []

    async def boom(thread_id, action):
        raise RuntimeError("LLM indisponible")

    monkeypatch.setattr(analysis_api, "record_decision", lambda *a: True)
    monkeypatch.setattr(analysis_api, "release_decision", lambda thread_id: released.append(thread_id))
    monkeypatch.setattr(analysis_api, "resume_analysis", boom)
    safe_client = TestClient(app, raise_server_exceptions=False)
    r = safe_client.post("/analysis/abc/decision", json={"action": "approve", "token": token()})
    assert r.status_code == 500 and released == ["abc"]


# Analyse déjà traitée : message clair au lieu d'une erreur
def test_decision_page_already_processed(monkeypatch):
    async def nothing(thread_id):
        return None

    monkeypatch.setattr(analysis_api, "get_pending_review", nothing)
    r = client.get("/analysis/abc/decision", params={"action": "approve", "token": token()})
    assert r.status_code == 200 and "déjà traitée" in r.text


# Le texte généré par le LLM est échappé : un script injecté n'est jamais exécutable
def test_decision_page_escapes_llm_text(monkeypatch):
    async def pending(thread_id):
        return {"supervisor_decision": "<script>alert(1)</script>", "analysis": "ok"}

    monkeypatch.setattr(analysis_api, "get_pending_review", pending)
    r = client.get("/analysis/abc/decision", params={"action": "approve", "token": token()})
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;alert(1)" in r.text


# Le rapport validé est bien envoyé à n8n
def test_notify_n8n_posts_report(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200

    def fake_post(url, **kwargs):
        calls.append((url, kwargs.get("json")))
        return FakeResponse()

    monkeypatch.setattr(analysis_api, "N8N_WEBHOOK_URL", "http://n8n/webhook/x")
    monkeypatch.setattr(analysis_api.requests, "post", fake_post)
    analysis_api.notify_n8n({"report": "R"})
    assert calls == [("http://n8n/webhook/x", {"report": "R"})]


# n8n injoignable : l'erreur est absorbée (la validation humaine ne doit pas échouer)
def test_notify_n8n_swallows_errors(monkeypatch):
    def down(url, **kwargs):
        raise requests.ConnectionError("n8n arrêté")

    monkeypatch.setattr(analysis_api, "N8N_WEBHOOK_URL", "http://n8n/webhook/x")
    monkeypatch.setattr(analysis_api.requests, "post", down)
    analysis_api.notify_n8n({"report": "R"})   # ne doit pas lever d'exception


# Le LLM a un délai maximal et des nouvelles tentatives (sinon un appel bloqué gèle l'analyse)
def test_llm_has_timeout_and_retries():
    from app.graph.llm import llm
    assert llm.request_timeout and llm.max_retries >= 2