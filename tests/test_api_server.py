"""API locale : santé, validations et erreurs rendues en JSON lisible."""
from fastapi.testclient import TestClient

import pytest

import api.main as server
from api import store

client = TestClient(server.app)


@pytest.fixture(autouse=True)
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(store, "CAPTURES", tmp_path / "captures")
    monkeypatch.setattr(store, "KEY_FILE", tmp_path / "key")
    monkeypatch.setattr(store, "_initialized", False)
    monkeypatch.setattr(store, "_fernet", None)
PNG = ("page.png", b"\x89PNG fake", "image/png")


def test_health_repond():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["database"]["patients"] == 0


def test_type_de_page_inconnu_refuse():
    r = client.post("/extract", files={"file": PNG}, data={"page_type": "inconnue"})
    assert r.status_code == 422


def test_ocr_indisponible_donne_503(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("PaddleOCR a échoué")
    monkeypatch.setattr(server, "extract_page", boom)
    r = client.post("/extract", files={"file": PNG})
    assert r.status_code == 503 and "PaddleOCR" in r.json()["detail"]


def test_resultat_renvoye_tel_quel(monkeypatch):
    pred = {"page_type": "accouchement", "fields": {"nn_poids": {"value": 3200, "status": "KNOWN", "confidence": 0.9}}}
    monkeypatch.setattr(server, "extract_page", lambda *_a, **_k: pred)
    r = client.post("/extract", files={"file": PNG}, data={"page_type": "accouchement", "use_model": "false"})
    assert r.status_code == 200 and r.json() == pred


def test_snapshot_vide_au_depart():
    r = client.get("/api/snapshot")
    assert r.status_code == 200 and r.json() == {"patients": {}, "visits": {}, "records": {}, "busy": []}


def test_dossier_inconnu_404():
    assert client.post("/api/records/rec_inconnu/validate").status_code == 404
