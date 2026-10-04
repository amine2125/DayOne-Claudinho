"""Lecture d'une fiche quelconque, sans gabarit, « OCR d'abord » : image -> champs (label, value, status, confidence).

  1. Photo redressée (feuille détectée), mise à la taille de travail.
  2. PaddleOCR lit toute la page (lignes de texte + positions), dans un processus séparé.
     Pas assez de texte -> refus.
  3. Les champs sont construits à partir de la position du texte (aucune position fixe) :
     - tableaux (grille de traits, OpenCV) : cellule = « ligne | colonne » ;
     - cases à cocher (carré imprimé, OpenCV) : étiquette = texte voisin, cochée = encre dedans ;
     - « Étiquette : valeur » sur une même ligne ;
     - écriture isolée (stylo bleu, ou chiffres) : rattachée au texte imprimé juste à gauche.
     Une étiquette vient toujours du texte imprimé lu par l'OCR : elle ne peut pas être inventée.
  4. Données personnelles (nom, conjoint, CIN, téléphone, adresse) : retirées des champs et masquées
     en noir. Seule l'image masquée est affichée ou envoyée au modèle.
  5. Le modèle local confirme que c'est une fiche de santé (image masquée).
  6. Valeur sûre (bon score OCR, bon format) -> KNOWN. Valeur douteuse, encre sans texte lu, ou écriture
     rattachée à aucun champ (oubli possible) : le modèle relit un petit morceau d'image.
     Accord -> KNOWN ; désaccord ou un seul lecteur -> NEEDS_REVIEW. Un oubli reste toujours à vérifier.

Le texte OCR brut ne quitte jamais la mémoire : seuls les champs retenus sortent.
"""

import re
import time
from pathlib import Path
from statistics import median

import numpy as np

from dayone import imaging, ocr, page, vlm
from dayone.normalize import ARABIC, comparable, fold, infer_kind, parse, restore_missing_letters, special_word
from dayone.privacy import is_personal, is_record_label, looks_like_cin, redact, same_identifier
from dayone.schema import make_field, validate_prediction
from dayone.vocabulary import known_word, label_reason

THRESHOLD = 0.7          # sous ce seuil de confiance : NEEDS_REVIEW
SURE_SCORE = 0.9         # score OCR au-dessus duquel une valeur au bon format n'est pas relue
MIN_TEXT_LINES = 8       # en dessous : pas une fiche
MIN_INK = 25             # pixels d'encre : en dessous, une zone sans texte lu est vide
SINGLE_READER_CAP = 0.6  # un seul lecteur : jamais KNOWN
# Sans modèle : une fiche de santé contient au moins quelques mots du domaine (français, anglais, arabe).
HEALTH_PREFIXES = ("grossess", "accouch", "naissan", "vaccin", "gestat", "partum", "sante", "medic", "patient",
                   "nouveau", "poids", "tension", "consult", "hopital", "maternit", "obstetr", "diabet", "hta",
                   "vih", "syphil", "hepatit", "parturi", "allait", "cesarien",
                   "pregnan", "deliver", "birth", "health", "hospital", "antenatal", "prenatal", "postnatal",
                   "postpartum", "midwife", "newborn", "gravid", "obstetric", "caesarean", "breastfeed", "maternal",
                   "حمل", "الحمل", "حامل", "الحامل", "ولاد", "الولاد", "صح", "الصح", "مستشف", "المستشف", "طب", "الطب",
                   "رضيع", "الرضيع", "مولود", "المولود", "نفاس", "النفاس", "قابل", "القابل", "لقاح", "تلقيح",
                   "التلقيح", "ضغط", "الضغط")
MIN_HEALTH_WORDS = 3
MIN_REGISTRY_WORDS = 5
# Étiquettes qui attendent un nom de lieu (« Lieu » seul : maison / hôpital, pas une ville).
PLACE_LABEL = re.compile(r"\b(region|province|prefecture|ville|city|wilaya|commune)\b|الجه[ةه]|اقليم|عمال[ةه]|مدين[ةه]")


class NotAFormError(ValueError):
    pass


