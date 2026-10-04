"""Base locale : parcours complet d'un dossier, chiffrement au repos, liaison sans création silencieuse."""
import json

import pytest

from api import store

PRED = json.load(open(store.ROOT / "outputs/predictions/page_02_identification_antecedents.json", encoding="utf-8"))


@pytest.fixture(autouse=True)
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(store, "CAPTURES", tmp_path / "captures")
    monkeypatch.setattr(store, "KEY_FILE", tmp_path / "key")
    monkeypatch.setattr(store, "_initialized", False)
    monkeypatch.setattr(store, "_fernet", None)


def fake_extract(data, use_model=True):
    return dict(PRED)                            # sans zones_masquees : pas de vue masquée à produire


def captured(code="AMN-27"):
    rid = store.create_record(code, "SF-014", [b"photo"])
    store.process_record(rid, extract=fake_extract)
    return rid


def resolve_all(rid):
    rec = store.snapshot(str)["records"][rid]
    for f in rec["pages"][0]["fields"].values():
        if f["status"] in store.TO_REVIEW:
            store.set_field(rid, 0, f["key"], "SF-014", value=None, status="NOT_PROVIDED")


def test_capture_lue_puis_a_verifier():
    rid = captured()
    rec = store.snapshot(str)["records"][rid]
    assert rec["state"] == "NEEDS_REVIEW"
    assert [h["state"] for h in rec["history"]] == ["CAPTURED", "PENDING_AI", "AI_PROCESSED", "NEEDS_REVIEW"]
    assert rec["pages"][0]["fields"]["age"]["value"] == 31


def test_valeurs_et_photo_chiffrees_au_repos(tmp_path):
    rid = captured()
    raw = (tmp_path / "test.db").read_bytes()
    # Valeurs lues jamais en clair. Les accents ne peuvent pas apparaître par hasard dans le chiffré (base64).
    assert "Lycée".encode() not in raw and "Étudiante".encode() not in raw
    assert PRED["title"].encode() not in raw                          # le titre lu est chiffré aussi
    photo = next((tmp_path / "captures").iterdir()).read_bytes()
    assert photo != b"photo" and store.fernet().decrypt(photo) == b"photo"
    assert rid


def test_lecture_impossible_donne_echec():
    rid = store.create_record("DRS-90", "SF-014", [b"x"])
    store.process_record(rid, extract=lambda *a, **k: (_ for _ in ()).throw(ValueError("mise en page")))
    rec = store.snapshot(str)["records"][rid]
    assert rec["state"] == "PROCESSING_FAILED" and rec["failure"]["reason"] == "LAYOUT"
    assert rec["pages"][0]["error"] == "mise en page"


def test_champs_ranges_dans_le_contrat():
    rid = captured()
    page = store.snapshot(str)["records"][rid]["pages"][0]
    assert page["pageType"] == "identification_antecedents" and page["title"]
    age = page["fields"]["age"]
    assert (age["label"], age["kind"], age["section"], age["value"]) == ("Age", "integer", "Identification", 31)
    autres = [f for f in page["fields"].values() if f["section"] == store.OTHER_SECTION]
    assert autres and all(f["label"] for f in autres)        # champ hors référence : gardé, avec son libellé


def test_page_inconnue_si_aucune_reference_ne_correspond():
    pred = {"title": "Fiche", "fields": [{"id": "x", "label": "Patate", "kind": "text",
                                          "value": "a", "status": "KNOWN", "confidence": 0.9}]}
    assert store.page_type_of(pred) == "unknown"
    assert store.fields_from_prediction(pred, 0, "t")["x"]["section"] == store.OTHER_SECTION


def test_une_page_ratee_parmi_d_autres_se_reprend():
    rid = store.create_record("AMN-30", "SF-014", [b"bonne", b"floue"])

    def extract(data, use_model=True):
        if data == b"floue":
            raise ValueError("Presque aucun texte sur cette image : ce n'est pas une fiche à lire.")
        return fake_extract(data)

    store.process_record(rid, extract=extract)
    rec = store.snapshot(str)["records"][rid]
    assert rec["state"] == "NEEDS_REVIEW" and rec["pages"][1]["error"].startswith("Presque")
    store.set_field(rid, 0, "age", "SF-014", value=32, status="KNOWN")
    with pytest.raises(store.TransitionError):
        store.validate(rid)                       # une page non lue bloque la validation

    store.replace_page(rid, 1, b"nette")
    store.process_record(rid, extract=extract)
    rec = store.snapshot(str)["records"][rid]
    assert "error" not in rec["pages"][1] and rec["pages"][1]["fields"]
    assert rec["pages"][0]["fields"]["age"]["value"] == 32   # la correction de la page 1 est gardée


def test_retirer_une_page_illisible():
    rid = store.create_record("AMN-31", "SF-014", [b"bonne", b"floue"])
    store.process_record(rid, extract=lambda d, use_model=True: fake_extract(d) if d == b"bonne"
                         else (_ for _ in ()).throw(ValueError("illisible")))
    store.drop_page(rid, 1)
    rec = store.snapshot(str)["records"][rid]
    assert len(rec["pages"]) == 1
    with pytest.raises(store.TransitionError):
        store.drop_page(rid, 0)                   # page lue (et seule) : on ne la retire pas


