"""Second lecteur local (Qwen2.5-VL via Ollama), appelé uniquement sur des crops ambigus.

Garde-fous contre l'invention :
1. Le modèle ne voit qu'un CROP du champ (pas la page) -> peu de contexte, pas de fuite.
2. On ne lui montre PAS la lecture OCR -> deux lectures indépendantes, comparables.
3. Il TRANSCRIT, il n'interprète pas : la valeur finale est produite par les parseurs Python.
4. Sortie contrainte par schéma JSON (format Ollama), température 0.
5. Sortie revalidée (Pydantic + longueur + parseur) ; toute anomalie = lecture ignorée.
6. Sa "confiance" n'est jamais utilisée. Seul l'accord/désaccord avec l'OCR compte.
"""
from __future__ import annotations

import base64
import logging

import cv2
import httpx
import numpy as np
from pydantic import BaseModel, Field, ValidationError

from app.ocr.types import BBox
from app.schemas.form_spec import FieldKind, FieldSpec
from app.scoring.status import VLMReading
from app.settings import settings

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a strict transcription tool for paper medical register forms. "
    "You copy EXACTLY the characters written in the image (handwritten or printed), in French, Arabic "
    "or English. Never guess, never complete, never correct, never infer from context or medical "
    "knowledge. If any character is uncertain, set legible to false. Answer only with JSON."
)

FORMAT_HINTS = {
    FieldKind.INT: "a whole number, possibly with a unit",
    FieldKind.FLOAT: "a number, possibly with a decimal comma and a unit",
    FieldKind.BLOOD_PRESSURE: "two numbers separated by a slash, like 120/80 or 12/8",
    FieldKind.BLOOD_GROUP: "a blood group like A+, O-, AB Rh+",
    FieldKind.GESTA_PARA: "like G3P2",
    FieldKind.GESTATIONAL_AGE: "weeks of amenorrhea like 32 SA or 32+3",
    FieldKind.DATE: "a date like 12/05/2025",
    FieldKind.ENUM: "a short word or symbol",
    FieldKind.FREE_TEXT: "short free text",
}

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "transcription": {"type": "string"},
        "legible": {"type": "boolean"},
        "empty": {"type": "boolean"},
    },
    "required": ["transcription", "legible", "empty"],
}


class _VLMOut(BaseModel):
    transcription: str = Field(max_length=60)
    legible: bool
    empty: bool


def crop_zone(image: np.ndarray, zone: BBox) -> np.ndarray:
    h_img, w_img = image.shape[:2]
    pad_y, pad_x = zone.h * 0.6, max(zone.h * 2.0, zone.w * 0.1)   # inclut un bout du libellé
    x1, y1 = max(0, int(zone.x1 - pad_x)), max(0, int(zone.y1 - pad_y))
    x2, y2 = min(w_img, int(zone.x2 + pad_x)), min(h_img, int(zone.y2 + pad_y))
    crop = image[y1:y2, x1:x2]
    if crop.size and crop.shape[0] < 64:     # agrandir les petits crops aide beaucoup les VLM
        f = 64 / crop.shape[0]
        crop = cv2.resize(crop, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    return crop


def read_field(image: np.ndarray, zone: BBox, spec: FieldSpec, display_name: str) -> VLMReading | None:
    crop = crop_zone(image, zone)
    if crop.size == 0:
        return None
    ok, png = cv2.imencode(".png", crop)
    if not ok:
        return None
    user_prompt = (
        f"This image shows ONE field of a form: '{display_name}'. Expected format: {FORMAT_HINTS[spec.kind]}. "
        "Transcribe only the VALUE written for this field, not the printed label. "
        "If nothing is written, return empty=true and transcription=\"\". "
        "If you cannot read every character with certainty, return legible=false."
    )
    payload = {
        "model": settings.vlm_model,
        "stream": False,
        "format": RESPONSE_SCHEMA,
        "options": {"temperature": 0, "num_predict": 64},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt, "images": [base64.b64encode(png.tobytes()).decode()]},
        ],
    }
    try:
        r = httpx.post(f"{settings.ollama_url}/api/chat", json=payload, timeout=settings.vlm_timeout_s)
        r.raise_for_status()
        out = _VLMOut.model_validate_json(r.json()["message"]["content"])
    except (httpx.HTTPError, KeyError, ValidationError, ValueError) as exc:
        log.warning("Lecture VLM ignorée pour %s : %s", spec.key, type(exc).__name__)
        return None
    if out.empty:
        return VLMReading(text=None, legible=True, model=settings.vlm_model)
    text = out.transcription.strip()
    return VLMReading(text=text or None, legible=out.legible and bool(text), model=settings.vlm_model)


def vlm_available() -> bool:
    try:
        r = httpx.get(f"{settings.ollama_url}/api/tags", timeout=2)
        return any(m.get("name", "").startswith(settings.vlm_model.split(":")[0]) for m in r.json().get("models", []))
    except (httpx.HTTPError, ValueError):
        return False