def extract_page(source, use_model: bool = True, model: str = vlm.DEFAULT_MODEL,
                 threshold: float = THRESHOLD, source_name: str = "", progress=None) -> dict:
    """Lit une fiche. `source` : chemin, octets ou image BGR. `progress(message)` : suivi optionnel."""
    say = progress or (lambda _msg: None)
    t0 = time.perf_counter()
    img = page.prepare(page.load_image(source))

    say("Lecture du texte (PaddleOCR)")
    lines = ocr.read_page(img)
    timings = {"ocr_s": round(time.perf_counter() - t0, 1)}
    if len(lines) < MIN_TEXT_LINES:
        raise NotAFormError("Presque aucun texte sur cette image : ce n'est pas une fiche à lire.")

    bm = imaging.blue_map(img)
    lines = _split_mixed(img, lines, bm)
    for i, l in enumerate(lines):
        l["i"] = i
        l["hand"] = imaging.is_handwritten(img, l["box"], bm)
    # Hauteur de référence : le texte imprimé (une écriture à la main, souvent grande, la fausserait).
    printed = [l["box"][3] - l["box"][1] for l in lines if not l["hand"]]
    th = median(printed or [l["box"][3] - l["box"][1] for l in lines])
    # Page écrite au stylo bleu : l'encre suffit à distinguer l'écriture de l'imprimé.
    blue_page = int(bm.sum()) > 1500
    used: set[int] = set()
    candidates: list[dict] = []   # {label, text, score, box (zone de la valeur)}
    fields: list[dict] = []
    dropped = {"personnels": 0}

    say("Tableaux, cases à cocher, étiquettes")
    tables = []
    for region in imaging.find_tables(img):
        cells = _table_cells(img, region, lines, used)
        if cells is not None:
            tables.append(region)
            candidates += cells
    boxes = _checkboxes(img, lines, th, tables, bm)
    for _, _, label_lines, _ in boxes:
        used.update(label_lines)
    box_fields, n_personal = _checkbox_fields(img, boxes, th, bm)
    fields += box_fields
    dropped["personnels"] += n_personal
    candidates += _colon_fields(img, lines, used, th, tables, blue_page, bm)
    candidates += _orphan_values(lines, used, th, tables, blue_page)
    if blue_page:
        candidates += _ink_fields(img, lines, used, th, tables, bm, [b[0] for b in boxes])

    # Données personnelles : masquées en noir avant tout usage de l'image (affichage, modèle).
    zones, personal, ids = _personal_zones(img, lines, candidates, used, th)
    # Oublis : écriture lue par l'OCR mais rattachée à aucun champ. Elle sort quand même, à vérifier.
    loose = _loose_handwriting(lines, used, th, zones)
    safe = redact(img, zones)

    t1 = time.perf_counter()
    model_ok = use_model and vlm.available(model)[0]
    if model_ok:
        say("Vérification : est-ce bien une fiche de santé ?")
        if not vlm.is_health_form(safe, model):
            vlm.unload(model)
            raise NotAFormError("Cette image n'est pas une fiche ou un registre de santé.")
    elif not _health_words(lines):
        raise NotAFormError("Cette image ne ressemble pas à une fiche de santé (aucun mot du domaine lu).")

    doubtful, places = [], []
    for c, is_pers in zip(candidates, personal):
        if is_pers:
            dropped["personnels"] += 1
            continue
        field, needs_model = _from_ocr(img, c, threshold, blue_page, bm)
        if field["kind"] == "text" and PLACE_LABEL.search(fold(c["label"])):
            places.append((field, c))
        if c.get("hand_label"):
            field["raison"] = "etiquette_manuscrite"
            if field["status"] == "KNOWN":
                field.update(status="NEEDS_REVIEW", confidence=min(field["confidence"], SINGLE_READER_CAP))
        fields.append(field)
        if needs_model:
            doubtful.append((field, c))
    for c in loose:
        field, _ = _from_ocr(img, c, threshold, blue_page, bm)
        field.update(_loose_cap(field), raison="non_rattache")
        fields.append(field)
        doubtful.append((field, c))
    if (doubtful or places) and model_ok:
        say(f"Relecture de {len(doubtful)} valeur(s) douteuse(s) ou non rattachée(s) par {model}")
        try:
            for field, c in doubtful:
                answer = vlm.read_value(_crop(safe, _with_label(c), th), c["label"], model)
                field.update(_combine(field, c, answer, threshold))
                c["answer"] = answer
                if c.get("loose"):
                    field.update(_loose_cap(field))
                if is_personal(field["label"], str(field["value"] or "")) or is_personal("", answer):
                    field["drop"] = True
                    zones.append(c["box"])
                    ids.append(answer)
            for field, c in places:
                if isinstance(field["value"], str) and not field.get("drop"):
                    _place(field, vlm.suggest_place(_crop(safe, c["box"], th), c["label"],
                                                    [c["text"], c.get("answer", ""), field["value"]], model))
        finally:
            vlm.unload(model)
    elif model_ok:
        vlm.unload(model)
    # N° de fiche relu par le modèle, identique à un CIN vu sur la page : identifiant direct, retiré et masqué.
    for field, c in doubtful:
        if is_record_label(c["label"]) and not field.get("drop") and _copies_id(str(field["value"] or ""), ids):
            field["drop"] = True
            dropped["personnels"] += 1
            zones.append(c["box"])
    timings["modele_s"] = round(time.perf_counter() - t1, 1)

    fields = [f for f in fields if not f.pop("drop", False)]
    for f in fields:
        _restore(f)
        _flag(f)
    fields = _dedupe(fields)
    timings["total_s"] = round(time.perf_counter() - t0, 1)
    pred = {
        "source": source_name,
        "title": _title(lines, img, zones),
        "mode": "ocr+verification",
        "model": model if model_ok else None,
        "threshold": threshold,
        "timings": timings,
        "ignores": dropped,
        "zones_masquees": [[int(v) for v in z] for z in zones],
        "fields": fields,
    }
    validate_prediction(pred)
    return pred


# ---------------- Construction des champs à partir du texte ----------------

def _is_title(text: str) -> bool:
    """Titre ou en-tête de section (« ET DU POST PARTUM ») : plusieurs mots, tout en majuscules."""
    letters = [c for c in text if c.isalpha()]
    return len(text.split()) >= 2 and len(letters) >= 6 and all(c.isupper() for c in letters)


def _split_mixed(img, lines: list[dict], bm) -> list[dict]:
    """L'OCR lit souvent l'étiquette imprimée et l'écriture bleue d'un seul bloc (« Province El Jadida ») :
    on coupe la ligne là où commence l'encre bleue (là où elle finit, en arabe). Rien ne change au stylo
    noir (pas de bleu)."""
    out = []
    for l in lines:
        x0, y0, x1, y1 = l["box"]
        cols = bm[y0:y1, x0:x1].sum(axis=0)
        blue_x = np.nonzero(cols)[0]
        t = l["text"]
        if len(blue_x) < 5 or len(t) < 4:
            out.append(l)
            continue
        rtl = _rtl(t)
        # Étiquette à gauche et écriture à droite ; en arabe, l'inverse.
        start = x0 + int(blue_x[-1]) + 1 if rtl else x0 + int(blue_x[0])
        label_share = (x1 - start) / max(x1 - x0, 1) if rtl else (start - x0) / max(x1 - x0, 1)
        blue_share = (cols[:start - x0] if rtl else cols[start - x0:]).astype(bool).mean()
        if not (0.2 <= label_share <= 0.85 and blue_share > 0.3):
            out.append(l)
            continue
        colon = re.search(r"[:;]", t)
        if colon:
            k = colon.end()                  # l'étiquette imprimée finit aux deux-points
        else:
            # Sinon, coupure proportionnelle, ramenée à l'espace le plus proche.
            k = round(label_share * len(t))
            spaces = [i for i, ch in enumerate(t) if ch == " "]
            if spaces:
                near = min(spaces, key=lambda i: abs(i - k))
                if abs(near - k) <= 3:
                    k = near + 1
        label, value = t[:k].strip(), t[k:].strip()
        if len(label) < 2 or len(value) < (1 if colon else 2):
            out.append(l)
            continue
        label_box, value_box = ((start, y0, x1, y1), (x0, y0, start, y1)) if rtl else \
            ((x0, y0, start, y1), (start, y0, x1, y1))
        out.append({**l, "text": label, "box": label_box})
        out.append({**l, "text": value, "box": value_box})
    return out


