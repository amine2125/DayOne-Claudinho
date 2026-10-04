"""Extraction d'une page : image -> champs (value, status, confidence).

Mode « gabarit » (mise en page des pages du registre reconnue) :
  1. alignement sur la page de référence (OpenCV) ;
  2. cases cochées : part d'encre dans la case (OpenCV) ;
  3. zones de texte vides : pas d'encre -> NOT_PROVIDED ;
  4. zones écrites : PaddleOCR (processus séparé, terminé avant l'étape 5) ;
  5. zones douteuses seulement : relecture par le modèle local, puis comparaison.
     Accord -> KNOWN ; désaccord ou lecteur unique -> NEEDS_REVIEW.
Mode « modèle seul » (mise en page inconnue, ex. photo d'un autre registre) :
  le modèle lit la page entière ; tous les champs sont NEEDS_REVIEW.

Le texte OCR brut n'est jamais écrit sur disque ni dans les logs : seuls les champs du schéma sortent.
"""

import re
import time
from pathlib import Path

from dayone import imaging, ocr, vlm
from dayone.normalize import comparable, fold, looks_doubtful, parse, restore_missing_letters, special_word
from dayone.schema import Field, load_schema, make_field, validate_prediction

THRESHOLD = 0.7          # sous ce seuil de confiance : NEEDS_REVIEW
SINGLE_READER_CAP = 0.6  # un seul lecteur (OCR ou modèle) : jamais KNOWN


class LayoutError(ValueError):
    pass


def extract_page(source, page_type: str | None = None, use_model: bool = True,
                 model: str = vlm.DEFAULT_MODEL, threshold: float = THRESHOLD,
                 source_name: str = "", progress=None) -> dict:
    """Lit une page. `source` : chemin, octets ou image BGR. `progress(message)` : suivi optionnel."""
    say = progress or (lambda _msg: None)
    t0 = time.perf_counter()
    img = imaging.load_image(source)

    say("Alignement sur le gabarit")
    al = imaging.align(img, page_type) if page_type else imaging.detect_page_type(img)
    timings = {"alignement_s": round(time.perf_counter() - t0, 1)}

    if not al.ok:
        if not page_type and use_model and vlm.available(model)[0]:
            say("Mise en page non reconnue : le modèle devine le type de page")
            page_type, title = vlm.guess_page_type(img, model)
            if not page_type:
                raise LayoutError(f"Page non traitée en V1 (titre lu : « {title} »). Seules les pages "
                                  "« Identification et antécédents » et « Accouchement » sont lues. "
                                  "Si c'est bien l'une d'elles, choisir le type de page dans la liste.")
        if not page_type:
            raise LayoutError("Mise en page non reconnue : choisir le type de page dans la liste, puis relancer.")
        return _model_only(img, page_type, use_model, model, threshold, source_name, timings, say)

    schema = load_schema(al.page_type)
    aligned = imaging.warp(img, al)
    ink = imaging.handwriting_mask(aligned, al.page_type)
    fields: dict[str, dict] = {}
    to_read: dict[str, Field] = {}

    for f in schema.fields:
        if f.kind == "checkbox":
            fields[f.id] = _checkbox(imaging.checkbox_ratio(ink, f))
        elif imaging.ink_pixels(ink, f) < imaging.MIN_INK_PIXELS:
            fields[f.id] = make_field(None, "NOT_PROVIDED", 0.95, source="encre")
        else:
            to_read[f.id] = f

    say(f"PaddleOCR sur {len(to_read)} zones écrites")
    t1 = time.perf_counter()
    crops = {fid: imaging.zone_crop(aligned, f) for fid, f in to_read.items()}
    ocr_out = ocr.read_zones(crops)
    timings["ocr_s"] = round(time.perf_counter() - t1, 1)

    doubtful = {}
    for fid, f in to_read.items():
        text, score = ocr_out.get(fid, ("", 0.0))
        field, is_doubtful = _from_ocr(f, text, score, imaging.ink_pixels(ink, f), threshold)
        fields[fid] = field
        if is_doubtful:
            doubtful[fid] = text

    model_used = False
    if doubtful and use_model:
        ok, why = vlm.available(model)
        if ok:
            say(f"Modèle {model} sur {len(doubtful)} zones à vérifier")
            t2 = time.perf_counter()
            answers = vlm.read_zones({fid: crops[fid] for fid in doubtful},
                                     {fid: to_read[fid].label for fid in doubtful}, model)
            timings["modele_s"] = round(time.perf_counter() - t2, 1)
            model_used = True
            for fid, ocr_text in doubtful.items():
                fields[fid] = _combine(to_read[fid], ocr_text, fields[fid], answers.get(fid, ""), threshold)
        else:
            say(f"Modèle indisponible ({why}) : zones douteuses laissées en NEEDS_REVIEW")

    _restore_words(schema, fields)
    _apply_not_applicable(schema, fields)
    timings["total_s"] = round(time.perf_counter() - t0, 1)
    pred = {
        "page_type": al.page_type,
        "source": source_name,
        "mode": "gabarit",
        "model": model if model_used else None,
        "threshold": threshold,
        "alignment_inliers": al.inliers,
        "timings": timings,
        "fields": {f.id: fields[f.id] for f in schema.fields},
    }
    validate_prediction(pred)
    return pred


