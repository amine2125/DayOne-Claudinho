"""Comparaison d'une prédiction aux valeurs de référence tapées par un humain (annotations/*.csv)."""

import csv
from collections import Counter
from pathlib import Path

from dayone.dataset import ROOT
from dayone.normalize import comparable, fold
from dayone.schema import STATUSES, load_schema

ANNOTATION_DIR = ROOT / "annotations"
COLUMNS = ["field_id", "groupe", "libelle", "type", "value", "status"]
TRUE_WORDS = {"x", "true", "vrai", "oui", "1", "coche"}

# Issue d'un champ, du meilleur au pire.
OUTCOMES = ("correct", "a_revoir", "statut_different", "manque", "erreur_silencieuse")


def annotation_path(page_number: int, page_type: str) -> Path:
    return ANNOTATION_DIR / f"page_{int(page_number):02d}_{page_type}.csv"


def write_template(path: Path, page_type: str) -> None:
    """Modèle vide : la liste des champs, sans aucune valeur (jamais rempli par l'IA)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        for f in load_schema(page_type).fields:
            w.writerow([f.id, f.group, f.label, f.kind, "", ""])


def load_annotation(path: Path, page_type: str) -> dict[str, dict] | None:
    """CSV humain -> {id: {value, status}}. None si le fichier n'a pas encore été rempli.

    Règles de saisie : valeur seule -> KNOWN ; ni valeur ni statut -> NOT_PROVIDED ;
    case cochée : « x » ; « RAS » accepté tel quel.
    """
    schema = load_schema(page_type)
    with path.open(newline="", encoding="utf-8") as fh:
        rows = {r["field_id"]: r for r in csv.DictReader(fh)}
    if not any((r.get("value") or "").strip() or (r.get("status") or "").strip() for r in rows.values()):
        return None
    missing = {f.id for f in schema.fields} - set(rows)
    if missing:
        raise ValueError(f"{path.name} : champs absents {sorted(missing)}")
    ref = {}
    for f in schema.fields:
        value = (rows[f.id].get("value") or "").strip()
        status = (rows[f.id].get("status") or "").strip().upper()
        if status and status not in STATUSES:
            raise ValueError(f"{path.name} / {f.id} : statut inconnu « {status} »")
        if not status:
            status = "KNOWN" if value else "NOT_PROVIDED"
        if f.kind == "checkbox" and status == "KNOWN":
            v = fold(value)
            value = True if v in TRUE_WORDS else False if v in {"false", "faux", "non", "0"} else value
        ref[f.id] = {"value": value if status == "KNOWN" else None, "status": status}
    return ref


def compare(pred: dict, ref: dict[str, dict]) -> list[dict]:
    """Une ligne par champ : statut et valeur des deux côtés, et l'issue."""
    schema = load_schema(pred["page_type"])
    rows = []
    for f in schema.fields:
        p, r = pred["fields"][f.id], ref[f.id]
        same_value = comparable(f.kind, p["value"]) == comparable(f.kind, r["value"])
        if p["status"] == "NEEDS_REVIEW":
            outcome = "a_revoir"
        elif r["status"] == "KNOWN":
            if p["status"] == "KNOWN":
                outcome = "correct" if same_value else "erreur_silencieuse"
            else:
                outcome = "manque"
        elif p["status"] == "KNOWN":
            outcome = "erreur_silencieuse"   # valeur inventée là où la référence n'en a pas
        else:
            outcome = "correct" if p["status"] == r["status"] else "statut_different"
        rows.append({
            "field_id": f.id, "kind": f.kind, "table": f.table,
            "ref_status": r["status"], "ref_value": r["value"],
            "pred_status": p["status"], "pred_value": p["value"], "confidence": p["confidence"],
            "outcome": outcome,
        })
    return rows


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"champs": 0}
    c = Counter(r["outcome"] for r in rows)
    known = [r for r in rows if r["ref_status"] == "KNOWN"]
    known_ok = sum(r["outcome"] == "correct" for r in known)
    auto = [r for r in rows if r["pred_status"] != "NEEDS_REVIEW"]
    return {
        "champs": n,
        "issues": {o: c.get(o, 0) for o in OUTCOMES},
        "exactitude_globale": round(c.get("correct", 0) / n, 3),
        "valeurs_connues_justes": f"{known_ok}/{len(known)}",
        "exactitude_valeurs_connues": round(known_ok / len(known), 3) if known else None,
        "part_a_revoir": round(c.get("a_revoir", 0) / n, 3),
        "exactitude_sans_revue": round(sum(r["outcome"] == "correct" for r in auto) / len(auto), 3) if auto else None,
        "erreurs_silencieuses": c.get("erreur_silencieuse", 0),
    }