def _center(box) -> tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def _inside(box, region) -> bool:
    cx, cy = _center(box)
    x, y, w, h = region
    return x <= cx <= x + w and y <= cy <= y + h


def _join(ls: list[dict]) -> tuple[str, float]:
    ls = sorted(ls, key=lambda l: (round(l["box"][1] / 15), l["box"][0]))
    text = " ".join(l["text"] for l in ls).strip()
    return text, (min(l["score"] for l in ls) if ls else 0.0)


def _table_cells(img, region, lines, used) -> list[dict] | None:
    """Cellules d'un tableau -> candidats « ligne | colonne ». None si la grille n'est pas un tableau."""
    ys, xs = imaging.table_grid(img, region)
    if len(ys) < 3 or len(xs) < 3:
        return None
    grid = [[[] for _ in range(len(xs) - 1)] for _ in range(len(ys) - 1)]
    for l in lines:
        if not _inside(l["box"], region):
            continue
        cx, cy = _center(l["box"])
        r = next((k for k in range(len(ys) - 1) if ys[k] <= cy < ys[k + 1]), None)
        c = next((k for k in range(len(xs) - 1) if xs[k] <= cx < xs[k + 1]), None)
        if r is not None and c is not None:
            grid[r][c].append(l)
            used.add(l["i"])
    header = [_join(grid[0][c])[0] for c in range(len(xs) - 1)]
    data_rows = range(1, len(ys) - 1)
    # Première colonne = étiquettes de ligne s'il y a plusieurs lignes de données et qu'elle n'est pas manuscrite.
    first_col_hand = any(l["hand"] for r in data_rows for l in grid[r][0])
    row_labels = len(data_rows) >= 2 and not first_col_hand
    out = []
    for r in data_rows:
        row_label = _join(grid[r][0])[0] if row_labels else ""
        for c in range(1 if row_labels else 0, len(xs) - 1):
            col = header[c]
            if not col and not row_label:
                continue
            label = f"{row_label} | {col}" if row_label and col else (col or row_label)
            text, score = _join(grid[r][c])
            box = (xs[c] + 3, ys[r] + 3, xs[c + 1] - 3, ys[r + 1] - 3)
            out.append({"label": label.strip(" :"), "text": text, "score": score, "box": box})
    return out


def _checkboxes(img, lines, th, tables, bm=None):
    """Cases hors tableaux : (case, étiquette, lignes OCR de l'étiquette, intitulé du groupe ou "")."""
    boxes = [b for b in imaging.find_checkboxes(img, th, bm)
             if not any(_inside((b[0], b[1], b[0] + b[2], b[1] + b[3]), t) for t in tables)]
    out = []
    for box, label in imaging.label_checkboxes(boxes, lines, th, img):
        if len(label) < 2 and not label.isdigit():
            continue
        bx, by, bw, bh = box
        cy = by + bh / 2
        # Lignes OCR qui portent l'étiquette : sur la rangée de la case, juste à droite (ou à gauche).
        near = [l["i"] for l in lines if abs(_center(l["box"])[1] - cy) < 0.7 * th
                and -bw <= l["box"][0] - bx <= 4 * th + bw]
        head = _group_heading(box, lines, th)
        if head is not None:
            near.append(head["i"])
        out.append([box, label, near, head["text"].split(":")[0].strip() if head is not None else ""])
    # Rangées suivantes d'un même groupe (« CSCA ☐ CSUA ☐ » sous « DR ☐ CSC ☐ CSU ☐ ») : même intitulé
    # que la case alignée juste au-dessus.
    out.sort(key=lambda o: o[0][1])
    for o in out:
        if o[3]:
            continue
        (bx, by, bw, bh) = o[0]
        above = [a for a in out if a[3] and 0 < by - a[0][1] <= 2.2 * th and abs(bx - a[0][0]) <= 2 * th]
        if above:
            o[3] = max(above, key=lambda a: a[0][1])[3]
    # Rangée numérotée sans intitulé à deux-points (« VAT □1 □2 ») : le titre de la rangée sert d'intitulé.
    for o in out:
        m = re.fullmatch(r"(.+?)\s+(\d{1,2})", o[1])
        if not o[3] and m and sum(re.fullmatch(rf"{re.escape(m.group(1))}\s+\d{{1,2}}", a[1]) is not None
                                  for a in out) >= 2:
            o[3] = m.group(1)
    # La ligne qui porte l'intitulé sur la rangée (« VAT: X1 ») appartient au groupe : pas un autre champ.
    for o in out:
        if o[3]:
            cy = o[0][1] + o[0][3] / 2
            o[2] += [l["i"] for l in lines if abs(_center(l["box"])[1] - cy) < 0.7 * th
                     and l["box"][0] < o[0][0] and fold(l["text"]).startswith(fold(o[3]))]
    return [tuple(o) for o in out]


def _checkbox_fields(img, boxes, th, bm) -> tuple[list[dict], int]:
    """Cases d'un même groupe -> un seul champ : « Mode de la couverture = Fixe ». Case seule -> oui/vide."""
    groups: dict[str, list] = {}
    for box, label, _, head in boxes:
        groups.setdefault(fold(head) if head else f"#{id(box)}", []).append((box, label, head))
    fields, n_personal = [], 0
    for members in groups.values():
        head = members[0][2]
        if len(members) == 1:
            box, label, _ = members[0]
            if head and not set(fold(label).split()) <= set(fold(head).split()) | {"a", "de", "la"}:
                label = f"{head} | {label}"
            elif head:
                label = head
            if is_personal(label):
                n_personal += 1
                continue
            fields.append(_box_field(label, imaging.mark_ratio(img, box, bm)))
            continue
        if is_personal(head):
            n_personal += len(members)
            continue
        options = []
        for box, label, _ in _reading_order(members, th):
            opt = label[len(head):].strip(" :|") if fold(label).startswith(fold(head)) else label
            options.append((opt or label, imaging.check_state(imaging.mark_ratio(img, box, bm))))
        fields.append(_group_field(head, options))
    return fields, n_personal


