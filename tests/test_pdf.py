"""Fiche PDF d'un dossier validé : mise en page, tableaux, arabe, aucune donnée personnelle ajoutée."""
import pypdfium2 as pdfium

from api.pdf import _section_blocks, build_pdf, value_text


def field(label, value, status="KNOWN", kind="text", section="Identification", origin="AI"):
    return {"key": label, "label": label, "kind": kind, "section": section, "value": value, "status": status, "origin": origin}


FINAL = {"record_id": "rec_1", "patient_code": "AMN-27", "midwife_id": "wa-1", "captured_at": "2026-10-04T09:00:00",
         "validated_at": "2026-10-04T09:10:00", "pages": [{"index": 0, "page_type": "identification_antecedents", "fields": [
             field("Age", 31, kind="integer"), field("Date", "2026-02-03", kind="date"),
             field("HTA | Famille de la femme", "aucun", section="Antécédents"), field("HTA | Mari", "Père", section="Antécédents"),
             field("Diabète | Famille de la femme", "aucun", section="Antécédents"), field("Diabète | Mari", None, "NOT_PROVIDED", section="Antécédents"),
             field("فصيلة الدم", "O+", origin="MANUAL"), field("Poids", 3250, "NEEDS_REVIEW", kind="weight")]}]}


def test_pdf_is_built_and_readable():
    data = build_pdf(FINAL)
    assert data.startswith(b"%PDF")
    text = pdfium.PdfDocument(data)[0].get_textpage().get_text_range()
    assert "AMN-27" in text and "03/02/2026" in text and "3250 g" in text and "à vérifier" in text


def test_registry_table_becomes_a_grid():
    blocks = _section_blocks(FINAL["pages"][0]["fields"][2:6])
    assert blocks[0][0] == "grid" and blocks[0][1]["rows"] == ["HTA", "Diabète"]
    assert blocks[0][1]["cols"] == ["Famille de la femme", "Mari"]


def test_values_are_readable():
    assert value_text({"value": True, "status": "KNOWN"}) == "Oui"
    assert value_text({"value": None, "status": "UNKNOWN"}) == "Inconnu"
    assert value_text({"value": "........", "status": "NEEDS_REVIEW"}) == "—"     # pointillés du formulaire
    assert value_text({"value": "F", "status": "KNOWN", "kind": "sex"}) == "Féminin"
