import csv

from dayone.evaluate import compare, load_annotation, match_fields, summarize, write_template
from dayone.normalize import comparable, infer_kind, parse, restore_missing_letters, special_word
from dayone.schema import make_field


def test_parse():
    assert parse("date", "12/11/2022") == ("2022-11-12", True)
    assert parse("date", "31/02/2022") == (None, False)
    assert parse("weight", "3626 g") == (3626, True)
    assert parse("weight", "3626 9") == (3626, True)       # « g » lu « 9 »
    assert parse("weight", "3,2 kg") == (3200, True)
    assert parse("weight", "36779") == (36779, False)      # hors format -> à revoir
    assert parse("weeks", "40 SA") == (40, True)
    assert parse("integer", "21 ans") == (21, True)
    assert parse("sex", "F") == ("F", True)
    assert parse("text", "R.A.S") == ("aucun", True)
    assert special_word("?") == "unknown"


def test_infer_kind():
    assert infer_kind("Date | Accouch. 1") == "date"
    assert infer_kind("Poids à la naissance") == "weight"
    assert infer_kind("Age gestationnel (SA)") == "weeks"
    assert infer_kind("Age") == "integer"
    assert infer_kind("Profession") == "text"


def test_comparable():
    assert comparable("text", "Cycles réguliers") == comparable("text", "cycles reguliers")
    assert comparable("date", "12/11/2022") == comparable("date", "2022-11-12")
    assert comparable("text", "RAS") == comparable("text", "aucun")


def test_restore_missing_letters():
    assert restore_missing_letters("Commer ante") == "Commerçante"
    assert restore_missing_letters("Maternit") == "Maternité"
    assert restore_missing_letters("Maternité") is None          # déjà juste
    assert restore_missing_letters("Commerxante") is None        # une autre lettre : jamais corrigée


def _f(label, value, status="KNOWN", kind="text"):
    return {"id": label, "label": label, "kind": kind, **make_field(value, status, 0.9)}


def test_label_matching():
    pred = [_f("Profession", "Étudiante"), _f("Profession", "Ouvrier"), _f("HTA | Famille de la femme", "aucun"),
            _f("Date | Accouch. 1", "2022-11-12", kind="date")]
    m = match_fields("identification_antecedents", pred)
    assert m["profession_femme"]["value"] == "Étudiante"
    assert m["profession_mari"]["value"] == "Ouvrier"
    assert m["hered_hta_femme"]["value"] == "aucun"
    assert m["acc1_date"]["value"] == "2022-11-12"


def test_annotation_roundtrip(tmp_path):
    page_type = "accouchement"
    path = tmp_path / "page_04_accouchement.csv"
    write_template(path, page_type)
    assert load_annotation(path, page_type) is None        # modèle vide = pas encore rempli

    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    for r in rows:
        if r["field_id"] == "nn_vivant":
            r["value"] = "x"
        if r["field_id"] == "nn_poids":
            r["value"] = "3587 g"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    ref = load_annotation(path, page_type)
    assert ref["nn_vivant"] == {"value": True, "status": "KNOWN"}

    pred = {"fields": [_f("Vivant", True, kind="checkbox"), _f("Poids à la naissance", 3581, kind="weight")]}
    out = {r["field_id"]: r["outcome"] for r in compare(pred, ref, page_type)}
    assert out["nn_vivant"] == "correct"
    assert out["nn_poids"] == "erreur_silencieuse"
    assert out["nn_sexe"] == "correct"                      # absent des deux côtés
    assert summarize(compare(pred, ref, page_type))["erreurs_silencieuses"] == 1


def test_restore_inside_sentence():
    assert restore_missing_letters("Asthme l ger") == "Asthme léger"
    assert restore_missing_letters("Ut rus cicatriciel") == "Utérus cicatriciel"
