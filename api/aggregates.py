"""Agrégats anonymes pour le système de santé (tableau de bord, rôles superviseur et épidémiologiste).

- Calculés ici, côté serveur : le navigateur ne reçoit que des comptes, jamais un dossier ni un code patiente.
- Petits effectifs masqués : un compte entre 1 et K-1 femmes est renvoyé `null` (affiché « < 5 »), pour
  qu'aucune femme ne soit reconnaissable dans une case. Moins de K femmes en tout : rien n'est montré.
- Registre : seulement les femmes liées à un dossier (une femme = une fois), et seulement les valeurs
  sûres ou vérifiées (KNOWN) ; une valeur encore « à vérifier » n'est pas comptée.
- Aucune norme clinique : des distributions et des comptes, pas de seuil (« tension élevée »), pas de risque.

Deux sources : la base locale (`registry`) et le jeu synthétique fourni (`synthetic`, 200 femmes), qui sert
à montrer l'usage tant que la base compte peu de patientes.
"""

import csv
from collections import Counter
from datetime import datetime, timezone
from statistics import mean

from api import store
from dayone import suivi
from dayone.dataset import ROOT

K = 5
SYNTHETIC_CSV = ROOT / "data" / "maternal_registry_synthetic.csv"

# Classes des histogrammes : (début, fin, pas). Une classe de plus de chaque côté pour les valeurs hors plage.
BINS = {
    "systolic": (70, 160, 10),
    "diastolic": (40, 110, 10),
    "temperature": (35.0, 40.0, 0.5),
    "hemoglobin": (7, 16, 1),
    "birthWeight": (1500, 5000, 500),
    "gaAtBirth": (30, 44, 2),
}
TESTS = ("hiv", "syphilis", "hbs", "hcv")
TRIMESTER_WEEKS = (13, 27)          # 1er trimestre ≤ 13 SA, 2e ≤ 27 SA, 3e ensuite
PRETERM_WEEKS = 37                  # définition (avant 37 SA), pas un jugement


def _mask(n: int) -> int | None:
    return None if 0 < n < K else n