def _checkbox(ratio: float) -> dict:
    if ratio >= imaging.CHECK_ON:
        return make_field(True, "KNOWN", 0.8 + min(ratio, 0.2), source="case")
    if ratio <= imaging.CHECK_OFF:
        # Case seule non cochée : on ne sait pas si c'est « non » ou « non renseigné ».
        return make_field(None, "NOT_PROVIDED", 0.95, source="case")
    return make_field(None, "NEEDS_REVIEW", 0.4, source="case")


def _from_ocr(f: Field, text: str, score: float, ink: int, threshold: float) -> tuple[dict, bool]:
    """Champ issu de l'OCR seul, et indique s'il faut le faire relire par le modèle."""
    if not text.strip():
        # De l'encre mais rien de lu : trace parasite ou écriture difficile.
        conf = 0.5 if ink < imaging.FAINT_INK_PIXELS else 0.3
        return make_field(None, "NEEDS_REVIEW", conf, source="ocr"), True
    word = special_word(text)
    if word == "unknown":
        return make_field(None, "UNKNOWN", score, source="ocr"), score < threshold
    if word == "illegible":
        return make_field(None, "ILLEGIBLE", score, source="ocr"), False
    value, format_ok = parse(f.kind, text)
    conf = score * (1.0 if format_ok else 0.6) * (0.6 if looks_doubtful(text) else 1.0)
    status = "KNOWN" if conf >= threshold and value is not None else "NEEDS_REVIEW"
    return make_field(value, status, conf, source="ocr"), status != "KNOWN"


def _combine(f: Field, ocr_text: str, ocr_field: dict, answer: str, threshold: float) -> dict:
    """Croise la lecture OCR et celle du modèle pour une zone douteuse."""
    a = answer.strip()
    if a.upper() == "EMPTY" or not a:
        if not ocr_text.strip():
            return make_field(None, "NOT_PROVIDED", 0.7, source="ocr+modele")
        return _review(ocr_field)
    if a.upper() == "ILLEGIBLE":
        if not ocr_text.strip():
            return make_field(None, "ILLEGIBLE", 0.6, source="ocr+modele")
        return _review(ocr_field)

    word = special_word(a)
    if word == "unknown":
        status = "UNKNOWN" if special_word(ocr_text) == "unknown" else "NEEDS_REVIEW"
        return make_field(None, status, 0.75 if status == "UNKNOWN" else 0.5, source="ocr+modele")
    value, format_ok = parse(f.kind, a)
    if ocr_text.strip() and comparable(f.kind, ocr_text) == comparable(f.kind, a):
        # Deux lectures indépendantes identiques.
        conf = max(ocr_field["confidence"], 0.85) if format_ok else 0.5
        status = "KNOWN" if conf >= threshold and value is not None else "NEEDS_REVIEW"
        return make_field(value, status, conf, source="ocr+modele")
    if f.kind == "text" and ocr_text.strip() and _ascii_letters(ocr_text) == _ascii_letters(a):
        # Mêmes lettres, seules les lettres accentuées ou les espaces diffèrent : on garde la lecture du modèle.
        return make_field(value, "KNOWN", max(min(ocr_field["confidence"], 0.9), threshold), source="ocr+modele")
    # Désaccord, ou modèle seul : on garde la lecture la plus plausible, à faire valider.
    if value is None or not format_ok:
        value = ocr_field["value"] if ocr_field["value"] is not None else value
    return make_field(value, "NEEDS_REVIEW", min(SINGLE_READER_CAP, 0.5 if ocr_text.strip() else SINGLE_READER_CAP),
                      source="ocr+modele")


