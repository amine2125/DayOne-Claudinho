"""Mesures suivies d'une visite à l'autre (poids, TA, HU, BCF, T°…), tirées des champs d'une page lue.

Aucune logique clinique : une ligne du registre est reconnue par son libellé imprimé (« Poids (kg) »),
une valeur par son format (« 104/74 », « 11.8 g/dL »). Pas de seuil, pas d'interprétation : ce module ne
dit jamais si une valeur est bonne ou mauvaise. Il alimente les courbes du tableau de bord, les contrôles
de cohérence de la lecture (dayone/coherence.py) et les agrégats anonymes (api/aggregates.py).

Entrée : les champs d'une page au format de l'API ({clé: {label, kind, value, status, origin, column…}}).
Sortie : {"kind", "facts", "visits"} ; chaque visite porte sa colonne, sa date, son âge gestationnel, le
rendez-vous écrit et ses valeurs (avec la clé du champ d'origine : on remonte toujours au papier).
"""

import re
from datetime import date

from dayone.normalize import fold

# Statuts d'une valeur qu'on peut montrer sur une courbe (à vérifier : montrée, mais marquée comme telle).
USABLE = ("KNOWN", "NEEDS_REVIEW")

# Ligne du registre -> mesure. Libellé replié, partie avant « | » (la colonne est à part). Premier motif gagnant.
ROWS = [
    ("date", r"^venue le$|^date de (la )?consultation$|^date de (la )?visite$"),
    ("appointment", r"rendez vous|^revenir\b|^rdv\b"),
    ("gaWeeks", r"^age probable$|^age gestationnel$"),
    ("weight", r"^poids\b"),
    ("bp", r"^ta$|^t a$|^tension( arterielle)?$"),
    ("fundalHeight", r"^hu\b|hauteur uterine"),
    ("fhr", r"^bcf\b|bruits? du coeur"),
    ("temperature", r"^temperature\b|^t$|^t c$"),
    ("pulse", r"^pouls\b"),
    ("hemoglobin", r"^hemoglobine\b|^hb$"),
    ("glycemia", r"^bilan glycemique|^glycemie"),
    ("albuminuria", r"^albuminurie|^proteinurie"),
    ("glycosuria", r"^glucosurie|^glycosurie"),
    ("oedema", r"^o?edemes?$"),
    ("fetalMovements", r"^mouvements actifs"),
    ("hiv", r"\bvih\b|\bhiv\b"),
    ("syphilis", r"syphilis|\btpha\b|\bvdrl\b"),
    ("hbs", r"\bag ?hbs\b|^hbs\b"),
    ("hcv", r"hepatite c\b|\bvhc\b|\bhcv\b"),
    ("toxo", r"^toxoplasmose"),
    ("rubella", r"^rubeole$"),
    ("iron", r"^fer$"),
    ("headCirc", r"perimetre cranien"),
    ("length", r"^taille$"),
    ("ageDays", r"^age$"),
]
NUMERIC = ("weight", "fundalHeight", "fhr", "temperature", "pulse", "hemoglobin", "glycemia", "headCirc", "length")
TESTS = ("hiv", "syphilis", "hbs", "hcv", "toxo", "rubella")
CATEGORICAL = ("albuminuria", "glycosuria", "oedema", "fetalMovements", "iron") + TESTS
UNITS = {"weight": "kg", "fundalHeight": "cm", "fhr": "bpm", "temperature": "°C", "pulse": "bpm",
         "hemoglobin": "g/dL", "glycemia": "g/L", "headCirc": "cm", "length": "cm", "bp": "mmHg"}

# Colonnes du tableau des visites quand la lecture n'a pas donné leur numéro (ancienne lecture) :
# on se repère sur l'intitulé imprimé. Sans numéro ni intitulé reconnu, la valeur n'est pas placée.
VISIT_COLUMNS = ["1er trimestre visite 1", "1er trimestre visite 2", "1er trimestre visite 3",
                 "2eme trimestre visite 1", "2eme trimestre visite 2", "2eme trimestre visite 3",
                 "3eme trimestre 7eme mois", "3eme trimestre 8eme mois", "3eme trimestre 9eme mois"]

KIND_OF_PAGE = {
    "grossesse_actuelle": "antenatal",
    "accouchement": "delivery",
    "postpartum_precoce_mere": "postpartum_mother",
    "postpartum_tardif_mere": "postpartum_mother",
    "postpartum_precoce_nouveau_ne": "postpartum_newborn",
    "postpartum_tardif_nouveau_ne": "postpartum_newborn",
}


# ---------------- reconnaître la page ----------------

def _rows(fields) -> set[str]:
    return {fold(str(f.get("label", "")).split("|")[0]) for f in fields}


ANTENATAL_ROWS = {"venue le", "age probable", "hu cm", "bcf", "glucosurie", "albuminurie", "poids kg",
                  "examen des seins", "mouvements actifs", "anomalies squelette"}
