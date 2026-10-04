"""Règles non négociables : format des champs, données personnelles, verrou du test, local uniquement,
contrôles anti-invention. Tests rapides : ni PaddleOCR ni modèle."""

import numpy as np
import pytest

from dayone import imaging, vlm
from dayone.dataset import TestSplitLocked as SplitLocked
from dayone.dataset import load_index
from dayone.extract import _box_field, _colon_fields, _combine, _from_ocr, _orphan_values
from dayone.privacy import is_personal
from dayone.schema import make_field, validate_field, validate_prediction


def line(text, x0, y0, x1, y1, score=0.99):
    return {"text": text, "score": score, "box": (x0, y0, x1, y1)}


def test_field_needs_value_status_confidence():
    with pytest.raises(ValueError):
        validate_field({"value": None, "status": "KNOWN"})                      # confidence manquante
    with pytest.raises(ValueError):
        validate_field({"value": None, "status": "KNOWN", "confidence": 0.9})   # KNOWN sans valeur
    with pytest.raises(ValueError):
        validate_field({"value": 1, "status": "SURE", "confidence": 0.9})
    with pytest.raises(ValueError):
        make_field(1, "KNOWN", 1.5)
    assert make_field(None, "NOT_PROVIDED", 0.95)["value"] is None


@pytest.mark.parametrize("label,value", [
    ("Nom du Mari", "Said"), ("CIN", ""), ("Téléphone", ""), ("Adresse", ""), ("Patiente", "Meryem"),
    ("Profession", "06 00 76 13 48"), ("Remarque", "CB609814"),
])
def test_personal_data_detected(label, value):
    assert is_personal(label, value)


@pytest.mark.parametrize("label,value", [
    ("Profession (mari)", "Ouvrier"), ("Nombre", "1"), ("Mari/famille", "RAS"), ("A domicile", ""),
    ("Date", "12/11/2022"), ("Poids", "3626 g"),
])
def test_not_personal(label, value):
    assert not is_personal(label, value)


def test_prediction_refuses_personal_field():
    f = {"id": "cin", "label": "CIN", "kind": "text", **make_field("AB12345", "KNOWN", 0.9)}
    with pytest.raises(ValueError):
        validate_prediction({"fields": [f]})


def test_test_split_is_locked():
    with pytest.raises(SplitLocked):
        load_index("test")


def test_cloud_is_refused(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "https://ollama.com")
    with pytest.raises(vlm.NotLocalError):
        vlm._check_local("qwen3-vl:4b-instruct")
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11434")
    with pytest.raises(vlm.NotLocalError):
        vlm._check_local("qwen3-vl:235b-cloud")
    assert vlm._check_local("qwen3-vl:4b-instruct")


def L(text, x0, y0, x1, y1, hand=False, score=0.99, i=None):
    return {"text": text, "score": score, "box": (x0, y0, x1, y1), "hand": hand, "i": i}


def _ids(lines):
    for k, l in enumerate(lines):
        l["i"] = k
    return lines


def test_colon_fields_pair_label_and_value():
    img = np.full((400, 1000, 3), 240, np.uint8)
    lines = _ids([L("Age :", 10, 10, 60, 30), L("26", 80, 10, 110, 30, hand=True),
                  L("Niveau d'instruction :", 10, 60, 200, 80), L("Aucun", 220, 60, 280, 80, hand=True),
                  L("Adresse :", 10, 110, 90, 130), L("12 rue X", 100, 108, 300, 135, hand=True)])
    fields = {c["label"]: c["text"] for c in _colon_fields(img, lines, set(), 20, [], blue_page=True)}
    assert fields["Age"] == "26" and fields["Niveau d'instruction"] == "Aucun"
    assert fields["Adresse"] == "12 rue X"          # l'adresse reste sur sa ligne (puis sera filtrée)


def test_printed_text_is_not_a_value_on_blue_pages():
    img = np.full((400, 1000, 3), 240, np.uint8)
    lines = _ids([L("Gestation :", 10, 10, 100, 30), L("Parité", 200, 10, 260, 30)])
    fields = {c["label"]: c["text"] for c in _colon_fields(img, lines, set(), 20, [], blue_page=True)}
    assert fields["Gestation"] == ""


def test_short_label_with_value_on_one_line():
    lines = _ids([L("Vaccinée contre la rubéole", 40, 100, 300, 120), L("Le 12/05/2022", 500, 100, 640, 120)])
    out = _orphan_values(lines, set(), 20, [], blue_page=True)
    assert out[0]["label"] == "Vaccinée contre la rubéole | Le" and out[0]["text"] == "12/05/2022"


