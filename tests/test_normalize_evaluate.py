import csv

from dayone.evaluate import compare, load_annotation, summarize, write_template
from dayone.normalize import comparable, parse, special_word
from dayone.schema import load_schema, make_field


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


def test_comparable():
    assert comparable("text", "Cycles réguliers") == comparable("text", "cycles reguliers")
    assert comparable("date", "12/11/2022") == comparable("date", "2022-11-12")
    assert comparable("text", "RAS") == comparable("text", "aucun")


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
        if r["field_id"] == "cesarienne_indication":
            r["status"] = "NOT_APPLICABLE"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    ref = load_annotation(path, page_type)
    assert ref["nn_vivant"] == {"value": True, "status": "KNOWN"}
    assert ref["nn_age_gestationnel"]["status"] == "NOT_PROVIDED"

    s = load_schema(page_type)
    pred = {"page_type": page_type, "fields": {f.id: make_field(None, "NOT_PROVIDED", 0.9) for f in s.fields}}
    pred["fields"]["nn_vivant"] = make_field(True, "KNOWN", 1.0)
    pred["fields"]["nn_poids"] = make_field(3581, "KNOWN", 0.9)          # erreur silencieuse
    pred["fields"]["cesarienne_indication"] = make_field(None, "NOT_APPLICABLE", 0.9)
    rows = {r["field_id"]: r["outcome"] for r in compare(pred, ref)}
    assert rows["nn_vivant"] == "correct"
    assert rows["nn_poids"] == "erreur_silencieuse"
    assert summarize(compare(pred, ref))["erreurs_silencieuses"] == 1


def test_restore_missing_letters():
    from dayone.normalize import restore_missing_letters as r

    assert r("Commer ante") == "Commerçante"
    assert r("Maternit") == "Maternité"
    assert r("Cycles r guliers") == "Cycles réguliers"
    assert r("Maternité") is None          # déjà juste
    assert r("Commerxante") is None        # une autre lettre : jamais corrigée
    assert r("Voie basse") is None
