import pytest
from app.rag.ingest import latest_filing

# Faux JSON SEC : 4 dépôts, du plus récent au plus ancien
FAKE = {"name": "MICROSOFT CORP", "tickers": ["MSFT"], "filings": {"recent": {
    "form": ["8-K", "10-K", "10-Q", "10-K"],
    "accessionNumber": ["0001-26-1", "0001193125-26-323660", "0001-26-3", "0001193125-25-100"],
    "filingDate": ["2026-08-01", "2026-07-30", "2026-04-25", "2025-07-30"],
    "reportDate": ["2026-07-31", "2026-06-30", "2026-03-31", "2025-06-30"],
    "primaryDocument": ["a.htm", "msft-20260630.htm", "c.htm", "msft-20250630.htm"],
}}}


class FakeResponse:
    def raise_for_status(self): pass
    def json(self): return FAKE


# Le dernier 10-K est choisi (pas l'ancien) et l'URL est correctement construite
def test_latest_filing_picks_most_recent(monkeypatch):
    monkeypatch.setattr("app.rag.ingest.requests.get", lambda *a, **k: FakeResponse())
    f = latest_filing("0000789019", "10-K")
    assert f["accession"] == "0001193125-26-323660"
    assert f["url"].endswith("/789019/000119312526323660/msft-20260630.htm")


# Type de dépôt absent : erreur explicite
def test_latest_filing_not_found(monkeypatch):
    monkeypatch.setattr("app.rag.ingest.requests.get", lambda *a, **k: FakeResponse())
    with pytest.raises(ValueError):
        latest_filing("0000789019", "20-F")