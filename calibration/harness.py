"""Passe de lecture instrumentée, sans modifier le code de lecture (dayone/).

On lance `dayone.extract.extract_page` tel quel, en espionnant deux fonctions :
- `extract._crop` pour connaître la zone de chaque morceau d'image ;
- `vlm.read_value` pour garder le morceau, le libellé, la réponse du modèle et son temps.
Pour chaque morceau, la bonne réponse vient du PDF (calibration/references.py).
"""

import time

import cv2

from calibration.references import text_in
from dayone import extract, vlm


def _png(img) -> bytes:
    return cv2.imencode(".png", img)[1].tobytes()


def instrumented_read(page_number: int, image_path, model: str = vlm.DEFAULT_MODEL, read_value=None) -> tuple[dict, list[dict]]:
    """Lit une page avec le modèle. Renvoie (sortie de extract_page, morceaux envoyés au modèle)."""
    crops: list[dict] = []
    last = {}
    real_crop, real_read = extract._crop, vlm.read_value
    reader = read_value or real_read

    def crop_spy(img, box, th):
        last.update(box=tuple(int(v) for v in box), shape=img.shape[:2])
        return real_crop(img, box, th)

    def read_spy(crop, label, model=model):
        t = time.perf_counter()
        answer = reader(crop, label, model)
        crops.append({
            "page": page_number, "label": label, "box": last["box"], "shape": last["shape"],
            "crop_png": _png(crop), "answer": answer, "seconds": round(time.perf_counter() - t, 2),
            "reference": text_in(page_number, last["box"], last["shape"]),
        })
        return answer

    extract._crop, vlm.read_value = crop_spy, read_spy
    try:
        pred = extract.extract_page(image_path, use_model=True, model=model)
    finally:
        extract._crop, vlm.read_value = real_crop, real_read
    return pred, crops
