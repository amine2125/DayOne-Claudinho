"""Modèle de vision local (Ollama, famille qwen3-vl). 100 % local : tout hôte distant est refusé."""

import json
import os
import re
from urllib.parse import urlparse

import cv2
import numpy as np

from dayone.normalize import fold

# Variante « instruct » : la variante par défaut réfléchit même avec think=False (lent, réponses vides).
DEFAULT_MODEL = os.environ.get("DAYONE_MODEL", "qwen3-vl:2b-instruct")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

ZONE_PROMPT = (
    "This image is a cropped field from a French handwritten medical form. Field: \"{label}\". "
    "Copy exactly the handwritten text you see, character by character, keeping the original spelling. "
    "Do not guess or complete. If nothing is written, answer EMPTY. If it cannot be read, answer ILLEGIBLE. "
    "Answer with the text only."
)


class NotLocalError(RuntimeError):
    pass


def _check_local(model: str) -> str:
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    name = urlparse(host if "://" in host else f"http://{host}").hostname or ""
    if name not in LOCAL_HOSTS:
        raise NotLocalError(f"OLLAMA_HOST doit être local (reçu : {name}).")
    if "cloud" in model.lower():
        raise NotLocalError(f"modèle cloud refusé : {model}")
    return host


def _client(model: str):
    import ollama

    return ollama.Client(host=_check_local(model))


def available(model: str = DEFAULT_MODEL) -> tuple[bool, str]:
    """Le serveur Ollama local répond-il, et le modèle est-il installé ?"""
    try:
        names = {m.model for m in _client(model).list().models}
    except NotLocalError as e:
        return False, str(e)
    except Exception:
        return False, "serveur Ollama injoignable (lancer `ollama serve`)"
    if model not in names:
        return False, f"modèle {model} absent (lancer `ollama pull {model}`)"
    return True, "ok"


def _png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("encodage PNG impossible")
    return buf.tobytes()


def _clean_answer(text: str) -> str:
    t = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip().strip('"').strip()
    return t.splitlines()[0].strip() if t else ""


def _same_text(a: str, b: str) -> bool:
    fa, fb = fold(a), fold(b)
    return bool(fa) and (fa == fb or (len(fa) > 3 and fa in fb))


def read_zones(crops: dict[str, np.ndarray], labels: dict[str, str], model: str = DEFAULT_MODEL) -> dict[str, str]:
    """{id: image} -> {id: texte lu}. 'EMPTY' et 'ILLEGIBLE' sont renvoyés tels quels. Décharge le modèle à la fin."""
    if not crops:
        return {}
    client = _client(model)
    out = {}
    try:
        for fid, img in crops.items():
            resp = client.chat(
                model=model,
                messages=[{"role": "user", "content": ZONE_PROMPT.format(label=labels[fid]), "images": [_png(img)]}],
                think=False,
                options={"temperature": 0, "num_ctx": 2048, "num_predict": 40},
                keep_alive="2m",
            )
            answer = _clean_answer(resp.message.content)
            # Un petit modèle recopie parfois l'étiquette du champ quand la zone est vide.
            out[fid] = "EMPTY" if _same_text(answer, labels[fid]) else answer
    finally:
        unload(model)
    return out


def read_page(img: np.ndarray, fields: list[tuple[str, str]], model: str = DEFAULT_MODEL) -> dict[str, str]:
    """Mode de secours (mise en page inconnue) : le modèle lit la page entière.

    Seuls les champs du schéma sont demandés (jamais nom, CIN, téléphone, adresse).
    """
    h, w = img.shape[:2]
    scale = 1280 / max(h, w)
    if scale < 1:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    keys = {fid: {"type": "string"} for fid, _ in fields}
    listing = "\n".join(f"- {fid}: {label}" for fid, label in fields)
    prompt = (
        "This is a photo of a page from a French handwritten maternal health register. "
        "Fill the JSON object with the handwritten value of each field below, copied exactly. "
        "Use \"\" if the field is absent from the page or empty. Never guess.\n" + listing
    )
    client = _client(model)
    try:
        resp = client.chat(
            model=model,
            messages=[{"role": "user", "content": prompt, "images": [_png(img)]}],
            format={"type": "object", "properties": keys, "required": list(keys)},
            think=False,
            options={"temperature": 0, "num_ctx": 8192},
        )
    finally:
        unload(model)
    try:
        data = json.loads(resp.message.content)
    except json.JSONDecodeError:
        return {}
    labels = dict(fields)
    return {k: str(v) for k, v in data.items()
            if k in keys and v not in (None, "") and not _same_text(str(v), labels[k])}


# Titre exact de la page accouchement : « date prévue d'accouchement » (autre page) ne doit pas compter.
TITLE_KEYWORDS = {"identification_antecedents": ("identification", "antecedent"),
                  "accouchement": ("deroulement de l accouchement",)}


def guess_page_type(img: np.ndarray, model: str = DEFAULT_MODEL) -> tuple[str | None, str]:
    """Mise en page inconnue : le modèle recopie le titre imprimé, puis on cherche des mots-clés.

    Renvoie (type de page V1 ou None, titre lu). Le choix ne dépend jamais du seul avis du modèle.
    """
    h, w = img.shape[:2]
    scale = 1024 / max(h, w)
    if scale < 1:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    prompt = "Copy the main printed title or section headings at the top of this form page. Answer with the text only."
    client = _client(model)
    try:
        resp = client.chat(model=model, messages=[{"role": "user", "content": prompt, "images": [_png(img)]}],
                           think=False, options={"temperature": 0, "num_ctx": 4096, "num_predict": 30})
    finally:
        unload(model)
    title = _clean_answer(resp.message.content)
    t = fold(title)
    hits = [pt for pt, words in TITLE_KEYWORDS.items() if any(w in t for w in words)]
    return (hits[0] if len(hits) == 1 else None), title


def unload(model: str = DEFAULT_MODEL) -> None:
    try:
        _client(model).generate(model=model, keep_alive=0)
    except Exception:
        pass
