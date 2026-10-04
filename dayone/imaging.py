"""Cases à cocher, sans gabarit : petits carrés imprimés repérés sur la page, encre mesurée à l'intérieur."""

import re

import cv2
import numpy as np

CHECK_ON = 0.03    # part d'encre à l'intérieur : au-dessus = cochée (pages dev : vides = 0, cochées ≥ 0,04)
CHECK_OFF = 0.01   # en dessous = vide ; entre les deux = ambigu


def blue_mask(img: np.ndarray) -> np.ndarray:
    """Encre bleue (stylo)."""
    b, g, r = (img[:, :, i].astype(np.int16) for i in range(3))
    return ((b - r > 35) & (b - g > 25)).astype(np.uint8)


def printed_mask(img: np.ndarray) -> np.ndarray:
    """Encre plus sombre que le papier autour (seuil adaptatif : photos mal éclairées), sans le stylo bleu."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    dark = cv2.adaptiveThreshold(gray, 1, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 25)
    return (dark & (1 - blue_mask(img))).astype(np.uint8)


def find_checkboxes(img: np.ndarray, text_height: float, bm: np.ndarray | None = None) -> list[tuple[int, int, int, int]]:
    """Petits carrés imprimés (x, y, w, h), de taille proche de la hauteur du texte.

    On cherche leurs 4 côtés droits (traits courts horizontaux et verticaux) : une croix ou un trait
    de coche, en diagonale, n'empêche pas de retrouver le carré. Un carré tracé à l'encre bleue est une
    lettre écrite à la main (« O »), pas une case imprimée.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    m = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 20)
    k = max(5, int(0.4 * text_height))
    horiz = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (k, 1)))
    vert = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, k)))
    n, _, stats, _ = cv2.connectedComponentsWithStats(cv2.dilate(horiz | vert, np.ones((3, 3), np.uint8)))
    lo, hi = 0.4 * text_height, 1.8 * text_height
    boxes = []
    for i in range(1, n):
        x, y, w, h = (int(v) for v in stats[i, :4])
        if not (0.35 * text_height <= w <= 2.2 * text_height and 0.35 * text_height <= h <= 2.2 * text_height):
            continue
        cols = np.where(vert[y:y + h, x:x + w].mean(axis=0) / 255 >= 0.5)[0]
        rows = np.where(horiz[y:y + h, x:x + w].mean(axis=1) / 255 >= 0.5)[0]
        if len(cols) < 2 or len(rows) < 2:
            continue
        bw, bh = int(cols[-1] - cols[0] + 1), int(rows[-1] - rows[0] + 1)
        if lo <= bw <= hi and lo <= bh <= hi and 0.7 <= bw / bh <= 1.45:   # photo de biais : un peu déformé
            b = (x + int(cols[0]), y + int(rows[0]), bw, bh)
            if bm is None or not _blue_outline(b, horiz | vert, bm):
                boxes.append(b)
    return boxes


def _blue_outline(box, sides: np.ndarray, bm: np.ndarray) -> bool:
    """Les côtés du carré sont-ils surtout à l'encre bleue ?"""
    x, y, w, h = box
    edge = sides[y:y + h, x:x + w] > 0
    return bool(edge.sum()) and bm[y:y + h, x:x + w][edge].mean() > 0.5