def test_value_needs_two_readers():
    img = np.full((100, 300, 3), 240, np.uint8)
    c = {"label": "Age", "text": "26", "score": 0.99, "box": (10, 10, 60, 30)}
    field, again = _from_ocr(img, c, 0.7)
    assert field["status"] == "KNOWN" and field["value"] == 26 and not again
    weak = {**c, "score": 0.6}
    field, again = _from_ocr(img, weak, 0.7)
    assert field["status"] == "NEEDS_REVIEW" and again
    assert _combine(field, weak, "26", 0.7)["status"] == "KNOWN"          # le modèle confirme
    assert _combine(field, weak, "62", 0.7)["status"] == "NEEDS_REVIEW"   # désaccord
    empty = {**c, "text": ""}
    assert _from_ocr(img, empty, 0.7)[0]["status"] == "NOT_PROVIDED"      # ni texte ni encre


def test_near_ras_is_doubtful():
    img = np.full((100, 300, 3), 240, np.uint8)
    field, again = _from_ocr(img, {"label": "HTA", "text": "KAS", "score": 1.0, "box": (0, 0, 40, 20)}, 0.7)
    assert field["status"] == "NEEDS_REVIEW" and again


def test_dotted_line_is_empty():
    img = np.full((100, 300, 3), 240, np.uint8)
    c = {"label": "Autres", "text": "..........", "score": 0.9, "box": (0, 0, 40, 20)}
    assert _from_ocr(img, c, 0.7)[0]["status"] == "NOT_PROVIDED"


def test_checkbox_rules():
    assert _box_field("Rubéole", 0.4)["value"] is True
    assert _box_field("Rubéole", 0.0)["status"] == "NOT_PROVIDED"      # case vide : jamais « false »
    assert _box_field("Rubéole", 0.02)["status"] == "NEEDS_REVIEW"


def test_checkbox_found_and_marked():
    img = np.full((200, 400, 3), 230, np.uint8)
    img[50:72, 40:42] = img[50:72, 60:62] = 20          # côtés verticaux
    img[50:52, 40:62] = img[70:72, 40:62] = 20          # côtés horizontaux
    boxes = imaging.find_checkboxes(img, 22)
    assert len(boxes) == 1
    assert imaging.check_state(imaging.mark_ratio(img, boxes[0])) is False
    for i in range(4, 18):                               # croix au stylo bleu
        img[50 + i, 40 + i] = img[50 + i, 62 - i] = (200, 40, 30)
    assert imaging.check_state(imaging.mark_ratio(img, boxes[0])) is True
    label = imaging.checkbox_label(boxes[0], [line("Consanguinité", 70, 50, 200, 72)], 22)
    assert label == "Consanguinité"


def test_staff_name_is_personal():
    assert is_personal("EXAMEN FAIT PAR | Resu", "Aya")


def test_establishment_name_is_not_personal_but_cin_is():
    assert not is_personal("Nom de l'établissement sanitaire", "CIS Sidi Smail")
    assert is_personal("Nom/Prénom de la parturiente", "")
    assert is_personal("ET DU POST PARTUM", "cm: 164195")          # « CIN : » mal lu par l'OCR


def test_blue_ink_found_under_warm_light():
    img = np.full((60, 200, 3), (180, 174, 232), np.uint8)          # papier rose sous lampe chaude
    img[20:40, 10:80] = (100, 92, 155)                              # imprimé : sombre, même teinte que le papier
    img[20:40, 110:180] = (150, 120, 175)                           # stylo bleu : un peu moins rouge
    bm = imaging.blue_map(img)
    assert bm[30, 140] == 1 and bm[30, 40] == 0


def test_label_and_handwriting_in_one_ocr_line_are_split():
    from dayone.extract import _split_mixed

    img = np.full((60, 400, 3), 240, np.uint8)
    bm = np.zeros((60, 400), np.uint8)
    bm[10:40, 200:380] = 1                                          # écriture bleue à droite
    out = _split_mixed(img, [L("Province El Jadida", 10, 10, 380, 40)], bm)
    assert [o["text"] for o in out] == ["Province", "El Jadida"]


def test_almost_nothing_read_is_doubtful():
    img = np.full((100, 300, 3), 240, np.uint8)
    field, again = _from_ocr(img, {"label": "N° de la fiche", "text": ")", "score": 0.99, "box": (0, 0, 40, 20)}, 0.7)
    assert field["status"] == "NEEDS_REVIEW" and again


@pytest.mark.parametrize("value", ["A64185", "2026-823-001"])
def test_record_number_is_kept(value):
    assert not is_personal("N° de la fiche", value)          # forme de CIN ou de téléphone, mais c'est le code du registre


