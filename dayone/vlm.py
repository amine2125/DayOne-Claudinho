"""Modèle de vision local (Ollama, famille qwen3-vl). 100 % local : tout hôte distant est refusé."""

import os
import re
from urllib.parse import urlparse

import cv2
import numpy as np

# Variante « instruct » : les autres variantes réfléchissent même avec think=False (lent, réponses vides).
# 4b : lit correctement une fiche inconnue (le 2b est trop faible), ~3,3 Go de mémoire.
DEFAULT_MODEL = os.environ.get("DAYONE_MODEL", "qwen3-vl:4b-instruct")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

GATE_PROMPT = (
    "Is this image a page of a medical or health record: a printed form or register with fields, "
    "possibly filled by hand? Answer only yes or no."
)
VALUE_PROMPT = (
    "This image is a small crop of a handwritten medical form (French, Arabic or English), around the field "
    "\"{label}\". Copy exactly the handwritten value you see, character by character, keeping the original "
    "spelling, language and script (do not translate). "
    "Ignore printed text. Do not guess or complete. If nothing is handwritten, answer EMPTY. "
    "If it cannot be read, answer ILLEGIBLE. Answer with the value only."
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


def _fit(img: np.ndarray, size: int) -> np.ndarray:
    scale = size / max(img.shape[:2])
    return cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else img


def is_health_form(img: np.ndarray, model: str = DEFAULT_MODEL) -> bool:
    resp = _client(model).chat(
        model=model, messages=[{"role": "user", "content": GATE_PROMPT, "images": [_png(_fit(img, 1024))]}],
        think=False, options={"temperature": 0, "num_ctx": 4096, "num_predict": 3}, keep_alive="5m",
    )
    return resp.message.content.strip().lower().startswith(("yes", "oui"))


def read_value(crop: np.ndarray, label: str, model: str = DEFAULT_MODEL) -> str:
    """Relecture d'une valeur douteuse sur un petit morceau d'image. 'EMPTY' / 'ILLEGIBLE' renvoyés tels quels."""
    resp = _client(model).chat(
        model=model,
        messages=[{"role": "user", "content": VALUE_PROMPT.format(label=label), "images": [_png(_fit(crop, 768))]}],
        think=False, options={"temperature": 0, "num_ctx": 2048, "num_predict": 40}, keep_alive="2m",
    )
    t = re.sub(r"<think>.*?</think>", "", resp.message.content, flags=re.S).strip().strip('"').strip()
    return t.splitlines()[0].strip() if t else ""


def unload(model: str = DEFAULT_MODEL) -> None:
    try:
        _client(model).generate(model=model, keep_alive=0)
    except Exception:
        pass
