"""Prétraitement OpenCV : contrôle qualité, détection de page, redressement, contraste.

On donne à PaddleOCR une image COULEUR améliorée (pas binarisée : la binarisation
dégrade souvent la reconnaissance). La version binarisée sert seulement à mesurer
la présence d'encre dans une zone (NON_FOURNI vs ILLISIBLE).
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.schemas.models import QualityLevel, QualityReport
from app.settings import settings


@dataclass
class PreprocessResult:
    image: np.ndarray            # BGR redressée + contraste, envoyée à l'OCR
    quality: QualityReport


def decode_image(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Image illisible ou format non supporté")
    return img


def resize_max(img: np.ndarray, max_side: int) -> np.ndarray:
    h, w = img.shape[:2]
    scale = max_side / max(h, w)
    if scale >= 1:
        return img
    return cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)


def measure_quality(img: np.ndarray) -> tuple[float, float, float, float]:
    """(netteté, luminosité, contraste, encre la plus sombre) sur une version 1000 px, pour être comparables.

    Un document est surtout blanc : une luminosité moyenne élevée est normale. La surexposition
    se voit au fait qu'il ne reste plus de traits sombres (1er percentile de gris trop clair)."""
    gray = cv2.cvtColor(resize_max(img, 1000), cv2.COLOR_BGR2GRAY)
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    p1, p99 = np.percentile(gray, (1, 99))
    return blur, float(gray.mean()), float(p99 - p1), float(p1)   # contraste = plage dynamique


def _order_corners(pts: np.ndarray) -> np.ndarray:
    pts = pts.reshape(4, 2).astype(np.float32)
    s, d = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]],
                    dtype=np.float32)  # tl, tr, br, bl


def find_page_quad(img: np.ndarray, min_area_ratio: float = 0.25) -> np.ndarray | None:
    small = resize_max(img, 800)
    ratio = img.shape[1] / small.shape[1]
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    edges = cv2.dilate(cv2.Canny(gray, 50, 150), np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = min_area_ratio * small.shape[0] * small.shape[1]
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        area = cv2.contourArea(c)
        if area < min_area:
            break
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4 and cv2.isContourConvex(approx) and _is_paper_edge(gray, approx):
            return _order_corners(approx * ratio)
        # Fallback boîte englobante orientée (minAreaRect)
        rect = cv2.minAreaRect(c)
        box = cv2.boxPoints(rect)
        if _is_paper_edge(gray, box):
            return _order_corners(box * ratio)
    return None


def find_page_by_threshold(img: np.ndarray, min_area_ratio: float = 0.25) -> np.ndarray | None:
    """Repli : la feuille (claire) se détache d'un fond sombre. Otsu -> plus grande région -> 4 coins."""
    small = resize_max(img, 800)
    ratio = img.shape[1] / small.shape[1]
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (7, 7), 0)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    area_ratio = cv2.contourArea(c) / (small.shape[0] * small.shape[1])
    if not (min_area_ratio <= area_ratio <= 0.97):
        return None
    hull = cv2.convexHull(c)
    for eps in (0.02, 0.03, 0.04, 0.05, 0.06):
        approx = cv2.approxPolyDP(hull, eps * cv2.arcLength(hull, True), True)
        if len(approx) == 4 and _is_paper_edge(gray, approx):
            return _order_corners(approx * ratio)
    # Repli minAreaRect
    rect = cv2.minAreaRect(hull)
    box = cv2.boxPoints(rect)
    if _is_paper_edge(gray, box):
        return _order_corners(box * ratio)
    return None


def _is_paper_edge(gray: np.ndarray, quad: np.ndarray, ring: int = 12, min_diff: float = 25.0) -> bool:
    """Un vrai bord de feuille sépare le papier d'un fond différent (table, tissu).
    Un cadre imprimé DANS le formulaire a le même papier des deux côtés -> rejeté."""
    mask = np.zeros(gray.shape, np.uint8)
    cv2.fillPoly(mask, [quad.reshape(-1, 2).astype(np.int32)], 255)
    k = np.ones((ring, ring), np.uint8)
    inside = cv2.subtract(mask, cv2.erode(mask, k))
    outside = cv2.subtract(cv2.dilate(mask, k), mask)
    if cv2.countNonZero(outside) < 50:          # le quadrilatère touche les bords de l'image
        return False
    return abs(float(gray[inside > 0].mean()) - float(gray[outside > 0].mean())) >= min_diff


def page_fills_frame(img: np.ndarray, band: float = 0.03) -> bool:
    """Bordure claire et homogène = le papier occupe tout le cadre (scan, photo serrée)."""
    gray = cv2.cvtColor(resize_max(img, 800), cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    bh, bw = max(2, int(h * band)), max(2, int(w * band))
    border = np.concatenate([gray[:bh].ravel(), gray[-bh:].ravel(), gray[:, :bw].ravel(), gray[:, -bw:].ravel()])
    return float(border.mean()) > 170 and float(border.std()) < 40


def warp_page(img: np.ndarray, quad: np.ndarray) -> np.ndarray:
    tl, tr, br, bl = quad
    w = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    h = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)
    return cv2.warpPerspective(img, cv2.getPerspectiveTransform(quad, dst), (w, h))