def _histogram(values: list[float], name: str) -> dict:
    lo, hi, step = BINS[name]
    edges = []
    x = lo
    while x < hi:
        edges.append(x)
        x = round(x + step, 2)
    counts = Counter()
    for v in values:
        if v < lo:
            counts["low"] += 1
        elif v >= hi:
            counts["high"] += 1
        else:
            counts[min(int((v - lo) // step), len(edges) - 1)] += 1
    bins = [{"from": None, "to": lo, "count": _mask(counts["low"])}]
    bins += [{"from": e, "to": round(e + step, 2), "count": _mask(counts[i])} for i, e in enumerate(edges)]
    bins.append({"from": hi, "to": None, "count": _mask(counts["high"])})
    return {"n": len(values), "bins": bins}


def _counts(counter: Counter, keys: tuple[str, ...]) -> dict:
    return {k: _mask(counter.get(k, 0)) for k in keys}


# ---------------- une femme ----------------

def _woman(pages: list[tuple[str, dict]]) -> dict:
    """Ce qu'on compte pour une femme, à partir de ses pages (de la plus ancienne à la plus récente)."""
    w: dict = {"antenatal": False, "tests": {}, "sbp": [], "dbp": [], "temp": [], "hb": [], "visits": set()}
    for page_type, fields in pages:
        sure = {k: f for k, f in fields.items() if f.get("status") == "KNOWN"}
        s = suivi.series(page_type, sure)
        if page_type == "grossesse_actuelle":
            w["antenatal"] = True
            for f in fields.values():           # ligne du test présente sur la page, même vide
                m = suivi._measure_of(str(f.get("label", "")))
                if m in TESTS:
                    w["tests"].setdefault(m, "notRecorded")
        if not s:
            continue
        if s["kind"] == "delivery":
            facts = s["facts"]
            w["mode"] = facts.get("mode", {}).get("value") or w.get("mode")
            if "place" in facts:
                w["place"] = _place(facts["place"]["keys"])
            for name in ("birthWeight", "gaWeeks"):
                if name in facts:
                    w[name] = facts[name]["value"]
            continue
        for v in s["visits"]:
            vals = v["values"]
            if s["kind"] == "antenatal":
                if v.get("date"):
                    w["visits"].add(v["date"])
                if v.get("gaWeeks") is not None:
                    w["firstGa"] = min(w.get("firstGa", 99), v["gaWeeks"])
                if "bp" in vals:
                    w["sbp"].append(vals["bp"]["value"][0])
                    w["dbp"].append(vals["bp"]["value"][1])
                if "hemoglobin" in vals:
                    w["hb"].append(vals["hemoglobin"]["value"])
                for t in TESTS:
                    code = vals.get(t, {}).get("code")
                    if code in ("pos", "neg"):
                        w["tests"][t] = "pos" if code == "pos" or w["tests"].get(t) == "pos" else "neg"
            elif s["kind"] == "postpartum_mother" and "temperature" in vals:
                w["temp"].append(vals["temperature"]["value"])
    return w


PLACES = ("maternite", "clinique_privee", "maison_accouchement", "domicile", "autre")


def _place(keys: list[str]) -> str:
    """Lieu le plus précis coché (« En milieu surveillé » n'est que l'intitulé du groupe)."""
    ticked = {k.removeprefix("lieu_") for k in keys}
    return next((p for p in PLACES if p in ticked), "autre")


def _registry_women() -> list[dict]:
    with store.db() as c:
        women = []
        for p in c.execute("SELECT id FROM patients").fetchall():
            pages = []
            for r in c.execute("""SELECT pg.* FROM pages pg JOIN records r ON r.id = pg.record_id
                                  WHERE r.patient_id = ? AND pg.fields_enc IS NOT NULL
                                  ORDER BY r.created_at, pg.idx""", (p["id"],)).fetchall():
                fields = store._load_fields(r)
                pages.append((store._page_type(r["page_type"], fields), fields))
            women.append(_woman(pages))
        return women


def _synthetic_women() -> list[dict]:
    def num(row, col):
        v = (row.get(col) or "").strip()
        try:
            return float(v)
        except ValueError:
            return None

    women = []
    with SYNTHETIC_CSV.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            w: dict = {"antenatal": True, "tests": {}, "temp": [], "visits": set()}
            sbp, dbp, hb = (num(row, c) for c in ("mean systolic bp (mmhg)", "mean diastolic bp (mmhg)", "hemoglobin (g/dl)"))
            w["sbp"], w["dbp"], w["hb"] = ([sbp] if sbp else []), ([dbp] if dbp else []), ([hb] if hb else [])
            for t, col in (("hiv", "hiv test result"), ("syphilis", "syphilis test result"), ("hcv", "hepatitis c test result")):
                v = num(row, col)
                w["tests"][t] = "notRecorded" if v is None else ("pos" if v == 1 else "neg")
            ga0 = num(row, "gestational age at enrollment (weeks)")
            if ga0 is not None:
                w["firstGa"] = ga0
            mode = num(row, "type of delivery (0=vaginal,1=cesarean)")
            if mode is not None:
                w["mode"] = "cesarean" if mode == 1 else "vaginal"
            for name, col in (("birthWeight", "child birth weight (g)"), ("gaWeeks", "gestational age at birth (weeks)")):
                v = num(row, col)
                if v is not None:
                    w[name] = v
            women.append(w)
    return women


# ---------------- les agrégats ----------------

def build(source: str = "registry") -> dict:
    women = _synthetic_women() if source == "synthetic" else _registry_women()
    out = {"source": source, "k": K, "women": len(women), "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if len(women) < K:
        return {**out, "women": _mask(len(women)), "suppressed": True, "panels": {}}

    def with_values(key):
        return [mean(w[key]) for w in women if w.get(key)]

    def trimester(ga):
        return "t1" if ga <= TRIMESTER_WEEKS[0] else "t2" if ga <= TRIMESTER_WEEKS[1] else "t3"

    sbp, dbp, temp, hb = with_values("sbp"), with_values("dbp"), with_values("temp"), with_values("hb")
    tests = []
    for t in TESTS:
        if not any(t in w["tests"] for w in women):
            continue                        # test absent de cette source (Ag HBs du registre, VHC du jeu synthétique)
        c = Counter(w["tests"].get(t) or ("notRecorded" if w["antenatal"] else "noPage") for w in women)
        tests.append({"test": t, **_counts(c, ("pos", "neg", "notRecorded", "noPage"))})
    births = [w for w in women if w.get("mode") or w.get("birthWeight")]
    ga_birth = [w["gaWeeks"] for w in women if w.get("gaWeeks")]
    panels = {
        "bp": {"systolic": _histogram(sbp, "systolic"), "diastolic": _histogram(dbp, "diastolic")} if sbp else None,
        "temperature": _histogram(temp, "temperature") if temp else None,
        "hemoglobin": _histogram(hb, "hemoglobin") if hb else None,
        "tests": tests,
        "anc": {
            "firstVisit": _counts(Counter(trimester(w["firstGa"]) for w in women if "firstGa" in w), ("t1", "t2", "t3")),
            "visitCounts": _counts(Counter(str(min(len(w["visits"]), 9)) for w in women if w["visits"]),
                                   tuple(str(i) for i in range(1, 10))) if any(w["visits"] for w in women) else None,
        },
        "delivery": {
            "n": len(births),
            "mode": _counts(Counter(w.get("mode") for w in births if w.get("mode")), ("vaginal", "cesarean")),
            "place": _counts(Counter(w["place"] for w in births if w.get("place")), PLACES),
            "birthWeight": _histogram([w["birthWeight"] for w in births if w.get("birthWeight")], "birthWeight"),
            "gaAtBirth": _histogram(ga_birth, "gaAtBirth"),
            "preterm": _counts(Counter("preterm" if g < PRETERM_WEEKS else "term" for g in ga_birth), ("preterm", "term")),
        },
        "completeness": [
            {"measure": m, "recorded": _mask(n), "total": len(women)}
            for m, n in (("bp", len(sbp)), ("hemoglobin", len(hb)), ("hiv", sum(w["tests"].get("hiv") in ("pos", "neg") for w in women)),
                         ("syphilis", sum(w["tests"].get("syphilis") in ("pos", "neg") for w in women)),
                         ("birthWeight", sum(1 for w in births if w.get("birthWeight"))))
        ],
    }
    return {**out, "panels": panels}