MOTHER_HINTS = ("pouls", "lochies", "perinee", "globe uterin", "sphincters", "mollets", "desire utiliser")
NEWBORN_HINTS = ("allaitement", "bcg", "refus de teter", "nouveau ne premature", "vaccins administres",
                 "tirage sous costal", "supplementation en vitamine d")


def page_type_from_labels(fields) -> str | None:
    """Type de page du registre d'après les libellés imprimés lus (le titre lu n'est pas fiable).

    Seulement quand c'est net ; sinon None (la page reste « non reconnue », rien n'est inventé).
    Post-partum précoce ou tardif : la page de la mère précoce porte « 7ème et 8ème jour » ; celle du
    nouveau-né se distingue par l'âge écrit (jours). `fields` : les champs lus (liste ou valeurs d'un dict).
    """
    fields = list(fields.values()) if isinstance(fields, dict) else list(fields)
    rows = _rows(fields)
    text = " ".join(rows)
    if len(rows & ANTENATAL_ROWS) >= 3 or {"ddr", "date prevue d accouchement"} <= rows:
        return "grossesse_actuelle"
    newborn = "perimetre cranien" in text and any(h in text for h in NEWBORN_HINTS)
    mother = sum(h in text for h in MOTHER_HINTS) >= 2
    if mother and not newborn:
        early = re.search(r"7eme et 8eme jour|apres le 8eme jour", text)
        return "postpartum_precoce_mere" if early else "postpartum_tardif_mere"
    if newborn and not mother:
        age = next((_age_days(f.get("value")) for f in fields
                    if fold(str(f.get("label", ""))) == "age" and f.get("status") in USABLE), None)
        if age is None:
            return None
        return "postpartum_precoce_nouveau_ne" if age <= 21 else "postpartum_tardif_nouveau_ne"
    return None


# ---------------- lire une valeur ----------------

def _number(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"\d+(?:[.,]\d+)?", str(value))
    return float(m.group().replace(",", ".")) if m else None


def _age_days(value) -> int | None:
    """« 7 jours » -> 7 ; « 6 sem » -> 42 ; nombre seul -> jours."""
    n = _number(value)
    if n is None:
        return None
    t = fold(str(value))
    if re.search(r"\bsem|\bsemaines?\b|\bweeks?\b", t):
        return int(n * 7)
    if re.search(r"\bmois\b|\bmonths?\b", t):
        return int(n * 30)
    return int(n)


def blood_pressure(value) -> list[int] | None:
    """« 104/74 » -> [104, 74] ; « 12/8 » (cmHg, courant sur le papier) -> [120, 80]."""
    if value is None or isinstance(value, bool):
        return None
    m = re.search(r"(\d{2,3}(?:[.,]\d)?)\s*[/\\]\s*(\d{1,3}(?:[.,]\d)?)", str(value))
    if not m:
        return None
    s, d = (float(g.replace(",", ".")) for g in m.groups())
    if s < 30 and d < 30:                 # cmHg
        s, d = s * 10, d * 10
    return [round(s), round(d)]


def _iso(value) -> str | None:
    """Date ISO (déjà normalisée par la lecture) ou JJ/MM/AAAA écrite."""
    if not value or isinstance(value, bool):
        return None
    t = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        return t
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})", re.sub(r"\s+", "", t))
    if not m:
        return None
    d, mo, y = (int(g) for g in m.groups())
    y += 2000 if y < 100 else 0
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def category(measure: str, value) -> str | None:
    """Code d'une valeur écrite en mots : neg, pos, traces, immune, non_immune, yes, no. Sinon None."""
    if value is True:
        return "yes"
    if value is None or value is False:
        return None
    t = fold(str(value))
    if measure in TESTS:
        if re.search(r"non immun", t):
            return "non_immune"
        if re.search(r"immun", t):
            return "immune"
    if re.fullmatch(r"neg\w*|negati\w*|-|0|absent\w*|negative", t):
        return "neg"
    if re.fullmatch(r"pos\w*|positi\w*|\+{1,4}|present\w*", t):
        return "pos"
    if re.search(r"trace", t):
        return "traces"
    if re.fullmatch(r"oui|yes|o", t):
        return "yes"
    if re.fullmatch(r"non|no|aucun\w*|ras|n", t):
        return "no"
    return None


def _weight_kg(f: dict) -> float | None:
    """Poids de la mère en kg. La lecture range les poids en grammes (« 58.8 kg » -> 58800)."""
    n = _number(f.get("value"))
    if n is None:
        return None
    if f.get("kind") == "weight" and n >= 1000:
        return round(n / 1000, 1)
    return round(n, 1)


def _weight_g(f: dict) -> int | None:
    """Poids d'un nouveau-né en grammes (« 3,2 kg » écrit -> 3200)."""
    n = _number(f.get("value"))
    if n is None:
        return None
    return int(round(n * 1000)) if n < 10 else int(round(n))


