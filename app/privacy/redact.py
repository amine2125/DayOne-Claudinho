"""Confidentialité : 3 couches, de la plus robuste à la plus fragile.

1. LISTE BLANCHE (principale) : seuls les champs du schéma sont persistés. Aucun champ
   "nom", "téléphone", etc. n'existe -> impossible de les stocker par erreur.
   Les tokens OCR bruts ne sont JAMAIS persistés ni journalisés.
2. ZONES : les libellés nominatifs (Nom, Tél, CIN, Époux, الاسم...) sont reconnus par le
   mapper ; leur zone de valeur est exclue de l'extraction et noircie sur toute image conservée.
3. REGEX : filet de sécurité sur le texte qui reste (raw_text, texte libre).
"""
from __future__ import annotations

import re

import cv2
import numpy as np

from app.ocr.types import BBox
from app.schemas.form_spec import OUTPUT_FIELDS
from app.schemas.models import ExtractionRecord
from app.validators.normalize import fold_digits

MASK = "[MASQUE]"

_PATTERNS = [
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),                              # email
    re.compile(r"(?:\+|00)\d{2,3}[\s.\-]?\d(?:[\s.\-]?\d){7,10}"),       # téléphone international
    re.compile(r"\b0\d(?:[\s.\-]?\d){8}\b"),                              # téléphone national (10 chiffres)
    re.compile(r"\b\d(?:[\s.\-]?\d){8,}\b"),                              # toute suite >= 9 chiffres
    re.compile(r"\b[A-Za-z]{1,2}\s?\d{5,7}\b"),                          # CIN marocaine (AB123456)
]
# Mots qui précèdent souvent un nom propre dans un texte libre
_NAME_CUES = re.compile(r"\b(mme|mlle|madame|mr|m\.|monsieur|dr|epouse|épouse|fille de|السيدة|السيد)\s+\S+(\s+\S+)?",
                        re.IGNORECASE)


def scrub_text(text: str | None) -> str | None:
    if not text:
        return text
    out = fold_digits(text)
    for p in _PATTERNS:
        out = p.sub(MASK, out)
    return _NAME_CUES.sub(MASK, out)


def scrub_record(record: ExtractionRecord) -> ExtractionRecord:
    fields = {}
    for key, res in record.fields.items():
        if key not in OUTPUT_FIELDS:            # liste blanche
            continue
        update = {"raw_text": scrub_text(res.raw_text)}
        if isinstance(res.value, str):
            update["value"] = scrub_text(res.value)
        update["alternatives"] = [scrub_text(a) if isinstance(a, str) else a for a in res.alternatives]
        fields[key] = res.model_copy(update=update)
    return record.model_copy(update={"fields": fields})


def mask_image(image: np.ndarray, zones: list[BBox]) -> np.ndarray:
    out = image.copy()
    for z in zones:
        cv2.rectangle(out, (int(z.x1), int(z.y1)), (int(z.x2), int(z.y2)), (0, 0, 0), thickness=-1)
    return out
