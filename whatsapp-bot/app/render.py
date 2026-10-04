"""Mise en forme WhatsApp des pages lues par l'API DayOne, et lecture des corrections.

Une page vient de GET /api/records/{id} :
    {"index": 0, "pageType": "...", "title": "...", "error": "..." (si illisible),
     "fields": {"age": {"label": "Age", "kind": "integer", "section": "Identification",
                        "value": 31, "status": "KNOWN", ...}, ...}}

Chaque champ porte un numéro (sa position dans la liste affichée) : c'est ce numéro que
l'utilisateur tape pour corriger. Le même ordre sert à l'affichage et à la correction.
"""

import re
from dataclasses import dataclass
from datetime import date

# Statuts qui ont quelque chose à montrer (les cases vides et non applicables sont tues)
SHOWN_STATUSES = ("KNOWN", "UNKNOWN", "NEEDS_REVIEW", "ILLEGIBLE")
# Statuts qui demandent l'œil de la sage-femme (les mêmes que l'API : store.TO_REVIEW)
UNCERTAIN_STATUSES = ("NEEDS_REVIEW", "ILLEGIBLE")

PAGE_NAMES = {"identification_antecedents": "Identification et antécédents", "accouchement": "Accouchement"}
UNITS = {"weight": "g", "length": "cm", "weeks": "SA"}
NUMERIC_KINDS = ("integer", "weight", "length", "weeks")
UNKNOWN_WORDS = {"?", "??", "inconnu", "inconnue", "nsp", "ne sait pas"}
# « aucun » n'en fait pas partie : c'est une vraie réponse sur le registre (antécédents)
EMPTY_WORDS = {"-", "vide", "non renseigné"}
YES_WORDS = {"oui", "o", "x", "coché", "coche", "vrai", "yes"}
NO_WORDS = {"non", "n", "faux", "no", "pas coché"}
KIND_HINTS = {
    "integer": "un nombre (ex. 3)",
    "weight": "un poids en grammes (ex. 3250)",
    "length": "une longueur en cm (ex. 34)",
    "weeks": "un nombre de semaines (ex. 39)",
    "date": "une date JJ/MM/AAAA (ex. 06/02/2026)",
    "checkbox": "*oui* ou *non*",
    "sex": "*F* ou *M*",
    "text": "le texte tel qu'écrit sur la page",
}
REASONS = {
    "non_rattache": "écriture rattachée à aucun champ",
    "etiquette_douteuse": "étiquette mal lue",
    "champ_nouveau": "champ inconnu du registre",
    "choix_nouveau": "case inconnue du registre",
    "valeur_douteuse": "lecture incertaine",
    "lieu_corrige": "nom de lieu corrigé",
    "etiquette_manuscrite": "nom du champ écrit à la main",
}
LINK_REASONS = {
    "SAME_CODE": "même code",
    "SIMILAR_CODE": "code proche",
    "SAME_AGE": "même âge",
    "CLOSE_AGE": "âge proche",
    "SAME_GESTATION": "même gestation",
}


@dataclass(frozen=True)
class NumberedField:
    number: int
    key: str
    field: dict

    @property
    def label(self) -> str:
        return self.field.get("label") or self.key.replace("_", " ").capitalize()

    @property
    def kind(self) -> str:
        return self.field.get("kind") or "text"


def page_name(page: dict) -> str:
    return PAGE_NAMES.get(page.get("pageType", "")) or page.get("title") or "Page"


def numbered_fields(page: dict) -> list[NumberedField]:
    """Champs regroupés par section (dans l'ordre où les sections apparaissent), puis numérotés."""
    sections: dict[str, list[tuple[str, dict]]] = {}
    for key, field in page.get("fields", {}).items():
        sections.setdefault(field.get("section", ""), []).append((key, field))
    ordered = [item for items in sections.values() for item in items]
    return [NumberedField(i, key, field) for i, (key, field) in enumerate(ordered, start=1)]


def by_number(page: dict, number: int) -> NumberedField | None:
    fields = numbered_fields(page)
    return fields[number - 1] if 1 <= number <= len(fields) else None


def uncertain(page: dict) -> list[NumberedField]:
    return [f for f in numbered_fields(page) if f.field.get("status") in UNCERTAIN_STATUSES]


# --- Valeurs ---