def _ascii_letters(text: str) -> str:
    """Lettres sans accent, minuscules, sans espaces ni lettres accentuées : « Commer ante » -> « commerante »."""
    return "".join(c for c in text.lower() if c.isascii() and c.isalnum())


def _review(ocr_field: dict) -> dict:
    """Lectures contradictoires : on garde la valeur OCR, à faire valider."""
    return make_field(ocr_field["value"], "NEEDS_REVIEW", min(ocr_field["confidence"], 0.5), source="ocr+modele")


def _restore_words(schema, fields: dict) -> None:
    """Remet les lettres accentuées absentes de la page (« Commer ante » -> « Commerçante »), via le lexique.

    La lecture d'origine reste dans `valeur_lue`.
    """
    for f in schema.fields:
        value = fields[f.id]["value"]
        if f.kind != "text" or not isinstance(value, str) or value == "aucun":
            continue
        word = restore_missing_letters(value)
        if word:
            fields[f.id] = {**fields[f.id], "value": word, "valeur_lue": value}


def _apply_not_applicable(schema, fields: dict) -> None:
    """Champ vide dont la condition du formulaire est clairement fausse -> NOT_APPLICABLE."""
    for f in schema.fields:
        cond = f.applicable_if
        if not cond or fields[f.id]["status"] != "NOT_PROVIDED":
            continue
        if "any_checked" in cond:
            deps = [fields[d] for d in cond["any_checked"]]
            # Toutes les cases de la condition sont lues comme vides.
            false = all(d["status"] == "NOT_PROVIDED" for d in deps)
        else:
            dep = fields[cond["text_matches"]["field"]]
            false = dep["status"] == "KNOWN" and not re.search(cond["text_matches"]["pattern"], fold(str(dep["value"])))
            deps = [dep]
        if false:
            conf = min([fields[f.id]["confidence"]] + [d["confidence"] for d in deps])
            fields[f.id] = make_field(None, "NOT_APPLICABLE", conf, source="regle")


def _model_only(img, page_type, use_model, model, threshold, source_name, timings, say) -> dict:
    schema = load_schema(page_type)
    answers = {}
    if use_model:
        ok, why = vlm.available(model)
        if not ok:
            raise RuntimeError(f"Mise en page non reconnue et modèle indisponible : {why}")
        say(f"Mise en page non reconnue : lecture de la page entière par {model}")
        t = time.perf_counter()
        # Les cellules des grands tableaux sont rarement au même endroit sur un autre registre : non demandées.
        labels = [(f.id, f.label + (" (checkbox: answer x if checked)" if f.kind == "checkbox" else ""))
                  for f in schema.fields if not f.table]
        answers = vlm.read_page(img, labels, model)
        timings["modele_s"] = round(time.perf_counter() - t, 1)
    fields = {}
    for f in schema.fields:
        a = answers.get(f.id, "").strip()
        if f.kind == "checkbox":
            value = True if fold(a) in ("x", "oui", "yes", "true", "coche") else None
        else:
            value, _ = parse(f.kind, a) if a else (None, False)
        # Lecteur unique, sans gabarit : tout est à vérifier par un humain.
        fields[f.id] = make_field(value, "NEEDS_REVIEW", 0.4 if value is not None else 0.2, source="modele_seul")
    timings["total_s"] = round(sum(timings.values()), 1)
    pred = {
        "page_type": page_type, "source": source_name, "mode": "modele_seul",
        "model": model if use_model else None, "threshold": threshold, "alignment_inliers": 0,
        "timings": timings, "fields": fields,
    }
    validate_prediction(pred)
    return pred


def source_label(path) -> str:
    """Nom de fichier seul (jamais de chemin complet dans les sorties)."""
    return Path(path).name
