"""Rendu WhatsApp des contrôles de cohérence et des poids de la mère (kg)."""
from app import render


def test_alerte_de_coherence_expliquee_a_la_sage_femme():
    page = {"pageType": "grossesse_actuelle", "fields": {
        "rdv": {"label": "Rendez-vous | 2ème trimestre - Visite 3", "kind": "date", "section": "Autres champs lus",
                "value": "2025-01-29", "status": "NEEDS_REVIEW", "reason": "incoherent",
                "alerts": [{"code": "appointment_before_visit", "params": {},
                            "text": "Rendez-vous 29/01/2025 : avant la visite du 01/11/2025 : à vérifier sur le papier."}]}}}
    text = render.confirm_uncertain_text(page)
    assert "ne colle pas avec le reste du registre" in text
    assert "avant la visite du 01/11/2025" in text
    assert render.page_name(page) == "Grossesse actuelle"


def test_poids_de_la_mere_en_kg():
    assert render.format_value("weight", {"value": 62700, "status": "KNOWN"}) == "62,7 kg"
    assert render.format_value("weight", {"value": 3250, "status": "KNOWN"}) == "3250 g"
    assert render.parse_value("weight", "62,7 kg") == (62700, "KNOWN")
    assert render.parse_value("weight", "62.7") == (62700, "KNOWN")
    assert render.parse_value("weight", "3250") == (3250, "KNOWN")
