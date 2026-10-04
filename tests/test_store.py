"""Base locale : parcours complet d'un dossier, chiffrement au repos, liaison sans création silencieuse."""
import json

import pytest

from api import store

PRED = json.load(open(store.ROOT / "outputs/predictions/page_02_identification_antecedents.json"))


@pytest.fixture(autouse=True)
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(store, "CAPTURES", tmp_path / "captures")
    monkeypatch.setattr(store, "KEY_FILE", tmp_path / "key")
    monkeypatch.setattr(store, "_initialized", False)
    monkeypatch.setattr(store, "_fernet", None)


def fake_extract(data, page_type=None, use_model=True):
    return {**PRED, "mode": "modele_seul"}       # pas d'alignement : pas de vue masquée à produire


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
    assert b"Lyc" not in raw and "Étudiante".encode() not in raw    # valeurs lues jamais en clair
    photo = next((tmp_path / "captures").iterdir()).read_bytes()
    assert photo != b"photo" and store.fernet().decrypt(photo) == b"photo"
    assert rid


def test_lecture_impossible_donne_echec():
    rid = store.create_record("DRS-90", "SF-014", [b"x"])
    store.process_record(rid, extract=lambda *a, **k: (_ for _ in ()).throw(ValueError("mise en page")))
    rec = store.snapshot(str)["records"][rid]
    assert rec["state"] == "PROCESSING_FAILED" and rec["failure"]["reason"] == "LAYOUT"


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
