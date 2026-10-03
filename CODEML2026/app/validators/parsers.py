"""Parseurs déterministes : texte brut -> valeur typée.

Règle d'or : un parseur ne devine jamais. S'il hésite, il renvoie une erreur ou un
`warning` (qui fait baisser la confiance), et la sage-femme tranche.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from rapidfuzz import fuzz, process

from app.schemas.form_spec import FieldKind, FieldSpec
from app.validators.normalize import NOTHING_TOKENS, normalize_text

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_UNITS = re.compile(
    r"(kg|kgs|cm|mmhg|cmhg|bpm|b/min|bat/min|/min|ans|an|years|yrs|sa|sem|semaines|weeks|°c|°|c\b|"
    r"كغ|كلغ|سم|سنة|اسبوع)"
)
# Confusions OCR classiques dans une zone qui DEVRAIT être numérique
_OCR_DIGIT_FIXES = str.maketrans({"o": "0", "O": "0", "l": "1", "I": "1", "|": "1", "s": "5", "S": "5", "B": "8"})


@dataclass
class ParseResult:
    ok: bool
    value: Any = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @staticmethod
    def fail(error: str) -> ParseResult:
        return ParseResult(ok=False, error=error)


def _to_float(s: str) -> float:
    return float(s.replace(",", "."))


def parse_number(text: str, spec: FieldSpec) -> ParseResult:
    t = normalize_text(text)
    t_wo_units = _UNITS.sub(" ", t)
    warnings: list[str] = []
    nums = _NUMBER.findall(t_wo_units)
    if not nums:
        fixed = t_wo_units.translate(_OCR_DIGIT_FIXES)
        nums = _NUMBER.findall(fixed)
        if not nums:
            return ParseResult.fail("aucun_nombre")
        warnings.append("correction_caracteres_ocr")
    if len(nums) > 1:
        return ParseResult.fail("plusieurs_nombres")
    value = _to_float(nums[0])

    # Virgule oubliée : "375" pour une température, "685" pour un poids.
    if (spec.kind == FieldKind.FLOAT and spec.hard_max is not None and value > spec.hard_max
            and "," not in nums[0] and "." not in nums[0]):
        candidate = value / 10
        if spec.soft_min is not None and spec.soft_max is not None and spec.soft_min <= candidate <= spec.soft_max:
            value = candidate
            warnings.append("virgule_manquante_supposee")

    if spec.kind == FieldKind.INT:
        if value != int(value):
            return ParseResult.fail("entier_attendu")
        value = int(value)
    else:
        value = round(value, 1)
    return ParseResult(ok=True, value=value, warnings=warnings)


_BP = re.compile(r"(\d{2,3})\s*[/\\|]\s*(\d{1,3})")


def parse_blood_pressure(text: str, spec: FieldSpec) -> ParseResult:
    t = normalize_text(text)
    m = _BP.search(t)
    if not m:
        return ParseResult.fail("format_tension_attendu_120/80")
    sys_, dia = int(m.group(1)), int(m.group(2))
    warnings: list[str] = []
    # Notation en cmHg fréquente sur les registres : "12/8" -> 120/80
    if sys_ <= 30 and dia <= 20:
        sys_, dia = sys_ * 10, dia * 10
        warnings.append("cmHg_converti_en_mmHg")
    return ParseResult(ok=True, value={"tension_systolique": sys_, "tension_diastolique": dia},
                       warnings=warnings)


_GP = re.compile(r"\bg\s*(\d{1,2})\s*p\s*(\d{1,2})")
_GP_SLASH = re.compile(r"^\s*(\d{1,2})\s*/\s*(\d{1,2})\s*$")   # sous un libellé "G/P" : "3/2"


def parse_gesta_para(text: str, spec: FieldSpec) -> ParseResult:
    t = normalize_text(text)
    m = _GP.search(t) or _GP_SLASH.match(t)
    if not m:
        return ParseResult.fail("format_GxPy_attendu")
    return ParseResult(ok=True, value={"gestite": int(m.group(1)), "parite": int(m.group(2))})


_BG = re.compile(r"\b(ab|a|b|o|0)\s*(?:rh|rhesus)?\s*(\+|-|pos\w*|neg\w*|موجب|سالب)?(?=\s|$|[^a-z])")


def parse_blood_group(text: str, spec: FieldSpec) -> ParseResult:
    t = normalize_text(text).replace("(", " ").replace(")", " ")
    t = re.sub(r"\b(groupe|gs|groupage)\b", " ", t).strip()
    m = _BG.search(t)
    if not m:
        return ParseResult.fail("groupe_sanguin_non_reconnu")
    group = m.group(1).upper().replace("0", "O")
    warnings = ["zero_lu_comme_O"] if m.group(1) == "0" else []
    rh_raw = m.group(2)
    rh = None
    if rh_raw:
        rh = "POSITIF" if rh_raw in ("+", "موجب") or rh_raw.startswith("pos") else "NEGATIF"
    return ParseResult(ok=True, value={"groupe_sanguin": group, "rhesus": rh}, warnings=warnings)


_GA = re.compile(r"(\d{1,2})(?:[.,](\d))?\s*(?:sa|sem\w*|weeks?|s|اسبوع\w*)?\s*(?:\+\s*(\d)\s*(?:j|jours?|d|days?)?)?")


def parse_gestational_age(text: str, spec: FieldSpec) -> ParseResult:
    t = normalize_text(text)
    if re.search(r"\bmois\b|\bmonths?\b|شهر|اشهر", t):
        return ParseResult.fail("age_gestationnel_en_mois")  # conversion = interprétation -> on refuse
    m = _GA.search(t)
    if not m:
        return ParseResult.fail("format_SA_attendu")
    weeks = int(m.group(1))
    if m.group(2):
        return ParseResult(ok=True, value=float(f"{weeks}.{m.group(2)}"), warnings=["decimale_ambigue_jours_ou_dixiemes"])
    days = int(m.group(3)) if m.group(3) else 0
    if days > 6:
        return ParseResult.fail("jours_superieurs_a_6")
    return ParseResult(ok=True, value=weeks if days == 0 else round(weeks + days / 7, 1))


_DATE_DMY = re.compile(r"\b(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{2,4})\b")
_DATE_YMD = re.compile(r"\b(\d{4})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{1,2})\b")


def parse_date(text: str, spec: FieldSpec, today: date | None = None) -> ParseResult:
    t = normalize_text(text)
    today = today or date.today()
    if m := _DATE_YMD.search(t):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    elif m := _DATE_DMY.search(t):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000  # registres récents
    else:
        return ParseResult.fail("format_date_attendu_jj/mm/aaaa")
    try:
        parsed = date(y, mo, d)
    except ValueError:
        return ParseResult.fail("date_inexistante")
    if parsed > today:
        return ParseResult.fail("date_dans_le_futur")
    if parsed.year < 2000:
        return ParseResult.fail("date_trop_ancienne")
    return ParseResult(ok=True, value=parsed.isoformat())


def parse_enum(text: str, spec: FieldSpec) -> ParseResult:
    t = normalize_text(text).strip(" .:;")
    mapping = {normalize_text(k): v for k, v in spec.enum_map.items()}
    if t in mapping:
        warnings = ["symbole_interprete"] if t in {"+", "-", "(+)", "(-)", "p", "n"} else []
        return ParseResult(ok=True, value=mapping[t], warnings=warnings)
    # Valeur dans une phrase : "négatif (-)", "TPHA neg"
    words = re.split(r"[\s,;()]+", t)
    hits = {mapping[w] for w in words if w in mapping and len(w) > 1}
    if len(hits) == 1:
        return ParseResult(ok=True, value=hits.pop())
    if len(hits) > 1:
        return ParseResult.fail("valeurs_contradictoires")
    # Faute d'OCR légère : "negatlf" -> negatif (seulement sur des mots assez longs)
    if len(t) >= 4:
        best = process.extractOne(t, [k for k in mapping if len(k) >= 4], scorer=fuzz.ratio)
        if best and best[1] >= 85:
            return ParseResult(ok=True, value=mapping[best[0]], warnings=["correspondance_approximative"])
    return ParseResult.fail("valeur_hors_liste")


def parse_free_text(text: str, spec: FieldSpec) -> ParseResult:
    t = normalize_text(text).strip(" .:;")
    if t in NOTHING_TOKENS:
        return ParseResult(ok=True, value="AUCUNE")
    # Texte libre : on garde le texte (après redaction en aval), toujours relu par la sage-femme
    return ParseResult(ok=True, value=text.strip(), warnings=["texte_libre_a_relire"])


def parse_text(text: str, spec: FieldSpec) -> ParseResult:
    t = re.sub(r"\s+", " ", text).strip(" .:;_")
    return ParseResult(ok=True, value=t) if t else ParseResult.fail("texte_vide")


_CODE = re.compile(r"^[A-Z0-9][A-Z0-9\-/]{3,24}$")


def parse_code(text: str, spec: FieldSpec) -> ParseResult:
    """N° de fiche (code patiente) : on ne corrige rien, un caractère douteux = à revoir."""
    t = re.sub(r"[\s_]+", "", text.upper()).strip("/.:;")
    if not _CODE.match(t):
        return ParseResult.fail("format_code_invalide")
    return ParseResult(ok=True, value=t)


PARSERS = {
    FieldKind.INT: parse_number,
    FieldKind.FLOAT: parse_number,
    FieldKind.ENUM: parse_enum,
    FieldKind.BLOOD_PRESSURE: parse_blood_pressure,
    FieldKind.BLOOD_GROUP: parse_blood_group,
    FieldKind.GESTA_PARA: parse_gesta_para,
    FieldKind.GESTATIONAL_AGE: parse_gestational_age,
    FieldKind.DATE: parse_date,
    FieldKind.FREE_TEXT: parse_free_text,
    FieldKind.TEXT: parse_text,
    FieldKind.CODE: parse_code,
}


def parse_value(text: str, spec: FieldSpec) -> ParseResult:
    return PARSERS[spec.kind](text, spec)
