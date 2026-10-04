"""Crée les modèles d'annotation VIDES (annotations/*.csv) que l'humain remplit à la main.

Patientes 1-2 (dev) ; patientes 9-10 (test) seulement avec --final.
Ne lit aucune image et n'écrase jamais un fichier existant.
Usage : python -m scripts.make_annotation_templates [--final]
"""

import argparse
import sys

from dayone.dataset import PAGES_PER_PATIENT, PAGE_TYPES
from dayone.evaluate import annotation_path, write_template
from dayone.schema import REFERENCE_PAGE_TYPES

DEV_PATIENTS = (1, 2)
TEST_PATIENTS = (9, 10)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true", help="ajoute les patientes de test 9 et 10")
    args = ap.parse_args()

    patients = DEV_PATIENTS + (TEST_PATIENTS if args.final else ())
    positions = {pos: pt for pos, pt in PAGE_TYPES.items() if pt in REFERENCE_PAGE_TYPES}
    for patient in patients:
        for pos, page_type in positions.items():
            page = (patient - 1) * PAGES_PER_PATIENT + pos
            path = annotation_path(page, page_type)
            if path.exists():
                print(f"déjà présent, conservé : {path.name}")
                continue
            write_template(path, page_type)
            print(f"créé : {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
