"""Modèles Pydantic exposés par l'API et persistés (jamais de données nominatives)."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class FieldStatus(str, Enum):
    CONNU = "CONNU"
    INCONNU = "INCONNU"            # écrit explicitement "inconnu", "?", "NSP"...
    NON_FOURNI = "NON_FOURNI"      # zone localisée mais vide
    ILLISIBLE = "ILLISIBLE"        # de l'encre mais rien de lisible
    NON_APPLICABLE = "NON_APPLICABLE"
    A_REVISER = "A_REVISER"        # le système doute : la sage-femme tranche


class FieldSource(str, Enum):
    OCR = "ocr"
    OCR_VLM = "ocr+vlm"            # OCR et VLM d'accord
    VLM = "vlm"                    # proposé par le VLM seul -> jamais CONNU
    RULE = "regle"
    MANUAL = "manuel"              # saisi / corrigé par la sage-femme
    NONE = "aucune"


class Localisation(str, Enum):
    INLINE = "inline"              # "Poids : 68 kg" dans la même boîte
    RIGHT = "droite"               # valeur à droite du libellé
    BELOW = "dessous"
    TABLE = "tableau"              # cellule sous un en-tête de colonne
    PATTERN = "motif"              # trouvé par regex sans libellé (ex: G3P2)
    NOT_FOUND = "non_localise"


class QualityLevel(str, Enum):
    BONNE = "BONNE"
    MOYENNE = "MOYENNE"
    REJETEE = "REJETEE"


class QualityReport(BaseModel):
    level: QualityLevel
    blur_score: float = Field(description="Variance du Laplacien (plus haut = plus net)")
    brightness: float
    contrast: float = Field(description="Plage dynamique p99 - p1 des niveaux de gris")
    page_detected: bool
    reasons: list[str] = []


class ConfidenceSignals(BaseModel):
    """Facteurs qui composent la confiance, exposés pour l'audit."""

    ocr: float | None = None
    quality: float = 1.0
    localisation: float = 1.0
    validation: float = 1.0
    vlm_agreement: bool | None = None


class FieldResult(BaseModel):
    value: Any = None
    status: FieldStatus
    confidence: float = Field(ge=0.0, le=1.0)
    source: FieldSource = FieldSource.NONE
    raw_text: str | None = None
    reasons: list[str] = []
    alternatives: list[Any] = []   # ex: lecture VLM divergente
    signals: ConfidenceSignals | None = None
    bbox: list[int] | None = None  # zone de la valeur, pour surligner dans l'UI


class ExtractionRecord(BaseModel):
    """Une ligne de registre (mode tableau) ou une fiche (mode formulaire)."""

    row_index: int = 0
    fields: dict[str, FieldResult]


class ExtractionResponse(BaseModel):
    job_id: str
    quality: QualityReport
    layout: str                    # "formulaire" | "tableau" | "aucun"
    needs_retake: bool
    retake_reason: str | None = None
    records: list[ExtractionRecord] = []
    labels_found_ratio: float = 0.0
    vlm_calls: int = 0
    timings_ms: dict[str, float] = {}
    message: str = ""              # texte lisible type WhatsApp (jamais le JSON brut)
    debug: dict | None = None      # image de travail (zones nominatives noircies), pour la page de test
