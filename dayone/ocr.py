"""PaddleOCR sur la page entière, dans un processus séparé.

2e passe : l'encre que la 1re passe n'a pas lue est découpée et relue seule (une ligne ratée en entier
réapparaît souvent quand on la lit isolée de ses voisines).

Multilingue : la détection trouve le texte quelle que soit la langue ; chaque ligne est lue par le modèle
latin (français, anglais), et une ligne mal lue est relue par le modèle arabe. La meilleure lecture est gardée.

Le processus enfant est terminé avant tout appel au modèle : sa mémoire est rendue
(PaddleOCR et Ollama ne tournent jamais en même temps). Le texte lu ne passe que par
un tube en mémoire : il n'est jamais écrit sur disque ni dans les logs.
"""

import pickle
import subprocess
import sys

import numpy as np

from dayone.dataset import ROOT


def read_page(img: np.ndarray) -> list[dict]:
    """Image BGR -> lignes [{text, score, box: (x0, y0, x1, y1)}], dans l'ordre de lecture."""
    proc = subprocess.run([sys.executable, "-m", "dayone.ocr"], input=pickle.dumps(img),
                          capture_output=True, cwd=ROOT)
    if proc.returncode != 0:
        # stderr de Paddle ne contient pas le texte lu ; on n'en garde que la fin.
        raise RuntimeError("PaddleOCR a échoué : " + proc.stderr.decode(errors="ignore")[-500:])
    return pickle.loads(proc.stdout)


MIN_SECOND_SCORE = 0.6   # 2e passe : lectures plus fragiles, on ne garde que les assez sûres
RETRY_ARABIC = 0.85      # lecture latine sous ce score : la ligne est relue par le modèle arabe
ARABIC_MODEL = "arabic_PP-OCRv5_mobile_rec"
_arabic = []             # modèle arabe, chargé seulement si une ligne en a besoin


def _arabic_reader():
    if not _arabic:
        from paddleocr import TextRecognition

        _arabic.append(TextRecognition(model_name=ARABIC_MODEL))
    return _arabic[0]


def _arabic_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return sum("\u0600" <= c <= "\u06ff" for c in letters) / len(letters) if letters else 0.0


def _best_script(img: np.ndarray, lines: list[dict]) -> None:
    """Relit en arabe les lignes mal lues par le modèle latin ; garde la lecture arabe si elle est
    vraiment en arabe et plus sûre."""
    doubtful = [l for l in lines if l["score"] < RETRY_ARABIC]
    crops = [img[max(0, y0):y1, max(0, x0):x1] for x0, y0, x1, y1 in (l["box"] for l in doubtful)]
    keep = [(l, c) for l, c in zip(doubtful, crops) if c.size]
    if not keep:
        return
    for (l, _), r in zip(keep, _arabic_reader().predict([c for _, c in keep], batch_size=16)):
        text, score = r["rec_text"].strip(), float(r["rec_score"])
        if text and _arabic_share(text) >= 0.5 and score > l["score"]:
            l.update(text=text, score=score, script="ar")


def _read(ocr, img: np.ndarray, offset=(0, 0)) -> list[dict]:
    """Lignes lues sur une image (ou un morceau, replacé dans la page par `offset`)."""
    import cv2

    pad, scale = 0, 1
    if offset != (0, 0):
        # Petit morceau : agrandi et entouré de marge, sinon la détection le rate.
        scale = 2 if img.shape[0] < 48 else 1
        pad = 20
        img = cv2.copyMakeBorder(cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC),
                                 pad, pad, pad, pad, cv2.BORDER_REPLICATE)
    res = ocr.predict(img)[0]
    found = [{"text": text.strip(), "score": float(score), "box": tuple(int(v) for v in box)}
             for text, score, box in zip(res["rec_texts"], res["rec_scores"], res["rec_boxes"])]
    _best_script(img, found)
    out = []
    for l in found:
        if l["text"]:
            x0, y0, x1, y1 = ((v - pad) // scale for v in l["box"])
            out.append({**l, "box": (x0 + offset[0], y0 + offset[1], x1 + offset[0], y1 + offset[1])})
    return out


def _worker() -> None:
    import contextlib
    import os
    from statistics import median

    from dayone import imaging

    img = pickle.loads(sys.stdin.buffer.read())
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
        lines = _read(ocr, img)
        if lines:
            th = median(l["box"][3] - l["box"][1] for l in lines)
            bm = imaging.blue_map(img)
            halo = imaging.blue_halo(bm)
            for (x0, y0, x1, y1), blue in imaging.unread_ink(img, [l["box"] for l in lines], th, bm):
                crop = img[y0:y1, x0:x1].copy()
                if not blue:
                    # Imprimé seul : l'écriture bleue voisine est effacée, sinon les deux sont lues mêlées.
                    crop[halo[y0:y1, x0:x1] > 0] = np.median(crop.reshape(-1, 3), axis=0)
                for l in _read(ocr, crop, offset=(x0, y0)):
                    if l["score"] >= MIN_SECOND_SCORE and sum(c.isalnum() for c in l["text"]) >= 2:
                        lines.append(l)
        lines.sort(key=lambda d: ((d["box"][1] + d["box"][3]) // 2 // 20, d["box"][0]))
    sys.stdout.buffer.write(pickle.dumps(lines))


MODELS = ("PP-OCRv5_mobile_det", "latin_PP-OCRv5_mobile_rec", ARABIC_MODEL)


def models_ready() -> bool:
    from pathlib import Path

    root = Path.home() / ".paddlex" / "official_models"
    return all((root / m).is_dir() for m in MODELS)


def download_models() -> None:
    """Télécharge une fois les modèles PaddleOCR (détection, latin, arabe) : ensuite tout marche hors ligne."""
    import os

    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    from paddleocr import TextDetection, TextRecognition

    TextDetection(model_name=MODELS[0])
    for name in MODELS[1:]:
        TextRecognition(model_name=name)


if __name__ == "__main__":
    if sys.argv[1:] == ["--download"]:
        download_models()
        sys.exit(0 if models_ready() else 1)
    _worker()