def _group_heading(box, lines, th):
    """Intitulé d'un groupe de cases : texte imprimé finissant par « : », sans valeur, à gauche sur la même
    rangée ou juste au-dessus (« Mode de la couverture : » au-dessus de « Fixe ☒ Mobile ☐ »).
    En arabe : à droite des cases, et le « : » (souvent perdu par l'OCR) n'est exigé que sur la même rangée."""
    bx, by, bw, bh = box
    cy = by + bh / 2
    best = None
    for l in lines:
        t = l["text"].strip()
        if l["hand"]:
            continue
        rtl = _rtl(t)
        colon = bool(re.search(r"[A-Za-zÀ-ÿ\u0621-\u064a]{3}[^:]*:\s*$", t) or (rtl and re.match(r"\s*:", t)))
        if rtl:
            if l["box"][2] < bx + bw:
                continue
        elif not colon or l["box"][0] > bx:
            continue
        ly = _center(l["box"])[1]
        # Écriture juste après l'intitulé (à droite, ou à gauche en arabe) : c'est un champ « étiquette : valeur ».
        if any(m["hand"] and abs(_center(m["box"])[1] - ly) < 0.6 * th
               and (m["box"][2] <= l["box"][0] + th if rtl else m["box"][0] >= l["box"][2] - th) for m in lines):
            continue
        dy = cy - ly
        same_row = abs(dy) < 0.6 * th and colon and (l["box"][0] >= bx + bw if rtl else l["box"][2] <= bx)
        # Au-dessus : seulement un intitulé seul sur sa ligne (« Gestation : 4 » est un champ, pas un intitulé).
        alone = not any(m is not l and abs(_center(m["box"])[1] - ly) < 0.6 * th
                        and -th <= (l["box"][0] - m["box"][2] if rtl else m["box"][0] - l["box"][2]) <= 4 * th
                        for m in lines)
        above = 0.6 * th <= dy <= 2.6 * th and alone
        if same_row or above:
            score = abs(dy) + (0 if same_row else th)
            if best is None or score < best[0]:
                best = (score, l)
    return best[1] if best else None


def _is_value_line(l: dict, blue_page: bool) -> bool:
    """Ligne qui peut être une valeur écrite à la main. Sur une page au stylo bleu, seul le bleu compte
    (plus les nombres, dates, poids…) ; au stylo noir, on ne peut pas distinguer : tout compte."""
    t = l["text"]
    digits, letters = sum(c.isdigit() for c in t), sum(c.isalpha() for c in t)
    return l["hand"] or not blue_page or digits > letters


def _rtl(text: str) -> bool:
    """Texte surtout en arabe : écrit de droite à gauche, la valeur est à gauche de l'étiquette."""
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(bool(ARABIC.match(c)) for c in letters) >= len(letters) / 2


def _label_part(l: dict) -> tuple[str, str] | None:
    """« Étiquette : suite » (l'OCR lit parfois « ; ») -> (étiquette, suite). Imprimée ou écrite au stylo :
    une étiquette ajoutée à la main par la sage-femme (« Poids : 62 kg ») est lue aussi, puis à vérifier."""
    m = re.match(r"\s*([^:;]*?[A-Za-zÀ-ÿ\u0621-\u064a]{2}[^:;]*?)\s*[:;](.*)", l["text"])
    if not m:
        return None
    return m.group(1).strip(), m.group(2).strip()


def _colon_fields(img, lines, used, th, tables, blue_page: bool, bm=None) -> list[dict]:
    """« Étiquette : valeur ». Chaque morceau d'écriture va à l'étiquette la plus proche sur sa gauche
    (sur sa droite pour une étiquette en arabe), même rangée d'abord : une valeur ne peut pas glisser
    vers le champ du dessus ou du dessous."""
    free = [l for l in lines if l["i"] not in used and not any(_inside(l["box"], t) for t in tables)]
    labels = [(l, *lp) for l in free if (lp := _label_part(l))]
    # Écriture avec « : » juste après une étiquette imprimée de la même rangée : c'est sa valeur
    # (« Observations : pas de signes : RAS »), pas une étiquette manuscrite.
    printed = [l for l, _, _ in labels if not l["hand"]]
    labels = [(l, lab, after) for l, lab, after in labels if not l["hand"] or not any(
        abs(_center(p["box"])[1] - _center(l["box"])[1]) < 0.8 * th
        and -3 * th <= (p["box"][0] - l["box"][2] if _rtl(p["text"]) else l["box"][0] - p["box"][2]) <= 12 * th
        for p in printed)]
    label_ids = {l["i"] for l, _, _ in labels}
    attached = {l["i"]: [] for l, _, _ in labels}
    for v in free:
        if v["i"] in label_ids or not _is_value_line(v, blue_page):
            continue
        vy, vh = _center(v["box"])[1], v["box"][3] - v["box"][1]
        best = None
        for l, _, _ in labels:
            dy = abs(_center(l["box"])[1] - vy)
            dx = l["box"][0] - v["box"][2] if _rtl(l["text"]) else v["box"][0] - l["box"][2]
            if dy < 0.8 * max(th, vh) and -3 * th <= dx <= 12 * th:
                score = dy + 0.05 * dx
                if best is None or score < best[0]:
                    best = (score, l)
        if best:
            attached[best[1]["i"]].append(v)
    out = []
    for l, label, after in labels:
        rtl = _rtl(l["text"])
        parts = sorted(attached[l["i"]], key=lambda m: -m["box"][0] if rtl else m["box"][0])
        used.add(l["i"])
        used.update(m["i"] for m in parts)
        lx0, ly0, lx1, ly1 = l["box"]
        # Partie de la ligne OCR occupée par l'étiquette (à gauche, ou à droite en arabe).
        label_w = (lx1 - lx0) * (len(label) + 1) // max(len(l["text"]), 1)
        cut = lx1 - label_w if rtl else lx0 + label_w
        # Texte après « : » dans la même ligne OCR : valeur seulement s'il est écrit à la main
        # (encre bleue dans cette partie de la ligne), ou si l'on ne peut pas le savoir (stylo noir).
        after_blue = bm is not None and int((bm[ly0:ly1, lx0:cut] if rtl else bm[ly0:ly1, cut:lx1]).sum()) >= 40
        after_ok = after and (not blue_page or after_blue or l["hand"]
                              or sum(c.isdigit() for c in after) > sum(c.isalpha() for c in after))
        texts = ([after] if after_ok else []) + [m["text"] for m in parts]
        scores = ([l["score"]] if after_ok else []) + [m["score"] for m in parts]
        same_row = [m for m, _, _ in labels if m is not l and abs(_center(m["box"])[1] - _center(l["box"])[1]) < 0.6 * th]
        if rtl:
            x1 = cut
            x0 = min([m["box"][0] for m in parts], default=lx0 - 10 * th)
            x0 = max([x0, 0] + [m["box"][2] + 4 for m in same_row if m["box"][2] < lx0])
            box = (min(x0, x1 - 1), ly0, x1, ly1)
        else:
            x0 = cut
            x1 = max([m["box"][2] for m in parts], default=lx1 + 10 * th)
            x1 = min([x1, img.shape[1]] + [m["box"][0] - 4 for m in same_row if m["box"][0] > lx1])
            box = (x0, ly0, max(x1, x0 + 1), ly1)
        out.append({"label": label, "text": " ".join(texts).strip(), "score": min(scores) if scores else 0.0,
                    "box": tuple(int(v) for v in box), "label_box": l["box"], "hand_label": l["hand"]})
    return out


