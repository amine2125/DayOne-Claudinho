"""Mise en forme des valeurs lues, et normalisation commune à l'extraction et à l'évaluation.

Aucune logique clinique : on ne fait que reconnaître un format (date, nombre, unité).
"""

import re
import unicodedata
from datetime import date
from functools import lru_cache
from pathlib import Path

NONE_WORDS = {"ras", "r a s", "aucun", "aucune", "neant", "rien", "pas de", "non",
              "none", "nil", "no", "لا شيء", "لا يوجد", "لا"}
UNKNOWN_WORDS = {"?", "??", "inconnu", "inconnue", "nsp", "ne sait pas", "non connu", "nc",
                 "unknown", "غير معروف", "مجهول"}
ILLEGIBLE_WORDS = {"illisible", "illegible", "غير مقروء"}


ARABIC = re.compile(r"[\u0621-\u064a]")


def fold(text: str) -> str:
    """Minuscules, sans accents (ni voyelles arabes), ponctuation réduite à des espaces. Lettres arabes gardées."""
    t = text.replace("œ", "oe").replace("Œ", "Oe").replace("æ", "ae").replace("Æ", "Ae")
    t = "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))
    t = "".join(c for c in t if c.isascii() or ARABIC.match(c))
    t = re.sub(r"[^a-z0-9/?\u0621-\u064a]+", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def special_word(text: str) -> str | None:
    """'none' (RAS, aucun…), 'unknown' (?, inconnu…), 'illegible' ou None."""
    t = fold(text).replace(".", "")
    if t in NONE_WORDS:
        return "none"
    if t in UNKNOWN_WORDS or text.strip() in UNKNOWN_WORDS:
        return "unknown"
    if t in ILLEGIBLE_WORDS:
        return "illegible"
    return None


def _number(text: str) -> float | None:
    """Premier nombre du texte ('3626 g' -> 3626, '3 626 g' -> 3626, '3,2 kg' -> 3.2)."""
    t = text.replace(",", ".")
    m = re.search(r"(?<!\d)\d{1,2} \d{3}(?!\d)", t)
    if m:
        return float(m.group().replace(" ", ""))
    m = re.search(r"\d+(?:\.\d+)?", t)
    return float(m.group()) if m else None


LEXICON_FILE = Path(__file__).resolve().parent.parent / "schema" / "lexique.txt"


@lru_cache
def _lexicon_patterns() -> list[tuple[str, re.Pattern]]:
    """Chaque mot du lexique -> motif où chaque lettre accentuée peut manquer (rien ou un espace)."""
    out = []
    for line in LEXICON_FILE.read_text(encoding="utf-8").splitlines():
        word = line.strip()
        if not word or word.startswith("#"):
            continue
        parts = [f"(?:{re.escape(c)}| ?)" if not c.isascii() else re.escape(c) for c in word]
        out.append((word, re.compile("".join(parts), re.IGNORECASE)))
    return out


def restore_missing_letters(text: str) -> str | None:
    """Remet les lettres accentuées absentes de la page, mot par mot ou expression par expression,
    grâce au lexique : « Commer ante » -> « Commerçante », « Asthme l ger » -> « Asthme léger ».

    Seules les lettres accentuées absentes sont remises : toutes les autres lettres doivent être identiques.
    Renvoie None si rien n'a changé.
    """
    t = re.sub(r"\s+", " ", text.strip())
    out = t
    # Expressions les plus longues d'abord ; un passage déjà corrigé n'est pas retouché.
    for word, pat in sorted(_lexicon_patterns(), key=lambda wp: -len(wp[0])):
        bounded = re.compile(rf"(?<![\w]){pat.pattern}(?![\w])", re.IGNORECASE)
        def repl(m, word=word):
            found = m.group(0)
            if found.lower() == word.lower():
                return found
            first = word[:1].upper() if found[:1].isupper() else word[:1].lower()   # casse de la page
            return first + word[1:]
        out = bounded.sub(repl, out)
    return None if out == t else out


def parse(kind: str, text: str):
    """Texte lu -> (valeur typée, format_ok). Ne devine jamais : format_ok=False si ça ne colle pas."""
    text = (text or "").strip()
    if not text:
        return None, False
    word = special_word(text)
    if word == "none" and kind not in ("integer", "weight", "length", "weeks", "sex"):
        return "aucun", True
    if kind == "text":
        return re.sub(r"\s+", " ", text), True
    if kind == "integer":
        clean = fold(text).replace("ans", "").replace(" ", "")
        if re.fullmatch(r"\d{1,3}", clean):
            return int(clean), True
        n = _number(text)
        return (int(n) if n is not None and n == int(n) else None), False
    if kind == "date":
        return _parse_date(text)
    if kind == "weight":
        n = _number(text)
        if n is None:
            return None, False
        t = fold(text)
        grams = n * 1000 if ("kg" in t or n < 10) else n
        return int(round(grams)), 300 <= grams <= 7000
    if kind == "length":
        n = _number(text)
        return (n if n is None or n != int(n) else int(n)), n is not None and 10 <= n <= 70
    if kind == "weeks":
        n = _number(text)
        return (int(n) if n is not None else None), n is not None and n == int(n) and 4 <= n <= 45
    if kind == "sex":
        t = fold(text)
        if t in ("f", "fille", "feminin", "femme"):
            return "F", True
        if t in ("m", "g", "garcon", "masculin", "homme"):
            return "M", True
        return None, False
    raise ValueError(f"type inconnu : {kind}")


def _parse_date(text: str):
    t = re.sub(r"\s+", "", text).replace("-", "/").replace(".", "/")
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})", t)
    if m:
        d, mo, y = (int(g) for g in m.groups())
        y += 2000 if y < 100 else 0
        try:
            return date(y, mo, d).isoformat(), 1950 <= y <= 2100
        except ValueError:
            return None, False
    m = re.fullmatch(r"(\d{1,2})/(\d{4})", t)
    if m:
        mo, y = int(m.group(1)), int(m.group(2))
        return (f"{y:04d}-{mo:02d}", 1 <= mo <= 12)
    if re.fullmatch(r"(19|20)\d{2}", t):
        return t, True
    return None, False


def comparable(kind: str, value) -> str:
    """Forme canonique pour comparer une prédiction à la référence."""
    if value is None:
        return ""
    if kind == "checkbox":
        return str(value).lower()
    if isinstance(value, str):
        parsed, ok = parse(kind, value)
        if ok and parsed is not None:
            value = parsed
    if isinstance(value, float) and value == int(value):
        value = int(value)
    return fold(str(value))


# Type d'un champ deviné d'après son étiquette (fiche inconnue). Premier motif trouvé = type retenu.
KIND_RULES = [   # français, anglais, arabe
    ("date", r"\bdate\b|\ble\b|\bddr\b|\bne[e]? le\b|\bon\b|تاريخ"),
    ("weeks", r"\bsa\b|age gestationnel|terme|gestational age|\bweeks\b|اسبوع|الاسابيع"),
    ("weight", r"\bpoids\b|\bweight\b|وزن|الوزن"),
    ("length", r"perimetre|taille|\bhu\b|hauteur uterine|circumference|height|length|محيط|طول"),
    ("sex", r"\bsexe\b|\bsex\b|gender|الجنس"),
    ("integer", r"\bage\b|gestation|gestite|parite|nombre|\bnb\b|enfants vivants|number of|gravidity|parity"
                r"|العمر|السن|عدد"),
]


def infer_kind(label: str) -> str:
    t = fold(label)
    for kind, pattern in KIND_RULES:
        if re.search(pattern, t):
            return kind
    return "text"
