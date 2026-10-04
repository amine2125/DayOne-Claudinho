"""Lit des fiches et écrit outputs/predictions/*.json (champs retenus uniquement, jamais le texte OCR brut).

Usage :
  python -m scripts.run_extraction --image photo.jpg        # n'importe quelle fiche
  python -m scripts.run_extraction --pages 2 10             # pages du jeu de développement
  python -m scripts.run_extraction                          # pages dev annotables (identification, accouchement)
  python -m scripts.run_extraction --split test --final     # évaluation finale
Options : --model, --threshold.
N'affiche que des comptes de statuts, jamais les valeurs lues.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from dayone import vlm
from dayone.dataset import OUTPUTS, load_index, page_path
from dayone.extract import THRESHOLD, NotAFormError, extract_page, source_label
from dayone.schema import REFERENCE_PAGE_TYPES
from scripts.check_integrity import main as check_integrity

PRED_DIR = OUTPUTS / "predictions"


def prediction_path(page_number, page_type: str) -> Path:
    return PRED_DIR / f"page_{int(page_number):02d}_{page_type}.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", nargs="*", help="une ou plusieurs images quelconques (photo, scan)")
    ap.add_argument("--split", default="dev", choices=["dev", "test"])
    ap.add_argument("--final", action="store_true", help="autorise le split test (évaluation finale)")
    ap.add_argument("--pages", nargs="*", type=int, help="numéros de page du jeu de données")
    ap.add_argument("--model", default=vlm.DEFAULT_MODEL)
    ap.add_argument("--threshold", type=float, default=THRESHOLD)
    args = ap.parse_args()

    jobs = []  # (image, chemin de sortie, nom)
    if args.image:
        for img in map(Path, args.image):
            jobs.append((img, PRED_DIR / f"{img.stem}.json", source_label(img)))
    else:
        rows = load_index(args.split, final=args.final)
        rows = [r for r in rows if int(r["page_number"]) in args.pages] if args.pages else \
            [r for r in rows if r["page_type"] in REFERENCE_PAGE_TYPES]
        for r in rows:
            jobs.append((page_path(r), prediction_path(r["page_number"], r["page_type"]), f"page {r['page_number']}"))
    if not jobs:
        print("Aucune page à traiter.")
        return 1

    PRED_DIR.mkdir(parents=True, exist_ok=True)
    for img, out, name in jobs:
        print(name)
        try:
            pred = extract_page(img, model=args.model, threshold=args.threshold, source_name=name,
                                progress=lambda m: print("  ·", m))
        except NotAFormError as e:
            print(f"  refusée : {e}")
            continue
        out.write_text(json.dumps(pred, ensure_ascii=False, indent=1), encoding="utf-8")
        counts = Counter(f["status"] for f in pred["fields"])
        print(f"  {len(pred['fields'])} champs, {pred['timings']['total_s']} s, statuts {dict(counts)} "
              f"-> {out.relative_to(OUTPUTS.parent)}")

    return check_integrity()


if __name__ == "__main__":
    sys.exit(main())
