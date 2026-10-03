"""Module de traitement du texte et des images (Mode Local Intégral - Zéro Masquage).

Conformément à la directive :
  Le modèle tourne à 100% en local sur la machine, il n'y a aucun risque de fuite cloud.
  L'intégralité des données (Nom, Prénom, CIN, Téléphone, Adresse, etc.) est extraite
  en clair sans masquage afin de constituer le dossier médical complet du patient.
"""
from __future__ import annotations

import cv2
import numpy as np

from app.ocr.types import BBox
from app.schemas.models import ExtractionRecord


def scrub_text(text: str | None) -> str | None:
    """En mode local sans masquage, restitue le texte intégralement."""
    return text


def scrub_record(record: ExtractionRecord) -> ExtractionRecord:
    """En mode local sans masquage, conserve tous les champs intacts."""
    return record


def mask_image(image: np.ndarray, zones: list[BBox]) -> np.ndarray:
    """En mode local sans masquage, conserve l'image originale sans barres noires."""
    return image.copy()
