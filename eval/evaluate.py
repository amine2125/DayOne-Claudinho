"""Évaluation sur le CSV de référence du hackathon + calibration des seuils.

    python -m eval.evaluate --csv data/reference.csv --images data/images [--use-vlm] [--target 0.98]

Format CSV attendu (adapter COLS ci-dessous si les noms diffèrent) :
    image, ligne (optionnel, 0-based), langue (fr/ar/en, optionnel), ecriture (manuscrit/imprime, optionnel),
    puis une colonne par champ de sortie (age, poids_kg, ...) contenant la valeur OU un statut
    (INCONNU, NON_FOURNI, ILLISIBLE, NON_APPLICABLE). Les valeurs de référence passent par les
    MÊMES parseurs que les prédictions -> "68 kg" et "68" sont comparés comme 68.0.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from app.pipeline import extract
from app.schemas.form_spec import FIELDS_BY_KEY, OUTPUT_FIELDS
from app.schemas.models import FieldStatus
from app.validators.parsers import parse_value

COLS = {"image": "image", "row": "ligne", "lang": "langue", "writing": "ecriture"}
STATUS_WORDS = {s.value for s in FieldStatus} - {"CONNU", "A_REVISER"}
TOLERANCE = {"temperature": 0.1, "age_gestationnel": 0.5, "poids_kg": 0.5}


def ref_value(field: str, raw: str):
    """-> (statut_ref, valeur_canonique)"""
    raw = (raw or "").strip()
    if not raw:
        return "NON_FOURNI", None
    if raw.upper() in STATUS_WORDS:
        return raw.upper(), None
    spec = FIELDS_BY_KEY.get(field)
    if field == "rhesus":
        spec = FIELDS_BY_KEY["vih"]       # même vocabulaire positif / négatif
    if spec is not None:
        p = parse_value(raw, spec)
        if p.ok and not isinstance(p.value, dict):
            return "CONNU", p.value
    try:
        return "CONNU", float(raw.replace(",", "."))
    except ValueError:
        return "CONNU", raw.upper()


def same(field: str, a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= TOLERANCE.get(field, 0)
    return str(a).strip().upper() == str(b).strip().upper()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--images", required=True)
    ap.add_argument("--use-vlm", action="store_true")
    ap.add_argument("--target", type=float, default=0.98, help="précision visée pour CONNU")
    ap.add_argument("--out", default="eval/predictions.jsonl")
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.csv, encoding="utf-8")))
    cache: dict[str, dict] = {}
    items = []        # un item par (ligne de référence, champ)
    with open(args.out, "w", encoding="utf-8") as out:
        for row in rows:
            img = row[COLS["image"]]
            if img not in cache:
                resp = extract((Path(args.images) / img).read_bytes(), use_vlm=args.use_vlm)
                cache[img] = resp.model_dump(mode="json", exclude={"debug"})
                out.write(json.dumps({"image": img, **cache[img]}, ensure_ascii=False) + "\n")
            recs = cache[img]["records"]
            idx = int(row.get(COLS["row"]) or 0)
            pred_fields = recs[idx]["fields"] if idx < len(recs) else {}
            for field in OUTPUT_FIELDS:
                if field not in row:
                    continue
                rs, rv = ref_value(field, row[field])
                p = pred_fields.get(field, {"status": "A_REVISER", "value": None, "confidence": 0.0, "signals": None})
                items.append({
                    "field": field, "ref_status": rs, "ref_value": rv, "pred_status": p["status"],
                    "pred_value": p["value"], "conf": p["confidence"],
                    "vlm_agree": (p.get("signals") or {}).get("vlm_agreement"),
                    "lang": row.get(COLS["lang"], "?"), "writing": row.get(COLS["writing"], "?"),
                    "retake": cache[img]["needs_retake"],
                })
    report(items, args.target)


def report(items: list[dict], target: float) -> None:
    n = len(items)
    if not n:
        print("Aucun item évalué : vérifier les noms de colonnes (COLS)")
        return
    for it in items:
        it["value_ok"] = it["ref_value"] is not None and it["pred_value"] is not None \
            and same(it["field"], it["pred_value"], it["ref_value"])
        # Correct = bon statut, et bonne valeur si la référence en a une
        it["ok"] = (it["pred_status"] == it["ref_status"]) and (it["ref_value"] is None or it["value_ok"])

    known = [i for i in items if i["pred_status"] == "CONNU"]
    false_known = [i for i in known if not (i["ref_status"] == "CONNU" and i["value_ok"])]
    with_val = [i for i in items if i["ref_value"] is not None]
    numeric = [i for i in with_val if isinstance(i["ref_value"], (int, float)) and isinstance(i["pred_value"], (int, float))]

    print(f"\n=== {n} champs évalués ===")
    print(f"Exactitude champ (statut + valeur)  : {sum(i['ok'] for i in items) / n:.1%}")
    print(f"Exactitude statut                   : {sum(i['pred_status'] == i['ref_status'] for i in items) / n:.1%}")
    print(f"Exactitude valeur (réf. avec valeur): {sum(i['value_ok'] for i in with_val) / max(1, len(with_val)):.1%}")
    if numeric:
        mae = sum(abs(i["pred_value"] - i["ref_value"]) for i in numeric) / len(numeric)
        print(f"Numériques : exactes {sum(i['value_ok'] for i in numeric) / len(numeric):.1%}, MAE {mae:.2f}")
    print(f"Taux A_REVISER                      : {sum(i['pred_status'] == 'A_REVISER' for i in items) / n:.1%}")
    print(f"Taux FAUX CONNU (sécurité)          : {len(false_known) / max(1, len(known)):.2%} ({len(false_known)}/{len(known)})")
    print(f"Automatisation (CONNU et juste)     : {(len(known) - len(false_known)) / max(1, len(with_val)):.1%}")

    print("\nMatrice statuts (réf -> prédit) :")
    for (r, p), c in sorted(Counter((i["ref_status"], i["pred_status"]) for i in items).items()):
        print(f"  {r:15} -> {p:15} {c}")

    for key, title in (("lang", "langue"), ("writing", "écriture"), ("field", "champ")):
        groups = defaultdict(list)
        for i in items:
            groups[i[key]].append(i)
        print(f"\nPar {title} :")
        for g, its in sorted(groups.items()):
            k = [i for i in its if i["pred_status"] == "CONNU"]
            fk = sum(1 for i in k if not (i["ref_status"] == "CONNU" and i["value_ok"]))
            print(f"  {g:22} n={len(its):4}  exact={sum(i['ok'] for i in its) / len(its):6.1%}  "
                  f"faux_CONNU={fk / max(1, len(k)):6.1%}  a_reviser={sum(i['pred_status'] == 'A_REVISER' for i in its) / len(its):6.1%}")

    calibrate(items, target)


def calibrate(items: list[dict], target: float) -> None:
    """Choisit tau_known = plus petit seuil tel que précision(score >= tau) >= cible.
    Le score étant indépendant du statut, on calibre sur toutes les prédictions avec valeur."""
    print(f"\n=== Calibration (cible précision CONNU >= {target:.0%}) ===")
    for label, subset in (("sans accord VLM", [i for i in items if i["vlm_agree"] is not True]),
                          ("avec accord VLM", [i for i in items if i["vlm_agree"] is True])):
        scored = [i for i in subset if i["pred_value"] is not None and i["ref_value"] is not None]
        if len(scored) < 20:
            print(f"  {label}: trop peu d'exemples ({len(scored)})")
            continue
        print(f"  {label} ({len(scored)} ex.)   seuil  précision  couverture")
        chosen = None
        for t in [x / 100 for x in range(50, 100, 5)]:
            above = [i for i in scored if i["conf"] >= t]
            if not above:
                continue
            prec = sum(i["value_ok"] for i in above) / len(above)
            print(f"  {'':28} {t:.2f}   {prec:7.1%}   {len(above) / len(scored):7.1%}")
            if chosen is None and prec >= target:
                chosen = t
        var = "TAU_KNOWN_VLM_AGREE" if "avec" in label else "TAU_KNOWN"
        print(f"  -> REGISTRE_{var}={chosen}" if chosen else "  -> cible jamais atteinte : tout reste A_REVISER")
    low = [i for i in items if i["pred_value"] is not None and i["ref_value"] is not None and i["conf"] < 0.5]
    if low:
        print(f"\n  Exactitude des valeurs à score < 0.5 : {sum(i['value_ok'] for i in low) / len(low):.1%} "
              "(si < 30 %, ces lectures sont du bruit : relever REGISTRE_TAU_ILLEGIBLE)")


if __name__ == "__main__":
    main()
