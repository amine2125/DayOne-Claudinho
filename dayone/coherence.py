"""Contrôles de cohérence de la LECTURE : une valeur qui contredit le reste du registre est probablement mal lue.

Ce ne sont pas des contrôles cliniques. Aucun seuil médical (« tension élevée », « anémie ») : les plages
ci-dessous sont celles des valeurs physiquement possibles, pour repérer un chiffre mal lu (« 1047/74 »,
« 84,3 kg » entre 64,3 et 64,8, « 29/1/2025 » pour 29/11/2025). Le message dit toujours « à vérifier sur
le papier », jamais « anormal ». La sage-femme confirme ou corrige ; c'est elle qui décide.

Contrôles :
  - format possible d'une mesure (plage physique, systolique > diastolique) ;
  - suivi d'une visite à l'autre dans le tableau des visites : dates qui avancent, rendez-vous après la
    visite, âge gestationnel cohérent avec la DDR et les dates, valeur isolée très loin des deux visites voisines ;
  - calculs vérifiables : DPA = DDR + 280 j, dépassement = DDR + 287 j, gestité ≥ parité + avortements,
    accouchements listés ≤ parité, âge gestationnel à la naissance cohérent avec la DDR ;
  - cases qui s'excluent (voie basse et césarienne, vivant et mort-né).

Entrée : les pages d'un dossier [(index de page, type de page, champs)]. Sortie : {(index, clé): [alerte]},
alerte = {"code", "params", "text"} (texte en français pour l'agent WhatsApp ; code et paramètres pour
l'interface bilingue).
"""

import re
from datetime import date, timedelta

from dayone import suivi

# Plages des valeurs possibles (repérer une lecture fausse), pas des normes cliniques.
POSSIBLE = {
    "weight": (30, 200),            # kg, mère
    "fundalHeight": (5, 50),        # cm
    "fhr": (60, 220),               # battements / min
    "temperature": (34, 43),        # °C
    "pulse": (30, 220),
    "hemoglobin": (3, 25),          # g/dL
    "headCirc": (20, 60),           # cm, nouveau-né
    "length": (30, 80),             # cm, nouveau-né
}
NEWBORN_WEIGHT = (400, 7000)        # g
SYSTOLIC, DIASTOLIC = (60, 260), (30, 160)
GA_WEEKS = (4, 45)
# Valeur isolée : loin des DEUX visites voisines (dans le même sens) de plus que cet écart.
SPIKE = {"weight": 8, "fundalHeight": 8, "hemoglobin": 4, "bp": 50}
GA_TOLERANCE_WEEKS = 2
EDD_DAYS, TERM_DAYS, DATE_TOLERANCE_DAYS = 280, 287, 4
NAMES = {"weight": "Poids", "fundalHeight": "HU", "fhr": "BCF", "temperature": "Température", "pulse": "Pouls",
         "hemoglobin": "Hémoglobine", "headCirc": "Périmètre crânien", "length": "Taille", "bp": "TA",
         "gaWeeks": "Âge gestationnel"}


def _d(iso: str) -> date:
    return date.fromisoformat(iso[:10])


