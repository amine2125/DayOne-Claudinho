"""PaddleOCR sur les zones découpées, dans un processus séparé.

Le processus enfant est terminé avant tout appel au modèle : sa mémoire est rendue
(PaddleOCR et Ollama ne tournent jamais en même temps). Le texte lu ne passe que par
un tube en mémoire : il n'est jamais écrit sur disque ni dans les logs.
"""

import pickle
import subprocess
import sys

import numpy as np

from dayone.dataset import ROOT


def read_zones(crops: dict[str, np.ndarray]) -> dict[str, tuple[str, float]]:
    """{id: image} -> {id: (texte, score 0-1)}. Lance PaddleOCR une seule fois pour toutes les zones."""
    if not crops:
        return {}
    proc = subprocess.run(
        [sys.executable, "-m", "dayone.ocr"],
        input=pickle.dumps(crops), capture_output=True, cwd=ROOT,
    )
    if proc.returncode != 0:
        # stderr de Paddle ne contient pas le texte lu ; on n'en garde que la fin.
        raise RuntimeError("PaddleOCR a échoué : " + proc.stderr.decode(errors="ignore")[-500:])
    return pickle.loads(proc.stdout)


def _worker() -> None:
    import contextlib
    import os

    crops = pickle.loads(sys.stdin.buffer.read())
    # Paddle écrit des messages sur stdout : on les envoie vers stderr pour garder stdout propre.
    with contextlib.redirect_stdout(sys.stderr):
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        from paddleocr import PaddleOCR

        ocr = PaddleOCR(
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name="latin_PP-OCRv5_mobile_rec",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
        rec_only = None  # reconnaissance sans détection, chargée seulement si besoin
        out = {}
        for fid, img in crops.items():
            res = ocr.predict(img)[0]
            texts, scores = list(res["rec_texts"]), list(res["rec_scores"])
            boxes = res.get("rec_boxes")
            # Ordre de lecture : de haut en bas, puis de gauche à droite.
            if boxes is not None and len(texts) > 1:
                order = sorted(range(len(texts)), key=lambda i: (round(float(boxes[i][1]) / 25), float(boxes[i][0])))
                texts, scores = [texts[i] for i in order], [scores[i] for i in order]
            keep = [(t, s) for t, s in zip(texts, scores) if t.strip()]
            text = " ".join(t for t, _ in keep)
            score = float(np.mean([s for _, s in keep])) if keep else 0.0
            if not text:
                # Rien de détecté (souvent un chiffre isolé) : reconnaissance sur la zone entière.
                if rec_only is None:
                    from paddleocr import TextRecognition

                    rec_only = TextRecognition(model_name="latin_PP-OCRv5_mobile_rec")
                r = rec_only.predict(img)[0]
                text, score = r["rec_text"].strip(), float(r["rec_score"])
            out[fid] = (text, score)
    sys.stdout.buffer.write(pickle.dumps(out))


if __name__ == "__main__":
    _worker()
