"""Image : alignement sur le gabarit, encre manuscrite, découpe des zones, cases cochées (OpenCV)."""

from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np

from dayone.dataset import REGISTRY_DIR, ROOT
from dayone.schema import V1_PAGE_TYPES, Field, load_schema

MIN_INLIERS = 120          # en dessous : mise en page non reconnue
MIN_INK_PIXELS = 20        # en dessous : zone considérée vide (zones vides = 0 sur les pages dev)
FAINT_INK_PIXELS = 80      # en dessous : peu d'encre, une zone sans texte lu est vérifiée par le modèle
CHECK_ON = 0.06            # part d'encre dans la case : au-dessus = cochée (dev : vides = 0, cochées ≥ 0,08)
CHECK_OFF = 0.02           # en dessous = vide ; entre les deux = ambigu


def load_image(source) -> np.ndarray:
    """Chemin, octets ou tableau -> image BGR."""
    if isinstance(source, np.ndarray):
        return source
    if isinstance(source, (bytes, bytearray)):
        img = cv2.imdecode(np.frombuffer(source, np.uint8), cv2.IMREAD_COLOR)
    else:
        img = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("image illisible")
    return img


def printed_mask(img: np.ndarray) -> np.ndarray:
    """Encre imprimée (noire)."""
    return (img.max(axis=2) < 120).astype(np.uint8)


def blue_mask(img: np.ndarray) -> np.ndarray:
    """Encre bleue (stylo)."""
    b, g, r = (img[:, :, i].astype(np.int16) for i in range(3))
    return ((b - r > 35) & (b - g > 25)).astype(np.uint8)


def _clean(mask: np.ndarray, min_area: int = 8) -> np.ndarray:
    """Retire les points isolés et les restes de lignes imprimées (traits très fins et longs)."""
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    w, h = stats[:, cv2.CC_STAT_WIDTH], stats[:, cv2.CC_STAT_HEIGHT]
    line_residue = ((h <= 4) & (w >= 30)) | ((w <= 4) & (h >= 30))
    keep = ((stats[:, cv2.CC_STAT_AREA] >= min_area) & ~line_residue).astype(np.uint8)
    keep[0] = 0
    return keep[lab]


@dataclass
class Reference:
    page_type: str
    image: np.ndarray
    printed_dilated: np.ndarray
    keypoints: tuple
    descriptors: np.ndarray


_ORB = cv2.ORB_create(5000)


def _features(img: np.ndarray):
    gray = np.where(printed_mask(img) == 1, 0, 255).astype(np.uint8)
    return _ORB.detectAndCompute(gray, None)


@lru_cache
def reference(page_type: str) -> Reference:
    """Page de référence du gabarit (une page dev, lue sur place, jamais copiée)."""
    s = load_schema(page_type)
    paths = sorted(REGISTRY_DIR.glob(f"dossiers_specimen_10_patientes-{s.reference_page:02d}*.png"))
    if not paths:
        raise FileNotFoundError(f"page de référence {s.reference_page} absente de {REGISTRY_DIR.relative_to(ROOT)}")
    img = load_image(paths[0])
    kp, des = _features(img)
    dil = cv2.dilate(printed_mask(img), np.ones((7, 7), np.uint8))
    return Reference(page_type, img, dil, kp, des)


@dataclass
class Alignment:
    page_type: str
    inliers: int
    homography: np.ndarray | None

    @property
    def ok(self) -> bool:
        return self.homography is not None and self.inliers >= MIN_INLIERS


def align(img: np.ndarray, page_type: str) -> Alignment:
    ref = reference(page_type)
    kp, des = _features(img)
    if des is None or len(kp) < 50:
        return Alignment(page_type, 0, None)
    matches = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(des, ref.descriptors)
    matches = sorted(matches, key=lambda m: m.distance)[:1000]
    if len(matches) < 20:
        return Alignment(page_type, 0, None)
    src = np.float32([kp[m.queryIdx].pt for m in matches])
    dst = np.float32([ref.keypoints[m.trainIdx].pt for m in matches])
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    if H is None:
        return Alignment(page_type, 0, None)
    return Alignment(page_type, int(mask.sum()), H)


def detect_page_type(img: np.ndarray) -> Alignment:
    """Essaie chaque gabarit V1 ; garde le meilleur alignement."""
    return max((align(img, pt) for pt in V1_PAGE_TYPES), key=lambda a: a.inliers)


def warp(img: np.ndarray, al: Alignment) -> np.ndarray:
    w, h = load_schema(al.page_type).image_size
    return cv2.warpPerspective(img, al.homography, (w, h), borderValue=(255, 255, 255))


def handwriting_mask(aligned: np.ndarray, page_type: str) -> np.ndarray:
    """Encre bleue + tout trait sombre absent du gabarit imprimé (stylo noir, traits fins)."""
    extra = (aligned.min(axis=2) < 150).astype(np.uint8) & (1 - reference(page_type).printed_dilated)
    return _clean(blue_mask(aligned) | extra)


def ink_pixels(ink: np.ndarray, f: Field) -> int:
    x0, y0, x1, y1 = f.zone
    return int(ink[y0:y1, x0:x1].sum())


def zone_crop(aligned: np.ndarray, f: Field) -> np.ndarray:
    """Zone d'un champ, telle quelle (les essais montrent que nettoyer l'image abîme les traits fins), agrandie ×2."""
    x0, y0, x1, y1 = f.zone
    h, w = aligned.shape[:2]
    crop = aligned[max(y0 - 8, 0):min(y1 + 4, h), max(x0 - 4, 0):min(x1 + 4, w)]
    return cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)


def checkbox_ratio(ink: np.ndarray, f: Field) -> float:
    """Part de pixels d'encre à l'intérieur de la case."""
    cx, cy, size = f.box
    r = size // 2 - 4
    inner = ink[cy - r:cy + r, cx - r:cx + r]
    return float(inner.mean()) if inner.size else 0.0


def masked_preview(aligned: np.ndarray, page_type: str) -> np.ndarray:
    """Page alignée avec les zones personnelles noircies (pour l'affichage)."""
    out = aligned.copy()
    for x0, y0, x1, y1 in load_schema(page_type).excluded_zones.values():
        out[y0:y1, x0:x1] = 0
    return out
