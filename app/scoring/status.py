"""Règles de statut : table de décision déterministe, évaluée dans cet ordre.

  0. Champ non localisé            -> A_REVISER (ou NON_FOURNI si la colonne n'existe pas dans le registre)
  1. Zone vide (pas d'encre)       -> NON_FOURNI
  2. Encre mais aucune lecture     -> ILLISIBLE (ou A_REVISER si le VLM propose une lecture)
  3. "inconnu", "?", "NSP"          -> INCONNU
  4. "N/A", "sans objet"           -> NON_APPLICABLE
  5. "non fait"                    -> NON_FOURNI
  6. Texte non interprétable       -> ILLISIBLE si score < tau_illegible, sinon A_REVISER
  7. Valeur impossible             -> A_REVISER (valeur proposée, jamais CONNU)
  8. VLM en désaccord              -> A_REVISER (les deux lectures sont montrées)
  9. VLM seul                      -> A_REVISER (jamais CONNU sans lecture OCR concordante)
 10. Texte libre                   -> A_REVISER (sauf "RAS"/"néant")
 11. score >= seuil                -> CONNU ; score < tau_illegible -> ILLISIBLE ; sinon A_REVISER
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.mapping.mapper import FieldCandidate
from app.schemas.form_spec import FieldKind, FieldSpec
from app.schemas.models import FieldResult, FieldSource, FieldStatus, Localisation, QualityLevel
from app.scoring.confidence import QUALITY_FACTOR, compute_confidence
from app.settings import settings
from app.validators.normalize import (DASH_TOKENS, NOT_APPLICABLE_TOKENS, NOT_DONE_TOKENS,
                                      UNKNOWN_TOKENS, is_token_in)
from app.validators.parsers import ParseResult, parse_value
from app.validators.plausibility import check_range


@dataclass
class VLMReading:
    text: str | None          # transcription littérale proposée par le modèle local
    legible: bool
    model: str = ""


@dataclass
class FieldContext:
    quality: QualityLevel
    ink: float | None = None            # ratio d'encre dans la zone (si rien lu)
    vlm: VLMReading | None = None
    absent_from_form: bool = False


def _outputs(spec: FieldSpec) -> tuple[str, ...]:
    return spec.outputs or (spec.key,)


def _split(spec: FieldSpec, value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {spec.key: value}


def _same(spec: FieldSpec, base: FieldResult, **overrides) -> dict[str, FieldResult]:
    return {o: base.model_copy(update=overrides) for o in _outputs(spec)}


def resolve(spec: FieldSpec, cand: FieldCandidate | None, ctx: FieldContext) -> dict[str, FieldResult]:
    """Transforme un candidat de mapping en FieldResult(s) finaux (plusieurs pour un composite)."""
    qf = QUALITY_FACTOR[ctx.quality]

    # 0. Non localisé
    if cand is None:
        if ctx.absent_from_form:
            return _same(spec, FieldResult(status=FieldStatus.NON_FOURNI, confidence=qf, source=FieldSource.RULE,
                                           reasons=["absent_du_registre"]))
        return _same(spec, FieldResult(status=FieldStatus.A_REVISER, confidence=0.0,
                                       reasons=["champ_non_localise"]))

    loc_conf, signals = compute_confidence(None, ctx.quality, cand.localisation, cand.label_score)
    bbox = (cand.value_bbox or cand.zone).to_list() if (cand.value_bbox or cand.zone) else None
    text = (cand.raw_text or "").strip()

    # 1-2. Rien lu par l'OCR
    if not text:
        if ctx.vlm and ctx.vlm.legible and ctx.vlm.text:
            return _vlm_only(spec, ctx, loc_conf, bbox)
        if ctx.ink is not None and ctx.ink <= settings.ink_empty_max:
            return _same(spec, FieldResult(status=FieldStatus.NON_FOURNI, confidence=loc_conf, source=FieldSource.OCR,
                                           reasons=["zone_vide"], signals=signals, bbox=bbox))
        reason = "encre_sans_lecture" if ctx.ink is not None else "zone_vide_non_verifiee"
        status = FieldStatus.ILLISIBLE if ctx.ink is not None else FieldStatus.A_REVISER
        return _same(spec, FieldResult(status=status, confidence=loc_conf, source=FieldSource.OCR,
                                       reasons=[reason], signals=signals, bbox=bbox))

    score, signals = compute_confidence(cand.ocr_conf, ctx.quality, cand.localisation, cand.label_score)
    base = dict(raw_text=text, signals=signals, bbox=bbox, source=FieldSource.OCR, confidence=score)

    # 3-5. Mentions explicites
    if is_token_in(text, UNKNOWN_TOKENS):
        return _same(spec, FieldResult(status=FieldStatus.INCONNU, reasons=["mention_inconnu"], **base))
    if is_token_in(text, NOT_APPLICABLE_TOKENS):
        return _same(spec, FieldResult(status=FieldStatus.NON_APPLICABLE, reasons=["mention_non_applicable"], **base))
    if is_token_in(text, NOT_DONE_TOKENS):
        return _same(spec, FieldResult(status=FieldStatus.NON_FOURNI, reasons=["examen_non_fait"], **base))

    parsed = parse_value(text, spec)

    # 6. Non interprétable
    if not parsed.ok:
        if ctx.vlm and ctx.vlm.legible and ctx.vlm.text:
            vlm_res = _vlm_only(spec, ctx, loc_conf, bbox, ocr_text=text)
            if any(r.value is not None for r in vlm_res.values()):
                return vlm_res
        if is_token_in(text, DASH_TOKENS):
            return _same(spec, FieldResult(status=FieldStatus.A_REVISER, reasons=["tiret_ambigu"], **base))
        status = FieldStatus.ILLISIBLE if score < settings.tau_illegible else FieldStatus.A_REVISER
        return _same(spec, FieldResult(status=status, reasons=[parsed.error or "format_invalide"], **base))

    return _from_parsed(spec, parsed, cand, ctx, base)


def _from_parsed(spec: FieldSpec, parsed: ParseResult, cand: FieldCandidate, ctx: FieldContext,
                 base: dict) -> dict[str, FieldResult]:
    values = _split(spec, parsed.value)
    vlm_values: dict[str, Any] | None = None
    if ctx.vlm and ctx.vlm.legible and ctx.vlm.text:
        vp = parse_value(ctx.vlm.text, spec)        # le VLM transcrit, Python interprète
        vlm_values = _split(spec, vp.value) if vp.ok else {}

    results: dict[str, FieldResult] = {}
    for out in _outputs(spec):
        value = values.get(out)
        reasons = list(parsed.warnings)
        if value is None:
            results[out] = FieldResult(status=FieldStatus.A_REVISER, reasons=reasons + ["absent_de_la_valeur_composite"],
                                       **{**base, "confidence": 0.0})
            continue
        rc = check_range(out, value)
        if rc.warning:
            reasons.append(rc.warning)
        n_warn = len(parsed.warnings) + (1 if rc.warning and rc.hard_ok else 0)

        agree: bool | None = None
        alternatives: list[Any] = []
        if vlm_values is not None:
            agree = vlm_values.get(out) == value
            if not agree:
                alternatives.append(vlm_values.get(out) if vlm_values.get(out) is not None else ctx.vlm.text)

        score, signals = compute_confidence(cand.ocr_conf, ctx.quality, cand.localisation, cand.label_score,
                                            n_warn, agree)
        threshold = settings.tau_known_vlm_agree if agree else settings.tau_known

        if not rc.hard_ok:
            status = FieldStatus.A_REVISER                                  # 7
        elif agree is False:
            status = FieldStatus.A_REVISER; reasons.append("desaccord_ocr_vlm")   # 8
        elif spec.kind == FieldKind.FREE_TEXT and value != "AUCUNE":
            status = FieldStatus.A_REVISER                                  # 10
        elif score >= threshold:
            status = FieldStatus.CONNU                                      # 11
        elif score < settings.tau_illegible:
            status = FieldStatus.ILLISIBLE; reasons.append("confiance_tres_faible")
        else:
            status = FieldStatus.A_REVISER; reasons.append("confiance_insuffisante")

        results[out] = FieldResult(
            value=None if status == FieldStatus.ILLISIBLE else value, status=status, confidence=score,
            source=FieldSource.OCR_VLM if agree else FieldSource.OCR, raw_text=base["raw_text"],
            reasons=reasons, alternatives=alternatives, signals=signals, bbox=base["bbox"])
    return results


def _vlm_only(spec: FieldSpec, ctx: FieldContext, loc_conf: float, bbox, ocr_text: str | None = None
              ) -> dict[str, FieldResult]:
    """9. Lecture proposée par le VLM seul : pré-remplie pour la sage-femme, jamais CONNU."""
    vp = parse_value(ctx.vlm.text, spec)
    alts = [ocr_text] if ocr_text else []
    if not vp.ok:
        return _same(spec, FieldResult(status=FieldStatus.ILLISIBLE, confidence=0.0, source=FieldSource.VLM,
                                       raw_text=ctx.vlm.text, reasons=["lecture_vlm_non_interpretable"],
                                       alternatives=alts, bbox=bbox))
    values = _split(spec, vp.value)
    return {o: FieldResult(value=values.get(o), status=FieldStatus.A_REVISER, confidence=0.0,
                           source=FieldSource.VLM, raw_text=ctx.vlm.text, alternatives=alts, bbox=bbox,
                           reasons=["lecture_vlm_seule_a_confirmer"] + vp.warnings)
            for o in _outputs(spec)}
