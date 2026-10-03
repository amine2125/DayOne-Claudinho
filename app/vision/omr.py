"""Module Micro-OMR (Optical Mark Recognition) pour cases à cocher et choix multiples.

Permet de détecter et classifier les cases à cocher (Groupage, Rhésus, Facteurs de risque,
Mode d'accouchement, etc.) sans dépendre d'un modèle OCR textuel.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import cv2
import numpy as np

from app.ocr.types import BBox


@dataclass(frozen=True)
class CheckboxResult:
    bbox: BBox
    checked: bool
    confidence: float
    ink_density: float
    state: str  # "CHECKED" | "EMPTY" | "AMBIGUOUS"


def detect_checkboxes(
    img: np.ndarray,
    min_size: int = 10,
    max_size: int = 55,
    min_aspect: float = 0.70,
    max_aspect: float = 1.35,
) -> list[BBox]:
    """Détecte les contours carrés/rectangulaires caractéristiques des cases à cocher."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 4
    )

    contours, _ = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    boxes: list[BBox] = []
    seen: list[tuple[float, float, float, float]] = []

    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if not (min_size <= w <= max_size and min_size <= h <= max_size):
            continue
        aspect = w / float(h)
        if not (min_aspect <= aspect <= max_aspect):
            continue

        # Vérification quadrilatère
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.04 * peri, True)
        if len(approx) != 4:
            continue

        box = BBox(float(x), float(y), float(x + w), float(y + h))

        # Déduplication avec les boîtes quasi identiques
        dup = False
        for sx1, sy1, sx2, sy2 in seen:
            if abs(box.x1 - sx1) < 4 and abs(box.y1 - sy1) < 4 and abs(box.w - (sx2 - sx1)) < 4:
                dup = True
                break
        if not dup:
            seen.append((box.x1, box.y1, box.x2, box.y2))
            boxes.append(box)

    return boxes


def inspect_checkbox(gray: np.ndarray, box: BBox, border_margin: float = 0.22) -> CheckboxResult:
    """Mesure la présence d'encre à l'intérieur d'une case à cocher, en excluant les bordures."""
    h_img, w_img = gray.shape[:2]
    x1, y1, x2, y2 = box.x1, box.y1, box.x2, box.y2
    bw, bh = x2 - x1, y2 - y1

    # Marges internes pour ne pas compter le cadre imprimé
    mx, my = bw * border_margin, bh * border_margin
    ix1, iy1 = max(0, int(x1 + mx)), max(0, int(y1 + my))
    ix2, iy2 = min(w_img, int(x2 - mx)), min(h_img, int(y2 - my))

    if ix2 <= ix1 or iy2 <= iy1:
        return CheckboxResult(box, False, 0.5, 0.0, "AMBIGUOUS")

    patch = gray[iy1:iy2, ix1:ix2]
    # Binarisation locale par Otsu
    _, bin_patch = cv2.threshold(patch, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ink_density = float((bin_patch > 0).mean())

    # Seuils de classification calibrés
    if ink_density < 0.08:
        # Case vide
        conf = min(0.98, 1.0 - ink_density * 4.0)
        return CheckboxResult(box, False, conf, ink_density, "EMPTY")
    elif 0.12 <= ink_density <= 0.80:
        # Case cochée (coche, croix, trait oblique, coche grasse)
        conf = min(0.96, 0.72 + (ink_density - 0.12) * 0.3)
        return CheckboxResult(box, True, conf, ink_density, "CHECKED")
    elif ink_density > 0.80:
        # Rature ou macule d'encre lourde
        return CheckboxResult(box, False, 0.40, ink_density, "AMBIGUOUS")
    else:
        # Zone intermédiaire (0.08 - 0.12)
        return CheckboxResult(box, ink_density >= 0.10, 0.55, ink_density, "AMBIGUOUS")


def find_adjacent_checkbox(
    box_list: Sequence[BBox],
    label_box: BBox,
    direction: str = "left",
    max_dist: float = 80.0,
) -> BBox | None:
    """Associe une case à cocher située à gauche ou à droite d'un libellé."""
    candidates = []
    lh = label_box.h

    for b in box_list:
        # Alignement vertical
        if b.v_overlap(label_box) >= 0.35 or abs(b.cy - label_box.cy) <= max(14.0, 0.7 * lh):
            # Cas 1 : Case à gauche du libellé
            if direction == "left":
                dist = label_box.x1 - b.x2
                if 0 <= dist <= max_dist:
                    candidates.append((dist, b))
                # Cas 1bis : Case englobée au début du token (ex: "-Anémie")
                elif label_box.x1 - 12 <= b.x1 <= label_box.x1 + 35:
                    candidates.append((abs(b.x1 - label_box.x1), b))
            else:  # right
                dist = b.x1 - label_box.x2
                if 0 <= dist <= max_dist:
                    candidates.append((dist, b))
                elif label_box.x2 - 35 <= b.x2 <= label_box.x2 + 12:
                    candidates.append((abs(b.x2 - label_box.x2), b))

    if candidates:
        candidates.sort(key=lambda p: p[0])
        return candidates[0][1]
    return None


def resolve_group_selection(
    gray: np.ndarray,
    options: dict[str, BBox],
    all_checkboxes: Sequence[BBox] | None = None,
) -> tuple[str | None, float, str]:
    """Détermine quelle option est cochée parmi un ensemble d'options mutuellement exclusives.

    Ex: {"A": bbox_a, "B": bbox_b, "AB": bbox_ab, "O": bbox_o}
    Retourne: (meilleure_option, confiance, statut)
    """
    if not options:
        return None, 0.0, "NON_FOURNI"

    if all_checkboxes is None:
        all_checkboxes = detect_checkboxes(gray)

    scored_options: list[tuple[str, CheckboxResult]] = []

    for name, opt_box in options.items():
        # Chercher la case immédiatement à gauche ou à droite
        cb = find_adjacent_checkbox(all_checkboxes, opt_box, direction="left")
        if cb is None:
            cb = find_adjacent_checkbox(all_checkboxes, opt_box, direction="right", max_dist=40.0)

        if cb is not None:
            res = inspect_checkbox(gray, cb)
        else:
            # Si pas de contour fermé détecté, inspecter la zone juste à gauche du libellé
            h = opt_box.h
            w_box = max(14.0, h)
            fallback_box = BBox(
                max(0.0, opt_box.x1 - w_box - 4.0),
                opt_box.y1,
                opt_box.x1 - 2.0,
                opt_box.y2,
            )
            res = inspect_checkbox(gray, fallback_box)

        scored_options.append((name, res))

    checked_candidates = [
        (name, res) for name, res in scored_options if res.checked or res.state == "CHECKED"
    ]

    if len(checked_candidates) == 1:
        name, res = checked_candidates[0]
        return name, res.confidence, "CONNU"
    elif len(checked_candidates) > 1:
        # Plusieurs cases cochées : ambiguïté
        # Choisir celle avec la plus forte densité
        best = max(checked_candidates, key=lambda p: p[1].ink_density)
        return best[0], 0.60, "A_REVISER"
    else:
        # Aucune case cochée trouvée
        # Trouver la case la plus dense
        best = max(scored_options, key=lambda p: p[1].ink_density)
        if best[1].ink_density > 0.09:
            return best[0], 0.55, "A_REVISER"
        return None, 0.90, "NON_FOURNI"
