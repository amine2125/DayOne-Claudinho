"""API locale : santé, validations et erreurs rendues en JSON lisible."""
from fastapi.testclient import TestClient

import pytest

import api.main as server
from api import store
from dayone.extract import NotAFormError

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


def use_extract(monkeypatch, fn):
    monkeypatch.setattr(server.store, "extractor", lambda: fn)


def test_pas_une_fiche_donne_422(monkeypatch):
    def refuse(*_a, **_k):
        raise NotAFormError("Cette image n'est pas une fiche ou un registre de santé.")
    use_extract(monkeypatch, refuse)
    r = client.post("/extract", files={"file": PNG})
    assert r.status_code == 422 and "fiche" in r.json()["detail"]


def test_ocr_indisponible_donne_503(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("PaddleOCR a échoué")
    use_extract(monkeypatch, boom)
    r = client.post("/extract", files={"file": PNG})
    assert r.status_code == 503 and "PaddleOCR" in r.json()["detail"]


def test_resultat_renvoye_tel_quel(monkeypatch):
    pred = {"title": "Accouchement", "fields": [{"id": "poids", "label": "Poids", "kind": "weight",
                                                  "value": 3200, "status": "KNOWN", "confidence": 0.9}]}
    use_extract(monkeypatch, lambda *_a, **_k: pred)
    r = client.post("/extract", files={"file": PNG}, data={"use_model": "false"})
    assert r.status_code == 200 and r.json() == pred


def test_mode_demo_rejoue_une_sortie_enregistree(monkeypatch):
    monkeypatch.setenv("DAYONE_DEMO_EXTRACT", "1")
    r = client.post("/extract", files={"file": PNG})
    assert r.status_code == 200 and isinstance(r.json()["fields"], list)
    assert client.get("/health").json()["demo"] is True


def test_snapshot_vide_au_depart():
    r = client.get("/api/snapshot")
    assert r.status_code == 200 and r.json() == {"patients": {}, "visits": {}, "records": {}, "busy": []}


def test_dossier_inconnu_404():
    assert client.post("/api/records/rec_inconnu/validate").status_code == 404
    assert client.get("/api/records/rec_inconnu").status_code == 404


def test_parcours_whatsapp_par_l_api(monkeypatch):
    """Capture -> lecture -> dossier lisible -> reprise d'une page -> retrait d'une page illisible."""
    monkeypatch.setenv("DAYONE_DEMO_EXTRACT", "1")
    r = client.post("/api/records", files=[("files", PNG), ("files", ("p2.png", b"autre", "image/png"))],
                    data={"patient_code": "amn-27", "midwife_id": "wa_test"})
    assert r.status_code == 202
    rid = r.json()["id"]                      # TestClient exécute la lecture avant de rendre la main
    rec = client.get(f"/api/records/{rid}").json()
    assert rec["state"] == "NEEDS_REVIEW" and rec["busy"] is False and rec["patientCode"] == "AMN-27"
    assert [p["index"] for p in rec["pages"]] == [0, 1] and all(p["fields"] for p in rec["pages"])

    r = client.post(f"/api/records/{rid}/pages/1/photo", files={"file": ("p2b.png", b"nouvelle", "image/png")})
    assert r.status_code == 202
    rec = client.get(f"/api/records/{rid}").json()
    assert rec["state"] == "NEEDS_REVIEW" and rec["pages"][1]["fields"]
    assert "RETAKE page 1" in [h.get("note") for h in rec["history"]]

    # Une page lue ne se retire pas
    assert client.post(f"/api/records/{rid}/pages/0/drop").status_code == 409


def test_capture_page_par_page_puis_code_et_resultat_final(monkeypatch):
    monkeypatch.setenv("DAYONE_DEMO_EXTRACT", "1")
    r = client.post("/api/records", files=[("files", PNG)], data={"midwife_id": "wa_test"})
    assert r.status_code == 202
    rid = r.json()["id"]
    assert client.post(f"/api/records/{rid}/pages", files={"file": ("p2.png", b"deux", "image/png")}).json()["index"] == 1
    assert client.get(f"/api/records/{rid}/final").status_code == 404          # pas encore validé
    assert client.post(f"/api/records/{rid}/code", json={"code": ""}).status_code == 422
    assert client.post(f"/api/records/{rid}/code", json={"code": "amn-27"}).json()["patientCode"] == "AMN-27"
    rec = client.get(f"/api/records/{rid}").json()
    for page in rec["pages"]:
        for key, f in page["fields"].items():
            if f["status"] in ("NEEDS_REVIEW", "ILLEGIBLE"):
                client.post(f"/api/records/{rid}/pages/{page['index']}/fields/{key}", json={"by": "wa_test", "confirm": True})
    assert client.post(f"/api/records/{rid}/validate").status_code == 200
    assert client.post(f"/api/records/{rid}/link", json={"decision": "CREATE"}).status_code == 200
    final = client.get(f"/api/records/{rid}/final")
    assert final.status_code == 200 and final.json()["patient_code"] == "AMN-27" and len(final.json()["pages"]) == 2
    assert client.post(f"/api/records/{rid}/pages", files={"file": PNG}).status_code == 409   # dossier envoyé


def test_cle_d_api_exigee_quand_configuree(monkeypatch):
    monkeypatch.setattr(server, "API_KEY", "secret-de-test")
    assert client.get("/health").status_code == 200                      # santé : toujours ouverte
    assert client.post("/api/records", files={"photo": PNG}).status_code == 401
    assert client.get("/api/snapshot").status_code == 401                 # pas depuis cette machine : clé exigée
    r = client.get("/api/snapshot", headers={"Authorization": "Bearer mauvaise"})
    assert r.status_code == 401
    assert client.get("/api/snapshot", headers={"Authorization": "Bearer secret-de-test"}).status_code == 200


def test_tableau_de_bord_local_sans_cle(monkeypatch):
    monkeypatch.setattr(server, "API_KEY", "secret-de-test")
    local = TestClient(server.app, client=("127.0.0.1", 50000))
    assert local.get("/api/snapshot").status_code == 200                  # lecture locale : permise
    assert local.post("/api/records", files={"photo": PNG}).status_code == 401   # écriture : clé exigée


def test_sans_cle_configuree_rien_ne_change(monkeypatch):
    monkeypatch.setattr(server, "API_KEY", "")
    assert client.get("/api/snapshot").status_code == 200
