"""Test de fumée : PaddleOCR puis Ollama sur une page dev, l'un après l'autre.

N'affiche jamais le texte lu : seulement temps, RAM, nombre de lignes et titre trouvé oui/non.
Usage : python -m scripts.smoke_test [--model qwen3-vl:4b-instruct]
"""

import argparse
import json
import multiprocessing as mp
import resource
import sys
import time

from dayone.dataset import OUTPUTS, load_index, page_path

PAGE_TYPE = "identification_antecedents"
TITLE_WORD = "IDENTIFICATION"


def _ocr_worker(image: str, queue) -> None:
    from paddleocr import PaddleOCR

    t0 = time.perf_counter()
    # Modèles nommés explicitement (`lang` est ignoré dès qu'un nom de modèle est donné).
    ocr = PaddleOCR(
        text_detection_model_name="PP-OCRv5_mobile_det",
        text_recognition_model_name="latin_PP-OCRv5_mobile_rec",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    t1 = time.perf_counter()
    res = ocr.predict(image)[0]
    t2 = time.perf_counter()
    texts, scores = res["rec_texts"], res["rec_scores"]
    queue.put({
        "init_s": round(t1 - t0, 1),
        "predict_s": round(t2 - t1, 1),
        "lines": len(texts),
        "mean_score": round(sum(scores) / len(scores), 3) if scores else None,
        "title_found": any(TITLE_WORD in t.upper() for t in texts),
        "peak_ram_gb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9, 2),  # octets sur macOS
    })


def run_ocr(image: str) -> dict:
    # Processus séparé : la mémoire de PaddleOCR est rendue avant l'appel à Ollama.
    ctx = mp.get_context("spawn")
    queue = ctx.Queue()
    p = ctx.Process(target=_ocr_worker, args=(image, queue))
    p.start()
    p.join()
    if p.exitcode != 0:
        raise RuntimeError(f"PaddleOCR a échoué (code {p.exitcode}).")
    return queue.get()


def run_ollama(image: str, model: str) -> dict:
    import ollama

    t0 = time.perf_counter()
    resp = ollama.chat(
        model=model,
        messages=[{
            "role": "user",
            "content": "Recopie uniquement le titre imprimé en haut de cette page, sans rien ajouter.",
            "images": [image],
        }],
        think=False,
        options={"temperature": 0},
    )
    elapsed = time.perf_counter() - t0
    loaded = next((m for m in ollama.ps().models if m.model == model), None)
    out = {
        "seconds": round(elapsed, 1),
        "title_found": TITLE_WORD in resp.message.content.upper(),
        "model_ram_gb": round(loaded.size / 1e9, 2) if loaded else None,
        "eval_tokens": resp.eval_count,
        "prompt_tokens": resp.prompt_eval_count,
    }
    ollama.generate(model=model, keep_alive=0)  # décharge le modèle
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3-vl:4b-instruct")
    args = ap.parse_args()

    row = next(r for r in load_index("dev") if r["page_type"] == PAGE_TYPE)
    image = str(page_path(row))
    print(f"Page : n°{row['page_number']} (patiente {row['patient']}, {row['page_type']})")

    ocr = run_ocr(image)
    print("PaddleOCR :", ocr)
    llm = run_ollama(image, args.model)
    print(f"Ollama ({args.model}) :", llm)

    OUTPUTS.mkdir(exist_ok=True)
    out = OUTPUTS / f"smoke_test_{args.model.replace(':', '_')}.json"
    out.write_text(json.dumps({"page_number": row["page_number"], "paddleocr": ocr, "ollama": llm}, indent=2))
    ok = ocr["lines"] > 0 and ocr["title_found"] and llm["title_found"]
    print("OK" if ok else "KO", f"-> {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