def mark_ratio(img: np.ndarray, box, bm: np.ndarray | None = None) -> float:
    """Part de pixels marqués (stylo bleu ou trait sombre) à l'intérieur de la case, bord exclu."""
    x, y, w, h = box
    m = max(3, w // 6)
    inner = img[y + m:y + h - m, x + m:x + w - m]
    if inner.size == 0:
        return 0.0
    blue = bm[y + m:y + h - m, x + m:x + w - m] if bm is not None else blue_mask(inner)
    marked = blue | (inner.max(axis=2) < 130).astype(np.uint8)
    return float(marked.mean())


def check_state(ratio: float) -> bool | None:
    """True = cochée, False = vide, None = ambigu."""
    if ratio >= CHECK_ON:
        return True
    if ratio <= CHECK_OFF:
        return False
    return None


def find_tables(img: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Tableaux (x, y, w, h) : grilles de traits imprimés avec au moins 3 traits verticaux (2 colonnes de données)."""
    m = printed_mask(img) * 255
    H, W = m.shape
    horiz = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (W // 12, 1)))
    # Traits verticaux de photo souvent coupés : on recolle les petits trous avant de les chercher.
    vert = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 9)))
    vert = cv2.morphologyEx(vert, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, H // 60)))
    grid = cv2.dilate(horiz | vert, np.ones((5, 5), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(grid)
    out = []
    for i in range(1, n):
        x, y, w, h = (int(v) for v in stats[i, :4])
        if w < 0.3 * W or h < 0.04 * H:
            continue
        cols = np.where(vert[y:y + h, x:x + w].mean(axis=0) > 0.2 * 255)[0]
        n_cols = int(np.sum(np.diff(cols) > 3)) + 1 if len(cols) else 0
        if n_cols >= 3:
            out.append((x, y, w, h))
    return out


CROSS_MARKS = {"x", "X", "×", "✓", "✔", "✗", "✘", "+"}
BOX_GLYPHS = re.compile(r"[□■☐☑☒✓✔✗✘▢◻]")


def _gap_before(img, box) -> bool:
    """Y a-t-il un espace vide juste à gauche de la case ? (une lettre dans un mot n'en a pas)."""
    bx, by, bw, bh = box
    gw = max(3, int(0.3 * bw))
    strip = img[by + 2:by + bh - 2, max(0, bx - gw - 1):bx - 1]
    return strip.size == 0 or (strip.min(axis=2) < 130).mean() < 0.05


def _fits_before(text: str, x0: int, bx: int, text_height: float) -> bool:
    """Case collée au mot (« Mobile☐ ») : tout le mot tient avant la case, avec une largeur de lettre normale,
    et il finit par une minuscule (une « case » qui serait une lettre fausserait la largeur)."""
    t = text.strip()
    return len(t) >= 3 and t[-1].islower() and 0.3 * text_height <= (bx - x0) / len(t) <= 0.9 * text_height


def _gap_after(img, box) -> bool:
    """Y a-t-il un espace vide juste à droite de la case ?"""
    bx, by, bw, bh = box
    gw = max(3, int(0.3 * bw))
    strip = img[by + 2:by + bh - 2, bx + bw + 1:bx + bw + gw + 1]
    return strip.size == 0 or (strip.min(axis=2) < 130).mean() < 0.05


def _uppercase_title(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return len(text.split()) >= 2 and len(letters) >= 6 and all(c.isupper() for c in letters)


def checkbox_label(box, lines: list[dict], text_height: float, img: np.ndarray | None = None) -> str:
    """Étiquette d'une case : le texte le plus proche sur la même ligne, à droite ou à gauche.

    L'OCR lit parfois la case comme un caractère « □ » au milieu d'une ligne : on coupe la ligne
    à l'endroit de la case. Un texte très court (« 1 », « 2 ») est préfixé par le texte qui précède (« VAT 1 »).
    """
    bx, by, bw, bh = box
    cy = by + bh / 2
    row = sorted((l for l in lines if abs((l["box"][1] + l["box"][3]) / 2 - cy) < 0.7 * text_height),
                 key=lambda l: l["box"][0])
    after, before = "", ""
    d_after = d_before = None
    for l in row:
        x0, _, x1, _ = l["box"]
        text = l["text"]
        if text.strip() in CROSS_MARKS and x1 - x0 <= 2.5 * bw and x0 - bw <= bx <= x1 + bw:
            continue                         # la croix de la case lue comme du texte (« X »)
        if x0 < bx + bw / 2 < x1:            # la ligne OCR traverse la case
            pos = (bx + bw / 2 - x0) / max(x1 - x0, 1) * len(text)
            glyphs = [m.start() for m in BOX_GLYPHS.finditer(text)]
            if glyphs:                       # l'OCR a écrit la case : on coupe au « □ » le plus proche
                g = min(glyphs, key=lambda i: abs(i - pos))
                after, before = after or text[g + 1:], text[:g] or before
                if text[:g].strip():
                    d_before = 0                 # « CSC □ » : le mot collé avant la case
            elif bx - x0 <= bw and not _uppercase_title(text) and (img is None or _gap_after(img, box)):
                after = after or text        # case au début de la ligne : toute la ligne est l'étiquette
            elif x1 - (bx + bw) <= bw and not _uppercase_title(text) and \
                    (img is None or _gap_before(img, box) or _fits_before(text, x0, bx, text_height)):
                after, d_after = after or text, 0      # case à la fin de la ligne (« CSCA ☐ ») : idem
            else:                            # au milieu d'un mot : c'est une lettre, pas une case
                return ""
        elif -bw <= x0 - (bx + bw) <= 4 * text_height and not after:
            after, d_after = text, x0 - (bx + bw)
        elif -bw <= bx - x1 <= 8 * text_height:   # colonne de cases alignées à droite de leurs étiquettes
            before, d_before = text, bx - x1
    def clean(t: str) -> str:
        t = re.sub(r"\s+", " ", BOX_GLYPHS.sub(" ", t)).strip(" :")
        t = re.sub(r"^[^\w«(]+", "", t)          # caractères parasites en tête (« ] Forceps »)
        return re.sub(r"^[Xx](?=\s*\d)\s*", "", t)  # case cochée lue « X » (« X1 » -> « 1 »)

    # Le texte collé à la case l'emporte : « Fixe ☒   Mobile ☐ » -> la 1re case est « Fixe ».
    if d_after is not None and d_before is not None and d_before < d_after and len(clean(before)) > 2:
        after, before = before, ""
    elif not after and d_before is not None:
        after, before = before, ""
    # Jetons parasites d'un seul caractère non latin (la case lue « σ » par l'OCR).
    label = " ".join(t for t in clean(after).split() if not (len(t) == 1 and not t.isascii()))
    first = label.split()[0] if label else ""
    if first.isdigit() and len(first) <= 2:
        # Rangée de cases numérotées (« VAT : □1 □2 … ») : numéro de la case + intitulé de la rangée.
        title = clean(re.split(r"[:□]", row[0]["text"])[0]) if row else ""
        label = f"{title} {first}".strip() if title and not title[0].isdigit() else first
    return label


def _in_big_text(box, lines: list[dict], text_height: float) -> bool:
    """La « case » est-elle une lettre d'un titre en gros caractères (« D », « O ») ?"""
    bx, by, bw, bh = box
    cx, cy = bx + bw / 2, by + bh / 2
    # Une case au début de sa ligne est une vraie case (la croix rend seulement la ligne OCR plus haute).
    return any(l["box"][0] <= cx <= l["box"][2] and l["box"][1] <= cy <= l["box"][3]
               and l["box"][3] - l["box"][1] > 1.5 * text_height and bx - l["box"][0] > bw for l in lines)


def label_checkboxes(boxes, lines: list[dict], text_height: float,
                     img: np.ndarray | None = None) -> list[tuple[tuple, str]]:
    """Étiquette chaque case. Une rangée de cases numérotées (« VAT □1 □2 □3 ») est renumérotée
    de gauche à droite avec les chiffres lus sur la ligne, car l'OCR fusionne souvent « □3 □4 »."""
    boxes = [b for b in boxes if not _in_big_text(b, lines, text_height)]
    labeled = [(b, checkbox_label(b, lines, text_height, img)) for b in boxes]
    cy = lambda b: b[1] + b[3] / 2
    groups = []   # [titre, [cases]]
    for b, lab in labeled:
        m = re.fullmatch(r"(.*?)\s*(\d{1,2})", lab)
        if not m:
            continue
        g = next((g for g in groups if g[0] == m.group(1) and abs(cy(g[1][0]) - cy(b)) < 0.8 * text_height), None)
        if g:
            g[1].append(b)
        else:
            groups.append([m.group(1), [b]])
    renamed = {}
    for title, row_boxes in groups:
        # Cases sans étiquette sur la même rangée (souvent cochées : la croix gêne l'OCR).
        x_min, x_max = min(b[0] for b in row_boxes), max(b[0] for b in row_boxes)
        step = 6 * row_boxes[0][2]
        row_boxes += [b for b, lab in labeled if not lab and b not in row_boxes
                      and abs(cy(b) - cy(row_boxes[0])) < 0.8 * text_height and x_min - step <= b[0] <= x_max + step]
        row_boxes.sort(key=lambda b: b[0])
        y = cy(row_boxes[0])
        text = " ".join(l["text"] for l in sorted(lines, key=lambda l: l["box"][0])
                        if abs((l["box"][1] + l["box"][3]) / 2 - y) < 0.8 * text_height)
        digits = re.findall(r"\d{1,2}", BOX_GLYPHS.sub(" ", text))
        names = digits if len(digits) == len(row_boxes) else [str(i + 1) for i in range(len(row_boxes))]
        for b, d in zip(row_boxes, names):
            renamed[b] = f"{title} {d}".strip()
    return [(b, renamed.get(b, lab)) for b, lab in labeled]


def _line_positions(mask: np.ndarray, axis: int, min_frac: float, joined: bool = False) -> list[int]:
    """Positions des traits d'un masque (horizontaux : axis=0 -> y ; verticaux : axis=1 -> x).
    Chaque trait est une composante assez longue ; sa position est sa moyenne (robuste à une légère pente).
    `joined` : un trait coupé en morceaux alignés (bandeau sombre qui traverse le tableau) compte pour la
    somme de ses morceaux."""
    n, lab, stats, cent = cv2.connectedComponentsWithStats(mask)
    length = stats[:, cv2.CC_STAT_WIDTH] if axis == 0 else stats[:, cv2.CC_STAT_HEIGHT]
    full = mask.shape[1] if axis == 0 else mask.shape[0]
    pieces = sorted((int(cent[i, 1] if axis == 0 else cent[i, 0]), int(length[i])) for i in range(1, n))
    if not joined:
        pieces = [(p, n_px) for p, n_px in pieces if n_px >= min_frac * full]
    groups: list[list[tuple[int, int]]] = []
    for p, n_px in pieces:
        if groups and p - groups[-1][-1][0] <= 8:
            groups[-1].append((p, n_px))
        else:
            groups.append([(p, n_px)])
    return [round(sum(p * n_px for p, n_px in g) / sum(n_px for _, n_px in g))
            for g in groups if sum(n_px for _, n_px in g) >= min_frac * full]


def table_grid(img: np.ndarray, region) -> tuple[list[int], list[int]]:
    """Traits d'un tableau : (positions y des lignes, positions x des colonnes), en coordonnées de la page.

    Un tableau coupé par des bandeaux sombres (« EXAMEN CLINIQUE » sur toute la largeur) n'a que des morceaux
    de traits verticaux : s'il manque des colonnes, on recolle les morceaux alignés.
    """
    x, y, w, h = region
    m = printed_mask(img[y:y + h, x:x + w]) * 255
    horiz = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, w // 8), 1)))
    vert = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 9)))
    vert = cv2.morphologyEx(vert, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(15, h // 8))))
    ys = [y + p for p in _line_positions(horiz, 0, 0.5)]
    xs = [x + p for p in _line_positions(vert, 1, 0.4)]
    if len(xs) < 3:
        xs = [x + p for p in _line_positions(vert, 1, 0.4, joined=True)]
    return ys, xs


def vertical_rules(img: np.ndarray, y0: int, y1: int, xs: list[int]) -> list[bool]:
    """Pour chaque x, y a-t-il un trait vertical entre y0 et y1 ? (cellule fusionnée = pas de trait)."""
    band = printed_mask(img[y0:y1]) if y1 > y0 else None
    out = []
    for x in xs:
        if band is None:
            out.append(False)
            continue
        cols = band[:, max(0, x - 3):x + 4]
        out.append(bool(cols.size) and float(cols.max(axis=1).mean()) >= 0.6)
    return out


def ink_pixels(img: np.ndarray, box, blue_only: bool = False, bm: np.ndarray | None = None) -> int:
    """Pixels d'écriture dans une zone : stylo bleu, et (sauf `blue_only`) traits sombres hors traits imprimés longs."""
    x0, y0, x1, y1 = (max(0, int(v)) for v in box)
    crop = img[y0:y1, x0:x1]
    if crop.size == 0:
        return 0
    blue = bm[y0:y1, x0:x1] if bm is not None else blue_mask(crop)
    if blue_only:
        return int(blue.sum())
    dark = (crop.min(axis=2) < 110).astype(np.uint8)
    k = max(8, min(crop.shape[:2]) // 2)
    lines = cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (k, 1))) | \
        cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, k)))
    return int(((dark & (1 - lines)) | blue).sum())