def _orphan_values(lines, used, th, tables, blue_page: bool) -> list[dict]:
    """Écriture restée seule : rattachée au texte imprimé juste à sa gauche (à sa droite s'il est en arabe)."""
    out = []
    rest = [l for l in lines if l["i"] not in used and not any(_inside(l["box"], t) for t in tables)]
    for v in rest:
        if v["i"] in used:
            continue
        t = v["text"]
        digit_led = sum(c.isdigit() for c in t) > sum(c.isalpha() for c in t)
        m = re.fullmatch(r"([A-Za-zÀ-ÿ]{1,4})\s*:?\s*(\d.*)", t)
        if not (v["hand"] or digit_led or m):
            continue
        cy = _center(v["box"])[1]
        row_title = [l for l in lines if abs(_center(l["box"])[1] - cy) < 0.6 * th and l["box"][2] <= v["box"][0]
                     and not l["hand"] and len(fold(l["text"])) > 3]
        if m and not v["hand"]:
            # « Le 12/05/2022 » lu d'un bloc : petit mot imprimé + valeur.
            label, text = m.group(1), m.group(2)
            if row_title:
                label = f"{min(row_title, key=lambda l: l['box'][0])['text'].strip(' :')} | {label}"
            used.add(v["i"])
            out.append({"label": label, "text": text, "score": v["score"], "box": v["box"], "label_box": v["box"]})
            continue
        near = [l for l in rest if l is not v and l["i"] not in used and not l["hand"]
                and abs(_center(l["box"])[1] - cy) < 0.6 * th and sum(c.isalpha() for c in l["text"]) >= 2
                and not _is_title(l["text"])]
        left = [l for l in near if 0 <= v["box"][0] - l["box"][2] <= 8 * th]
        # Étiquette en arabe : elle est à droite de la valeur.
        right = [l for l in near if _rtl(l["text"]) and 0 <= l["box"][0] - v["box"][2] <= 8 * th]
        if not left and not right:
            continue
        lab = max(left, key=lambda l: l["box"][2]) if left else min(right, key=lambda l: l["box"][0])
        label = lab["text"].strip(" :;")
        if len(fold(label)) <= 3 and row_title:
            # Étiquette très courte (« Le ») : préfixée par l'intitulé imprimé de la rangée.
            label = f"{min(row_title, key=lambda l: l['box'][0])['text'].strip(' :')} | {label}"
        used.update((v["i"], lab["i"]))
        out.append({"label": label, "text": t, "score": v["score"], "box": v["box"], "label_box": lab["box"]})
    return out


