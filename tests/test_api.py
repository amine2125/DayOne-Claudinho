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
    # Aucune donnée nominative nulle part dans la réponse
    dumped = json.dumps(body, ensure_ascii=False)
    assert "Fatima" not in dumped and "0612345678" not in dumped
    assert body["debug"]["pii_zones"]
    assert "{" not in body["message"]                 # message lisible, pas de JSON


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
    assert "[MASQUE]" in scrub_text("appeler le 06 12 34 56 78")
    assert "[MASQUE]" in scrub_text("CIN AB123456")
    assert "[MASQUE]" in scrub_text("vue par Mme Benali hier")
    assert scrub_text("TA 120/80 le 14/03/2025") == "TA 120/80 le 14/03/2025"