def test_misread_cin_prefix_is_personal():
    assert is_personal("", "C (M; N64)9S") and is_personal("N° de la fiche", "cin: A64185")


def test_record_number_copying_a_cin_is_dropped():
    from dayone.extract import _copies_id

    assert _copies_id("A64185", ["cm: A64185"]) and _copies_id("A64185", ["C (M; N64)9S"])
    assert not _copies_id("2026-823-001", ["CB609814", "06 00 76 13 48"])


def test_personal_value_masked_up_to_next_label():
    from dayone.extract import _personal_zones
    from dayone.privacy import redact

    img = np.full((100, 1000, 3), 240, np.uint8)
    lines = _ids([L("Nom du Mari :", 10, 40, 120, 60), L("Profession :", 600, 40, 700, 60)])
    cand = [{"label": "Nom du Mari", "text": "", "score": 0.0, "box": (125, 40, 300, 60), "label_box": (10, 40, 120, 60)},
            {"label": "Profession", "text": "Ouvrier", "score": 0.99, "box": (705, 40, 800, 60),
             "label_box": (600, 40, 700, 60)}]
    zones, personal, _ = _personal_zones(img, lines, cand, {0, 1}, 20)
    assert personal == [True, False]
    out = redact(img, zones)
    assert (out[50, 130:590] == 0).all()                      # nom masqué au-delà du trait
    assert (out[50, 10:115] == 240).all() and (out[50, 610:] == 240).all()   # étiquettes et champ voisin intacts


def test_loose_handwriting_is_kept_for_review():
    from dayone.extract import _loose_cap, _loose_handwriting

    lines = _ids([L("Observations", 10, 10, 150, 30), L("Bon état", 20, 50, 120, 70, hand=True),
                  L("06 00 76 13 48", 400, 200, 560, 220, hand=True)])
    zones = []
    out = _loose_handwriting(lines, {0}, 20, zones)
    assert [(c["label"], c["text"]) for c in out] == [("Observations", "Bon état")]
    assert zones == [(400, 200, 560, 220)]                    # téléphone isolé : masqué, pas extrait
    assert _loose_cap(make_field("Bon état", "KNOWN", 0.95, source="ocr"))["status"] == "NEEDS_REVIEW"


@pytest.mark.parametrize("label", ["Nom de l’établissement sanitaire", "Nom de l’établissemient sanitaire"])
def test_establishment_with_curly_apostrophe_is_not_personal(label):
    assert not is_personal(label, "CIS Sidi Smail")


def test_checkbox_group_gives_the_checked_option():
    from dayone.extract import _group_field

    f = _group_field("Mode de la couverture", [("Fixe", True), ("Mobile", False)])
    assert (f["label"], f["value"], f["status"]) == ("Mode de la couverture", "Fixe", "KNOWN")
    assert _group_field("Type", [("DR", False), ("CSC", False)])["status"] == "NOT_PROVIDED"
    assert _group_field("Type", [("DR", True), ("CSC", None)])["status"] == "NEEDS_REVIEW"


def test_evaluation_unfolds_checkbox_groups():
    from dayone.evaluate import expand_groups
    from dayone.extract import _group_field

    out = expand_groups([{"id": "vat", **_group_field("VAT", [("1", True), ("2", False)])}])
    assert [(f["label"], f["value"], f["status"]) for f in out] == [("VAT 1", True, "KNOWN"),
                                                                    ("VAT 2", None, "NOT_PROVIDED")]


def test_box_glued_to_its_word_is_a_box():
    assert imaging._fits_before("Mobile", 574, 665, 30)          # « Mobile☐ »
    assert not imaging._fits_before("CSU", 0, 200, 30)           # trop large : ce n'est pas le mot de la case


def test_unread_ink_finds_a_line_the_ocr_missed():
    img = np.full((300, 800, 3), 240, np.uint8)
    for x in range(50, 300, 7):                                   # « lettres » : traits verticaux
        img[100:120, x:x + 3] = 30                                # ligne non lue
        img[200:220, x:x + 3] = 30                                # ligne déjà lue par l'OCR
    bm = np.zeros((300, 800), np.uint8)
    zones = imaging.unread_ink(img, [(50, 200, 300, 220)], 20, bm)
    assert len(zones) == 1 and zones[0][0][1] < 110 < zones[0][0][3] and zones[0][1] is False