def is_handwritten(img: np.ndarray, box, bm: np.ndarray) -> bool:
    """Ligne écrite au stylo bleu (voir `blue_map`). Un stylo noir n'est pas détecté ici."""
    x0, y0, x1, y1 = box
    crop = img[y0:y1, x0:x1]
    if crop.size == 0:
        return False
    ink = crop.min(axis=2) < 160
    return bool(ink.sum()) and bm[y0:y1, x0:x1][ink].mean() > 0.3


def blue_map(img: np.ndarray) -> np.ndarray:
    """Encre de stylo bleu sur toute la page, quel que soit l'éclairage.

    1. Balance des couleurs : le papier devient neutre (une photo sous lampe chaude rend tout rosé).
    2. Une encre est « bleue » si elle est nettement plus bleue que l'encre imprimée de cette même page
       (référence : le 30e centile des pixels sombres, surtout de l'imprimé).
    """
    f = img.astype(np.float32)
    flat = f.reshape(-1, 3)
    light = flat[flat.sum(axis=1) >= np.percentile(flat.sum(axis=1), 60)]
    paper = np.median(light, axis=0)
    bal = f * (paper.mean() / np.maximum(paper, 1))
    b, g, r = bal[..., 0], bal[..., 1], bal[..., 2]
    dark = bal.min(axis=2) < 0.75 * paper.mean()
    if dark.sum() < 50:
        return np.zeros(img.shape[:2], np.uint8)
    d = b - r
    base = np.percentile(d[dark], 30)
    return (dark & (d - base > 20)).astype(np.uint8)


