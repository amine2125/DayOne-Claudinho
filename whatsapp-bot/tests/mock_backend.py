"""Mock Backend API server for local testing.

Ne lit pas la photo : renvoie une vraie sortie DayOne tirée de `outputs/predictions/`,
au même format que `dayone.extract.extract_page`.
Légende contenant « flou » → 422, pour tester une page illisible.

Run with:
uvicorn tests.mock_backend:app --port 8080 --reload
"""

import json
import logging
import random
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mock-backend")

PREDICTIONS_DIR = Path(__file__).resolve().parents[2] / "outputs" / "predictions"

app = FastAPI(title="Mock Backend API (Simulation DayOne / OCR)")


@app.post("/analyze")
async def analyze_document(
    file: UploadFile = File(...),
    user_phone: str = Form(...),
    caption: str | None = Form(default=None),
):
    """Simulates image processing and extraction."""
    content = await file.read()
    logger.info("Received image from ***%s: filename=%s, size=%d bytes, caption=%s",
                user_phone[-4:], file.filename, len(content), caption)

    if caption and "flou" in caption.lower():
        raise HTTPException(422, "Photo trop floue : reprenez-la bien à plat, sans reflet.")

    sample = random.choice(sorted(PREDICTIONS_DIR.glob("*.json")))
    logger.info("Returning sample prediction %s", sample.name)
    return json.loads(sample.read_text(encoding="utf-8"))
