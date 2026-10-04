"""Schéma des pages (source de vérité : schema/*.json) et validation des sorties."""

import json
from dataclasses import dataclass, field
from functools import lru_cache

from dayone.dataset import ROOT

SCHEMA_DIR = ROOT / "schema"
V1_PAGE_TYPES = ("identification_antecedents", "accouchement")

STATUSES = ("KNOWN", "UNKNOWN", "NOT_PROVIDED", "ILLEGIBLE", "NOT_APPLICABLE", "NEEDS_REVIEW")
KINDS = ("text", "integer", "date", "weight", "length", "weeks", "sex", "checkbox")

# Données personnelles : jamais de champ portant ces noms, jamais de zone lue.
FORBIDDEN_FIELDS = ("nom", "nom_patiente", "nom_mari", "conjoint", "cin", "telephone", "adresse")


@dataclass(frozen=True)
class Field:
    id: str
    label: str
    group: str
    kind: str
    zone: tuple | None = None      # (x0, y0, x1, y1) dans l'image de référence
    box: tuple | None = None       # (cx, cy, taille) pour une case à cocher
    table: bool = False            # cellule d'un grand tableau
    applicable_if: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PageSchema:
    page_type: str
    title: str
    reference_page: int
    image_size: tuple
    excluded_zones: dict
    fields: tuple

    def field(self, field_id: str) -> Field:
        return next(f for f in self.fields if f.id == field_id)


@lru_cache
def load_schema(page_type: str) -> PageSchema:
    if page_type not in V1_PAGE_TYPES:
        raise ValueError(f"type de page hors V1 : {page_type} (attendu : {V1_PAGE_TYPES})")
    raw = json.loads((SCHEMA_DIR / f"{page_type}.json").read_text(encoding="utf-8"))
    fields = tuple(
        Field(id=f["id"], label=f["label"], group=f["group"], kind=f["kind"],
              zone=tuple(f["zone"]) if "zone" in f else None,
              box=tuple(f["box"]) if "box" in f else None,
              table=f.get("table", False), applicable_if=f.get("applicable_if", {}))
        for f in raw["fields"]
    )
    schema = PageSchema(raw["page_type"], raw["title"], raw["reference_page"],
                        tuple(raw["image_size"]), raw["excluded_zones"], fields)
    _check_schema(schema)
    return schema


def _check_schema(s: PageSchema) -> None:
    ids = [f.id for f in s.fields]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{s.page_type} : identifiant de champ en double")
    for f in s.fields:
        if f.kind not in KINDS:
            raise ValueError(f"{f.id} : type inconnu {f.kind}")
        if f.id in FORBIDDEN_FIELDS:
            raise ValueError(f"{f.id} : donnée personnelle interdite dans le schéma")
        if (f.kind == "checkbox") != (f.box is not None) or (f.kind != "checkbox") != (f.zone is not None):
            raise ValueError(f"{f.id} : une case a `box`, un champ texte a `zone`")


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
    """Vérifie une sortie complète : tous les champs du schéma, et rien d'autre."""
    schema = load_schema(pred["page_type"])
    expected = {f.id for f in schema.fields}
    got = set(pred["fields"])
    if got != expected:
        raise ValueError(f"champs manquants {sorted(expected - got)} / en trop {sorted(got - expected)}")
    for fid, f in pred["fields"].items():
        validate_field(f, fid)
