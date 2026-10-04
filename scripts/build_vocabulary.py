"""Construit schema/vocabulaire.txt : les mots imprimés du registre (étiquettes, intitulés, choix des cases).

Sources :
- le PDF du registre : seul le texte imprimé est gardé (police Helvetica) ; l'écriture simulée
  (police Caveat : valeurs, noms, CIN…) est ignorée. Un mot doit être imprimé chez au moins 5 patientes :
  une étiquette est la même pour toutes, un nom imprimé (« MÈRE — <nom> ») n'appartient qu'à une seule ;
- les photos du vrai livret (`1-*.jpg`) : lignes imprimées lues par l'OCR avec un score ≥ 0,95,
  jamais l'écriture bleue ni une donnée personnelle.
Aucune valeur ni donnée personnelle n'entre donc dans le vocabulaire.

Le vocabulaire ne sert pas à lire : une étiquette absente est quand même lue, mais elle part en
NEEDS_REVIEW (raison « champ_nouveau »). Pour ajouter un mot : une ligne dans schema/vocabulaire.txt.

Usage : python -m scripts.build_vocabulary
"""

import ctypes
import sys

import pypdfium2 as pdfium
import pypdfium2.raw as raw

from dayone import imaging, ocr, page
from dayone.dataset import PAGES_PER_PATIENT, REGISTRY_DIR, ROOT
from dayone.normalize import fold
from dayone.privacy import is_personal
from dayone.vocabulary import VOCABULARY_FILE

PDF = REGISTRY_DIR / "dossiers_specimen_10_patientes.pdf"
PRINTED_FONTS = (b"Helvetica",)
# Mentions du jeu synthétique, pas des étiquettes du registre.
SKIP = ("specimen", "donnees fictives", "patiente fictive", "document synthetique")
SURE_PRINTED = 0.95
MIN_PATIENTS = 5


def printed_lines(page) -> list[str]:
    tp = page.get_textpage()
    buf, flags = ctypes.create_string_buffer(256), ctypes.c_int()
    chars = []
    for k in range(raw.FPDFText_CountChars(tp)):
        raw.FPDFText_GetFontInfo(tp, k, buf, 256, ctypes.byref(flags))
        c = chr(raw.FPDFText_GetUnicode(tp, k))
        chars.append(c if buf.value.startswith(PRINTED_FONTS) or c in "\r\n" else "\n")
    return [line for line in "".join(chars).splitlines() if line.strip()]


def photo_lines(path) -> list[str]:
    """Lignes imprimées sûres d'une photo du livret (ni écriture bleue, ni donnée personnelle)."""
    img = page.prepare(page.load_image(path))
    bm = imaging.blue_map(img)
    return [l["text"] for l in ocr.read_page(img)
            if l["score"] >= SURE_PRINTED and not imaging.is_handwritten(img, l["box"], bm)
            and not is_personal(l["text"], l["text"])]


def main() -> int:
    seen: dict[str, set[int]] = {}     # mot -> patientes chez qui il est imprimé
    pdf = pdfium.PdfDocument(PDF)
    for k, pdf_page in enumerate(pdf):
        patient = k // PAGES_PER_PATIENT + 1
        for line in printed_lines(pdf_page):
            f = fold(line)
            if any(s in f for s in SKIP) or is_personal(line, line):
                continue
            for w in f.replace("/", " ").split():
                if len(w) >= 2 and not w.isdigit():
                    seen.setdefault(w, set()).add(patient)
    words = {w for w, patients in seen.items() if len(patients) >= MIN_PATIENTS}
    for photo in sorted(REGISTRY_DIR.glob("1-*.jpg")):
        for line in photo_lines(photo):
            words.update(w for w in fold(line).replace("/", " ").split() if len(w) >= 3 and w.isalpha())
    header = ("# Mots imprimés du registre (repliés : minuscules, sans accents). Un mot par ligne.\n"
              "# Généré par `python -m scripts.build_vocabulary`, depuis le texte imprimé du PDF (jamais l'écriture).\n"
              "# Une étiquette dont les mots manquent ici est lue quand même, mais part en NEEDS_REVIEW.\n"
              "# Ajouter un mot à la main est permis (une ligne).\n")
    VOCABULARY_FILE.write_text(header + "\n".join(sorted(words)) + "\n", encoding="utf-8")
    print(f"{len(words)} mots -> {VOCABULARY_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
