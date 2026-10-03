"""Rattachement des tokens OCR aux champs du schéma, par la géométrie.

Deux mises en page gérées automatiquement :
- "formulaire" : paires libellé -> valeur (à droite, ou à gauche pour l'arabe, ou dessous)
- "tableau"    : registre en lignes/colonnes ; une ligne d'en-têtes définit les colonnes

Le mapper ne parse rien : il produit des CANDIDATS (texte brut + bboxes + confiance OCR).
Le parsing et les statuts sont faits en aval, de façon déterministe.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.mapping.labels import PII, LabelHit, match_label
from app.ocr.types import BBox, OCRPage, OCRToken
from app.schemas.form_spec import FIELDS_BY_KEY, OUTPUT_FIELDS, PRODUCERS
from app.schemas.models import Localisation
from app.validators.normalize import normalize_text

_UNIT_ONLY = re.compile(r"^\(?\s*(kg|cm|mmhg|cmhg|bpm|ans|sa|°c|°|/min|semaines)\s*\)?$")

# Motifs reconnaissables sans libellé (repli quand le libellé n'est pas lu)
_PATTERNS: dict[str, re.Pattern] = {
    "tension_arterielle": re.compile(r"^[^/\d]*\d{2,3}\s*/\s*\d{1,3}(?!\s*/)[^/\d]*$"),
    "gesta_para": re.compile(r"\bg\s*\d{1,2}\s*p\s*\d{1,2}\b"),
    "age_gestationnel": re.compile(r"\b\d{1,2}\s*(sa|sem)\b"),
}


@dataclass
class FieldCandidate:
    spec_key: str
    raw_text: str | None               # None = rien lu dans la zone
    tokens: list[OCRToken]
    localisation: Localisation
    zone: BBox | None = None           # zone de recherche (pour mesure d'encre / crop VLM)
    label_score: float = 100.0

    @property
    def ocr_conf(self) -> float | None:
        # Le maillon le plus faible : un seul chiffre douteux suffit à rendre la valeur douteuse
        return min(t.confidence for t in self.tokens) if self.tokens else None

    @property
    def value_bbox(self) -> BBox | None:
        if not self.tokens:
            return None
        box = self.tokens[0].bbox
        for t in self.tokens[1:]:
            box = box.union(t.bbox)
        return box


@dataclass
class MappedRecord:
    row_index: int
    candidates: dict[str, FieldCandidate]


@dataclass
class MappingResult:
    layout: str                                         # formulaire | tableau | aucun
    records: list[MappedRecord]
    pii_zones: list[BBox] = field(default_factory=list)  # zones à masquer, jamais extraites
    absent_specs: set[str] = field(default_factory=set)  # tableau : colonne absente du registre
    labels_found_ratio: float = 0.0


Labeled = list[tuple[OCRToken, LabelHit | None]]


def _same_line(a: BBox, b: BBox) -> bool:
    return a.v_overlap(b) >= 0.5


def _coverage(spec_keys: set[str]) -> float:
    covered = sum(1 for out in OUTPUT_FIELDS
                  if out in spec_keys or any(p in spec_keys for p in PRODUCERS.get(out, ())))
    return covered / len(OUTPUT_FIELDS)


# --------------------------------------------------------------------------- formulaire

def _search_side(label: OCRToken, free: list[OCRToken], labels: list[OCRToken], page_w: int,
                 direction: str) -> tuple[list[OCRToken], BBox]:
    lb, h = label.bbox, label.bbox.h
    sign = 1 if direction == "right" else -1

    def ahead(b: BBox) -> bool:
        return b.x1 >= lb.x2 - 0.3 * h if sign > 0 else b.x2 <= lb.x1 + 0.3 * h

    def dist(b: BBox) -> float:
        return b.x1 - lb.x2 if sign > 0 else lb.x1 - b.x2

    # Le prochain libellé sur la même ligne borne la zone de valeur
    stops = [dist(o.bbox) for o in labels if o is not label and _same_line(o.bbox, lb) and ahead(o.bbox)]
    limit = min(stops) if stops else max(6 * h, 0.35 * page_w)

    line = sorted((t for t in free if _same_line(t.bbox, lb) and ahead(t.bbox) and dist(t.bbox) < limit),
                  key=lambda t: dist(t.bbox))
    picked: list[OCRToken] = []
    edge, max_gap = 0.0, max(6 * h, 0.25 * page_w)
    for t in line:
        if dist(t.bbox) - edge > max_gap:
            break
        picked.append(t)
        edge = dist(t.bbox) + t.bbox.w
        max_gap = 2 * h            # au-delà du 1er token, on n'accepte que des tokens rapprochés
    if sign > 0:
        zone = BBox(lb.x2, lb.y1 - 0.2 * h, min(page_w, lb.x2 + limit), lb.y2 + 0.2 * h)
    else:
        zone = BBox(max(0, lb.x1 - limit), lb.y1 - 0.2 * h, lb.x1, lb.y2 + 0.2 * h)
    return picked, zone


def _search_below(label: OCRToken, free: list[OCRToken]) -> list[OCRToken]:
    lb, h = label.bbox, label.bbox.h
    below = [t for t in free
             if t.bbox.h_overlap(lb) >= 0.3 and 0 <= t.bbox.y1 - lb.y2 + 0.2 * h <= 2.5 * h]
    return [min(below, key=lambda t: t.bbox.y1)] if below else []


def map_form(page: OCRPage, labeled: Labeled) -> MappingResult:
    labels = [t for t, hit in labeled if hit is not None]
    free = [t for t, hit in labeled if hit is None]
    used: set[int] = set()
    best: dict[str, FieldCandidate] = {}
    pii_zones: list[BBox] = []

    for tok, hit in sorted(((t, h) for t, h in labeled if h is not None),
                           key=lambda p: (p[0].bbox.cy, p[0].bbox.x1)):
        direction = "left" if tok.script == "arabic" else "right"
        if hit.remainder:
            cand = FieldCandidate(hit.spec_key, hit.remainder, [tok], Localisation.INLINE,
                                  zone=tok.bbox, label_score=hit.score)
        else:
            avail = [t for t in free if id(t) not in used]
            picked, zone = _search_side(tok, avail, labels, page.width, direction)
            loc = Localisation.RIGHT
            if not picked:
                picked = _search_below(tok, avail)
                loc = Localisation.BELOW
            if picked:
                used.update(id(t) for t in picked)
                ordered = sorted(picked, key=lambda t: t.bbox.x1, reverse=direction == "left")
                raw = " ".join(t.text for t in ordered)
                cand = FieldCandidate(hit.spec_key, raw, picked, loc, zone=zone, label_score=hit.score)
            else:
                cand = FieldCandidate(hit.spec_key, None, [], Localisation.RIGHT, zone=zone,
                                      label_score=hit.score)

        if hit.spec_key == PII:
            pii_zones.append(cand.zone.union(tok.bbox) if cand.zone else tok.bbox)
            continue
        prev = best.get(hit.spec_key)
        if prev is None or (prev.raw_text is None and cand.raw_text is not None) \
                or (cand.raw_text is not None and cand.label_score > prev.label_score):
            best[hit.spec_key] = cand

    # Repli par motif pour les champs dont le libellé n'a pas été lu
    remaining = [t for t in free if id(t) not in used]
    for key, pattern in _PATTERNS.items():
        if key in best or any(o in best for o in FIELDS_BY_KEY[key].outputs):
            continue
        matches = [t for t in remaining if pattern.search(normalize_text(t.text))]
        if len(matches) == 1:   # ambigu s'il y en a plusieurs -> on ne choisit pas
            best[key] = FieldCandidate(key, matches[0].text, matches, Localisation.PATTERN,
                                       zone=matches[0].bbox, label_score=0.0)

    found = {k for k, c in best.items() if c.localisation != Localisation.PATTERN}
    return MappingResult("formulaire", [MappedRecord(0, best)], pii_zones,
                         labels_found_ratio=_coverage(found))


# --------------------------------------------------------------------------- tableau

def _find_header(labeled: Labeled) -> list[tuple[OCRToken, LabelHit]] | None:
    """Une ligne contenant >= 3 libellés de champs distincts (sans valeur inline) = en-tête."""
    candidates = [(t, h) for t, h in labeled if h is not None and not h.remainder]
    free = [t for t, h in labeled if h is None]
    best: list[tuple[OCRToken, LabelHit]] | None = None
    for t, _ in candidates:
        line = [(o, oh) for o, oh in candidates if _same_line(o.bbox, t.bbox)]
        keys = {oh.spec_key for _, oh in line if oh.spec_key != PII}
        # "Poids 68  TA 120/80  T 37" : des valeurs sur la même ligne -> formulaire, pas en-tête
        values_on_line = sum(1 for f in free if _same_line(f.bbox, t.bbox) and any(c.isdigit() for c in f.text))
        if values_on_line >= len(line) / 2:
            continue
        if len(keys) >= 3 and (best is None or len(line) > len(best)):
            best = line
    return best


def _cluster_rows(tokens: list[OCRToken]) -> list[list[OCRToken]]:
    rows: list[list[OCRToken]] = []
    row_box: list[BBox] = []
    for t in sorted(tokens, key=lambda t: t.bbox.cy):
        for i, box in enumerate(row_box):
            if box.v_overlap(t.bbox) >= 0.4:
                rows[i].append(t)
                row_box[i] = box.union(t.bbox)
                break
        else:
            rows.append([t])
            row_box.append(t.bbox)
    return rows


def map_table(page: OCRPage, labeled: Labeled, header: list[tuple[OCRToken, LabelHit]]) -> MappingResult:
    header = sorted(header, key=lambda p: p[0].bbox.cx)
    columns: list[tuple[str, float, float]] = []
    for i, (tok, hit) in enumerate(header):
        left = 0.0 if i == 0 else (header[i - 1][0].bbox.x2 + tok.bbox.x1) / 2
        right = float(page.width) if i == len(header) - 1 else (tok.bbox.x2 + header[i + 1][0].bbox.x1) / 2
        columns.append((hit.spec_key, left, right))
    header_bottom = max(t.bbox.y2 for t, _ in header)

    body = [t for t, hit in labeled
            if hit is None and t.bbox.cy > header_bottom and not _UNIT_ONLY.match(normalize_text(t.text))]
    records: list[MappedRecord] = []
    pii_zones: list[BBox] = [t.bbox for t, h in header if h.spec_key == PII]
    for idx, row in enumerate(_cluster_rows(body)):
        y1, y2 = min(t.bbox.y1 for t in row), max(t.bbox.y2 for t in row)
        cands: dict[str, FieldCandidate] = {}
        for key, x1, x2 in columns:
            cell = sorted((t for t in row if x1 <= t.bbox.cx < x2), key=lambda t: t.bbox.x1)
            zone = BBox(x1, y1, x2, y2)
            if key == PII:
                pii_zones.append(zone)
                continue
            if key in cands:
                continue                       # colonne en double : on garde la première
            raw = " ".join(t.text for t in cell) if cell else None
            cands[key] = FieldCandidate(key, raw, cell, Localisation.TABLE, zone=zone)
        if any(c.raw_text for c in cands.values()):
            records.append(MappedRecord(idx, cands))

    present = {k for k, _, _ in columns if k != PII}
    absent = {k for k in FIELDS_BY_KEY if k not in present}
    return MappingResult("tableau", records, pii_zones, absent, labels_found_ratio=_coverage(present))


# --------------------------------------------------------------------------- entrée

def map_page(page: OCRPage) -> MappingResult:
    labeled: Labeled = [(t, match_label(t)) for t in page.tokens]
    if not any(h for _, h in labeled):
        return MappingResult("aucun", [])
    header = _find_header(labeled)
    if header is not None:
        return map_table(page, labeled, header)
    return map_form(page, labeled)