def _ink_fields(img, lines, used, th, tables, bm, checkboxes=()) -> list[dict]:
    """Étiquette imprimée suivie d'écriture bleue que l'OCR n'a pas lue (ou sans « : ») : champ sans texte,
    dont la zone d'encre sera relue par le modèle. Une écriture trop fine ou floue ne se perd donc pas.
    Les croix des cases à cocher ne comptent pas ; l'encre doit être surtout bleue (pas de l'imprimé sombre)."""
    h, w = img.shape[:2]
    bm = bm.copy()
    for bx, by, bw, bh in checkboxes:
        bm[max(0, by - bh // 2):by + bh + bh // 2, max(0, bx - bw // 2):bx + bw + bw // 2] = 0
    out = []
    for l in lines:
        t = l["text"].strip(" :;")
        if l["i"] in used or any(_inside(l["box"], tb) for tb in tables) or _is_title(t) \
                or sum(c.isalpha() for c in t) < 3 or (l["hand"] and label_reason(t) and not is_personal(t)):
            continue
        x0, y0, x1, y1 = l["box"]
        cy = _center(l["box"])[1]
        others = [m["box"] for m in lines if m is not l and not m["hand"] and abs(_center(m["box"])[1] - cy) < 0.6 * th]
        # Zone de la valeur : du côté de l'écriture (à droite ; à gauche en arabe), jusqu'au texte imprimé
        # suivant. Le cadre de l'étiquette en fait partie : l'OCR l'étend souvent sur une valeur qu'il n'a pas lue.
        if _rtl(t):
            zx0 = int(max([x0 - 12 * th, 0] + [b[2] for b in others if b[2] <= x0]))
            zone = (zx0, int(y0 - 0.3 * th), x1, int(y1 + 0.3 * th))
        else:
            zx1 = int(min([x1 + 12 * th, w] + [b[0] for b in others if b[0] >= x1]))
            zone = (x0, int(y0 - 0.3 * th), zx1, int(y1 + 0.3 * th))
        box = imaging.blue_blobs(img, bm, zone, min_ink=3 * MIN_INK)
        if box is None:
            continue
        used.add(l["i"])
        out.append({"label": t, "text": "", "score": 0.0, "box": box, "label_box": l["box"]})
    return out


# ---------------- Données personnelles ----------------

def _personal_zones(img, lines, candidates, used, th) -> tuple[list[tuple], list[bool], list[str]]:
    """Zones à masquer, pour chaque candidat : est-il personnel ?, et les identifiants vus sur la page.
    - valeur d'un champ personnel (« Nom du mari : … », « CIN : … »), jusqu'à l'étiquette suivante
      sur la rangée ou jusqu'au bord de la page (un nom déborde souvent du trait) ;
    - étiquette personnelle restée seule : elle et la zone à sa droite, de la même façon ;
    - écriture qui a la forme d'un identifiant (« CIN : A64185 », téléphone), où qu'elle soit ;
    - N° de fiche qui recopie un identifiant de la page (voir `_copies_id`) : identifiant direct, masqué."""
    h, w = img.shape[:2]
    records = [c["box"] for c in candidates if is_record_label(c["label"])]
    shaped = [l for l in lines if is_personal("", l["text"]) and not any(_inside(l["box"], b) for b in records)]
    flags = [is_personal(c["label"], c["text"]) for c in candidates]
    ids = [c["text"] for c, f in zip(candidates, flags) if f and is_personal("", c["text"])] + \
        [l["text"] for l in shaped]
    flags = [f or (is_record_label(c["label"]) and _copies_id(c["text"], ids)) for c, f in zip(candidates, flags)]
    raw = [l["box"] for l in shaped]
    for c, f in zip(candidates, flags):
        if not f:
            continue
        x0, y0, x1, y1 = c["box"]
        if "label_box" not in c:
            raw.append(c["box"])
        elif _rtl(c["label"]):
            raw.append((min(x0, _row_start(lines, c["label_box"], th)), y0, x1, y1))
        else:
            raw.append((x0, y0, max(x1, _row_end(lines, c["label_box"], th, w)), y1))
    for l in lines:
        # Même une ligne vue comme manuscrite : l'encre bleue de la valeur déborde souvent sur l'étiquette.
        if l["i"] in used or not is_personal(l["text"].split(":")[0]):
            continue
        x0, y0, x1, y1 = l["box"]
        if _rtl(l["text"]):
            raw.append((_row_start(lines, l["box"], th), y0, x1, y1))
        else:
            raw.append((x0, y0, _row_end(lines, l["box"], th, w), y1))
    zones = []
    pad = 0.4 * th
    for x0, y0, x1, y1 in raw:
        z = [x0 - pad, y0 - pad, x1 + pad, y1 + pad]
        # L'écriture déborde souvent la zone : on l'englobe entière.
        for m in lines:
            if (m["hand"] or is_personal("", m["text"])) and _inside(m["box"], (z[0], z[1], z[2] - z[0], z[3] - z[1])):
                z = [min(z[0], m["box"][0]), min(z[1], m["box"][1]), max(z[2], m["box"][2]), max(z[3], m["box"][3])]
        zones.append((max(0, int(z[0])), max(0, int(z[1])), min(w, int(z[2])), min(h, int(z[3]))))
    return zones, flags, ids


def _row_start(lines, box, th) -> int:
    """Bord gauche de la zone d'une valeur écrite à gauche de son étiquette (arabe) : étiquette précédente
    sur la rangée, sinon bord de la page."""
    cy = _center(box)[1]
    prv = [m["box"][2] for m in lines if not m["hand"] and m["box"][2] < box[0] - th
           and abs(_center(m["box"])[1] - cy) < 0.6 * th and _label_part(m)]
    return max(prv, default=-4) + 4


def _copies_id(value: str, ids: list[str]) -> bool:
    """N° de fiche qui recopie un identifiant : même valeur qu'un CIN ou un téléphone de la page, ou forme
    de CIN alors qu'un CIN est écrit sur la page (l'OCR lit souvent mal l'un des deux : prudence)."""
    return bool(value) and (any(same_identifier(value, v) for v in ids)
                            or (looks_like_cin(value) and any(looks_like_cin(v) for v in ids)))


def _row_end(lines, box, th, w) -> int:
    """Bord droit de la zone d'une valeur : étiquette imprimée suivante sur la rangée, sinon bord de la page."""
    cy = _center(box)[1]
    nxt = [m["box"][0] for m in lines if not m["hand"] and m["box"][0] > box[2] + th
           and abs(_center(m["box"])[1] - cy) < 0.6 * th and _label_part(m)]
    return min(nxt, default=w + 4) - 4


def _loose_handwriting(lines, used, th, zones) -> list[dict]:
    """Écriture lue par l'OCR mais rattachée à aucun champ : rien ne doit se perdre. Étiquette = texte imprimé
    le plus proche (à gauche sur la rangée, sinon juste au-dessus). Écriture personnelle -> masquée, pas extraite."""
    printed = [l for l in lines if not l["hand"] and sum(c.isalpha() for c in l["text"]) >= 2
               and not _is_title(l["text"])]
    out = []
    for v in lines:
        if v["i"] in used or not v["hand"] or sum(c.isalnum() for c in v["text"]) < 2:
            continue
        if any(_inside(v["box"], (z[0], z[1], z[2] - z[0], z[3] - z[1])) for z in zones):
            continue
        cx, cy = _center(v["box"])
        left = [l for l in printed if abs(_center(l["box"])[1] - cy) < 0.6 * th and l["box"][2] <= v["box"][0] + th]
        above = [l for l in printed if 0 < cy - _center(l["box"])[1] <= 3 * th
                 and l["box"][0] < v["box"][2] and l["box"][2] > v["box"][0]]
        lab = max(left, key=lambda l: l["box"][2]) if left else \
            min(above, key=lambda l: cy - _center(l["box"])[1]) if above else None
        label = lab["text"].split(":")[0].strip(" ;") if lab else ""
        used.add(v["i"])
        if is_personal(label, v["text"]):
            zones.append(v["box"])
            continue
        out.append({"label": label or "Écriture non rattachée", "text": v["text"], "score": v["score"],
                    "box": v["box"], "label_box": lab["box"] if lab else v["box"], "loose": True})
    return out


def _health_words(lines) -> bool:
    """Sans modèle : assez de mots médicaux, ou au moins un mot médical et plusieurs mots du registre."""
    words = {w for w in fold(" ".join(l["text"] for l in lines)).split() if not any(c.isdigit() for c in w)}
    medical = len({p for p in HEALTH_PREFIXES if any(w.startswith(p) for w in words)})
    registry = sum(len(w) >= 4 and known_word(w) for w in words)
    return medical >= MIN_HEALTH_WORDS or (medical >= 1 and registry >= MIN_REGISTRY_WORDS)


def _flag(f: dict) -> None:
    """Raison visible de chaque doute. Étiquette nouvelle ou mal lue (vocabulaire) : jamais KNOWN, même si
    la valeur est bien lue. Raisons : non_rattache, etiquette_douteuse, champ_nouveau, choix_nouveau,
    lieu_corrige, etiquette_manuscrite, valeur_douteuse."""
    reason, distrust = f.get("raison"), False
    if not reason:
        reason = label_reason(f["label"])
        distrust = reason is not None
    if not reason and f.get("options"):
        new = [o for o in f["options"] if not o.isdigit() and label_reason(o)]
        if new:
            reason = "choix_nouveau"
            distrust = any(o in str(f["value"] or "").split(", ") for o in new)
    if distrust and f["status"] == "KNOWN":
        f.update(status="NEEDS_REVIEW", confidence=min(f["confidence"], SINGLE_READER_CAP))
    if not reason and f["status"] == "NEEDS_REVIEW":
        reason = "valeur_douteuse"
    if reason:
        f["raison"] = reason


def _place(f: dict, suggestion: str) -> None:
    """Nom de lieu deviné par le modèle (« ElSaidida » -> « El Jadida ») : la lecture d'origine est gardée,
    et le champ reste toujours à vérifier (le modèle peut se tromper de ville)."""
    suggestion = suggestion.strip()
    if not suggestion or len(suggestion) > 60 or fold(suggestion) == fold(f["value"]) \
            or suggestion.upper() in ("EMPTY", "ILLEGIBLE") or is_personal("", suggestion):
        return
    f["valeur_lue"] = f["value"]
    f["value"] = suggestion
    f["raison"] = "lieu_corrige"
    if f["status"] == "KNOWN":
        f.update(status="NEEDS_REVIEW", confidence=min(f["confidence"], SINGLE_READER_CAP))


def _loose_cap(field: dict) -> dict:
    """Écriture non rattachée : l'étiquette est devinée par la position, donc jamais KNOWN."""
    status = "NEEDS_REVIEW" if field["status"] == "KNOWN" else field["status"]
    return make_field(field["value"], status, min(field["confidence"], SINGLE_READER_CAP), source=field["source"])


# ---------------- Statut et vérification ----------------

def _with_label(c: dict):
    """Zone de la valeur, étendue à son étiquette si elle est sur la même ligne : le modèle lit mieux
    l'écriture quand il voit de quel champ il s'agit (« Région : Casa-Settat »)."""
    x0, y0, x1, y1 = c["box"]
    lx0, ly0, lx1, ly1 = c.get("label_box", c["box"])
    same_row = min(y1, ly1) - max(y0, ly0) > 0.3 * min(y1 - y0, ly1 - ly0)
    if same_row and lx1 <= x0 + 5:
        return (min(x0, lx0), min(y0, ly0), x1, max(y1, ly1))
    return c["box"]


def _crop(img, box, th):
    """Petit morceau autour de la valeur : marge large sur les côtés, étroite en hauteur (pas la ligne voisine)."""
    x0, y0, x1, y1 = box
    mx, my = int(th), int(0.25 * th)
    return img[max(0, y0 - my):min(img.shape[0], y1 + my), max(0, x0 - mx):min(img.shape[1], x1 + mx)]


def _looks_odd(text: str) -> bool:
    """Lecture suspecte même avec un bon score : presque « RAS » (« KAS »), ou caractères parasites."""
    t = fold(text)
    if t != "ras" and len(t) == 3 and sum(a != b for a, b in zip(t, "ras")) == 1:
        return True
    if sum(c.isalnum() for c in text) < 2 and not text.strip().isdigit():
        return True                       # « ) », « - » : presque rien de lu
    return any(not (c.isalnum() or c in " /.,'-°:()+%") for c in text.strip())


def _from_ocr(img, c: dict, threshold: float, blue_page: bool = False, bm=None) -> tuple[dict, bool]:
    """Champ tel que lu par l'OCR, et faut-il le faire relire par le modèle ?"""
    kind = infer_kind(c["label"])
    base = {"label": c["label"], "kind": kind}
    # Reste du trait ou des deux-points collé devant la valeur (« :Teacher », « _Normal ») : retiré, mais
    # la première lettre a pu être mangée par le trait (« _Cycée » pour « Lycée ») -> relue par le modèle.
    text = re.sub(r"^[\s:;_.,]+(?=\S)", "", c["text"]) if re.search(r"\w", c["text"]) else c["text"]
    trimmed = text != c["text"].strip()
    if not text or re.fullmatch(r"[\s._…·]+|[\s._…·\-–—]{3,}", text):
        if imaging.ink_pixels(img, c["box"], blue_only=blue_page, bm=bm) >= MIN_INK:
            return {**base, **make_field(None, "NEEDS_REVIEW", 0.3, source="ocr")}, True   # encre sans texte lu
        return {**base, **make_field(None, "NOT_PROVIDED", 0.9, source="ocr")}, False
    word = special_word(text)
    if word == "unknown":
        return {**base, **make_field(None, "UNKNOWN", c["score"], source="ocr")}, c["score"] < SURE_SCORE
    if word == "illegible":
        return {**base, **make_field(None, "ILLEGIBLE", c["score"], source="ocr")}, False
    value, format_ok = parse(kind, text)
    if value is None:
        value = text
    odd = _looks_odd(text) or (trimmed and kind == "text")
    sure = c["score"] >= SURE_SCORE and format_ok and not odd
    conf = c["score"] * (1.0 if format_ok else 0.6) * (0.6 if odd else 1.0)
    status = "KNOWN" if sure and conf >= threshold else "NEEDS_REVIEW"
    return {**base, **make_field(value, status, conf, source="ocr")}, status != "KNOWN"


def _combine(field: dict, c: dict, answer: str, threshold: float) -> dict:
    """Croise la lecture OCR et celle du modèle pour une valeur douteuse."""
    kind, ocr_text, a = field["kind"], c["text"], answer.strip()
    if not a or a.upper() == "EMPTY" or fold(a) == fold(c["label"]):
        if not ocr_text:
            return make_field(None, "NOT_PROVIDED", 0.7, source="ocr+modele")
        return make_field(field["value"], "NEEDS_REVIEW", min(field["confidence"], 0.5), source="ocr+modele")
    if a.upper() == "ILLEGIBLE":
        status = "ILLEGIBLE" if not ocr_text else "NEEDS_REVIEW"
        return make_field(None if not ocr_text else field["value"], status, 0.5, source="ocr+modele")
    if special_word(a) == "unknown":
        return make_field(None, "UNKNOWN" if special_word(ocr_text) == "unknown" else "NEEDS_REVIEW", 0.5,
                          source="ocr+modele")
    value, format_ok = parse(kind, a)
    if value is None:
        value = a
    if ocr_text and comparable(kind, ocr_text) == comparable(kind, a):
        conf = max(field["confidence"], 0.85) if format_ok else 0.5
        return make_field(value, "KNOWN" if conf >= threshold else "NEEDS_REVIEW", conf, source="ocr+modele")
    if kind == "text" and ocr_text and _letters(ocr_text) == _letters(a):
        # Mêmes lettres : seules des lettres accentuées ou des espaces diffèrent.
        return make_field(value, "KNOWN", max(min(field["confidence"], 0.9), threshold), source="ocr+modele")
    # Désaccord, ou modèle seul : la lecture la plus plausible, à faire valider.
    if not format_ok and field["value"] is not None:
        value = field["value"]
    return make_field(value, "NEEDS_REVIEW", 0.5 if ocr_text else SINGLE_READER_CAP, source="ocr+modele")


def _letters(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isascii() and ch.isalnum())


def _reading_order(members, th):
    """Cases dans l'ordre de lecture : rangée par rangée, de gauche à droite."""
    rows = []
    for m in sorted(members, key=lambda m: m[0][1]):
        if rows and m[0][1] - rows[-1][0][0][1] < 0.6 * th:
            rows[-1].append(m)
        else:
            rows.append([m])
    return [m for row in rows for m in sorted(row, key=lambda m: m[0][0])]


def _group_field(head: str, options: list[tuple[str, bool | None]]) -> dict:
    """Groupe de cases : valeur = case(s) cochée(s). Aucune cochée -> NOT_PROVIDED ; case ambiguë -> à revoir."""
    checked = [o for o, state in options if state is True]
    value = ", ".join(checked) or None
    if any(state is None for _, state in options):
        status, conf = "NEEDS_REVIEW", 0.4
    else:
        status, conf = ("KNOWN", 0.9) if checked else ("NOT_PROVIDED", 0.9)
    kind = "sex" if infer_kind(head) == "sex" else "text"
    return {"label": head, "kind": kind, **make_field(value, status, conf, source="case"),
            "options": [o for o, _ in options]}


def _box_field(label: str, ratio: float) -> dict:
    """Case lue par OpenCV : cochée -> KNOWN true ; vide -> NOT_PROVIDED (jamais false) ; ambiguë -> à revoir."""
    base = {"label": label, "kind": "checkbox"}
    state = imaging.check_state(ratio)
    if state is True:
        return {**base, **make_field(True, "KNOWN", 0.9, source="case")}
    if state is False:
        return {**base, **make_field(None, "NOT_PROVIDED", 0.9, source="case")}
    return {**base, **make_field(None, "NEEDS_REVIEW", 0.4, source="case")}


def _restore(f: dict) -> None:
    """Lettres accentuées absentes de la page (« Commer ante » -> « Commerçante »), via le lexique."""
    if f["kind"] == "text" and isinstance(f["value"], str) and f["value"] != "aucun":
        word = restore_missing_letters(f["value"])
        if word:
            f["valeur_lue"] = f["value"]
            f["value"] = word


def _dedupe(fields: list[dict]) -> list[dict]:
    """Donne à chaque champ un identifiant unique (doublons exacts retirés)."""
    seen, out = set(), []
    for f in fields:
        key = (fold(f["label"]), str(f["value"]), f["status"])
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    ids = {}
    for f in out:
        base = re.sub(r"[^a-z0-9]+", "_", fold(f["label"])).strip("_")[:60] or "champ"
        ids[base] = ids.get(base, 0) + 1
        f["id"] = base if ids[base] == 1 else f"{base}_{ids[base]}"
    return [{"id": f.pop("id"), **f} for f in out]


def _title(lines: list[dict], img, zones) -> str:
    """Titre de la fiche : en haut de la page, texte imprimé sans « : » (une étiquette n'est pas un titre),
    de préférence en majuscules ; le plus grand. Jamais une écriture, une valeur ni une zone masquée."""
    top = [l for l in lines if l["box"][1] < 0.2 * img.shape[0] and len(l["text"]) > 3 and ":" not in l["text"]
           and not l.get("hand") and not is_personal(l["text"], l["text"])
           and not any(_inside(l["box"], (z[0], z[1], z[2] - z[0], z[3] - z[1])) for z in zones)]
    titles = [l for l in top if sum(c.isupper() for c in l["text"]) >= 6
              and not any(c.islower() for c in l["text"])] or top
    return max(titles, key=lambda l: l["box"][3] - l["box"][1])["text"] if titles else ""


def source_label(path) -> str:
    """Nom de fichier seul (jamais de chemin complet dans les sorties)."""
    return Path(path).name
