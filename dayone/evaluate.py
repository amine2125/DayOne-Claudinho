"""Comparaison d'une fiche lue aux valeurs de référence tapées par un humain (annotations/*.csv).

La lecture étant sans gabarit, chaque champ de référence est associé au champ lu dont l'étiquette
lui ressemble le plus (mots en commun).
"""

import csv
from collections import Counter
from pathlib import Path

from dayone.dataset import ROOT
from dayone.normalize import comparable, fold
from dayone.schema import STATUSES, reference_fields

ANNOTATION_DIR = ROOT / "annotations"
COLUMNS = ["field_id", "groupe", "libelle", "type", "value", "status"]
TRUE_WORDS = {"x", "true", "vrai", "oui", "1", "coche"}
MIN_MATCH = 0.5     # part minimale des mots de l'étiquette de référence retrouvés

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
        for f in reference_fields(page_type):
            w.writerow([f.id, f.group, f.label, f.kind, "", ""])


def load_annotation(path: Path, page_type: str) -> dict[str, dict] | None:
    """CSV humain -> {id: {value, status}}. None si le fichier n'a pas encore été rempli.

    Règles de saisie : valeur seule -> KNOWN ; ni valeur ni statut -> NOT_PROVIDED ;
    case cochée : « x » ; « RAS » accepté tel quel.
    """
    fields = reference_fields(page_type)
    with path.open(newline="", encoding="utf-8") as fh:
        rows = {r["field_id"]: r for r in csv.DictReader(fh)}
    if not any((r.get("value") or "").strip() or (r.get("status") or "").strip() for r in rows.values()):
        return None
    missing = {f.id for f in fields} - set(rows)
    if missing:
        raise ValueError(f"{path.name} : champs absents {sorted(missing)}")
    ref = {}
    for f in fields:
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


def _tokens(label: str) -> set[str]:
    return set(fold(label.replace("|", " ").replace("—", " ")).split())


def expand_groups(fields: list[dict]) -> list[dict]:
    """Groupe de cases (« VAT = 1 », options 1 à 5) -> une case par option (« VAT 1 » cochée, « VAT 2 » vide…),
    car la référence liste les cases une par une."""
    out = []
    for f in fields:
        if not f.get("options"):
            out.append(f)
            continue
        checked = {fold(v) for v in str(f["value"] or "").split(",")}
        for opt in f["options"]:
            on = fold(opt) in checked
            status = "KNOWN" if on else "NEEDS_REVIEW" if f["status"] == "NEEDS_REVIEW" else "NOT_PROVIDED"
            out.append({**f, "label": f"{f['label']} {opt}", "kind": "checkbox", "value": True if on else None,
                        "status": status, "options": None})
    return out


def match_fields(page_type: str, pred_fields: list[dict]) -> dict[str, dict]:
    """{id de référence: champ lu}. Association gloutonne, meilleure ressemblance d'abord ;
    à égalité, le premier champ lu (ordre de la page) va au premier champ de référence."""
    refs = reference_fields(page_type)
    pred_fields = expand_groups(pred_fields)
    pairs = []
    for i, r in enumerate(refs):
        rt = _tokens(r.label)
        for j, p in enumerate(pred_fields):
            pt = _tokens(p["label"])
            if not rt or not pt:
                continue
            cover = len(rt & pt) / len(rt)
            if cover >= MIN_MATCH:
                score = cover - 0.1 * len(pt - rt) / len(pt)
                pairs.append((-score, j, i))
    used_r, used_p, out = set(), set(), {}
    for _, j, i in sorted(pairs):
        if i in used_r or j in used_p:
            continue
        used_r.add(i)
        used_p.add(j)
        out[refs[i].id] = pred_fields[j]
    return out


def compare(pred: dict, ref: dict[str, dict], page_type: str) -> list[dict]:
    """Une ligne par champ de référence : statut et valeur des deux côtés, et l'issue."""
    matched = match_fields(page_type, pred["fields"])
    rows = []
    for f in reference_fields(page_type):
        r = ref[f.id]
        p = matched.get(f.id) or {"value": None, "status": "NOT_PROVIDED", "confidence": 0.0, "label": ""}
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
            "field_id": f.id, "kind": f.kind, "table": f.table, "pred_label": p.get("label", ""),
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
