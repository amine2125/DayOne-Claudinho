"""Bonnes réponses tirées du PDF du registre : l'écriture simulée y est du texte.

L'imprimé est en Helvetica ; l'écriture de chaque patiente fictive a sa propre police (Caveat,
ShadowsIntoLight, Gaegu, ReenieBeanie…) : tout ce qui n'est pas en Helvetica est de l'écriture.

Chaque caractère manuscrit a sa position sur la page. Pour un morceau d'image envoyé au modèle,
la bonne réponse est donc l'écriture qui se trouve dans cette zone, sans rien annoter à la main.
Les données personnelles (nom, CIN, téléphone, adresse) ne sont jamais renvoyées : ces zones
sont déjà masquées avant d'envoyer l'image au modèle, et `dayone.privacy` filtre le reste.
"""

import ctypes
from functools import lru_cache

import pypdfium2 as pdfium
import pypdfium2.raw as raw

from dayone.dataset import REGISTRY_DIR

PDF = REGISTRY_DIR / "dossiers_specimen_10_patientes.pdf"
PRINTED_FONT = b"Helvetica"
PNG_SIZE = (1654, 2339)          # rendu des pages principales (A4 à 200 dpi)


@lru_cache(maxsize=1)
def _doc():
    return pdfium.PdfDocument(PDF)


@lru_cache(maxsize=None)
def hand_chars(page_number: int) -> list[tuple[str, float, float, float, float]]:
    """Caractères manuscrits d'une page (1-80) : (car., x0, y0, x1, y1) en fraction de la page, y vers le bas."""
    pg = _doc()[page_number - 1]
    w, h = pg.get_size()
    tp = pg.get_textpage()
    buf, flags = ctypes.create_string_buffer(256), ctypes.c_int()
    l, r, b, t = (ctypes.c_double() for _ in range(4))
    out = []
    for k in range(raw.FPDFText_CountChars(tp)):
        raw.FPDFText_GetFontInfo(tp, k, buf, 256, ctypes.byref(flags))
        if buf.value.startswith(PRINTED_FONT):
            continue
        ch = chr(raw.FPDFText_GetUnicode(tp, k))
        raw.FPDFText_GetCharBox(tp, k, ctypes.byref(l), ctypes.byref(r), ctypes.byref(b), ctypes.byref(t))
        out.append((ch, l.value / w, 1 - t.value / h, r.value / w, 1 - b.value / h))
    return out


@lru_cache(maxsize=None)
def hand_values(page_number: int) -> list[tuple[str, tuple]]:
    """Valeurs manuscrites d'une page, dans l'ordre du PDF : (texte, (x0, y0, x1, y1) en fraction de page)."""
    values, cur = [], []
    for c in hand_chars(page_number) + [("\n", 0, 0, 0, 0)]:
        if c[0] in "\r\n":
            boxes = [x for x in cur if x[3] > x[1]]
            text = "".join(x[0] for x in cur).strip()
            if text and boxes:
                values.append((text, (min(b[1] for b in boxes), min(b[2] for b in boxes),
                                      max(b[3] for b in boxes), max(b[4] for b in boxes))))
            cur = []
        else:
            cur.append(c)
    return values


def text_in(page_number: int, box: tuple, image_shape: tuple) -> str:
    """Valeurs manuscrites dont le centre est dans `box` (pixels de l'image de travail `image_shape`)."""
    ih, iw = image_shape[:2]
    x0, y0, x1, y1 = box[0] / iw, box[1] / ih, box[2] / iw, box[3] / ih
    found = [t for t, (a, b, c, d) in hand_values(page_number)
             if x0 <= (a + c) / 2 <= x1 and y0 <= (b + d) / 2 <= y1]
    return " ".join(found)


def values_in(page_number: int, box: tuple, image_shape: tuple, margin: float = 0.01) -> list[str]:
    """Valeurs manuscrites présentes dans le morceau (zone + petite marge, comme le découpage envoyé au modèle).

    Tolère une zone imprécise : la bonne réponse est l'une de ces valeurs.
    """
    ih, iw = image_shape[:2]
    x0, y0, x1, y1 = box[0] / iw - margin, box[1] / ih - margin / 2, box[2] / iw + margin, box[3] / ih + margin / 2
    return [t for t, (a, b, c, d) in hand_values(page_number)
            if x0 <= (a + c) / 2 <= x1 and y0 <= (b + d) / 2 <= y1]
