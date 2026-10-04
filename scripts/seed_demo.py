"""Base de démonstration : vraies pages du jeu dev lues par le pipeline, vérifiées comme sur WhatsApp, puis rattachées.

Usage :
  python -m scripts.seed_demo --patients 1 2 3                 # écrit demo.db (et demo_captures/)
  python -m scripts.seed_demo --patients 1 --cache outputs/demo_cache   # relance instantanée ensuite
Puis lancer l'API sur cette base :
  DAYONE_DB=demo.db DAYONE_CAPTURES=demo_captures DAYONE_KEY_FILE=.demo_key uvicorn api.main:app --port 8000

- Base séparée (demo.db) : la base de travail dayone.db n'est jamais touchée.
- Patientes 9 et 10 refusées : le test reste verrouillé.
- Un dossier par visite, daté par une date lue sur la page (venue, accouchement, consultation) :
  identification + grossesse actuelle ; accouchement ; post-partum précoce ; post-partum tardif.
- « Vérification » : les champs à vérifier sont confirmés tels quels, SAUF quand un contrôle de cohérence
  les signale (valeur probablement mal lue) : ce dossier reste « à vérifier », comme sur le terrain.
"""

import argparse
import json
import sys
from pathlib import Path

from dayone.dataset import ROOT, TEST_PATIENTS, load_index, page_path

VISITS = [(2, 3), (4,), (5, 6), (7, 8)]          # positions des pages dans le carnet, regroupées par visite
DATE_LABELS = ("venue le", "date de l accouchement", "date de la consultation")


def _date_of(fields: dict) -> str | None:
    """Date la plus récente lue sur les pages d'un dossier (pour dater la visite de démonstration)."""
    from dayone.normalize import fold
    dates = [f["value"] for f in fields.values()
             if isinstance(f.get("value"), str) and len(f["value"]) == 10 and f["value"][4] == "-"
             and fold(str(f.get("label", "")).split("|")[0]) in DATE_LABELS and f.get("status") == "KNOWN"]
    return max(dates) if dates else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--patients", nargs="+", type=int, default=[1])
    ap.add_argument("--db", default="demo.db")
    ap.add_argument("--captures", default="demo_captures")
    ap.add_argument("--key", default=".demo_key")
    ap.add_argument("--cache", help="dossier où garder les lectures (relance instantanée)")
    args = ap.parse_args()
    if set(args.patients) & TEST_PATIENTS:
        print("Patientes 9 et 10 : jeu de test verrouillé, refusé.")
        return 2

    from api import store
    store.DB_PATH, store.CAPTURES, store.KEY_FILE = ROOT / args.db, ROOT / args.captures, ROOT / args.key
    from dayone.extract import extract_page

    cache = Path(args.cache) if args.cache else None
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
    rows = {int(r["page_number"]): r for r in load_index("dev")}

    for patient in args.patients:
        code = f"DEMO-{patient:02d}"
        patient_id = None
        for positions in VISITS:
            pages = [rows[(patient - 1) * 8 + pos] for pos in positions if (patient - 1) * 8 + pos in rows]
            if not pages:
                continue
            photos = [page_path(r).read_bytes() for r in pages]
            preds = {}

            def extract(data, use_model=True, _pages=pages, _photos=photos, _preds=preds):
                row = _pages[_photos.index(data)]
                hit = cache / f"page_{int(row['page_number']):02d}.json" if cache else None
                if hit and hit.exists():
                    return json.loads(hit.read_text(encoding="utf-8"))
                pred = extract_page(data, use_model=use_model)
                if hit:
                    hit.write_text(json.dumps(pred, ensure_ascii=False), encoding="utf-8")
                return pred

            rid = store.create_record(code, "SF-DEMO", photos)
            store.process_record(rid, extract=extract)
            rec = store.record(rid, str)
            fields = {k: f for p in rec["pages"] for k, f in p["fields"].items()}
            day = _date_of(fields)
            if day:                                   # la visite prend la date lue sur la page
                with store.db() as c:
                    c.execute("UPDATE records SET created_at = ? WHERE id = ?", (f"{day}T10:00:00+00:00", rid))
                    c.execute("UPDATE pages SET captured_at = ? WHERE record_id = ?", (f"{day}T10:00:00+00:00", rid))
            flagged = [f["key"] for p in rec["pages"] for f in p["fields"].values() if f.get("alerts")]
            if flagged:
                print(f"{code} pages {[int(r['page_number']) for r in pages]} : {len(flagged)} incohérence(s), reste à vérifier")
                continue
            for p in rec["pages"]:
                for f in p["fields"].values():
                    if f["status"] in store.TO_REVIEW:
                        store.set_field(rid, p["index"], f["key"], "SF-DEMO", confirm=True)
            store.validate(rid)
            patient_id = store.link(rid, "EXISTING" if patient_id else "CREATE", patient_id)
            print(f"{code} pages {[int(r['page_number']) for r in pages]} : validé, rattaché ({day})")
    print(f"Base de démonstration : {store.DB_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