def test_new_or_misread_label_is_never_known():
    from dayone.extract import _flag
    from dayone.vocabulary import label_reason

    assert label_reason("Nombre de grossesses") is None                       # mots connus du registre
    assert label_reason("Patate") == "champ_nouveau"
    assert label_reason("33A$A-11") == "etiquette_douteuse"
    f = {"label": "Patate", "kind": "text", **make_field("Bintje", "KNOWN", 0.95, source="ocr")}
    _flag(f)
    assert (f["status"], f["raison"]) == ("NEEDS_REVIEW", "champ_nouveau") and f["confidence"] <= 0.6
    g = {"label": "Mode de la couverture", "kind": "text", "options": ["Fixe", "Patate"],
         **make_field("Patate", "KNOWN", 0.9, source="case")}
    _flag(g)
    assert (g["status"], g["raison"]) == ("NEEDS_REVIEW", "choix_nouveau")


def test_school_report_is_refused_without_model():
    from dayone.extract import _health_words

    school = [line("Bulletin de notes", 0, 0, 1, 1), line("Moyenne générale : 14", 0, 0, 1, 1),
              line("Mathématiques", 0, 0, 1, 1), line("Appréciation du professeur", 0, 0, 1, 1)]
    health = [line("Fiche de surveillance de la grossesse", 0, 0, 1, 1), line("Poids : 62 kg", 0, 0, 1, 1),
              line("Accouchement", 0, 0, 1, 1)]
    assert not _health_words(school) and _health_words(health)


@pytest.mark.parametrize("text", ["MÈRE — Tazi Meryem", "Patiente - Salma Idrissi", "الأم — فاطمة"])
def test_printed_name_in_header_is_personal(text):
    assert is_personal(text)


@pytest.mark.parametrize("label", ["الاسم الكامل", "رقم الهاتف", "العنوان", "اسم الزوج", "Patient name", "Phone"])
def test_arabic_and_english_personal_labels(label):
    assert is_personal(label)


def test_arabic_label_takes_the_value_on_its_left():
    img = np.full((100, 1000, 3), 240, np.uint8)
    lines = _ids([L("الوزن :", 800, 40, 900, 60), L("62", 600, 40, 650, 60, hand=True)])
    fields = {c["label"]: c["text"] for c in _colon_fields(img, lines, set(), 20, [], blue_page=True)}
    assert fields == {"الوزن": "62"}


def test_fold_keeps_arabic_letters():
    from dayone.normalize import fold

    assert fold("الاسْم : فاطمة") == "الاسم فاطمة" and fold("Mort fœtale in utéro") == "mort foetale in utero"


def test_arabic_label_and_handwriting_in_one_ocr_line_are_split():
    from dayone.extract import _split_mixed

    img = np.full((60, 400, 3), 240, np.uint8)
    bm = np.zeros((60, 400), np.uint8)
    bm[10:40, 20:180] = 1                                           # écriture bleue à gauche
    out = _split_mixed(img, [L("الوزن : 64 كغ", 10, 10, 380, 40)], bm)
    assert [(o["text"], o["box"][0] > 150) for o in out] == [("الوزن :", True), ("64 كغ", False)]


def test_leading_punctuation_is_not_part_of_the_value():
    img = np.full((100, 300, 3), 240, np.uint8)
    field, _ = _from_ocr(img, {"label": "Occupation", "text": ":Teacher", "score": 0.99, "box": (0, 0, 40, 20)}, 0.7)
    assert field["value"] == "Teacher"


def test_misread_arabic_name_label_is_still_personal():
    assert is_personal("ام الدمل")                                  # « الاسم الكامل » mal lu
    assert not is_personal("العمر") and not is_personal("عد الولادات")


def test_blue_letter_o_is_not_a_checkbox():
    img = np.full((100, 100, 3), 240, np.uint8)
    img[30:32, 30:56], img[54:56, 30:56], img[30:56, 30:32], img[30:56, 54:56] = 30, 30, 30, 30
    bm = np.zeros((100, 100), np.uint8)
    assert imaging.find_checkboxes(img, 26)                            # carré noir : une case
    bm[28:58, 28:58] = 1
    assert not imaging.find_checkboxes(img, 26, bm)                    # même carré, tracé en bleu : une lettre


def test_unread_handwriting_next_to_a_label_becomes_a_field():
    from dayone.extract import _ink_fields

    img = np.full((100, 800, 3), 240, np.uint8)
    bm = np.zeros((100, 800), np.uint8)
    img[40:60, 300:360] = (200, 60, 20)                               # « écriture » bleue non lue par l'OCR
    bm[40:60, 300:360] = 1
    lines = _ids([L("Weight", 100, 40, 200, 60)])
    out = _ink_fields(img, lines, set(), 20, [], bm)
    assert [(c["label"], c["text"]) for c in out] == [("Weight", "")] and out[0]["box"][0] >= 290
