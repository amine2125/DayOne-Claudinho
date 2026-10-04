"""Règles non négociables : schéma, statuts, données personnelles, verrou du test, local uniquement."""

import json

import pytest

from dayone import vlm
from dayone.dataset import TestSplitLocked as SplitLocked, load_index
from dayone.extract import _apply_not_applicable, _checkbox, _combine, _from_ocr
from dayone.schema import FORBIDDEN_FIELDS, V1_PAGE_TYPES, load_schema, make_field, validate_field


@pytest.mark.parametrize("page_type", V1_PAGE_TYPES)
def test_schema_has_no_personal_field(page_type):
    s = load_schema(page_type)
    ids = {f.id for f in s.fields}
    assert not ids & set(FORBIDDEN_FIELDS)
    # Aucune zone lue ne recouvre une zone personnelle.
    for x0, y0, x1, y1 in s.excluded_zones.values():
        for f in s.fields:
            if f.zone:
                fx0, fy0, fx1, fy1 = f.zone
                overlap_w = min(x1, fx1) - max(x0, fx0)
                overlap_h = min(y1, fy1) - max(y0, fy0)
                assert overlap_w <= 0 or overlap_h <= 12, f"{f.id} recouvre une zone personnelle"


def test_field_needs_value_status_confidence():
    with pytest.raises(ValueError):
        validate_field({"value": None, "status": "KNOWN"})            # confidence manquante
    with pytest.raises(ValueError):
        validate_field({"value": None, "status": "KNOWN", "confidence": 0.9})  # KNOWN sans valeur
    with pytest.raises(ValueError):
        validate_field({"value": 1, "status": "SURE", "confidence": 0.9})
    with pytest.raises(ValueError):
        make_field(1, "KNOWN", 1.5)
    assert make_field(None, "NOT_PROVIDED", 0.95)["value"] is None


def test_test_split_is_locked():
    with pytest.raises(SplitLocked):
        load_index("test")


def test_cloud_is_refused(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "https://ollama.com")
    with pytest.raises(vlm.NotLocalError):
        vlm._check_local("qwen3-vl:2b-instruct")
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11434")
    with pytest.raises(vlm.NotLocalError):
        vlm._check_local("qwen3-vl:235b-cloud")
    assert vlm._check_local("qwen3-vl:2b-instruct")


def test_checkbox_rules():
    assert _checkbox(0.4)["value"] is True and _checkbox(0.4)["status"] == "KNOWN"
    assert _checkbox(0.0)["status"] == "NOT_PROVIDED"   # case seule vide : jamais « false »
    assert _checkbox(0.04)["status"] == "NEEDS_REVIEW"


def test_ras_is_known_none():
    f = load_schema("identification_antecedents").field("hered_hta_femme")
    field, doubtful = _from_ocr(f, "RAS", 0.99, 200, 0.7)
    assert field == {"value": "aucun", "status": "KNOWN", "confidence": 0.99, "source": "ocr"}
    assert not doubtful


def test_near_ras_goes_to_review():
    f = load_schema("identification_antecedents").field("hered_hta_femme")
    field, doubtful = _from_ocr(f, "KAS", 1.0, 200, 0.7)
    assert field["status"] == "NEEDS_REVIEW" and doubtful


def test_cross_reading():
    f = load_schema("identification_antecedents").field("acc1_poids")
    ocr_field, _ = _from_ocr(f, "3626 9", 0.6, 200, 0.7)
    agree = _combine(f, "3626 9", ocr_field, "3626 g", 0.7)
    assert agree["status"] == "KNOWN" and agree["value"] == 3626
    disagree = _combine(f, "3626 9", ocr_field, "3826 g", 0.7)
    assert disagree["status"] == "NEEDS_REVIEW"
    # Un seul lecteur (OCR muet, modèle répond) : jamais KNOWN.
    empty, _ = _from_ocr(f, "", 0.0, 200, 0.7)
    assert _combine(f, "", empty, "3626 g", 0.7)["status"] == "NEEDS_REVIEW"
    assert _combine(f, "", empty, "EMPTY", 0.7)["status"] == "NOT_PROVIDED"


def test_not_applicable():
    s = load_schema("accouchement")
    fields = {f.id: make_field(None, "NOT_PROVIDED", 0.95) for f in s.fields}
    _apply_not_applicable(s, fields)
    assert fields["cesarienne_indication"]["status"] == "NOT_APPLICABLE"
    fields = {f.id: make_field(None, "NOT_PROVIDED", 0.95) for f in s.fields}
    fields["mode_cesarienne_urgence"] = make_field(True, "KNOWN", 1.0)
    _apply_not_applicable(s, fields)
    assert fields["cesarienne_indication"]["status"] == "NOT_PROVIDED"


def test_predictions_contain_no_personal_key(tmp_path):
    from dayone.dataset import OUTPUTS

    for p in (OUTPUTS / "predictions").glob("*.json"):
        pred = json.loads(p.read_text(encoding="utf-8"))
        assert not set(pred["fields"]) & set(FORBIDDEN_FIELDS)
        assert "/" not in pred["source"], "pas de chemin complet dans les sorties"
