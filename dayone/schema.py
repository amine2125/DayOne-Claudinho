"""Format de sortie (schema-first) et validation.

Une fiche lue donne une liste de champs, chacun :
  {id, label, kind, value, status, confidence, source}
Les fichiers schema/*.json listent les champs connus de deux pages du registre : ils servent
de référence pour l'évaluation (annotations), pas pour la lecture.
"""

import json
from dataclasses import dataclass
from functools import lru_cache

from dayone.dataset import ROOT

SCHEMA_DIR = ROOT / "schema"
REFERENCE_PAGE_TYPES = ("identification_antecedents", "accouchement")

STATUSES = ("KNOWN", "UNKNOWN", "NOT_PROVIDED", "ILLEGIBLE", "NOT_APPLICABLE", "NEEDS_REVIEW")
KINDS = ("text", "integer", "date", "weight", "length", "weeks", "sex", "checkbox")


@dataclass(frozen=True)
class Field:
    id: str
    label: str
    group: str
    kind: str
    table: bool = False


@lru_cache
def reference_fields(page_type: str) -> tuple[Field, ...]:
    """Champs connus d'une page du registre (pour les annotations et l'évaluation)."""
    if page_type not in REFERENCE_PAGE_TYPES:
        raise ValueError(f"page de référence inconnue : {page_type}")
    raw = json.loads((SCHEMA_DIR / f"{page_type}.json").read_text(encoding="utf-8"))
    return tuple(Field(f["id"], f["label"], f["group"], f["kind"], f.get("table", False)) for f in raw["fields"])


def make_field(value, status: str, confidence: float, **extra) -> dict:
    """Construit un champ de sortie valide (value + status + confidence)."""
    out = {"value": value, "status": status, "confidence": round(float(confidence), 3)}
    out.update(extra)
    validate_field(out)
    return out


def validate_field(f: dict, name: str = "champ") -> None:
    for key in ("value", "status", "confidence"):
        if key not in f:
            raise ValueError(f"{name} : clé `{key}` manquante")
    if f["status"] not in STATUSES:
        raise ValueError(f"{name} : statut inconnu {f['status']}")
    if not isinstance(f["confidence"], (int, float)) or not 0 <= f["confidence"] <= 1:
        raise ValueError(f"{name} : confidence doit être entre 0 et 1")
    if f["status"] == "KNOWN" and f["value"] is None:
        raise ValueError(f"{name} : KNOWN exige une valeur")


def validate_prediction(pred: dict) -> None:
    """Chaque champ : identifiant unique, étiquette, type connu, valeur/statut/confiance, jamais personnel."""
    from dayone.privacy import is_personal

    ids = [f["id"] for f in pred["fields"]]
    if len(ids) != len(set(ids)):
        raise ValueError("identifiant de champ en double")
    for f in pred["fields"]:
        if f.get("kind") not in KINDS or not f.get("label"):
            raise ValueError(f"{f.get('id')} : étiquette ou type manquant")
        if is_personal(f["label"], str(f["value"] or "")):
            raise ValueError(f"{f['id']} : donnée personnelle dans la sortie")
        validate_field(f, f["id"])