def format_value(kind: str, field: dict) -> str:
    status = field.get("status")
    value = field.get("value")
    if status == "UNKNOWN":
        return "Inconnu"
    if status == "ILLEGIBLE":
        return "illisible"
    if status in ("NOT_PROVIDED", "NOT_APPLICABLE") or value is None:
        return "?" if status == "NEEDS_REVIEW" else "—"
    if kind == "checkbox" or isinstance(value, bool):
        return "Oui" if value is True else str(value)
    if kind == "date" and isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        y, m, d = value.split("-")
        return f"{d}/{m}/{y}"
    if kind == "sex":
        return {"F": "Féminin", "M": "Masculin"}.get(str(value).upper(), str(value))
    if kind in UNITS:
        return f"{value} {UNITS[kind]}"
    return str(value)


def parse_value(kind: str, text: str) -> tuple[object, str]:
    """Lit une correction tapée par l'utilisateur. Retourne (valeur, statut).

    Lève ValueError avec le format attendu si la saisie ne convient pas.
    """
    raw = text.strip()
    low = raw.lower()
    if not raw:
        raise ValueError(KIND_HINTS.get(kind, "une valeur"))
    if low in UNKNOWN_WORDS:
        return None, "UNKNOWN"
    if low in EMPTY_WORDS:
        return None, "NOT_PROVIDED"

    if kind == "checkbox":
        if low in YES_WORDS:
            return True, "KNOWN"
        if low in NO_WORDS:
            # Règle DayOne : une case non cochée n'est jamais `false`, elle est NOT_PROVIDED
            return None, "NOT_PROVIDED"
        raise ValueError(KIND_HINTS["checkbox"])
    if kind in NUMERIC_KINDS:
        m = re.fullmatch(r"(\d{1,5})(?:\s*(?:g|cm|sa|semaines?|ans?))?", low)
        if not m:
            raise ValueError(KIND_HINTS[kind])
        return int(m.group(1)), "KNOWN"
    if kind == "date":
        m = re.fullmatch(r"(\d{1,2})[/.\- ](\d{1,2})[/.\- ](\d{2}|\d{4})", raw)
        if not m:
            raise ValueError(KIND_HINTS["date"])
        d, mo, y = (int(x) for x in m.groups())
        y = y + 2000 if y < 100 else y
        try:
            return date(y, mo, d).isoformat(), "KNOWN"
        except ValueError:
            raise ValueError(KIND_HINTS["date"]) from None
    if kind == "sex":
        sex = {"f": "F", "fille": "F", "féminin": "F", "m": "M", "garçon": "M", "garcon": "M", "masculin": "M"}
        if low not in sex:
            raise ValueError(KIND_HINTS["sex"])
        return sex[low], "KNOWN"
    if len(raw) > 120:
        raise ValueError("un texte de 120 caractères maximum")
    return raw, "KNOWN"


# --- Messages ---

def field_line(nf: NumberedField) -> str:
    flag = "⚠️ " if nf.field.get("status") in UNCERTAIN_STATUSES else ""
    edited = " ✏️" if nf.field.get("origin") in ("CORRECTED", "MANUAL") else ""
    return f"{nf.number}. {flag}{nf.label} : *{format_value(nf.kind, nf.field)}*{edited}"


def _cell(nf: NumberedField) -> str:
    """Une case de tableau dans sa rangée : « 5. Famille de la femme *aucun* »."""
    flag = "⚠️ " if nf.field.get("status") in UNCERTAIN_STATUSES else ""
    edited = " ✏️" if nf.field.get("origin") in ("CORRECTED", "MANUAL") else ""
    column = nf.label.split(" | ", 1)[1]
    return f"{nf.number}. {flag}{column} *{format_value(nf.kind, nf.field)}*{edited}"


