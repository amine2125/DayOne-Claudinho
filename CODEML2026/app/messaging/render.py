"""JSON final -> message lisible (WhatsApp ou interface simulée). L'utilisateur ne voit jamais le JSON."""
from __future__ import annotations

from app.schemas.form_spec import DISPLAY_NAMES, OUTPUT_FIELDS, OUTPUT_UNITS
from app.schemas.models import ExtractionRecord, FieldResult, FieldStatus, QualityReport

RETAKE_TIPS = {
    "photo_floue": "la photo est floue : tenez le téléphone immobile et touchez l'écran pour faire la mise au point",
    "photo_trop_sombre": "la photo est trop sombre : rapprochez-vous d'une fenêtre ou d'une lumière",
    "photo_surexposee": "la photo est trop claire : évitez le flash et les reflets",
    "contraste_insuffisant": "le texte ressort mal : placez la page sur un fond sombre et uni",
    "page_incomplete": "je ne trouve pas assez de champs : cadrez la page entière, sans doigt ni objet dessus",
    "aucun_libelle": "je ne reconnais pas le formulaire : cadrez la page entière, bien à plat",
}

_VALUE_LABELS = {
    "NEGATIF": "négatif", "POSITIF": "positif", "VOIE_BASSE": "voie basse",
    "CESARIENNE": "césarienne", "INSTRUMENTALE": "instrumentale", "AUCUNE": "aucune",
}


def _fmt_value(key: str, value) -> str:
    if key.startswith("date") and isinstance(value, str) and len(value) == 10:
        y, m, d = value.split("-")
        return f"{d}/{m}/{y}"
    if isinstance(value, float):
        txt = f"{value:g}".replace(".", ",")
    else:
        txt = _VALUE_LABELS.get(str(value), str(value))
    unit = OUTPUT_UNITS.get(key)
    return f"{txt} {unit}" if unit else txt


def _line(name: str, key: str, res: FieldResult) -> str | None:
    s = res.status
    if s == FieldStatus.CONNU:
        return f"✅ {name} : {_fmt_value(key, res.value)}"
    if s == FieldStatus.A_REVISER:
        if res.value is not None:
            return f"⚠️ {name} : {_fmt_value(key, res.value)} ? (à vérifier)"
        if "champ_non_localise" in res.reasons:
            return f"⚠️ {name} : non trouvé sur la photo"
        return f"⚠️ {name} : à vérifier" + (f" (lu « {res.raw_text} »)" if res.raw_text else "")
    if s == FieldStatus.ILLISIBLE:
        return f"❓ {name} : illisible"
    if s == FieldStatus.INCONNU:
        return f"➖ {name} : noté inconnu"
    if s == FieldStatus.NON_APPLICABLE:
        return f"➖ {name} : non applicable"
    if s == FieldStatus.NON_FOURNI:
        return None if "absent_du_registre" in res.reasons else f"➖ {name} : non renseigné"
    return None


def render_record(record: ExtractionRecord, n_records: int = 1) -> str:
    f = record.fields
    lines: list[str] = []
    done: set[str] = set()
    for key in OUTPUT_FIELDS:
        if key in done or key not in f:
            continue
        if key == "tension_systolique" and "tension_diastolique" in f:
            sys_, dia = f["tension_systolique"], f["tension_diastolique"]
            done.add("tension_diastolique")
            if sys_.status == dia.status == FieldStatus.CONNU:
                lines.append(f"✅ TA : {sys_.value}/{dia.value} mmHg")
                continue
            if sys_.value is not None and dia.value is not None and FieldStatus.ILLISIBLE not in (sys_.status, dia.status):
                lines.append(f"⚠️ TA : {sys_.value}/{dia.value} mmHg ? (à vérifier)")
                continue
        line = _line(DISPLAY_NAMES.get(key, key), key, f[key])
        if line:
            lines.append(line)
    header = f"Ligne {record.row_index + 1}/{n_records} — j'ai extrait :" if n_records > 1 else "J'ai extrait :"
    return "\n".join([header, *lines])


def render_response(records: list[ExtractionRecord], quality: QualityReport, needs_retake: bool,
                    retake_reason: str | None) -> str:
    if needs_retake and not records:
        tip = RETAKE_TIPS.get(retake_reason or "", "la photo n'est pas exploitable")
        return f"📷 Je ne peux pas lire cette photo : {tip}.\n\n[Reprendre la photo]   [Saisir à la main]"
    parts = [render_record(r, len(records)) for r in records]
    n_review = sum(1 for r in records for v in r.fields.values()
                   if v.status in (FieldStatus.A_REVISER, FieldStatus.ILLISIBLE))
    footer: list[str] = []
    if n_review:
        footer.append(f"{n_review} champ(s) à vérifier. Le registre papier fait foi.")
    if needs_retake:
        footer.append("💡 " + RETAKE_TIPS.get(retake_reason or "", "une meilleure photo aiderait").capitalize() + ".")
    footer.append("[Confirmer]   [Corriger]   [Reprendre la photo]")
    return "\n\n".join(parts) + "\n\n" + "\n".join(footer)
