"""Orchestration : photo -> qualité -> OCR -> mapping -> règles -> (VLM si besoin) -> JSON."""
from __future__ import annotations

import base64
import threading
import time
import uuid

import cv2
import numpy as np

from app.mapping.mapper import FieldCandidate, MappedRecord, MappingResult, map_page
from app.messaging.render import render_response
from app.ocr.engine import OCREngine, get_engine
from app.privacy.redact import mask_image, scrub_record
from app.schemas.form_spec import DISPLAY_NAMES, FORM_FIELDS, OUTPUT_FIELDS, PRODUCERS
from app.schemas.models import (ExtractionRecord, ExtractionResponse, FieldResult, FieldStatus, QualityLevel)
from app.scoring.status import FieldContext, resolve
from app.settings import settings
from app.validators.plausibility import cross_field_conflicts
from app.vision.preprocess import decode_image, ink_mask, ink_ratio, preprocess

_ocr_lock = threading.Lock()      # PaddleOCR n'est pas garanti thread-safe


def _needs_second_reader(results: dict[str, FieldResult]) -> bool:
    return any(r.status in (FieldStatus.A_REVISER, FieldStatus.ILLISIBLE)
               and "champ_non_localise" not in r.reasons and "absent_du_registre" not in r.reasons
               for r in results.values())


def _resolve_record(rec: MappedRecord, mapping: MappingResult, quality: QualityLevel, mask: np.ndarray,
                    ref_image: np.ndarray, use_vlm: bool, budget: list[int]) -> ExtractionRecord:
    by_spec: dict[str, dict[str, FieldResult]] = {}
    for spec in FORM_FIELDS:
        cand: FieldCandidate | None = rec.candidates.get(spec.key)
        ctx = FieldContext(quality=quality, absent_from_form=spec.key in mapping.absent_specs)
        if cand is not None and not cand.raw_text and cand.zone is not None:
            ctx.ink = ink_ratio(mask, (cand.zone.x1, cand.zone.y1, cand.zone.x2, cand.zone.y2))
        results = resolve(spec, cand, ctx)

        # Second lecteur local, seulement pour les cas douteux et dans la limite du budget
        if (use_vlm and cand is not None and cand.zone is not None and spec.send_to_vlm
                and budget[0] > 0 and _needs_second_reader(results)):
            from app.vlm.ollama_client import read_field
            budget[0] -= 1
            reading = read_field(ref_image, cand.value_bbox or cand.zone, spec, DISPLAY_NAMES.get(spec.key, spec.key))
            if reading is not None:
                ctx.vlm = reading
                results = resolve(spec, cand, ctx)
        by_spec[spec.key] = results

    fields: dict[str, FieldResult] = {}
    for out in OUTPUT_FIELDS:
        producers = PRODUCERS.get(out, (out,))
        chosen = None
        for p in producers:                       # le premier producteur effectivement localisé gagne
            if p in rec.candidates and out in by_spec.get(p, {}):
                chosen = by_spec[p][out]
                break
        fields[out] = chosen or by_spec[producers[0]][out]

    # Cohérence inter-champs : détecte une erreur de lecture, ne juge jamais la clinique
    values = {k: v.value for k, v in fields.items() if v.status in (FieldStatus.CONNU, FieldStatus.A_REVISER)}
    for keys, reason in cross_field_conflicts(values):
        for k in keys:
            fields[k] = fields[k].model_copy(update={"status": FieldStatus.A_REVISER,
                                                     "reasons": fields[k].reasons + [reason]})
    return scrub_record(ExtractionRecord(row_index=rec.row_index, fields=fields))


def extract(image_bytes: bytes, use_vlm: bool | None = None, engine: OCREngine | None = None,
            debug: bool = False) -> ExtractionResponse:
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    job_id = str(uuid.uuid4())
    use_vlm = settings.vlm_enabled if use_vlm is None else use_vlm

    pre = preprocess(decode_image(image_bytes))
    timings["pretraitement"] = round((time.perf_counter() - t0) * 1000, 1)

    if pre.quality.level == QualityLevel.REJETEE:
        reason = pre.quality.reasons[0] if pre.quality.reasons else None
        return ExtractionResponse(job_id=job_id, quality=pre.quality, layout="aucun", needs_retake=True,
                                  retake_reason=reason, timings_ms=timings,
                                  message=render_response([], pre.quality, True, reason))

    t1 = time.perf_counter()
    with _ocr_lock:
        run = (engine or get_engine()).run(pre.image)
    timings["ocr"] = round((time.perf_counter() - t1) * 1000, 1)

    t2 = time.perf_counter()
    mapping = map_page(run.page)
    mask = ink_mask(run.ref_image)
    budget = [settings.vlm_max_calls_per_page]
    records = [_resolve_record(r, mapping, pre.quality.level, mask, run.ref_image, use_vlm, budget)
               for r in mapping.records]
    timings["mapping_regles_vlm"] = round((time.perf_counter() - t2) * 1000, 1)

    needs_retake, reason = False, None
    if mapping.layout == "aucun":
        needs_retake, reason = True, "aucun_libelle"
    elif mapping.layout == "formulaire" and mapping.labels_found_ratio < settings.min_labels_ratio:
        needs_retake, reason = True, "page_incomplete"     # page masquée / mal cadrée
    timings["total"] = round((time.perf_counter() - t0) * 1000, 1)

    resp = ExtractionResponse(
        job_id=job_id, quality=pre.quality, layout=mapping.layout, needs_retake=needs_retake,
        retake_reason=reason, records=records, labels_found_ratio=round(mapping.labels_found_ratio, 2),
        vlm_calls=settings.vlm_max_calls_per_page - budget[0], timings_ms=timings,
        message=render_response(records, pre.quality, needs_retake, reason))
    if debug:
        # Image de travail AVEC zones nominatives noircies : jamais d'identifiant dans la réponse
        safe = mask_image(run.ref_image, mapping.pii_zones)
        ok, jpg = cv2.imencode(".jpg", safe, [cv2.IMWRITE_JPEG_QUALITY, 80])
        resp.debug = {
            "image_jpeg_b64": base64.b64encode(jpg.tobytes()).decode() if ok else None,
            "image_size": [int(run.ref_image.shape[1]), int(run.ref_image.shape[0])],
            "pii_zones": [z.to_list() for z in mapping.pii_zones],
            "engine": run.page.engine_info,
        }
    return resp
