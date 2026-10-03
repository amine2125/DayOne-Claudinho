"""Normalisation de texte multilingue (FR / AR / EN) avant matching et parsing."""
from __future__ import annotations

import re
import unicodedata

# Chiffres arabes orientaux (٠-٩) et persans (۰-۹) -> ASCII
_DIGITS = {ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}
_DIGITS.update({ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")})
_DIGITS.update({ord("٫"): ",", ord("،"): ",", ord("٪"): "%"})

_ARABIC_DIACRITICS = re.compile(r"[ً-ٰٟـ]")  # harakat + tatweel
_SPACES = re.compile(r"\s+")

UNKNOWN_TOKENS = {
    "inconnu", "inconnue", "?", "??", "nsp", "ne sait pas", "non connu", "unknown", "nk",
    "not known", "غير معروف", "غير معروفة", "لا تعرف", "مجهول",
}
NOT_APPLICABLE_TOKENS = {
    "na", "n/a", "n.a", "sans objet", "so", "non applicable", "not applicable", "لا ينطبق",
}
NOT_DONE_TOKENS = {"non fait", "nf", "non realise", "not done", "pas fait", "لم يتم", "لم تجر"}
NOTHING_TOKENS = {"ras", "r.a.s", "neant", "aucune", "aucun", "rien", "none", "nil", "لا شيء", "لا يوجد"}
DASH_TOKENS = {"-", "--", "/", "—", "–", "_", "x"}


def fold_digits(text: str) -> str:
    return text.translate(_DIGITS)


def strip_accents(text: str) -> str:
    """Retire les accents latins sans toucher à l'arabe."""
    out = []
    for ch in unicodedata.normalize("NFD", text):
        if unicodedata.category(ch) == "Mn" and not ("؀" <= ch <= "ۿ"):
            continue
        out.append(ch)
    return unicodedata.normalize("NFC", "".join(out))


def normalize_text(text: str) -> str:
    """Forme canonique pour comparer libellés et tokens : minuscule, sans accents, chiffres ASCII."""
    t = unicodedata.normalize("NFKC", text or "")
    t = fold_digits(t)
    t = _ARABIC_DIACRITICS.sub("", t)
    t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    t = strip_accents(t).lower()
    t = t.replace("’", "'").replace("`", "'")
    return _SPACES.sub(" ", t).strip()


def normalize_label(text: str) -> str:
    """Libellé sans ponctuation finale ni deux-points : 'Poids (kg) :' -> 'poids (kg)'."""
    t = normalize_text(text)
    return t.strip(" :.-=;|")


def is_token_in(text: str, vocab: set[str]) -> bool:
    t = normalize_text(text).strip(" .:;")
    return t in vocab
