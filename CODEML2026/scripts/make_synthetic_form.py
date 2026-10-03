"""Génère une fiche synthétique (image + tokens OCR alignés) pour tester sans PaddleOCR.

    python scripts/make_synthetic_form.py
-> examples/synthetic_form.jpg   (à déposer dans la page de test)
-> examples/fake_tokens.json     (rejoué par REGISTRE_OCR_ENGINE=fake)

Chaque ligne couvre un cas de statut : CONNU, A_REVISER, ILLISIBLE, NON_FOURNI, INCONNU, PII...
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

OUT = Path(__file__).resolve().parents[1] / "examples"
W, H = 1600, 1150
FONT = cv2.FONT_HERSHEY_SIMPLEX
HAND = cv2.FONT_HERSHEY_SCRIPT_SIMPLEX

# (libellé, valeur écrite, confiance OCR simulée de la valeur, écrire la valeur à l'encre ?)
ROWS = [
    ("Nom :", "Fatima Exemple", 0.95, True),           # nominatif -> masqué, jamais extrait
    ("Tel :", "0612345678", 0.97, True),               # nominatif
    ("Date :", "14/03/2025", 0.96, True),
    ("Age :", "28 ans", 0.62, True),                   # confiance faible -> A_REVISER
    ("Poids :", "68 kg", 0.97, True),                  # CONNU
    ("TA :", "12/8", 0.95, True),                      # cmHg -> 120/80, avertissement
    ("Temperature :", "375", 0.93, True),              # virgule manquante supposée -> A_REVISER
    ("Age gestationnel :", "32 SA", 0.94, True),
    ("Hauteur uterine :", None, 0.0, True),            # gribouillis non lu -> ILLISIBLE
    ("BCF :", None, 0.0, False),                       # zone vide -> NON_FOURNI
    ("VIH :", "neg", 0.96, True),
    ("Syphilis :", "?", 0.90, True),                   # INCONNU
    ("Hepatite C :", "negatif", 0.95, True),
    ("Groupe sanguin :", "O+", 0.92, True),
    ("Accouchement :", "VB", 0.91, True),
    ("Observations :", "RAS", 0.94, True),
]


def main() -> None:
    img = np.full((H, W, 3), 250, np.uint8)
    tokens = []
    cv2.putText(img, "REGISTRE CPN - FICHE SYNTHETIQUE", (60, 60), FONT, 1.1, (40, 40, 40), 2, cv2.LINE_AA)
    tokens.append({"text": "REGISTRE CPN - FICHE SYNTHETIQUE", "conf": 0.98, "box": [60, 30, 700, 70]})
    y = 120
    for label, value, conf, ink in ROWS:
        (lw, lh), _ = cv2.getTextSize(label, FONT, 0.9, 2)
        cv2.putText(img, label, (60, y), FONT, 0.9, (30, 30, 30), 2, cv2.LINE_AA)
        tokens.append({"text": label, "conf": 0.98, "box": [60, y - lh - 4, 60 + lw, y + 6]})
        cv2.line(img, (420, y + 8), (1100, y + 8), (170, 170, 170), 1)
        if value is not None:
            (vw, vh), _ = cv2.getTextSize(value, HAND, 1.3, 2)
            cv2.putText(img, value, (440, y), HAND, 1.3, (120, 40, 20), 2, cv2.LINE_AA)
            tokens.append({"text": value, "conf": conf, "box": [440, y - vh - 4, 440 + vw, y + 8]})
        elif ink:
            rng = np.random.default_rng(3)
            pts = np.stack([np.linspace(440, 640, 25), y - 12 + rng.normal(0, 9, 25)], axis=1).astype(np.int32)
            cv2.polylines(img, [pts], False, (120, 40, 20), 3, cv2.LINE_AA)
        y += 62
    cv2.putText(img, "G3P2", (1200, 300), HAND, 1.5, (120, 40, 20), 2, cv2.LINE_AA)   # trouvé par motif
    tokens.append({"text": "G3P2", "conf": 0.9, "box": [1200, 268, 1320, 308]})

    OUT.mkdir(exist_ok=True)
    cv2.imwrite(str(OUT / "synthetic_form.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    (OUT / "fake_tokens.json").write_text(json.dumps(tokens, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"OK -> {OUT / 'synthetic_form.jpg'} ({len(tokens)} tokens)")


if __name__ == "__main__":
    main()
