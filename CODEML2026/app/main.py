"""API FastAPI. Lancer : uvicorn app.main:app --reload  puis ouvrir http://localhost:8000"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.ocr.engine import get_engine
from app.pipeline import extract
from app.schemas.models import ExtractionResponse
from app.settings import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("registre")

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
_engine_error: str | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _engine_error
    try:
        get_engine()            # charge les modèles OCR au démarrage, pas à la 1re requête
    except Exception as exc:    # paddle absent, modèle introuvable... l'API reste up pour /health
        _engine_error = f"{type(exc).__name__}: {exc}"
        log.error("Moteur OCR indisponible : %s", _engine_error)
    yield


app = FastAPI(title="Registre obstétrical — extraction", version="0.1.0", lifespan=lifespan)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health() -> dict:
    info = {"ok": _engine_error is None, "ocr_engine": settings.ocr_engine, "ocr_error": _engine_error,
            "vlm_enabled": settings.vlm_enabled, "vlm_model": settings.vlm_model, "vlm_available": False}
    from app.vlm.ollama_client import vlm_available
    info["vlm_available"] = vlm_available()
    return info


@app.post("/extract", response_model=ExtractionResponse)
def extract_endpoint(
    file: UploadFile = File(..., description="Photo d'une page de registre (JPEG/PNG)"),
    use_vlm: bool | None = Form(None, description="Forcer/désactiver le second lecteur local"),
    debug: bool = Form(False, description="Renvoie l'image de travail (zones nominatives noircies)"),
) -> ExtractionResponse:
    if _engine_error:
        raise HTTPException(503, f"Moteur OCR indisponible : {_engine_error}")
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image trop lourde (max 15 Mo)")
    try:
        return extract(data, use_vlm=use_vlm, debug=debug)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