MAX_UNREAD = 30    # zones relues au plus par la 2e passe OCR


def unread_ink(img: np.ndarray, boxes, text_height: float, bm: np.ndarray) -> list[tuple[tuple, bool]]:
    """Encre que l'OCR n'a pas lue : écriture ou imprimé hors des lignes trouvées (l'OCR rate parfois une
    ligne entière quand l'écriture touche le pointillé). Encre bleue et encre sombre à part : l'étiquette
    imprimée et la valeur manuscrite sont relues séparément. -> [(zone, encre bleue ?)]"""
    th = max(int(text_height), 8)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ink = cv2.adaptiveThreshold(gray, 1, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 2 * th + 1, 15)
    # Traits du formulaire (lignes, cadres) : retirés.
    k = 3 * th
    rules = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (k, 1))) | \
        cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, k)))
    ink = (ink & (1 - rules)) | bm
    pad = th // 4
    for x0, y0, x1, y1 in boxes:
        ink[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad] = 0
    ink[:th], ink[-th:], ink[:, :th], ink[:, -th:] = 0, 0, 0, 0     # bords de la photo : ombres, fond
    near_blue = blue_halo(bm)
    out = []
    for blue, part in ((True, ink & bm), (False, ink & (1 - near_blue))):
        merged = cv2.dilate(part, cv2.getStructuringElement(cv2.MORPH_RECT, (th, max(1, th // 4))))
        _, _, stats, _ = cv2.connectedComponentsWithStats(merged)
        for x, y, w, h, _ in stats[1:]:
            if 0.5 * th <= h <= 3 * th and w >= 1.5 * th and part[y:y + h, x:x + w].sum() >= 3 * th:
                out.append(((int(x), int(y), int(x + w), int(y + h)), blue))
    out.sort(key=lambda r: -(r[0][2] - r[0][0]) * (r[0][3] - r[0][1]))
    return out[:MAX_UNREAD]


def blue_halo(bm: np.ndarray) -> np.ndarray:
    """Encre bleue élargie de quelques pixels (le bord d'un trait bleu n'est pas toujours vu bleu)."""
    return cv2.dilate(bm, np.ones((7, 7), np.uint8))


def blue_blobs(img: np.ndarray, bm: np.ndarray, zone, min_ink: int) -> tuple[int, int, int, int] | None:
    """Écriture bleue dans une zone : les taches bleues assez grandes (les pixels bleus épars d'un texte
    imprimé ou d'un logo ne comptent pas), et surtout bleues (pas de l'encre sombre). -> cadre, ou None."""
    h, w = bm.shape
    x0, y0, x1, y1 = max(0, int(zone[0])), max(0, int(zone[1])), min(w, int(zone[2])), min(h, int(zone[3]))
    if x1 <= x0 or y1 <= y0:
        return None
    part = bm[y0:y1, x0:x1]
    n, lab, stats, _ = cv2.connectedComponentsWithStats(cv2.dilate(part, np.ones((3, 3), np.uint8)))
    keep = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= 30]
    if not keep:
        return None
    mask = np.isin(lab, keep) & (part > 0)
    if int(mask.sum()) < min_ink:
        return None
    ys, xs = np.nonzero(mask)
    bx0, by0, bx1, by1 = x0 + int(xs.min()), y0 + int(ys.min()), x0 + int(xs.max()) + 1, y0 + int(ys.max()) + 1
    dark = img[by0:by1, bx0:bx1].min(axis=2) < 160
    if not dark.any() or bm[by0:by1, bx0:bx1][dark].mean() < 0.5:
        return None
    return bx0, by0, bx1, by1