def _measure_of(label: str) -> str | None:
    row = fold(label.split("|")[0])
    return next((m for m, pat in ROWS if re.search(pat, row)), None)


def _column_of(f: dict) -> int | None:
    col = f.get("column", f.get("colonne"))
    if isinstance(col, int):
        return col
    head = fold(str(f.get("label", "")).split("|", 1)[1]) if "|" in str(f.get("label", "")) else ""
    head = re.sub(r"\s+", " ", head.replace(" - ", " "))
    return VISIT_COLUMNS.index(head) + 1 if head in VISIT_COLUMNS else None


def _entry(f: dict, value, **extra) -> dict:
    out = {"value": value, "key": f["key"], "status": f.get("status"), "origin": f.get("origin", "AI")}
    if f.get("alerts"):
        out["alerts"] = f["alerts"]
    return {**out, **extra}


def _value(measure: str, f: dict, page_kind: str):
    """Valeur typée d'un champ pour une mesure, ou None si on ne sait pas la lire sans deviner."""
    v = f.get("value")
    if measure == "weight":
        return _weight_g(f) if page_kind == "postpartum_newborn" else _weight_kg(f)
    if measure == "bp":
        return blood_pressure(v)
    if measure in ("date", "appointment"):
        return _iso(v)
    if measure == "gaWeeks":
        n = _number(v)
        return int(n) if n is not None else None
    if measure == "ageDays":
        return _age_days(v)
    if measure in NUMERIC:
        return _number(v)
    if measure in CATEGORICAL:
        return v if isinstance(v, str) and v.strip() else (True if v is True else None)
    return None


# ---------------- la page entière ----------------

FACT_LABELS = {
    "lmp": r"^ddr$|date des dernieres regles",
    "edd": r"^date prevue d accouchement$|^dpa$",
    "termDate": r"^date de depassement de terme$",
    "height": r"^taille$",
}
DELIVERY_FACTS = {"date": "date_accouchement", "birthWeight": "nn_poids", "headCirc": "nn_perimetre_cranien",
                  "gaWeeks": "nn_age_gestationnel", "sex": "nn_sexe"}


def series(page_type: str, fields: dict) -> dict | None:
    """Mesures d'une page : {"kind", "facts", "visits"} ; None si la page n'en porte pas."""
    kind = KIND_OF_PAGE.get(page_type)
    if kind is None:
        return None
    usable = {k: f for k, f in fields.items() if f.get("status") in USABLE and f.get("value") not in (None, "")}
    if kind == "delivery":
        return _delivery(usable)
    facts: dict = {}
    visits: dict = {}                       # colonne (ou 0 : page d'une seule visite) -> visite
    for f in usable.values():
        label = str(f.get("label", ""))
        if kind == "antenatal" and "|" not in label:
            row = fold(label)
            for name, pat in FACT_LABELS.items():
                if re.search(pat, row):
                    val = _number(f["value"]) if name == "height" else _iso(f["value"])
                    if val is not None:
                        facts[name] = _entry(f, val)
                    break
            continue
        measure = _measure_of(label)
        if measure is None or (measure == "ageDays" and kind != "postpartum_newborn"):
            continue
        if measure == "length" and kind != "postpartum_newborn":
            continue
        col = _column_of(f) if kind == "antenatal" else 0
        if col is None:
            continue                        # pas de colonne sûre : on ne place pas la valeur
        val = _value(measure, f, kind)
        if val is None:
            continue
        visit = visits.setdefault(col, {"column": col if kind == "antenatal" else None, "values": {}})
        if measure in ("date", "appointment", "gaWeeks", "ageDays"):
            visit[measure] = val
            visit.setdefault("keys", {})[measure] = f["key"]
        else:
            extra = {"code": category(measure, val)} if measure in CATEGORICAL else {}
            visit["values"][measure] = _entry(f, val, **extra)
    out_visits = [v for _, v in sorted(visits.items()) if v["values"] or v.get("date")]
    if not out_visits and not facts:
        return None
    return {"kind": kind, "facts": facts, "visits": out_visits}


def _delivery(usable: dict) -> dict | None:
    facts = {}
    for name, key in DELIVERY_FACTS.items():
        f = usable.get(key)
        if f is None:
            continue
        val = {"date": _iso, "birthWeight": lambda v: _weight_g({"value": v}),
               "headCirc": _number, "gaWeeks": _number, "sex": lambda v: v}[name](f["value"])
        if val is not None:
            facts[name] = _entry(f, val)
    modes = [k for k in usable if k.startswith("mode_") and usable[k]["value"] is True]
    places = [k for k in usable if k.startswith("lieu_") and usable[k]["value"] is True]
    if modes:
        facts["mode"] = {"value": "cesarean" if any("cesarienne" in m for m in modes) else "vaginal", "keys": modes}
    if places:
        facts["place"] = {"value": places[0].removeprefix("lieu_"), "keys": places}
    return {"kind": "delivery", "facts": facts, "visits": []} if facts else None
