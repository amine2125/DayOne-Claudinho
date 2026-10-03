"""Accès aux pages du registre, avec verrouillage des patientes de test."""

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
REGISTRY_DIR = DATA_DIR / "Paper Registry"
MANIFEST = ROOT / "manifest.json"
OUTPUTS = ROOT / "outputs"
INDEX_CSV = OUTPUTS / "index.csv"

PAGES_PER_PATIENT = 8
TEST_PATIENTS = {9, 10}

# Position de la page dans le dossier d'une patiente (1 à 8) -> type de page.
PAGE_TYPES = {
    1: "fiche_surveillance",
    2: "identification_antecedents",
    3: "grossesse_actuelle",
    4: "accouchement",
    5: "postpartum_precoce_mere",
    6: "postpartum_precoce_nouveau_ne",
    7: "postpartum_tardif_mere",
    8: "postpartum_tardif_nouveau_ne",
}

SPLITS = ("dev", "test", "photo")


class TestSplitLocked(PermissionError):
    pass


def split_for_patient(patient: int) -> str:
    return "test" if patient in TEST_PATIENTS else "dev"


def load_index(split: str = "dev", final: bool = False, include_duplicates: bool = False) -> list[dict]:
    """Lignes de l'index pour un split. Le split `test` exige final=True."""
    if split not in SPLITS:
        raise ValueError(f"split inconnu : {split} (attendu : {SPLITS})")
    if split == "test" and not final:
        raise TestSplitLocked("Patientes de test verrouillées : relancer avec --final.")
    if not INDEX_CSV.exists():
        raise FileNotFoundError(f"{INDEX_CSV} absent : lancer `python -m scripts.build_index`.")
    with INDEX_CSV.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["split"] == split]
    if not include_duplicates:
        rows = [r for r in rows if r["duplicate_of"] == ""]
    return rows


def page_path(row: dict) -> Path:
    return ROOT / row["path"]
