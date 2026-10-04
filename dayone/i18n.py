"""Textes de l'interface en français et en anglais (la lecture des fiches ne dépend pas de la langue choisie)."""

import re

LANGS = {"fr": "Français", "en": "English"}

TEXTS = {
    "fr": {
        "title": "DayOne — lecture de fiches de santé",
        "caption": "Photo d'une fiche (français, arabe, anglais) → champs structurés (valeur, statut, confiance). "
                   "100 % local, aucune donnée personnelle extraite (nom, CIN, téléphone, adresse).",
        "settings": "Réglages",
        "model": "Modèle local (Ollama)",
        "threshold": "Seuil « à vérifier »",
        "ollama_ready": "Ollama : prêt",
        "ollama_off": "Ollama : {why}",
        "source": "Source",
        "upload": "Importer une photo",
        "dev_page": "Page du jeu de développement",
        "uploader": "Photo ou scan d'une fiche (PNG, JPG)",
        "page": "Page",
        "page_label": "Page {n} — patiente {p} — {t}",
        "read": "Lire la fiche",
        "reading": "Lecture en cours (environ 1 minute)…",
        "done": "Terminé en {s} s",
        "refused": "Image refusée",
        "failed": "Échec",
        "start": "Choisir une photo ou une page, puis cliquer sur « Lire la fiche ».",
        "untitled": "Fiche lue",
        "personal_ignored": "{n} champ(s) personnel(s) ignoré(s), jamais extrait(s).",
        "image_caption": "Image lue — {n} zone(s) personnelle(s) masquée(s)",
        "only_review": "Seulement les champs à vérifier",
        "col_label": "Champ", "col_value": "Valeur", "col_status": "Statut", "col_confidence": "Confiance",
        "col_reason": "Pourquoi", "col_read": "Lu sur la page", "col_source": "Source",
        "edit_help": "Corriger une valeur ou un statut directement dans le tableau : le champ passe en source "
                     "« humain », confiance 1. « Lu sur la page » : mot complété par le lexique (lettre accentuée "
                     "absente de la page).",
        "known_needs_value": "{label} : le statut KNOWN exige une valeur.",
        "download": "Télécharger le résultat (JSON)",
        "reference": "Comparaison à la référence",
        "no_reference": "Pas de référence remplie pour cette page ({f}).",
        "accuracy": "Exactitude", "known_ok": "Valeurs connues justes", "to_review": "À vérifier",
        "silent": "Erreurs silencieuses",
    },
    "en": {
        "title": "DayOne — health record reader",
        "caption": "Photo of a record (French, Arabic, English) → structured fields (value, status, confidence). "
                   "100% local, no personal data extracted (name, national ID, phone, address).",
        "settings": "Settings",
        "model": "Local model (Ollama)",
        "threshold": "“Needs review” threshold",
        "ollama_ready": "Ollama: ready",
        "ollama_off": "Ollama: {why}",
        "source": "Source",
        "upload": "Upload a photo",
        "dev_page": "Development set page",
        "uploader": "Photo or scan of a record (PNG, JPG)",
        "page": "Page",
        "page_label": "Page {n} — patient {p} — {t}",
        "read": "Read the record",
        "reading": "Reading (about 1 minute)…",
        "done": "Done in {s} s",
        "refused": "Image refused",
        "failed": "Failed",
        "start": "Choose a photo or a page, then click “Read the record”.",
        "untitled": "Record read",
        "personal_ignored": "{n} personal field(s) ignored, never extracted.",
        "image_caption": "Image read — {n} personal area(s) blacked out",
        "only_review": "Only fields that need review",
        "col_label": "Field", "col_value": "Value", "col_status": "Status", "col_confidence": "Confidence",
        "col_reason": "Why", "col_read": "Read on the page", "col_source": "Source",
        "edit_help": "Fix a value or a status directly in the table: the field becomes source “human”, "
                     "confidence 1. “Read on the page”: word completed by the lexicon (accented letter missing "
                     "on the page).",
        "known_needs_value": "{label}: status KNOWN requires a value.",
        "download": "Download the result (JSON)",
        "reference": "Comparison with the reference",
        "no_reference": "No filled-in reference for this page ({f}).",
        "accuracy": "Accuracy", "known_ok": "Correct known values", "to_review": "Needs review",
        "silent": "Silent errors",
    },
}

STATUS = {
    "fr": {"KNOWN": "lu", "NEEDS_REVIEW": "à vérifier", "ILLEGIBLE": "illisible", "UNKNOWN": "inconnu",
           "NOT_PROVIDED": "vide", "NOT_APPLICABLE": "sans objet"},
    "en": {"KNOWN": "read", "NEEDS_REVIEW": "needs review", "ILLEGIBLE": "illegible", "UNKNOWN": "unknown",
           "NOT_PROVIDED": "empty", "NOT_APPLICABLE": "not applicable"},
}

REASON = {
    "fr": {"non_rattache": "écriture rattachée à aucun champ", "etiquette_douteuse": "étiquette mal lue",
           "champ_nouveau": "champ inconnu du registre", "choix_nouveau": "case inconnue du registre",
           "valeur_douteuse": "lecture incertaine"},
    "en": {"non_rattache": "handwriting not linked to a field", "etiquette_douteuse": "label misread",
           "champ_nouveau": "field unknown to the registry", "choix_nouveau": "checkbox unknown to the registry",
           "valeur_douteuse": "uncertain reading"},
}

# Messages du pipeline (écrits en français) -> anglais.
MESSAGES_EN = [
    (r"Lecture du texte \(PaddleOCR\)", "Reading the text (PaddleOCR)"),
    (r"Tableaux, cases à cocher, étiquettes", "Tables, checkboxes, labels"),
    (r"Vérification : est-ce bien une fiche de santé \?", "Checking: is this a health record?"),
    (r"Relecture de (\d+) valeur\(s\) douteuse\(s\) ou non rattachée\(s\) par (.+)",
     r"Second reading of \1 doubtful or unlinked value(s) by \2"),
    (r"Presque aucun texte sur cette image : ce n'est pas une fiche à lire\.",
     "Almost no text on this image: it is not a record to read."),
    (r"Cette image n'est pas une fiche ou un registre de santé\.", "This image is not a health record or registry."),
    (r"Cette image ne ressemble pas à une fiche de santé \(aucun mot du domaine lu\)\.",
     "This image does not look like a health record (no health-related words read)."),
    (r"serveur Ollama injoignable \(lancer `ollama serve`\)", "Ollama server unreachable (run `ollama serve`)"),
    (r"modèle (\S+) absent \(lancer `ollama pull \S+`\)", r"model \1 missing (run `ollama pull \1`)"),
    (r"PaddleOCR a échoué : ", "PaddleOCR failed: "),
    (r"Image illisible \(formats acceptés : PNG, JPG\)\.", "Unreadable image (accepted formats: PNG, JPG)."),
]


def t(lang: str, key: str, **kw) -> str:
    return TEXTS[lang][key].format(**kw)


def message(lang: str, text: str) -> str:
    """Message du pipeline dans la langue de l'interface."""
    if lang == "fr":
        return text
    for pattern, repl in MESSAGES_EN:
        text = re.sub(pattern, repl, text)
    return text
