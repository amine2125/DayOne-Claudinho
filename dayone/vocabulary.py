"""Vocabulaire des étiquettes connues (schema/vocabulaire.txt).

Il ne sert pas à lire : une étiquette inconnue est lue quand même. Il sert à ne pas faire confiance
trop vite : un champ dont l'étiquette est nouvelle ou mal lue part en NEEDS_REVIEW, même si sa valeur
est bien lue, avec une raison visible.
"""

import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

from dayone.normalize import fold

VOCABULARY_FILE = Path(__file__).resolve().parent.parent / "schema" / "vocabulaire.txt"
# Traductions arabe / anglais, écrites à la main (le registre fourni n'existe qu'en français).
TRANSLATIONS_FILE = VOCABULARY_FILE.with_name("vocabulaire_ar_en.txt")
ARABIC_PREFIXES = ("وال", "بال", "كال", "فال", "لل", "ال")
STOPWORDS = {"de", "la", "le", "les", "du", "des", "et", "en", "au", "aux", "a", "l", "d", "n", "no", "un", "une",
             "par", "pour", "sur", "si", "ou", "of", "the", "and"}
KNOWN_SHARE = 0.75   # part des mots de l'étiquette qui doivent être connus
SIMILAR = 0.8        # mot lu un peu de travers par l'OCR (« Bilah » / « bilan ») : encore connu
# Caractères qu'on ne trouve pas dans une étiquette imprimée (« 33A$A-11 », « H(:MiG ») : OCR raté.
ODD_CHARS = re.compile(r"[^\w\s'’\-/().,:;°|+%<>=«»]")


def _norm(word: str) -> str:
    """Mot replié ; en arabe : sans article (« الوزن » -> « وزن »), ة = ه, ى = ي."""
    if word and "\u0621" <= word[0] <= "\u064a":
        for p in ARABIC_PREFIXES:
            if word.startswith(p) and len(word) - len(p) >= 2:
                word = word[len(p):]
                break
        word = word.replace("ة", "ه").replace("ى", "ي")
    return word


@lru_cache
def _words() -> frozenset[str]:
    words = set()
    for path in (VOCABULARY_FILE, TRANSLATIONS_FILE):
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip() and not line.startswith("#"):
                    words.update(_norm(w) for w in fold(line).split())
    return frozenset(words)


@lru_cache(maxsize=4096)
def known_word(word: str) -> bool:
    words = _words()
    word = _norm(word)
    if word in words:
        return True
    return len(word) >= 4 and any(abs(len(v) - len(word)) <= 2 and SequenceMatcher(None, v, word).ratio() >= SIMILAR
                                  for v in words)


def label_reason(label: str) -> str | None:
    """None si l'étiquette est connue ; sinon « etiquette_douteuse » (mal lue) ou « champ_nouveau »."""
    if not _words():
        return None                       # pas de vocabulaire : rien à signaler
    text = re.sub(r"(?<=\w)\.(?=\w)", "", label.replace("|", " "))   # sigle « H.T.A » -> « HTA »
    chars = [c for c in text if not c.isspace()]
    if ODD_CHARS.search(text) or not chars or sum(c.isalpha() for c in chars) < 0.6 * len(chars):
        return "etiquette_douteuse"
    tokens = [t for t in fold(text).replace("/", " ").split() if t not in STOPWORDS and not t.isdigit()]
    if not tokens:
        return "etiquette_douteuse"
    share = sum(known_word(t) for t in tokens) / len(tokens)
    return None if share >= KNOWN_SHARE else "champ_nouveau"
