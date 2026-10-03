import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.ocr.engine import FakeOCREngine, set_engine
from app.privacy.redact import scrub_text

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture(scope="module")
def client():
    if not (EXAMPLES / "fake_tokens.json").exists():
        import subprocess, sys
        subprocess.run([sys.executable, "scripts/make_synthetic_form.py"], check=True,
                       cwd=EXAMPLES.parent)
    set_engine(FakeOCREngine(path=EXAMPLES / "fake_tokens.json"))
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_extract_formulaire_synthetique(client):
    img = (EXAMPLES / "synthetic_form.jpg").read_bytes()
    r = client.post("/extract", files={"file": ("f.jpg", img, "image/jpeg")}, data={"debug": "true"})
    assert r.status_code == 200
    body = r.json()
    f = body["records"][0]["fields"]
    assert f["poids_kg"] == {**f["poids_kg"], "value": 68.0, "status": "CONNU"}
    assert f["bcf_bpm"]["status"] == "NON_FOURNI"
    assert f["hauteur_uterine_cm"]["status"] == "ILLISIBLE"
    assert f["temperature"]["status"] == "A_REVISER" and f["temperature"]["value"] == 37.5
    assert f["syphilis"]["status"] == "INCONNU"
    # Vérification du format Tag-Valeur direct
    assert "donnees_extraites" in body
    assert body["donnees_extraites"]["poids_kg"] == 68.0
    assert "champs_extraits" in body
    assert any(c["tag"] == "poids_kg" for c in body["champs_extraits"])


def test_photo_floue_refusee_avant_ocr(client):
    img = cv2.imread(str(EXAMPLES / "synthetic_form.jpg"))
    blurred = cv2.GaussianBlur(img, (0, 0), 12)
    ok, buf = cv2.imencode(".jpg", blurred)
    r = client.post("/extract", files={"file": ("b.jpg", buf.tobytes(), "image/jpeg")}).json()
    assert r["needs_retake"] and r["quality"]["level"] == "REJETEE" and r["records"] == []
    assert "Reprendre la photo" in r["message"]


def test_photo_sombre_refusee(client):
    dark = np.full((800, 600, 3), 20, np.uint8)
    ok, buf = cv2.imencode(".jpg", dark)
    r = client.post("/extract", files={"file": ("d.jpg", buf.tobytes(), "image/jpeg")}).json()
    assert r["needs_retake"]


def test_fichier_non_image(client):
    r = client.post("/extract", files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 400


def test_page_html_servie(client):
    r = client.get("/")
    assert r.status_code == 200 and "/extract" in r.text


def test_scrub_text():
    # En mode local sans masquage, le texte est préservé intégralement
    assert scrub_text("appeler le 06 12 34 56 78") == "appeler le 06 12 34 56 78"
    assert scrub_text("CIN AB123456") == "CIN AB123456"
    assert scrub_text("vue par Mme Benali hier") == "vue par Mme Benali hier"
    assert scrub_text("TA 120/80 le 14/03/2025") == "TA 120/80 le 14/03/2025"


def test_rapidocr_engine():
    from app.ocr.engine import RapidOCREngine
    engine = RapidOCREngine()
    sample = cv2.imread(str(EXAMPLES / "synthetic_form.jpg"))
    run = engine.run(sample)
    assert run.page.engine_info["engine"] == "rapidocr"
    assert len(run.page.tokens) > 5
    # Verify at least one expected word is read
    texts = [t.text.lower() for t in run.page.tokens]
    assert any("poids" in t or "68" in t or "kg" in t or "fiche" in t for t in texts)


def test_whatsapp_simulate_and_patient_timeline(client):
    img = (EXAMPLES / "synthetic_form.jpg").read_bytes()
    # 1. Envoi photo via simulation WhatsApp
    r1 = client.post("/api/whatsapp/simulate", files={"file": ("f.jpg", img, "image/jpeg")},
                     data={"midwife_id": "SF-TEST"})
    assert r1.status_code == 200
    b1 = r1.json()
    assert "item_id" in b1
    assert "Registre analysé" in b1["reply"] or "analysé en local" in b1["reply"]

    # 2. Confirmation sage-femme
    r2 = client.post("/api/whatsapp/simulate", data={"last_item_id": b1["item_id"], "message_text": "1"})
    assert r2.status_code == 200
    b2 = r2.json()
    assert "patient_id" in b2
    assert "enregistré avec succès" in b2["reply"]

    # 3. Consultation timeline patiente
    r3 = client.get(f"/api/patients/{b2['patient_id']}/timeline")
    assert r3.status_code == 200
    b3 = r3.json()
    assert b3["profile"]["patient_id"] == b2["patient_id"]
    assert len(b3["visits"]) >= 1


def test_queue_endpoints(client):
    r_list = client.get("/api/queue")
    assert r_list.status_code == 200
    assert isinstance(r_list.json(), list)

    r_sync = client.post("/api/queue/sync")
    assert r_sync.status_code == 200
    assert "synced_count" in r_sync.json()


def test_real_registry_page_extraction():
    img_path = Path("data/Paper Registry/dossiers_specimen_10_patientes-03.png")
    if not img_path.exists():
        pytest.skip("Données réelles absentes")
    from app.ocr.engine import RapidOCREngine
    from app.pipeline import extract
    res = extract(img_path.read_bytes(), engine=RapidOCREngine())
    assert res.layout == "tableau_visites"
    assert len(res.records) >= 3
    dates = [r.fields["date_consultation"].value for r in res.records if "date_consultation" in r.fields]
    assert any(d is not None for d in dates)


