"""Vérifie que les fichiers de référence n'ont pas été modifiés (sha256 et taille vs manifest.json).

Usage : python -m scripts.check_integrity
"""

import hashlib
import json
import sys

from dayone.dataset import DATA_DIR, MANIFEST, ROOT

IGNORED = {".DS_Store"}


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    entries = json.loads(MANIFEST.read_text())["files"]
    expected = {e["path"]: e for e in entries}
    problems = []

    for rel, e in expected.items():
        p = ROOT / rel
        if not p.exists():
            problems.append(f"MANQUANT   {rel}")
        elif p.stat().st_size != e["bytes"] or sha256(p) != e["sha256"]:
            problems.append(f"MODIFIÉ    {rel}")

    on_disk = {str(p.relative_to(ROOT)) for p in DATA_DIR.rglob("*") if p.is_file() and p.name not in IGNORED}
    problems += [f"HORS MANIFEST {rel}" for rel in sorted(on_disk - expected.keys())]

    ok = len(expected) - sum(1 for p in problems if not p.startswith("HORS"))
    print(f"{ok}/{len(expected)} fichiers conformes au manifest.")
    for p in problems:
        print("  " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
