"""Données personnelles : jamais extraites, jamais stockées (nom, conjoint, CIN, téléphone, adresse),
et masquées en noir sur toute image affichée ou envoyée au modèle."""

import re
from difflib import SequenceMatcher

import numpy as np

from dayone.normalize import fold

# Mots d'étiquette qui désignent une donnée personnelle (comparés mot à mot : « nombre » ≠ « nom »).
# Français, anglais, arabe (nom, prénom, nom de famille, adresse, téléphone, mari, carte nationale, signature).
PERSONAL_WORDS = {"nom", "noms", "prenom", "prenoms", "cin", "cni", "telephone", "tel", "gsm", "portable",
                  "adresse", "conjoint", "epoux", "epouse", "signature", "identite",
                  "name", "surname", "firstname", "phone", "mobile", "address", "husband", "spouse", "passport",
                  "اسم", "الاسم", "واسم", "نسب", "النسب", "عنوان", "العنوان", "هاتف", "الهاتف", "جوال", "الجوال",
                  "زوج", "الزوج", "توقيع", "التوقيع", "جواز", "الجواز"}
PERSONAL_LABELS = {"patiente", "patient", "mari", "nom du mari", "patiente fictive", "المريضة", "الحامل"}
# Expressions qui désignent une personne (soignant ou proche) : son nom ne doit pas sortir.
PERSONAL_PHRASES = ("fait par", "rempli par", "examinateur", "signature", "visa", "sage femme", "medecin traitant",
                    "national id", "filled by", "examined by", "midwife",
                    "البطاقة الوطنية", "بطاقة التعريف", "رقم التعريف")

# Étiquettes personnelles en arabe : reconnues même mal lues (l'OCR arabe se trompe plus souvent),
# par ressemblance avec l'étiquette entière.
ARABIC_PERSONAL_LABELS = ("الاسم الكامل", "الاسم", "الاسم العائلي", "الاسم الشخصي", "اسم الزوج", "رقم الهاتف",
                          "العنوان", "النسب", "رقم البطاقة الوطنية", "التوقيع")
ARABIC_SIMILAR = 0.68

# « Nom de l’établissement » n’est pas une personne (apostrophe courbe : « letablissement » une fois replié).
NOT_A_PERSON = re.compile(r"\bnom (de l ?|du |de la )?(etabli\w*|structure|centre|hopital|service|formation|maternite)"
                          r"|\b(facility|hospital|clinic|centre|center|health) name\b|\bname of (the )?(facility|hospital|clinic)"
                          r"|(اسم|الاسم) (الموسسة|المركز|المستشفى)")   # forme repliée : « المؤسسة » perd sa hamza
# En-tête « rôle — nom » (« MÈRE — Tazi Meryem ») : le nom est imprimé sans étiquette « Nom ».
PERSON_HEADER = re.compile(r"^\s*(?i:m[eè]re|patiente?|femme|parturiente|nouveau[- ]?n[ée]e?|enfant|b[ée]b[ée]"
                           r"|mother|baby|newborn)\s*[—–-]+\s*[A-ZÀ-Ý][\w'-]+\s+[A-ZÀ-Ý]"   # deux mots : prénom + nom
                           r"|^\s*(الام|الأم|المريضة)\s*[—–-]+\s*\w")
# Valeur qui commence par « CIN : » (même mal lu par l'OCR : « C.I.N », « cm: », « C (M; »).
CIN_PREFIX = re.compile(r"^\s*(c\s*\.?\s*i\s*\.?\s*n|cni|c\W{0,2}m)\s*[:;.]", re.IGNORECASE)
PHONE = re.compile(r"(?:\+?\d[\s.-]?){9,}")
CIN = re.compile(r"\b[A-Z]{1,2}\s?\d{5,7}\b")
# N° de la fiche / du dossier : code du registre qui relie les visites. Il peut avoir la forme d'un CIN
# (« A64185 ») ou d'un téléphone (« 2026-823-001 ») : pour lui, seule l'étiquette compte.
RECORD_LABEL = re.compile(r"\b(n|no|num|numero)\b.*\b(fiche|dossier|registre)\b|\bcode\b")


def is_personal(label: str, value: str = "") -> bool:
    """Vrai si le champ est une donnée personnelle, par son étiquette ou par la forme de sa valeur."""
    if PERSON_HEADER.match(label) or PERSON_HEADER.match(value):
        return True
    lab = fold(label)
    words = set(lab.replace("/", " ").split())
    if NOT_A_PERSON.search(lab):
        words -= {"nom", "name", "اسم", "الاسم"}
    if words & PERSONAL_WORDS or lab in PERSONAL_LABELS or lab.startswith("patiente"):
        return True
    if any(p in lab for p in PERSONAL_PHRASES):
        return True
    if re.search(r"[\u0621-\u064a]", lab) and not NOT_A_PERSON.search(lab) and any(
            SequenceMatcher(None, lab, fold(p)).ratio() >= ARABIC_SIMILAR for p in ARABIC_PERSONAL_LABELS):
        return True
    v = value.strip()
    if not v:
        return False
    if CIN_PREFIX.match(v):
        return True
    if RECORD_LABEL.search(lab):
        return False
    return bool(PHONE.search(v.replace("/", "x"))) or bool(CIN.search(v.upper()))


def is_record_label(label: str) -> bool:
    return bool(RECORD_LABEL.search(fold(label)))


def identifier(text: str) -> str:
    """Valeur d'un identifiant, sans « CIN : » devant, en lettres et chiffres seuls."""
    t = CIN_PREFIX.sub("", text) if CIN_PREFIX.match(text) else text.split(":")[-1]
    return re.sub(r"[^A-Z0-9]", "", t.upper())


def looks_like_cin(text: str) -> bool:
    return bool(CIN_PREFIX.match(text)) or bool(CIN.search(text.upper()))


def same_identifier(a: str, b: str) -> bool:
    """Même identifiant, à une ou deux erreurs de lecture près (« A64185 » / « A64l85 »)."""
    a, b = identifier(a), identifier(b)
    return min(len(a), len(b)) >= 5 and SequenceMatcher(None, a, b).ratio() >= 0.8


def redact(img: np.ndarray, zones) -> np.ndarray:
    """Copie de l'image avec un rectangle noir sur chaque zone personnelle."""
    out = img.copy()
    for x0, y0, x1, y1 in zones:
        out[max(0, int(y0)):int(y1), max(0, int(x0)):int(x1)] = 0
    return out
