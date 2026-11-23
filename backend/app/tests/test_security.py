import pytest
from app.services import approval_token as at


# Secret de test pour tous les tests de ce fichier
@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setattr(at, "SECRET", "test-secret")


# Un token valide est accepté pour la bonne analyse et la bonne action
def test_valid_token():
    assert at.verify_token("t1", "approve", at.make_token("t1", "approve"))


# Un token "approve" ne permet pas de rejeter, ni d'agir sur une autre analyse
def test_token_bound_to_action_and_thread():
    token = at.make_token("t1", "approve")
    assert not at.verify_token("t1", "reject", token)
    assert not at.verify_token("t2", "approve", token)


# Une signature modifiée est refusée
def test_tampered_token():
    token = at.make_token("t1", "approve")
    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
    assert not at.verify_token("t1", "approve", tampered)


# Un token expiré est refusé
def test_expired_token(monkeypatch):
    monkeypatch.setattr(at, "TTL", -10)
    assert not at.verify_token("t1", "approve", at.make_token("t1", "approve"))


# Tokens mal formés : refusés sans erreur
@pytest.mark.parametrize("bad", ["", "garbage", "a.b.c", "123."])
def test_malformed_token(bad):
    assert not at.verify_token("t1", "approve", bad)


# Sans secret configuré, tout est refusé
def test_no_secret(monkeypatch):
    token = at.make_token("t1", "approve")
    monkeypatch.setattr(at, "SECRET", "")
    assert not at.verify_token("t1", "approve", token)