def values_text(page: dict, include_empty: bool = False) -> str:
    """Liste numérotée des valeurs, regroupées par section. Les cases d'un tableau (« HTA | Famille de la
    femme ») tiennent sur une ligne par rangée : « HTA : 5. Famille de la femme *aucun* · 6. Mari *aucun* »."""
    lines, current = [], None
    shown = [nf for nf in numbered_fields(page) if include_empty or nf.field.get("status") in SHOWN_STATUSES]
    i = 0
    while i < len(shown):
        nf = shown[i]
        section = nf.field.get("section")
        if section and section != current:
            current = section
            lines.append(f"\n*{section}*")
        row = nf.label.split(" | ", 1)[0] if " | " in nf.label else None
        group = [nf]
        while row and i + len(group) < len(shown):
            nxt = shown[i + len(group)]
            if nxt.field.get("section") != section or not nxt.label.startswith(row + " | "):
                break
            group.append(nxt)
        lines.append(f"{row} : " + " · ".join(_cell(g) for g in group) if len(group) > 1 else field_line(nf))
        i += len(group)
    return "\n".join(lines).strip() or "Aucune valeur lue sur cette page."


def review_text(page: dict, position: int, total: int) -> str:
    shown = sum(1 for nf in numbered_fields(page) if nf.field.get("status") in SHOWN_STATUSES)
    doubts = uncertain(page)
    lines = [f"📄 *Page {position + 1}/{total} · {page_name(page)}*", f"📊 {shown} valeur(s) lue(s)"]
    if doubts:
        names = ", ".join(f"{nf.number}. {nf.label}" for nf in doubts[:5])
        more = f" (+{len(doubts) - 5})" if len(doubts) > 5 else ""
        lines.append(f"⚠️ {len(doubts)} à vérifier : {names}{more}")
    else:
        lines.append("✅ Aucune incertitude restante.")
    lines += ["", "👇 Que voulez-vous faire ?"]
    return "\n".join(lines)


def confirm_uncertain_text(page: dict) -> str:
    doubts = uncertain(page)
    listed = "\n".join(
        f"• {nf.number}. {nf.label} : *{format_value(nf.kind, nf.field)}*"
        + (f" ({REASONS[nf.field['reason']]})" if nf.field.get("reason") in REASONS else "")
        for nf in doubts[:15]
    )
    return (
        f"⚠️ *{len(doubts)} valeur(s) restent à vérifier :*\n{listed}\n\n"
        "👇 Vous les avez vérifiées sur le registre ? Confirmez-les telles quelles, ou corrigez."
    )


def failed_page_text(page: dict, position: int, total: int, can_drop: bool) -> str:
    lines = [
        f"❌ *Page {position + 1}/{total} · lecture impossible*",
        page.get("error") or "Raison inconnue.",
        "",
        "👇 Reprendre la photo" + (", ou ignorer cette page ?" if can_drop else " ?"),
    ]
    return "\n".join(lines)


def _num(i: int) -> str:
    """1️⃣ … 9️⃣ ; au-delà, « 10. » (il n'existe pas de pastille 10)."""
    return f"{i}️⃣" if i < 10 else f"{i}."


def link_text(code: str, candidates: list[dict]) -> str:
    if not candidates:
        return (f"👤 Aucune patiente suivie avec le code *{code}*.\n\n"
                "👇 Créer la patiente, ou décider plus tard sur le tableau de bord ?")
    lines = [f"👤 *Ce registre ({code}) est-il celui d'une patiente déjà suivie ?*", ""]
    for i, cand in enumerate(candidates[:8], start=1):
        why = ", ".join(LINK_REASONS.get(r["kind"], r["kind"]) for r in cand.get("reasons", []))
        lines.append(f"{_num(i)} {cand['code']}" + (f" · {why}" if why else ""))
    lines += ["", "👇 Choisissez la patiente, une nouvelle patiente, ou « Je ne sais pas »."]
    return "\n".join(lines)


def final_text(final: dict) -> str:
    """Récapitulatif envoyé à la fin, tiré du résultat final stocké (GET /api/records/{id}/final)."""
    pages = final.get("pages", [])
    parts = [f"✅ *Registre enregistré* · code {final.get('patient_code', '')} · {len(pages)} page(s)"]
    for i, page in enumerate(pages):
        # Résultat final : liste de champs -> même forme que les pages de l'API pour la mise en forme
        view = {"pageType": page.get("page_type"), "title": page.get("title"),
                "fields": {f["key"]: f for f in page.get("fields", [])}}
        parts.append(f"\n📄 *Page {i + 1} · {page_name(view)}*\n{values_text(view)}")
    parts.append(f"\n🗂️ Résultat final enregistré (dossier {final.get('record_id', '')}), visible sur le tableau de bord.")
    return "\n".join(parts)
