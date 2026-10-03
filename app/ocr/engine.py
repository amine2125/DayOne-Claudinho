"""Moteurs OCR derrière une interface commune.

- PaddleOCREngine : PaddleOCR 3.x (PP-OCRv5), compatible 2.x en repli.
- FakeOCREngine   : rejoue des tokens JSON -> tests, démo sans GPU, développement du mapping.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from app.ocr.types import BBox, OCRPage, OCRToken, detect_script

log = logging.getLogger(__name__)


@dataclass
class OCRRun:
    page: OCRPage
    ref_image: np.ndarray   # image dans le repère des bboxes (PaddleOCR peut l'avoir pivotée)


class OCREngine(Protocol):
    def run(self, image: np.ndarray) -> OCRRun: ...


class PaddleOCREngine:
    """Une instance PaddleOCR par langue/écriture.

    Il n'existe pas de modèle unique latin+arabe : on lance le modèle latin ('fr', couvre aussi
    l'anglais) puis le modèle arabe, et on fusionne boîte par boîte en gardant la lecture la plus
    confiante. Les modèles sont chargés une seule fois (lent au premier appel).
    """

    def __init__(self, languages: list[str]):
        from paddleocr import PaddleOCR  # import tardif : l'API démarre même sans paddle installé

        import paddleocr
        self.version = getattr(paddleocr, "__version__", "?")
        self.major = int(self.version.split(".")[0]) if self.version[0].isdigit() else 3
        self.languages = languages
        self.models = {}
        for lang in languages:
            if self.major >= 3:
                self.models[lang] = PaddleOCR(
                    lang=lang,
                    use_doc_orientation_classify=True,   # photos à 90/180°
                    use_doc_unwarping=False,             # on redresse nous-mêmes avec OpenCV
                    use_textline_orientation=True,
                    text_rec_score_thresh=0.0,           # on GARDE les lectures peu sûres
                )
            else:
                self.models[lang] = PaddleOCR(lang=lang, use_angle_cls=True, drop_score=0.0, show_log=False)
        log.info("PaddleOCR %s chargé pour %s", self.version, languages)

    def _run_one(self, lang: str, image: np.ndarray) -> tuple[list[OCRToken], np.ndarray]:
        model = self.models[lang]
        tokens: list[OCRToken] = []
        ref = image
        if self.major >= 3:
            for res in model.predict(image):          # OCRResult : objet dict-like
                pre = res.get("doc_preprocessor_res") or {}
                if pre.get("output_img") is not None:
                    # Les bboxes sont dans le repère de l'image PIVOTÉE par PaddleOCR
                    ref = np.asarray(pre["output_img"])
                    if pre.get("angle") not in (None, 0, -1):
                        log.info("PaddleOCR a pivoté l'image de %s°", pre.get("angle"))
                texts = res.get("rec_texts", [])
                scores = res.get("rec_scores", [])
                polys = res.get("rec_polys")
                if polys is None:
                    polys = res.get("dt_polys", [])
                for text, score, poly in zip(texts, scores, polys):
                    if not str(text).strip():
                        continue
                    tokens.append(OCRToken(str(text), float(score), BBox.from_polygon(np.asarray(poly).tolist()),
                                           detect_script(str(text)), f"paddle-{lang}"))
        else:
            result = model.ocr(image, cls=True) or [[]]
            for poly, (text, score) in result[0] or []:
                tokens.append(OCRToken(text, float(score), BBox.from_polygon(poly), detect_script(text), f"paddle-{lang}"))
        return tokens, ref

    def run(self, image: np.ndarray) -> OCRRun:
        merged: list[OCRToken] = []
        ref = image
        for i, lang in enumerate(self.languages):
            tokens, ref_l = self._run_one(lang, image)
            if i == 0:
                merged, ref = tokens, ref_l
                continue
            if ref_l.shape != ref.shape:
                log.warning("Orientation différente entre modèles, %s ignoré", lang)
                continue
            merged = merge_readings(merged, tokens)
        h, w = ref.shape[:2]
        return OCRRun(OCRPage(merged, w, h, {"engine": "paddleocr", "version": self.version,
                                             "languages": self.languages}), ref)


def merge_readings(base: list[OCRToken], other: list[OCRToken], iou_min: float = 0.5) -> list[OCRToken]:
    """Pour chaque zone lue par deux modèles, garde la lecture la plus confiante."""
    out = list(base)
    for tok in other:
        match = max(range(len(out)), key=lambda i: out[i].bbox.iou(tok.bbox), default=None)
        if match is not None and out[match].bbox.iou(tok.bbox) >= iou_min:
            if tok.confidence > out[match].confidence:
                out[match] = tok
        elif tok.confidence >= 0.5:
            out.append(tok)
    return out


class FakeOCREngine:
    """Rejoue des tokens : [{"text": "Poids : 68 kg", "conf": 0.97, "box": [x1,y1,x2,y2]}, ...]."""

    def __init__(self, tokens: list[dict] | None = None, path: str | Path | None = None,
                 expected_size: tuple[int, int] | None = None):
        if path is not None:
            tokens = json.loads(Path(path).read_text(encoding="utf-8"))
        self.tokens = tokens or []
        self.expected_size = expected_size   # (largeur, hauteur) de l'image dont viennent les tokens

    def run(self, image: np.ndarray) -> OCRRun:
        h, w = image.shape[:2]
        if self.expected_size and (w, h) != self.expected_size:
            # Rejouer ces tokens sur une autre image afficherait des valeurs plausibles mais FAUSSES
            raise ValueError("Mode OCR factice : seule examples/synthetic_form.jpg peut être lue. "
                             "Lancez le serveur avec PaddleOCR pour les vraies photos.")
        toks = [OCRToken(t["text"], float(t["conf"]), BBox(*t["box"]), detect_script(t["text"]), "fake")
                for t in self.tokens]
        return OCRRun(OCRPage(toks, w, h, {"engine": "fake"}), image)


class RapidOCREngine:
    """Moteur OCR rapide et robuste basé sur RapidOCR (ONNX Runtime).
    Exécution locale multithread sur CPU, supporte latin, arabe, chiffres et symboles.
    """

    def __init__(self):
        from rapidocr_onnxruntime import RapidOCR
        self.engine = RapidOCR()
        log.info("RapidOCR (ONNX Runtime) initialisé avec succès.")

    def run(self, image: np.ndarray) -> OCRRun:
        results, _ = self.engine(image)
        tokens: list[OCRToken] = []
        if results:
            for item in results:
                poly, text, score = item[0], item[1], item[2]
                text_clean = str(text).strip()
                if not text_clean:
                    continue
                try:
                    conf = float(score)
                except (ValueError, TypeError):
                    conf = 0.5
                bbox = BBox.from_polygon(poly)
                script = detect_script(text_clean)
                tokens.append(OCRToken(text_clean, conf, bbox, script, "rapidocr"))

        h, w = image.shape[:2]
        page = OCRPage(tokens, w, h, {"engine": "rapidocr", "version": "onnx"})
        return OCRRun(page, image)


_engine: OCREngine | None = None


def get_engine() -> OCREngine:
    global _engine
    if _engine is None:
        from app.settings import settings
        choice = settings.ocr_engine.lower()
        if choice == "fake":
            examples = Path(__file__).resolve().parents[2] / "examples"
            import cv2
            ref = cv2.imread(str(examples / "synthetic_form.jpg"))
            size = (ref.shape[1], ref.shape[0]) if ref is not None else None
            _engine = FakeOCREngine(path=examples / "fake_tokens.json", expected_size=size)
        elif choice == "paddle":
            try:
                _engine = PaddleOCREngine(settings.ocr_languages)
            except Exception as e:
                log.warning("Impossible de charger PaddleOCR (%s), bascule automatique sur RapidOCR", e)
                try:
                    _engine = RapidOCREngine()
                except Exception as e2:
                    log.error("RapidOCR indisponible (%s), repli sur FakeOCREngine", e2)
                    examples = Path(__file__).resolve().parents[2] / "examples"
                    _engine = FakeOCREngine(path=examples / "fake_tokens.json")
        else:
            try:
                _engine = RapidOCREngine()
            except Exception as e:
                log.warning("Impossible de charger RapidOCR (%s), tentative PaddleOCR", e)
                try:
                    _engine = PaddleOCREngine(settings.ocr_languages)
                except Exception as e2:
                    log.error("Aucun moteur OCR disponible, repli sur FakeOCREngine: %s", e2)
                    examples = Path(__file__).resolve().parents[2] / "examples"
                    _engine = FakeOCREngine(path=examples / "fake_tokens.json")
    return _engine


def set_engine(engine: OCREngine) -> None:
    global _engine
    _engine = engine
