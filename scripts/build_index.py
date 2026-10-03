"""Construit outputs/index.csv : une ligne par image, avec patiente, type de page, split et doublons.

Ne lit que les noms de fichiers et les sha256 (aucun contenu de page).
Usage : python -m scripts.build_index
"""

import csv
import json
import re
import sys
from collections import Counter, defaultdict

from dayone.dataset import INDEX_CSV, MANIFEST, PAGE_TYPES, PAGES_PER_PATIENT, split_for_patient
from scripts.check_integrity import main as check_integrity

SPECIMEN = re.compile(r"dossiers_specimen_10_patientes-(\d+)(?:__.+)?\.png$")
PHOTO = re.compile(r"\d+-\d+\.jpg$")
FIELDS = ["path", "sha256", "page_number", "patient", "position", "page_type", "split", "duplicate_of"]


def main() -> int:
    if check_integrity() != 0:
        print("Intégrité KO : index non construit.")
        return 1

    rows = []
    for e in json.loads(MANIFEST.read_text())["files"]:
        path, name = e["path"], e["path"].rsplit("/", 1)[-1]
        if m := SPECIMEN.match(name):
            n = int(m.group(1))
            patient, position = (n - 1) // PAGES_PER_PATIENT + 1, (n - 1) % PAGES_PER_PATIENT + 1
            rows.append(dict(path=path, sha256=e["sha256"], page_number=n, patient=patient,
                             position=position, page_type=PAGE_TYPES[position], split=split_for_patient(patient)))
        elif PHOTO.match(name):
            rows.append(dict(path=path, sha256=e["sha256"], page_number="", patient="",
                             position="", page_type="", split="photo"))

    # Doublons : même sha256 -> le premier nom (ordre alphabétique) fait foi.
    first_by_sha = {}
    for r in sorted(rows, key=lambda r: r["path"]):
        r["duplicate_of"] = first_by_sha.setdefault(r["sha256"], r["path"])
        if r["duplicate_of"] == r["path"]:
            r["duplicate_of"] = ""

    # Même numéro de page mais contenu différent : à signaler, pas à deviner.
    by_page = defaultdict(set)
    for r in rows:
        if r["page_number"] != "":
            by_page[r["page_number"]].add(r["sha256"])
    conflicts = sorted(n for n, shas in by_page.items() if len(shas) > 1)

    INDEX_CSV.parent.mkdir(exist_ok=True)
    rows.sort(key=lambda r: (r["split"], r["page_number"] if r["page_number"] != "" else 0, r["path"]))
    with INDEX_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    unique = [r for r in rows if r["duplicate_of"] == ""]
    print(f"{len(rows)} images indexées, {len(rows) - len(unique)} doublons exacts, {len(unique)} uniques.")
    print("Uniques par split :", dict(Counter(r["split"] for r in unique)))
    print("Numéros de page couverts :", len(by_page))
    if conflicts:
        print("ATTENTION : même numéro de page, contenus différents :", conflicts)
    print(f"-> {INDEX_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
