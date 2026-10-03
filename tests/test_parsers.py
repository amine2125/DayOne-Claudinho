from datetime import date

import pytest

from app.schemas.form_spec import FIELDS_BY_KEY as F
from app.validators.parsers import parse_date, parse_value
from app.validators.plausibility import check_range, cross_field_conflicts


@pytest.mark.parametrize("text,expected", [
    ("68 kg", 68.0), ("68kg", 68.0), ("68,5 kg", 68.5), ("٦٨ كغ", 68.0), ("685", 68.5),
])
def test_poids(text, expected):
    r = parse_value(text, F["poids_kg"])
    assert r.ok and r.value == expected


def test_virgule_manquante_produit_un_avertissement():
    r = parse_value("375", F["temperature"])
    assert r.value == 37.5 and "virgule_manquante_supposee" in r.warnings


def test_plusieurs_nombres_refuse():
    assert not parse_value("68 (65)", F["poids_kg"]).ok


def test_age_entier():
    assert parse_value("28 ans", F["age"]).value == 28
    assert not parse_value("28,5", F["age"]).ok


@pytest.mark.parametrize("text,sys_,dia,warn", [
    ("120/80", 120, 80, False), ("TA 135 / 85 mmHg", 135, 85, False), ("12/8", 120, 80, True),
])
def test_tension(text, sys_, dia, warn):
    r = parse_value(text, F["tension_arterielle"])
    assert r.value == {"tension_systolique": sys_, "tension_diastolique": dia}
    assert ("cmHg_converti_en_mmHg" in r.warnings) == warn


@pytest.mark.parametrize("text,expected", [
    ("NEG", "NEGATIF"), ("négatif", "NEGATIF"), ("negative", "NEGATIF"), ("سلبي", "NEGATIF"),
    ("Positif", "POSITIF"), ("TPHA neg", "NEGATIF"), ("negatlf", "NEGATIF"), ("-", "NEGATIF"),
])
def test_serologie(text, expected):
    assert parse_value(text, F["vih"]).value == expected


def test_serologie_symbole_avertit():
    assert "symbole_interprete" in parse_value("+", F["vih"]).warnings


def test_serologie_contradictoire():
    assert not parse_value("pos neg", F["vih"]).ok


@pytest.mark.parametrize("text,group,rh", [
    ("O+", "O", "POSITIF"), ("AB Rh-", "AB", "NEGATIF"), ("A neg", "A", "NEGATIF"), ("B", "B", None),
])
def test_groupe(text, group, rh):
    assert parse_value(text, F["groupe_rhesus"]).value == {"groupe_sanguin": group, "rhesus": rh}


def test_groupe_zero_lu_comme_o():
    r = parse_value("0+", F["groupe_rhesus"])
    assert r.value["groupe_sanguin"] == "O" and "zero_lu_comme_O" in r.warnings


@pytest.mark.parametrize("text,expected", [("32 SA", 32), ("32SA+3j", 32.4), ("32+3", 32.4)])
def test_age_gestationnel(text, expected):
    assert parse_value(text, F["age_gestationnel"]).value == expected


def test_age_gestationnel_en_mois_refuse():
    assert not parse_value("7 mois", F["age_gestationnel"]).ok


def test_gesta_para():
    assert parse_value("G3P2", F["gesta_para"]).value == {"gestite": 3, "parite": 2}
    assert parse_value("3/2", F["gesta_para"]).value == {"gestite": 3, "parite": 2}


def test_dates():
    today = date(2026, 1, 1)
    assert parse_date("14/03/2025", F["date_consultation"], today).value == "2025-03-14"
    assert parse_date("14-03-25", F["date_consultation"], today).value == "2025-03-14"
    assert parse_date("٢٠٢٥/٠٣/١٤", F["date_consultation"], today).value == "2025-03-14"
    assert parse_date("31/02/2025", F["date_consultation"], today).error == "date_inexistante"
    assert parse_date("01/01/2027", F["date_consultation"], today).error == "date_dans_le_futur"


def test_mode_accouchement():
    assert parse_value("VB", F["mode_accouchement"]).value == "VOIE_BASSE"
    assert parse_value("Césarienne", F["mode_accouchement"]).value == "CESARIENNE"
    assert parse_value("قيصرية", F["mode_accouchement"]).value == "CESARIENNE"


def test_bornes_detectent_erreur_extraction():
    assert not check_range("poids_kg", 680).hard_ok
    assert check_range("poids_kg", 145).warning == "valeur_inhabituelle_a_verifier"
    assert check_range("poids_kg", 68).warning is None


def test_coherence_inter_champs():
    assert cross_field_conflicts({"tension_systolique": 80, "tension_diastolique": 120})
    assert cross_field_conflicts({"gestite": 1, "parite": 3})
    assert not cross_field_conflicts({"gestite": 3, "parite": 2})