def _fr(iso: str) -> str:
    d = _d(iso)
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def _num(v) -> str:
    return (f"{v:.1f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)).replace(".", ",")


def _shown(measure: str, v) -> str:
    return f"{v[0]}/{v[1]}" if measure == "bp" else _num(v)


class _Alerts:
    def __init__(self):
        self.out: dict[tuple[int, str], list[dict]] = {}

    def add(self, page: int, key: str | None, code: str, text: str, **params):
        if key is None:
            return
        alerts = self.out.setdefault((page, key), [])
        if not any(a["code"] == code for a in alerts):
            alerts.append({"code": code, "params": params, "text": text + " : à vérifier sur le papier."})


def check_record(pages: list[tuple[int, str, dict]], today: date | None = None) -> dict[tuple[int, str], list[dict]]:
    today = today or date.today()
    al = _Alerts()
    lmp = None                                     # DDR lue sur la page « Grossesse actuelle » du dossier
    delivery = None
    for idx, page_type, fields in pages:
        s = suivi.series(page_type, fields)
        if not s:
            if page_type == "identification_antecedents":
                _obstetric(al, idx, fields)
            continue
        if s["kind"] == "antenatal":
            lmp = _antenatal(al, idx, s, today) or lmp
        elif s["kind"] == "delivery":
            delivery = (idx, s)
            _exclusive(al, idx, fields)
        else:
            for v in s["visits"]:
                _formats(al, idx, v, newborn=s["kind"] == "postpartum_newborn")
                _future(al, idx, v, today)
        if page_type == "identification_antecedents":
            _obstetric(al, idx, fields)
    if delivery and lmp:
        _birth_ga(al, *delivery, lmp)
    return al.out


# ---------------- une visite ----------------

def _formats(al: _Alerts, idx: int, visit: dict, newborn: bool = False) -> None:
    for measure, e in visit["values"].items():
        v = e["value"]
        if measure == "bp":
            s, d = v
            if not (SYSTOLIC[0] <= s <= SYSTOLIC[1] and DIASTOLIC[0] <= d <= DIASTOLIC[1]):
                al.add(idx, e["key"], "format", f"TA {s}/{d} : chiffres impossibles pour une tension", measure="bp", value=f"{s}/{d}")
            elif s <= d:
                al.add(idx, e["key"], "bp_order", f"TA {s}/{d} : le 1er chiffre devrait être le plus grand", value=f"{s}/{d}")
            continue
        if measure == "weight" and newborn:
            lo, hi = NEWBORN_WEIGHT
        elif measure in POSSIBLE:
            lo, hi = POSSIBLE[measure]
        else:
            continue
        if not lo <= v <= hi:
            al.add(idx, e["key"], "format", f"{NAMES[measure]} {_num(v)} : valeur impossible pour ce champ",
                   measure=measure, value=v)
    ga = visit.get("gaWeeks")
    if ga is not None and not GA_WEEKS[0] <= ga <= GA_WEEKS[1]:
        al.add(idx, visit.get("keys", {}).get("gaWeeks"), "format", f"Âge gestationnel {ga} SA : valeur impossible",
               measure="gaWeeks", value=ga)


def _future(al: _Alerts, idx: int, visit: dict, today: date) -> None:
    if visit.get("date") and _d(visit["date"]) > today + timedelta(days=1):
        al.add(idx, visit["keys"]["date"], "future", f"Date {_fr(visit['date'])} : dans le futur", value=visit["date"])


# ---------------- tableau des visites ----------------

def _antenatal(al: _Alerts, idx: int, s: dict, today: date) -> str | None:
    facts, visits = s["facts"], s["visits"]
    lmp = facts.get("lmp", {}).get("value")
    if lmp:
        for name, days, label in (("edd", EDD_DAYS, "DPA"), ("termDate", TERM_DAYS, "Date de dépassement")):
            f = facts.get(name)
            if not f:
                continue
            expected = (_d(lmp) + timedelta(days=days)).isoformat()
            if abs((_d(f["value"]) - _d(expected)).days) > DATE_TOLERANCE_DAYS:
                text = f"{label} {_fr(f['value'])} : la DDR ({_fr(lmp)}) donne le {_fr(expected)}"
                for key in (f["key"], facts["lmp"]["key"]):
                    al.add(idx, key, f"{name}_lmp", text, value=f["value"], expected=expected, lmp=lmp)
    for v in visits:
        _formats(al, idx, v)
        _future(al, idx, v, today)
        keys = v.get("keys", {})
        if v.get("date") and v.get("appointment") and _d(v["appointment"]) <= _d(v["date"]):
            al.add(idx, keys.get("appointment"), "appointment_before_visit",
                   f"Rendez-vous {_fr(v['appointment'])} : avant la visite du {_fr(v['date'])}",
                   value=v["appointment"], visit=v["date"])
        if lmp and v.get("date") and v.get("gaWeeks") is not None:
            expected = round((_d(v["date"]) - _d(lmp)).days / 7)
            if abs(v["gaWeeks"] - expected) > GA_TOLERANCE_WEEKS:
                al.add(idx, keys.get("gaWeeks"), "ga_lmp",
                       f"{v['gaWeeks']} SA lu : la DDR ({_fr(lmp)}) et la date de venue ({_fr(v['date'])}) donnent environ {expected} SA",
                       value=v["gaWeeks"], expected=expected, lmp=lmp, visit=v["date"])
    dated = [v for v in visits if v.get("date")]
    doubtful = set()                        # dates déjà suspectes : on ne s'en sert pas pour juger un autre champ
    for prev, cur in zip(dated, dated[1:]):
        if _d(cur["date"]) <= _d(prev["date"]):
            al.add(idx, cur["keys"]["date"], "date_order",
                   f"Venue le {_fr(cur['date'])} : pas après la visite précédente ({_fr(prev['date'])})",
                   value=cur["date"], previous=prev["date"])
            doubtful.update((id(prev), id(cur)))
    for prev, cur in zip(dated, dated[1:]):
        if id(prev) in doubtful or id(cur) in doubtful:
            continue
        if not lmp and prev.get("gaWeeks") is not None and cur.get("gaWeeks") is not None:
            expected = cur["gaWeeks"] - prev["gaWeeks"]
            weeks = (_d(cur["date"]) - _d(prev["date"])).days / 7
            if abs(expected - weeks) > GA_TOLERANCE_WEEKS:
                al.add(idx, cur["keys"]["gaWeeks"], "ga_dates",
                       f"{cur['gaWeeks']} SA lu : {round(weeks)} semaines après la visite à {prev['gaWeeks']} SA",
                       value=cur["gaWeeks"], previous=prev["gaWeeks"], weeks=round(weeks))
    for measure, tol in SPIKE.items():
        _spikes(al, idx, visits, measure, tol)
    return lmp


def _spikes(al: _Alerts, idx: int, visits: list[dict], measure: str, tol: float) -> None:
    """Valeur loin des deux visites voisines, dans le même sens : chiffre probablement mal lu (6 ↔ 8, 3 ↔ 5)."""
    pts = [(v["values"][measure], v) for v in visits if measure in v["values"]]
    num = (lambda e: e["value"][0]) if measure == "bp" else (lambda e: e["value"])
    for i in range(1, len(pts) - 1):
        a, b, c = num(pts[i - 1][0]), num(pts[i][0]), num(pts[i + 1][0])
        if (b - a) * (b - c) > 0 and min(abs(b - a), abs(b - c)) > tol:
            e = pts[i][0]
            al.add(idx, e["key"], "spike",
                   f"{NAMES[measure]} {_shown(measure, e['value'])} : très loin des visites voisines "
                   f"({_shown(measure, pts[i - 1][0]['value'])} et {_shown(measure, pts[i + 1][0]['value'])})",
                   measure=measure, value=_shown(measure, e["value"]),
                   before=_shown(measure, pts[i - 1][0]["value"]), after=_shown(measure, pts[i + 1][0]["value"]))


# ---------------- antécédents et accouchement ----------------

def _int(fields: dict, key: str) -> int | None:
    f = fields.get(key)
    if not f or f.get("status") not in suivi.USABLE:
        return None
    v = f.get("value")
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _obstetric(al: _Alerts, idx: int, fields: dict) -> None:
    g, p = _int(fields, "gestation"), _int(fields, "parite")
    living, abortions = _int(fields, "enfants_vivants"), _int(fields, "obst_avortement_nombre")
    if g is not None and p is not None and p > g:
        for key in ("parite", "gestation"):
            al.add(idx, key, "parity_gravidity", f"Parité {p} plus grande que la gestité {g}", parity=p, gravidity=g)
    if g is not None and p is not None and abortions is not None and p + abortions > g:
        for key in ("obst_avortement_nombre", "gestation"):
            al.add(idx, key, "obstetric_sum", f"Parité {p} + avortements {abortions} dépassent la gestité {g}",
                   parity=p, abortions=abortions, gravidity=g)
    if p is not None and living is not None and living > p + 1:
        al.add(idx, "enfants_vivants", "living_parity",
               f"{living} enfants vivants pour une parité de {p} (naissances multiples ?)", living=living, parity=p)
    listed = sum(1 for n in range(1, 6) if any(
        fields.get(f"acc{n}_{k}", {}).get("value") not in (None, "") for k in ("date", "modalite", "poids")))
    if p is not None and listed > p:
        al.add(idx, "parite", "deliveries_parity", f"{listed} accouchements antérieurs décrits pour une parité de {p}",
               listed=listed, parity=p)


EXCLUSIVE = [
    ("two_modes", "Voie basse et césarienne cochées ensemble",
     ("mode_voie_basse_non_instrumentale", "mode_voie_basse_instrumentale"),
     ("mode_cesarienne_programmee", "mode_cesarienne_urgence")),
    ("alive_stillborn", "Vivant et mort-né cochés ensemble", ("nn_vivant",), ("nn_mort_ne",)),
]


def _exclusive(al: _Alerts, idx: int, fields: dict) -> None:
    ticked = {k for k, f in fields.items() if f.get("value") is True}
    for code, text, left, right in EXCLUSIVE:
        a, b = ticked & set(left), ticked & set(right)
        if a and b:
            for key in sorted(a | b):
                al.add(idx, key, code, text)


def _birth_ga(al: _Alerts, idx: int, s: dict, lmp: str) -> None:
    facts = s["facts"]
    born, ga = facts.get("date"), facts.get("gaWeeks")
    if not born or not ga:
        return
    expected = round((_d(born["value"]) - _d(lmp)).days / 7)
    if abs(ga["value"] - expected) > GA_TOLERANCE_WEEKS:
        al.add(idx, ga["key"], "birth_ga",
               f"{_num(ga['value'])} SA à la naissance : la DDR ({_fr(lmp)}) et la date d'accouchement donnent environ {expected} SA",
               value=ga["value"], expected=expected, lmp=lmp)


# ---------------- une lecture possible ? ----------------

BP_TEXT = re.compile(r"\d{1,3}(?:[.,]\d)?\s*[/\\]\s*\d{1,3}(?:[.,]\d)?\s*(?:[mc]m ?hg)?", re.IGNORECASE)

def plausible(label: str, text: str) -> bool | None:
    """La valeur écrite est-elle possible pour cette ligne du registre (« TA », « HU (cm) », « BCF ») ?

    None si la ligne n'est pas une mesure connue. Sert à choisir entre deux lectures d'un même trait
    (« |27 » : bordure de case ou chiffre 1 ?), jamais à juger la valeur.
    """
    measure = suivi._measure_of(label)
    if measure == "bp":
        if not BP_TEXT.fullmatch(text.strip()):
            return False
        bp = suivi.blood_pressure(text)
        return bool(bp) and SYSTOLIC[0] <= bp[0] <= SYSTOLIC[1] and DIASTOLIC[0] <= bp[1] <= DIASTOLIC[1] \
            and bp[0] > bp[1]
    n = suivi._number(text)
    if measure == "gaWeeks":
        return n is not None and GA_WEEKS[0] <= n <= GA_WEEKS[1]
    if measure == "weight":
        kg = n is not None and ("kg" in label.lower() or n >= 25)
        return n is not None and ((POSSIBLE["weight"][0] <= n <= POSSIBLE["weight"][1]) if kg
                                  else (NEWBORN_WEIGHT[0] <= n <= NEWBORN_WEIGHT[1] or n < 10))
    if measure in POSSIBLE:
        lo, hi = POSSIBLE[measure]
        return n is not None and lo <= n <= hi
    return None


# ---------------- appliquer aux champs ----------------

def apply(fields: dict, alerts: dict[str, list[dict]]) -> bool:
    """Pose les alertes sur les champs d'une page ; renvoie True si quelque chose a changé.

    - Champ encore tel que lu par l'IA : l'alerte y est posée ; s'il était KNOWN il passe NEEDS_REVIEW
      (raison « incoherent »), pour que l'agent WhatsApp le fasse vérifier.
    - Champ confirmé ou corrigé par la sage-femme : jamais d'alerte (elle a regardé le papier).
    - Alerte disparue (une autre valeur a été corrigée) : le champ retrouve son statut de lecture.
    """
    changed = False
    for key, f in fields.items():
        mine = alerts.get(key) if f.get("origin", "AI") == "AI" else None
        before = (f.get("alerts"), f.get("status"), f.get("reason"), f.get("coherence"))
        if mine:
            f["alerts"] = mine
            if f["status"] == "KNOWN":
                f.update(status="NEEDS_REVIEW", coherence=True)
                f.setdefault("reason", "incoherent")
        else:
            f.pop("alerts", None)
            if f.pop("coherence", False) and f.get("origin", "AI") == "AI" and f["status"] == "NEEDS_REVIEW":
                f["status"] = "KNOWN"
                if f.get("reason") == "incoherent":
                    f.pop("reason")
        changed |= before != (f.get("alerts"), f.get("status"), f.get("reason"), f.get("coherence"))
    return changed
