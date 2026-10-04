"""Mise en forme WhatsApp des sorties DayOne et lecture des corrections.

Une page analysée a la forme produite par `dayone.extract.extract_page` :
    {"page_type": "...", "fields": {"age": {"value": 31, "status": "KNOWN", "confidence": 0.94}, ...}}

Les libellés viennent de `schema/*.json` (source de vérité de DayOne). Chaque champ porte
un numéro stable (sa position dans le schéma) : c'est ce numéro que l'utilisateur tape pour corriger.
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

# Statuts qui ont quelque chose à montrer (les cases vides et non applicables sont tues)
SHOWN_STATUSES = ("KNOWN", "UNKNOWN", "NEEDS_REVIEW", "ILLEGIBLE")
# Statuts qui demandent l'œil de la sage-femme
UNCERTAIN_STATUSES = ("NEEDS_REVIEW", "ILLEGIBLE")

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


@dataclass(frozen=True)
class FieldDef:
    number: int
    id: str
    label: str
    group: str
    kind: str


@dataclass(frozen=True)
class PageDef:
    page_type: str
    title: str
    fields: tuple[FieldDef, ...]

    def by_number(self, number: int) -> FieldDef | None:
        return self.fields[number - 1] if 1 <= number <= len(self.fields) else None


def schema_dir() -> Path:
    configured = get_settings().SCHEMA_DIR
    # Par défaut : le dossier schema/ de DayOne, à côté de whatsapp-bot/
    return Path(configured) if configured else Path(__file__).resolve().parents[2] / "schema"


@lru_cache
def load_page_def(page_type: str) -> PageDef | None:
    path = schema_dir() / f"{page_type}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Schema not available for page_type=%s (%s)", page_type, exc)
        return None
    fields = tuple(
        FieldDef(i, f["id"], f["label"], f.get("group", ""), f.get("kind", "text"))
        for i, f in enumerate(raw["fields"], start=1)
    )
    return PageDef(raw["page_type"], raw.get("title", page_type), fields)


def page_def_for(page: dict) -> PageDef:
    """Schéma de la page ; à défaut, un schéma déduit des champs reçus (libellé = identifiant)."""
    found = load_page_def(page.get("page_type", ""))
    if found:
        return found
    fields = tuple(
        FieldDef(i, fid, fid.replace("_", " ").capitalize(), "", "text")
        for i, fid in enumerate(page.get("fields", {}), start=1)
    )
    return PageDef(page.get("page_type", "inconnu"), "Page non reconnue", fields)


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
    if kind == "checkbox":
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

def counts(page: dict) -> tuple[int, list[FieldDef]]:
    """(nombre de valeurs lues, champs incertains)."""
    pdef = page_def_for(page)
    fields = page.get("fields", {})
    shown = sum(1 for f in pdef.fields if fields.get(f.id, {}).get("status") in SHOWN_STATUSES)
    uncertain = [f for f in pdef.fields if fields.get(f.id, {}).get("status") in UNCERTAIN_STATUSES]
    return shown, uncertain


def field_line(fdef: FieldDef, field: dict) -> str:
    flag = "⚠️ " if field.get("status") in UNCERTAIN_STATUSES else ""
    edited = " ✏️" if field.get("source") == "sage-femme" else ""
    return f"{fdef.number}. {flag}{fdef.label} : *{format_value(fdef.kind, field)}*{edited}"


def values_text(page: dict, include_empty: bool = False) -> str:
    """Liste numérotée des valeurs, regroupées par section du registre."""
    pdef = page_def_for(page)
    fields = page.get("fields", {})
    lines, current_group = [], None
    for fdef in pdef.fields:
        field = fields.get(fdef.id, {"value": None, "status": "NOT_PROVIDED"})
        if not include_empty and field.get("status") not in SHOWN_STATUSES:
            continue
        if fdef.group and fdef.group != current_group:
            current_group = fdef.group
            lines.append(f"\n*{current_group}*")
        lines.append(field_line(fdef, field))
    return "\n".join(lines).strip() or "Aucune valeur lue sur cette page."


def review_text(page: dict, index: int, total: int) -> str:
    pdef = page_def_for(page)
    shown, uncertain = counts(page)
    lines = [f"📄 *Page {index + 1}/{total} · {pdef.title}*", f"📊 {shown} valeur(s) lue(s)"]
    if uncertain:
        names = ", ".join(f"{f.number}. {f.label}" for f in uncertain[:5])
        more = f" (+{len(uncertain) - 5})" if len(uncertain) > 5 else ""
        lines.append(f"⚠️ {len(uncertain)} à vérifier : {names}{more}")
    else:
        lines.append("✅ Aucune incertitude restante.")
    lines += [
        "",
        "Que voulez-vous faire ?",
        "1️⃣ Confirmer la page",
        "2️⃣ Corriger un champ",
        "3️⃣ Voir les valeurs",
        "4️⃣ Reprendre la photo",
        "👉 Répondez avec le chiffre.",
    ]
    return "\n".join(lines)


def failed_page_text(page: dict, index: int, total: int) -> str:
    return (
        f"❌ *Page {index + 1}/{total} · lecture impossible*\n"
        f"{page.get('error', 'Raison inconnue.')}\n\n"
        "4️⃣ Reprendre la photo\n"
        "5️⃣ Ignorer cette page\n"
        "👉 Répondez avec le chiffre."
    )


def final_text(pages: list[dict]) -> str:
    """Récapitulatif propre envoyé une fois le registre confirmé."""
    parts = [f"✅ *Registre confirmé* · {len(pages)} page(s)"]
    for i, page in enumerate(pages):
        pdef = page_def_for(page)
        _, uncertain = counts(page)
        header = f"\n📄 *Page {i + 1} · {pdef.title}*"
        if uncertain:
            header += f"\n⚠️ {len(uncertain)} valeur(s) restent à vérifier"
        parts.append(header + "\n" + values_text(page))
    return "\n".join(parts)