def test_correction_garde_la_valeur_de_l_ia():
    rid = captured()
    f = store.set_field(rid, 0, "age", "SF-014", value=32, status="KNOWN")
    assert (f["value"], f["aiValue"], f["origin"]) == (32, 31, "CORRECTED")


def test_validation_refusee_tant_qu_il_reste_des_doutes():
    rid = captured()
    with pytest.raises(store.TransitionError):
        store.validate(rid)
    resolve_all(rid)
    store.validate(rid)


def test_liaison_explicite_puis_code_proche_propose():
    first = captured("AMN-27")
    resolve_all(first)
    store.validate(first)
    pid = store.link(first, "CREATE")
    snap = store.snapshot(str)
    assert snap["records"][first]["state"] == "SYNCED" and snap["patients"][pid]["code"] == "AMN-27"

    second = captured("AMN-21")                  # 1 caractère différent : proposé, jamais lié tout seul
    cands = store.candidates(second)
    assert cands[0]["patientId"] == pid and cands[0]["reasons"][0]["kind"] == "SIMILAR_CODE"
    assert store.snapshot(str)["records"][second].get("patientId") is None


def test_pages_ajoutees_pendant_la_lecture():
    """Photo 2 envoyée avant la lecture de la photo 1 : le dossier n'est « lu » qu'une fois les deux lues."""
    rid = store.create_record("", "SF-014", [b"p1"])
    store.add_page(rid, b"p2")
    store.process_record(rid, extract=fake_extract)
    rec = store.snapshot(str)["records"][rid]
    assert rec["state"] == "NEEDS_REVIEW" and all(p["fields"] for p in rec["pages"])

    store.add_page(rid, b"p3")                    # dossier déjà lu : il repasse en lecture
    assert store.snapshot(str)["records"][rid]["state"] == "PENDING_AI"
    store.process_record(rid, extract=fake_extract)
    rec = store.snapshot(str)["records"][rid]
    assert rec["state"] == "NEEDS_REVIEW" and len(rec["pages"]) == 3
    assert "ADD page 2" in [h.get("note") for h in rec["history"]]


def test_lecture_partielle_attend_les_autres_pages():
    """Une lecture qui finit alors qu'une page attend encore ne déclare pas le dossier lu."""
    rid = store.create_record("", "SF-014", [b"p1"])

    def slow(data, use_model=True):
        if data == b"p1":
            store.add_page(rid, b"p2")            # la sage-femme envoie la page 2 pendant la lecture
        return fake_extract(data)

    store.process_record(rid, extract=slow)
    assert store.snapshot(str)["records"][rid]["state"] == "PENDING_AI"
    store.process_record(rid, extract=fake_extract)      # la lecture de la page 2 (tâche suivante)
    assert store.snapshot(str)["records"][rid]["state"] == "NEEDS_REVIEW"


def test_code_donne_apres_la_capture():
    rid = captured("")
    assert store.snapshot(str)["records"][rid]["patientCode"] == ""
    resolve_all(rid)
    store.validate(rid)
    with pytest.raises(store.TransitionError):
        store.link(rid, "CREATE")                 # pas de patiente sans code
    with pytest.raises(ValueError):
        store.set_code(rid, "   ")
    assert store.set_code(rid, " amn-27 ") == "AMN-27"
    pid = store.link(rid, "CREATE")
    with pytest.raises(store.TransitionError):
        store.set_code(rid, "AUTRE")              # patiente choisie : le code ne change plus
    assert store.snapshot(str)["patients"][pid]["code"] == "AMN-27"


def test_resultat_final_fige_a_la_validation_puis_complete():
    rid = captured()
    assert store.final_json(rid) is None
    store.set_field(rid, 0, "age", "SF-014", value=32, status="KNOWN")
    resolve_all(rid)
    store.validate(rid)
    final = store.final_json(rid)
    assert final["validated_at"] and final["patient_id"] is None
    age = next(f for f in final["pages"][0]["fields"] if f["key"] == "age")
    assert (age["value"], age["aiValue"], age["origin"], age["label"]) == (32, 31, "CORRECTED", "Age")
    pid = store.link(rid, "CREATE")
    final = store.final_json(rid)
    assert final["patient_id"] == pid and final["state"] == "SYNCED" and final["linked_at"]
    rec = store.snapshot(str)["records"][rid]
    assert rec["hasFinal"] and rec["validatedAt"]


def test_code_lu_sur_la_page_propose():
    pred = {**PRED, "fields": PRED["fields"] + [{"id": "n_de_fiche", "label": "N° de fiche", "kind": "text",
                                                  "value": "amn 27", "status": "KNOWN", "confidence": 0.9}]}
    rid = store.create_record("", "SF-014", [b"photo"])
    store.process_record(rid, extract=lambda d, use_model=True: dict(pred))
    assert store.snapshot(str)["records"][rid]["codeSuggestion"] == "AMN27"
    store.set_code(rid, "AMN-27")
    assert "codeSuggestion" not in store.snapshot(str)["records"][rid]
