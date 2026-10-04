"""Étapes 2 à 4 : compare des versions du prompt de relecture sur un échantillon fixe de morceaux.

Chaque réponse du modèle est classée :
- juste      : elle correspond à une valeur manuscrite de la zone (bonne réponse tirée du PDF),
               ou EMPTY quand la zone ne contient pas d'écriture ;
- fausse     : une autre valeur. C'est l'erreur dangereuse (risque d'erreur silencieuse) ;
- abstention : ILLEGIBLE. Sans danger : le champ reste à vérifier par la sage-femme.

Usage : python -m calibration.evaluate_prompts CROPS.pkl --patients 1-6 --n 150 --prompts base,v1,v2
"""

import argparse
import pickle
import random
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

from calibration.references import values_in
from dayone import vlm

PROMPTS = {
    "base": vlm.VALUE_PROMPT,
    "v1": (
        "This image is a small crop of a handwritten medical register (French, Arabic or English). The field is "
        "\"{label}\". The crop may also show the printed label and parts of neighbouring cells. Copy only the "
        "handwritten value that belongs to this field, exactly as written, character by character: same spelling, "
        "language, digits, units and date format (for example 12/11/2022). Never translate, never correct, never "
        "guess missing characters, and ignore all printed text. If no handwriting belongs to this field, answer "
        "EMPTY. If the handwriting cannot be read with certainty, answer ILLEGIBLE. Answer with the value only."
    ),
    "v2": vlm.VALUE_PROMPT + (
        " Examples of valid answers: 31 | Lycée | 12/11/2022 | 3626 g | RAS | Voie basse | Oui | EMPTY | ILLEGIBLE."
    ),
}


def ask(crop_png: bytes, label: str, prompt: str, model: str = vlm.DEFAULT_MODEL) -> str:
    """Même appel que dayone.vlm.read_value, avec un autre texte de prompt."""
    crop = cv2.imdecode(np.frombuffer(crop_png, np.uint8), cv2.IMREAD_COLOR)
    resp = vlm._client(model).chat(
        model=model,
        messages=[{"role": "user", "content": prompt.format(label=label), "images": [vlm._png(vlm._fit(crop, 768))]}],
        think=False, options={"temperature": 0, "num_ctx": 2048, "num_predict": 40}, keep_alive="10m",
    )
    t = re.sub(r"<think>.*?</think>", "", resp.message.content, flags=re.S).strip().strip('"').strip()
    return t.splitlines()[0].strip() if t else ""


def norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.casefold())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"[\s.,;:|]+", "", t)


def judge(answer: str, values: list[str]) -> str:
    a = answer.strip()
    if a.upper().startswith("ILLEGIBLE"):
        return "abstention"
    if not values:
        return "juste" if a.upper().startswith("EMPTY") or not a else "fausse"
    ok = {norm(v) for v in values} | {norm(" ".join(values))}
    return "juste" if norm(a) in ok else "fausse"


def sample(crops: list[dict], patients: set[int], n: int, seed: int = 0) -> list[dict]:
    """Échantillon fixe, réparti par type de page (même graine = mêmes morceaux pour tous les prompts)."""
    pool = [c for c in crops if c["patient"] in patients]
    rng = random.Random(seed)
    by_type: dict[str, list[dict]] = {}
    for c in pool:
        by_type.setdefault(c["page_type"], []).append(c)
    out = []
    for items in by_type.values():
        k = max(1, round(n * len(items) / len(pool)))
        out += rng.sample(items, min(k, len(items)))
    rng.shuffle(out)
    return out[:n]


def run(prompt_name: str, items: list[dict]) -> dict:
    t = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as pool:
        answers = list(pool.map(lambda c: ask(c["crop_png"], c["label"], PROMPTS[prompt_name]), items))
    verdicts = [judge(a, values_in(c["page"], c["box"], c["shape"])) for a, c in zip(answers, items)]
    n = len(items)
    res = {v: verdicts.count(v) for v in ("juste", "fausse", "abstention")}
    res.update(prompt=prompt_name, n=n, secondes=round(time.perf_counter() - t),
               answers=answers, verdicts=verdicts)
    print(f"{prompt_name:5} juste {res['juste']:3}/{n} ({100 * res['juste'] / n:4.1f} %) | fausse {res['fausse']:3} "
          f"({100 * res['fausse'] / n:4.1f} %) | abstention {res['abstention']:3} | {res['secondes']} s", flush=True)
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("crops")
    ap.add_argument("--patients", required=True, help="ex. 1-6 ou 7-8")
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--prompts", default="base,v1,v2")
    ap.add_argument("--out")
    args = ap.parse_args()
    a, b = (int(x) for x in args.patients.split("-"))
    items = sample(pickle.load(open(args.crops, "rb")), set(range(a, b + 1)), args.n)
    print(f"{len(items)} morceaux, patientes {args.patients}", flush=True)
    results = [run(p, items) for p in args.prompts.split(",")]
    if args.out:
        pickle.dump({"items": items, "results": results}, open(args.out, "wb"))


if __name__ == "__main__":
    main()