def deskew(img: np.ndarray, max_angle: float = 15.0) -> tuple[np.ndarray, float]:
    """Corrige une petite inclinaison via les lignes horizontales (règles du registre, lignes de texte).
    Les rotations de 90/180° sont gérées par le classifieur d'orientation de PaddleOCR."""
    gray = cv2.cvtColor(resize_max(img, 1200), cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 360, threshold=120,
                            minLineLength=gray.shape[1] // 4, maxLineGap=10)
    if lines is None:
        return img, 0.0
    angles = [np.degrees(np.arctan2(y2 - y1, x2 - x1)) for x1, y1, x2, y2 in lines.reshape(-1, 4)]  # (N,1,4) en 4.x
    angles = [a for a in angles if abs(a) <= max_angle]
    if len(angles) < 3:
        return img, 0.0
    angle = float(np.median(angles))
    if abs(angle) < 0.5:
        return img, 0.0
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE), angle


def remove_shadows(img: np.ndarray, kernel_size: int = 25) -> np.ndarray:
    """Élimination des ombres par division morphologique du fond estimé."""
    planes = cv2.split(img)
    result_planes = []
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    for plane in planes:
        dilated = cv2.dilate(plane, k)
        bg = cv2.medianBlur(dilated, 21)
        diff = 255 - cv2.absdiff(plane, bg)
        norm = cv2.normalize(diff, None, alpha=0, beta=255, norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_8U)
        result_planes.append(norm)
    return cv2.merge(result_planes)


def enhance(img: np.ndarray) -> np.ndarray:
    """Réhaussement du contraste et de la netteté de l'encre manuscrite."""
    cleaned = remove_shadows(img)
    lab = cv2.cvtColor(cleaned, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
    out = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
    if settings.denoise:
        out = cv2.fastNlMeansDenoisingColored(out, None, 5, 5, 7, 21)
    return out


def ink_mask(img: np.ndarray) -> np.ndarray:
    """Masque binaire de l'encre, ombres compensées et lignes du formulaire retirées."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    bg = cv2.medianBlur(cv2.dilate(gray, np.ones((7, 7), np.uint8)), 21)
    norm = 255 - cv2.absdiff(gray, bg)
    norm = cv2.normalize(norm, None, 0, 255, cv2.NORM_MINMAX)
    _, mask = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    h, w = mask.shape
    horiz = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, w // 30), 1)))
    vert = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, h // 30))))
    return cv2.subtract(mask, cv2.bitwise_or(horiz, vert))


def ink_ratio(mask: np.ndarray, box: tuple[float, float, float, float], margin: float = 0.1) -> float:
    x1, y1, x2, y2 = box
    mx, my = (x2 - x1) * margin, (y2 - y1) * margin
    h, w = mask.shape
    xa, ya = max(0, int(x1 + mx)), max(0, int(y1 + my))
    xb, yb = min(w, int(x2 - mx)), min(h, int(y2 - my))
    if xb <= xa or yb <= ya:
        return 0.0
    return float((mask[ya:yb, xa:xb] > 0).mean())


def preprocess(img: np.ndarray) -> PreprocessResult:
    img = resize_max(img, settings.max_image_side)
    blur, brightness, contrast, darkest_ink = measure_quality(img)
    reasons: list[str] = []
    level = QualityLevel.BONNE

    if blur < settings.blur_reject:
        reasons.append("photo_floue")
    if brightness < settings.brightness_min:
        reasons.append("photo_trop_sombre")
    if darkest_ink > settings.washed_out_ink_min:
        reasons.append("photo_surexposee")
    if contrast < settings.contrast_min:
        reasons.append("contraste_insuffisant")
    if reasons:
        level = QualityLevel.REJETEE

    page_detected = True
    if not page_fills_frame(img):     # scan ou photo cadrée serrée : rien à redresser
        quad = find_page_quad(img)
        if quad is None:
            quad = find_page_by_threshold(img)
        if quad is not None:
            img = warp_page(img, quad)
        else:
            page_detected = False
            reasons.append("bords_de_page_non_detectes")
    img, angle = deskew(img)
    if angle:
        reasons.append(f"inclinaison_corrigee_{angle:.1f}deg")

    if level != QualityLevel.REJETEE and (blur < settings.blur_warn or not page_detected):
        level = QualityLevel.MOYENNE

    report = QualityReport(level=level, blur_score=round(blur, 1), brightness=round(brightness, 1),
                           contrast=round(contrast, 1), page_detected=page_detected, reasons=reasons)
    return PreprocessResult(image=enhance(img), quality=report)
