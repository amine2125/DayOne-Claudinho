"""Étape 1 : récupère les morceaux d'image que la lecture enverrait au modèle, SANS appeler le modèle.

La liste des morceaux est fixée par l'OCR avant toute réponse du modèle : on remplace donc le
modèle par une réponse vide le temps de cette passe. Usage :
  python -m calibration.collect SORTIE.pkl PATIENTE [PATIENTE...]
"""

import csv
import pickle
import sys
from concurrent.futures import ProcessPoolExecutor

from dayone.dataset import ROOT


def _collect(row: dict) -> list[dict]:
    from calibration.harness import instrumented_read
    from dayone import vlm

    vlm.available = lambda model=None: (True, "ok")       # active le chemin « relecture »…
    vlm.is_health_form = lambda img, model=None: True     # …sans jamais appeler le modèle
    vlm.suggest_place = lambda *a, **k: ""
    vlm.unload = lambda *a, **k: None
    try:
        _, crops = instrumented_read(int(row["page_number"]), ROOT / row["path"], read_value=lambda c, l, m: "")
    except Exception as e:                                # page non lisible : on la signale, on continue
        print(f"page {row['page_number']} ignorée : {type(e).__name__}", flush=True)
        return []
    for c in crops:
        c["patient"] = int(row["patient"])
        c["page_type"] = row["page_type"]
        del c["answer"], c["seconds"]
    print(f"page {row['page_number']} : {len(crops)} morceaux", flush=True)
    return crops


def main() -> None:
    out, patients = sys.argv[1], {int(p) for p in sys.argv[2:]}
    rows = [r for r in csv.DictReader(open(ROOT / "outputs/index.csv"))
            if r["page_number"] and not r["duplicate_of"] and int(r["patient"]) in patients]
    with ProcessPoolExecutor(max_workers=4) as pool:
        crops = [c for page in pool.map(_collect, rows) for c in page]
    pickle.dump(crops, open(out, "wb"))
    print(f"TERMINÉ : {len(crops)} morceaux sur {len(rows)} pages -> {out}", flush=True)


if __name__ == "__main__":
    main()
