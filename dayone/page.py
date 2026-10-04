"""Préparation d'une photo : chargement, redressement de la feuille, taille de travail."""

import cv2
import numpy as np

WORK_SIZE = 1600   # plus grand côté de l'image de travail, en pixels


def load_image(source) -> np.ndarray:
    """Chemin, octets ou tableau -> image BGR."""
    if isinstance(source, np.ndarray):
        return source
    if isinstance(source, (bytes, bytearray)):
        img = cv2.imdecode(np.frombuffer(source, np.uint8), cv2.IMREAD_COLOR)
    else:
        img = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Image illisible (formats acceptés : PNG, JPG).")
    return img


def _order(pts: np.ndarray) -> np.ndarray:
    s, d = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    return np.float32([pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]])


def find_sheet(img: np.ndarray) -> np.ndarray | None:
    """Les 4 coins de la feuille (claire sur fond plus sombre), ou None si l'image est déjà cadrée."""
    h, w = img.shape[:2]
    scale = 800 / max(h, w)
    small = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (7, 7), 0)
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    hull = cv2.convexHull(max(cnts, key=cv2.contourArea))
    approx = cv2.approxPolyDP(hull, 0.02 * cv2.arcLength(hull, True), True)
    ratio = cv2.contourArea(approx) / (small.shape[0] * small.shape[1])
    if len(approx) != 4 or not 0.3 < ratio < 0.95:
        return None
    return _order(approx.reshape(4, 2).astype(np.float32) / scale)


def prepare(img: np.ndarray) -> np.ndarray:
    """Redresse la feuille si elle est photographiée de travers, puis met à la taille de travail."""
    quad = find_sheet(img)
    if quad is not None:
        tl, tr, br, bl = quad
        w = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
        h = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
        M = cv2.getPerspectiveTransform(quad, np.float32([[0, 0], [w, 0], [w, h], [0, h]]))
        img = cv2.warpPerspective(img, M, (w, h))
    scale = WORK_SIZE / max(img.shape[:2])
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    return cv2.resize(img, None, fx=scale, fy=scale, interpolation=interp)
