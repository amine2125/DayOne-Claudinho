"""Mise en forme des valeurs lues, et normalisation commune à l'extraction et à l'évaluation.

Aucune logique clinique : on ne fait que reconnaître un format (date, nombre, unité).
"""

import re
import unicodedata
from datetime import date
from functools import lru_cache
from pathlib import Path

NONE_WORDS = {"ras", "r a s", "aucun", "aucune", "neant", "rien", "pas de", "non"}
UNKNOWN_WORDS = {"?", "??", "inconnu", "inconnue", "nsp", "ne sait pas", "non connu", "nc"}
ILLEGIBLE_WORDS = {"illisible"}


def fold(text: str) -> str:
    """Minuscules, sans accents, ponctuation réduite à des espaces."""
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9/?]+", " ", t.lower())
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
    """« Commer ante » -> « Commerçante » si un seul mot du lexique correspond, sinon None.

    Seules les lettres accentuées absentes sont remises : toutes les autres lettres doivent être identiques.
    """
    t = re.sub(r"\s+", " ", text.strip())
    hits = {w for w, pat in _lexicon_patterns() if pat.fullmatch(t)}
    if len(hits) != 1:
        return None
    word = hits.pop()
    return None if word.lower() == t.lower() else word


COMMON_WORDS = ("ras", "aucun", "aucune")


def _distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def looks_doubtful(text: str) -> bool:
    """Lecture suspecte même avec un bon score : presque « RAS » (ex. « KAS »), ou caractères parasites."""
    t = fold(text)
    if not t:
        return True
    if any(_distance(t, w) == 1 for w in COMMON_WORDS) and t not in COMMON_WORDS:
        return True
    raw = text.strip()
    odd = sum(1 for c in raw if not (c.isalnum() or c in " /.,'-°:()"))
    return odd > 0 or (len(raw) <= 2 and not raw.isdigit() and fold(raw) not in ("f", "m"))


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
