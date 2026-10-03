from app.mapping.mapper import FieldCandidate
from app.ocr.types import BBox
from app.schemas.form_spec import FIELDS_BY_KEY as F
from app.schemas.models import FieldSource, FieldStatus as S, Localisation, QualityLevel
from app.scoring.confidence import compute_confidence
from app.scoring.status import FieldContext, VLMReading, resolve
from tests.helpers import tok

GOOD = QualityLevel.BONNE
ZONE = BBox(300, 100, 600, 130)


def cand(key, text, conf=0.95, loc=Localisation.RIGHT):
    toks = [tok(text, 300, 100, 400, 130, conf)] if text is not None else []
    return FieldCandidate(key, text, toks, loc, zone=ZONE)


def one(key, text, conf=0.95, **ctx):
    return resolve(F[key], cand(key, text, conf), FieldContext(quality=GOOD, **ctx))[key]


def test_connu():
    r = one("poids_kg", "68 kg", 0.97)
    assert (r.value, r.status, r.source) == (68.0, S.CONNU, FieldSource.OCR)


def test_confiance_faible_a_reviser_puis_illisible():
    assert one("poids_kg", "68", 0.7).status == S.A_REVISER
    r = one("poids_kg", "68", 0.2)
    assert r.status == S.ILLISIBLE and r.value is None and r.raw_text == "68"


def test_zone_vide_vs_encre():
    assert one("bcf_bpm", None, ink=0.0).status == S.NON_FOURNI
    assert one("bcf_bpm", None, ink=0.08).status == S.ILLISIBLE


def test_mentions_explicites():
    assert one("syphilis", "inconnu").status == S.INCONNU
    assert one("syphilis", "?").status == S.INCONNU
    assert one("syphilis", "N/A").status == S.NON_APPLICABLE
    assert one("syphilis", "non fait").status == S.NON_FOURNI


def test_valeur_impossible_jamais_connue():
    r = one("poids_kg", "300 kg", 0.99)
    assert r.status == S.A_REVISER and "valeur_impossible_erreur_extraction_probable" in r.reasons


def test_virgule_supposee_proposee_mais_a_reviser():
    r = one("poids_kg", "680 kg", 0.99)
    assert r.status == S.A_REVISER and r.value == 68.0 and "virgule_manquante_supposee" in r.reasons


def test_non_localise_et_absent():
    r = resolve(F["poids_kg"], None, FieldContext(quality=GOOD))["poids_kg"]
    assert r.status == S.A_REVISER and "champ_non_localise" in r.reasons
    r = resolve(F["poids_kg"], None, FieldContext(quality=GOOD, absent_from_form=True))["poids_kg"]
    assert r.status == S.NON_FOURNI


def test_composite_eclate():
    out = resolve(F["tension_arterielle"], cand("tension_arterielle", "120/80", 0.96), FieldContext(quality=GOOD))
    assert out["tension_systolique"].value == 120 and out["tension_diastolique"].value == 80
    assert out["tension_systolique"].status == S.CONNU


def test_vlm_accord_abaisse_le_seuil_sans_changer_le_score():
    no_vlm = one("poids_kg", "68", 0.78)
    agree = one("poids_kg", "68", 0.78, vlm=VLMReading("68 kg", True))
    assert no_vlm.status == S.A_REVISER and agree.status == S.CONNU
    assert agree.confidence == no_vlm.confidence and agree.source == FieldSource.OCR_VLM


def test_vlm_desaccord_force_revision():
    r = one("poids_kg", "68", 0.99, vlm=VLMReading("63", True))
    assert r.status == S.A_REVISER and r.value == 68.0 and r.alternatives == [63.0]


def test_vlm_seul_jamais_connu():
    r = one("poids_kg", None, ink=0.1, vlm=VLMReading("72", True))
    assert r.status == S.A_REVISER and r.value == 72.0 and r.source == FieldSource.VLM and r.confidence == 0.0


def test_vlm_illisible_nest_pas_utilise():
    assert one("poids_kg", None, ink=0.1, vlm=VLMReading("72", False)).status == S.ILLISIBLE


def test_texte_libre_toujours_relu():
    assert one("complications", "hémorragie post-partum", 0.99).status == S.A_REVISER
    assert one("complications", "RAS", 0.99).status == S.CONNU


def test_formule_confiance():
    score, sig = compute_confidence(0.9, QualityLevel.MOYENNE, Localisation.BELOW, 100, n_warnings=1)
    assert score == round(0.9 * 0.9 * 0.95 * 0.8, 3)
    assert sig.quality == 0.9 and sig.localisation == 0.95 and sig.validation == 0.8
