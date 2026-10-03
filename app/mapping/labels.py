"""Reconnaissance des libellés du formulaire dans les tokens OCR (exact, préfixe, flou)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from rapidfuzz import fuzz

from app.ocr.types import OCRToken
from app.schemas.form_spec import FORM_FIELDS, PII_LABELS
from app.validators.normalize import normalize_label

PII = "__pii__"
_SEP = re.compile(r"^[\s:=.\-–|)(]*")


@dataclass(frozen=True)
class LabelHit:
    spec_key: str          # clé du FieldSpec, ou PII
    score: float           # 0..100
    alias: str
    remainder: str         # texte après le libellé dans la même boîte ("68 kg")


@lru_cache(maxsize=1)
def _aliases() -> list[tuple[str, str]]:
    pairs = [(f.key, normalize_label(a)) for f in FORM_FIELDS for a in f.labels]
    pairs += [(PII, normalize_label(a)) for a in PII_LABELS]
    # Les alias longs d'abord : "hauteur uterine" doit gagner contre "hu", "tension" contre "t"
    return sorted(pairs, key=lambda p: -len(p[1]))


def _prefix_match(text: str, alias: str) -> str | None:
    """Renvoie le reste si `text` commence par `alias` suivi d'un séparateur (ou d'un chiffre)."""
    if text == alias:
        return ""
    if not text.startswith(alias):
        return None
    nxt = text[len(alias)]
    if nxt.isalpha():
        return None            # "tension".startswith("t") ne compte pas
    if nxt.isdigit() and len(alias) < 2:
        return None            # "g3p2" n'est pas le libellé "g" : c'est une valeur
    return _SEP.sub("", text[len(alias):]).strip()


def _raw_remainder(raw: str, normalized_rest: str) -> str:
    """Garde la graphie d'origine quand le libellé est séparé par ':'."""
    if normalized_rest and ":" in raw:
        return raw.split(":", 1)[1].strip()
    return normalized_rest


def match_label(token: OCRToken) -> LabelHit | None:
    raw = token.text
    text = normalize_label(raw)
    if not text:
        return None
    # 1) Libellé en début de boîte : "Poids : 68 kg", "TA", "HU 28"
    for key, alias in _aliases():
        rest = _prefix_match(text, alias)
        if rest is not None:
            return LabelHit(key, 100.0, alias, _raw_remainder(raw, rest))
    # 2) "68 : الوزن" -> formulaires arabes, libellé à droite
    if ":" in text:
        left, _, right = text.rpartition(":")
        for key, alias in _aliases():
            if right.strip() == alias:
                return LabelHit(key, 100.0, alias, left.strip())
    # 3) Flou pour les fautes d'OCR ("Poïds", "Temperatnre"), libellés longs uniquement
    label_part, _, rest = text.partition(":")
    label_part = label_part.strip()
    if len(label_part) < 4:
        return None
    best: LabelHit | None = None
    for key, alias in _aliases():
        if len(alias) < 5:
            continue
        score = fuzz.ratio(label_part, alias)
        if score >= 85 and (best is None or score > best.score):
            best = LabelHit(key, score, alias, rest.strip())
    return best
