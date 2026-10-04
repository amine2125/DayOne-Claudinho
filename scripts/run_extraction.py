"""Extrait les pages V1 et écrit outputs/predictions/*.json (champs du schéma uniquement).

Usage :
  python -m scripts.run_extraction                     # pages V1 du split dev
  python -m scripts.run_extraction --pages 2 10        # certaines pages dev
  python -m scripts.run_extraction --split test --final
  python -m scripts.run_extraction --image photo.jpg --page-type identification_antecedents
Options : --no-model (OCR + cases seulement), --model, --threshold.
N'affiche que des comptes de statuts, jamais les valeurs lues.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from dayone import vlm
from dayone.dataset import OUTPUTS, load_index, page_path
from dayone.extract import THRESHOLD, extract_page, source_label
from dayone.schema import V1_PAGE_TYPES
from scripts.check_integrity import main as check_integrity

PRED_DIR = OUTPUTS / "predictions"


def prediction_path(page_number, page_type: str) -> Path:
    return PRED_DIR / f"page_{int(page_number):02d}_{page_type}.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=["dev", "test"])
    ap.add_argument("--final", action="store_true", help="autorise le split test (évaluation finale)")
    ap.add_argument("--pages", nargs="*", type=int, help="numéros de page (défaut : toutes les pages V1 du split)")
    ap.add_argument("--image", help="une image quelconque (photo, scan)")
    ap.add_argument("--page-type", choices=V1_PAGE_TYPES)
    ap.add_argument("--no-model", action="store_true")
    ap.add_argument("--model", default=vlm.DEFAULT_MODEL)
    ap.add_argument("--threshold", type=float, default=THRESHOLD)
    args = ap.parse_args()

    jobs = []  # (image, page_type, chemin de sortie, nom)
    if args.image:
        img = Path(args.image)
        out = PRED_DIR / f"{img.stem}.json"
        jobs.append((img, args.page_type, out, source_label(img)))
    else:
        rows = [r for r in load_index(args.split, final=args.final) if r["page_type"] in V1_PAGE_TYPES]
        if args.pages:
            rows = [r for r in rows if int(r["page_number"]) in args.pages]
        for r in rows:
            jobs.append((page_path(r), r["page_type"], prediction_path(r["page_number"], r["page_type"]),
                         f"page {r['page_number']}"))
    if not jobs:
        print("Aucune page à traiter.")
        return 1

    PRED_DIR.mkdir(parents=True, exist_ok=True)
    for img, page_type, out, name in jobs:
        print(f"{name} ({page_type or 'type auto'})")
        pred = extract_page(img, page_type=page_type, use_model=not args.no_model, model=args.model,
                            threshold=args.threshold, source_name=name,
                            progress=lambda m: print("  ·", m))
        out.write_text(json.dumps(pred, ensure_ascii=False, indent=1), encoding="utf-8")
        counts = Counter(f["status"] for f in pred["fields"].values())
        print(f"  mode {pred['mode']}, {pred['timings']['total_s']} s, statuts {dict(counts)} -> {out.relative_to(OUTPUTS.parent)}")

    return check_integrity()


if __name__ == "__main__":
    sys.exit(main())
