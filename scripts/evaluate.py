"""Compare les prédictions aux annotations humaines remplies.

Usage : python -m scripts.evaluate              (split dev)
        python -m scripts.evaluate --split test --final
Sorties : outputs/evaluation_<split>.json et outputs/evaluation_<split>.md
"""

import argparse
import json
import sys

from dayone.dataset import OUTPUTS, load_index
from dayone.evaluate import annotation_path, compare, load_annotation, summarize
from dayone.schema import REFERENCE_PAGE_TYPES
from scripts.run_extraction import prediction_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=["dev", "test"])
    ap.add_argument("--final", action="store_true")
    args = ap.parse_args()

    rows_all, pages, notes = [], {}, []
    for r in load_index(args.split, final=args.final):
        if r["page_type"] not in REFERENCE_PAGE_TYPES:
            continue
        ann = annotation_path(r["page_number"], r["page_type"])
        if not ann.exists():
            continue
        ref = load_annotation(ann, r["page_type"])
        if ref is None:
            notes.append(f"{ann.name} : pas encore rempli")
            continue
        pred_file = prediction_path(r["page_number"], r["page_type"])
        if not pred_file.exists():
            notes.append(f"page {r['page_number']} : prédiction absente (lancer scripts.run_extraction)")
            continue
        rows = compare(json.loads(pred_file.read_text(encoding="utf-8")), ref, r["page_type"])
        pages[f"page_{int(r['page_number']):02d}_{r['page_type']}"] = summarize(rows)
        rows_all += [{"page": r["page_number"], **x} for x in rows]

    for n in notes:
        print(n)
    if not rows_all:
        print("Aucune page annotée à évaluer : remplir annotations/*.csv à la main (voir annotations/LISEZMOI.md).")
        return 1

    report = {
        "split": args.split,
        "global": summarize(rows_all),
        "hors_tableaux": summarize([x for x in rows_all if not x["table"]]),
        "par_page": pages,
        "erreurs": [x for x in rows_all if x["outcome"] in ("erreur_silencieuse", "manque", "statut_different")],
    }
    OUTPUTS.mkdir(exist_ok=True)
    out_json = OUTPUTS / f"evaluation_{args.split}.json"
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    out_md = OUTPUTS / f"evaluation_{args.split}.md"
    out_md.write_text(_markdown(report), encoding="utf-8")
    g = report["global"]
    print(f"{len(pages)} page(s) : exactitude {g['exactitude_globale']}, valeurs connues justes {g['valeurs_connues_justes']}, "
          f"à revoir {g['part_a_revoir']}, erreurs silencieuses {g['erreurs_silencieuses']}")
    print(f"-> {out_md.relative_to(OUTPUTS.parent)}")
    return 0


def _markdown(rep: dict) -> str:
    lines = [f"# Évaluation — split {rep['split']}", "",
             "| Périmètre | Champs | Exactitude | Valeurs connues justes | À revoir | Erreurs silencieuses |",
             "|---|---|---|---|---|---|"]
    for name, s in [("Global", rep["global"]), ("Hors tableaux", rep["hors_tableaux"])] + list(rep["par_page"].items()):
        lines.append(f"| {name} | {s['champs']} | {s['exactitude_globale']} | {s['valeurs_connues_justes']} | "
                     f"{s['part_a_revoir']} | {s['erreurs_silencieuses']} |")
    lines += ["", "**Erreur silencieuse** : le logiciel affiche KNOWN avec une valeur fausse. C'est l'erreur à éviter.",
              "**À revoir** : le logiciel a signalé un doute (NEEDS_REVIEW). Ce n'est pas une erreur.", ""]
    if rep["erreurs"]:
        lines += ["## Détail des écarts", "", "| Page | Champ | Étiquette lue | Référence | Prédiction | Issue |",
                  "|---|---|---|---|---|---|"]
        for e in rep["erreurs"]:
            lines.append(f"| {e['page']} | {e['field_id']} | {e['pred_label']} | {e['ref_status']} {e['ref_value'] or ''} | "
                         f"{e['pred_status']} {e['pred_value'] if e['pred_value'] is not None else ''} | {e['outcome']} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
