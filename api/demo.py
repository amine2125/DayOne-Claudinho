"""Lecture de démonstration, pour une machine sans PaddleOCR ni Ollama (DAYONE_DEMO_EXTRACT=1).

Ne lit pas la photo : renvoie une sortie réelle de dayone.extract enregistrée dans
outputs/predictions/, choisie d'après le contenu de la photo (même photo -> même sortie).
Sert à faire tourner le tableau de bord et l'agent WhatsApp de bout en bout. Jamais en production.
"""

import copy
import hashlib
import json
from functools import lru_cache

from dayone.dataset import ROOT

PREDICTIONS = ROOT / "outputs" / "predictions"


@lru_cache
def _samples() -> tuple[dict, ...]:
    return tuple(json.loads(p.read_text(encoding="utf-8")) for p in sorted(PREDICTIONS.glob("*.json")))


def extract_page(source, use_model: bool = True, **_kw) -> dict:
    data = source if isinstance(source, bytes) else str(source).encode()
    samples = _samples()
    if not samples:
        raise RuntimeError("Mode démo : aucune sortie dans outputs/predictions/")
    pick = int(hashlib.sha256(data).hexdigest(), 16) % len(samples)
    return copy.deepcopy(samples[pick])
