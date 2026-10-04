"""Tableau des visites, mesures suivies, contrôles de cohérence de la lecture, agrégats anonymes.
Tests rapides : ni PaddleOCR ni modèle."""

from datetime import date

import cv2
import numpy as np
import pytest

from api import aggregates, store
from dayone import coherence, imaging, suivi
from dayone.extract import _pipe_reading
from dayone.normalize import infer_kind, parse

TODAY = date(2026, 10, 4)


# ---------------- lecture du tableau ----------------

def test_tableau_coupe_par_des_bandeaux_garde_ses_colonnes():
    """Les bandeaux sombres (« EXAMEN CLINIQUE ») coupent les traits verticaux : on recolle les morceaux."""
    img = np.full((900, 800, 3), 255, np.uint8)
    xs, top, bottom = [50, 250, 400, 550, 750], 100, 850
    for y in range(top, bottom + 1, 50):
        cv2.line(img, (xs[0], y), (xs[-1], y), (0, 0, 0), 2)
    for x in xs:
        cv2.line(img, (x, top), (x, bottom), (0, 0, 0), 2)
    for y0 in (250, 500, 700):                              # bandeaux pleine largeur, traits internes coupés
        cv2.rectangle(img, (xs[0], y0), (xs[-1], y0 + 50), (60, 60, 60), -1)
    region = (xs[0] - 2, top - 2, xs[-1] - xs[0] + 4, bottom - top + 4)
    _, cols = imaging.table_grid(img, region)
    assert len(cols) == len(xs)


def test_poids_de_la_mere_en_kg_et_age_probable_en_semaines():
    assert parse("weight", "58.8", "Poids (kg) | 2ème trimestre - Visite 2") == (58800, True)
    assert parse("weight", "66 kg", "Poids") == (66000, True)
    assert parse("weight", "3626 g", "Poids à la naissance") == (3626, True)     # nouveau-né : inchangé
    assert parse("weight", "35000", "Poids à la naissance")[1] is False          # pas un poids de nouveau-né
    assert infer_kind("Age probable | 1er trimestre - Visite 2") == "weeks"
    assert infer_kind("Rendez-vous | 3ème trimestre - 8ème mois") == "date"


@pytest.mark.parametrize("label,read,expected", [
    ("TA | x", "|51/97", "151/97"),        # « | » = un 1 au stylo fin
    ("TA | x", "|137/92", "137/92"),       # « | » = bordure de case
    ("HU (cm) | x", "|27", "27"),
    ("BCF | x", "|29", "129"),
    ("Venue le | x", "0|/12/2025", "01/12/2025"),
])
def test_trait_lu_comme_barre(label, read, expected):
    assert _pipe_reading(label, read) == expected


# ---------------- mesures suivies ----------------

def cell(key, label, value, col=None, kind="text", status="KNOWN", origin="AI"):
    f = {"key": key, "label": label, "kind": kind, "value": value, "status": status, "origin": origin,
         "confidence": 0.95, "section": "Autres champs lus", "history": []}
    if col is not None:
        f["column"] = col
    return f


def antenatal(weights=(58800, 62700, 64300), rdv="2025-08-17"):
    cols = {2: ("2025-07-20", 12), 5: ("2025-09-28", 22), 6: ("2025-11-01", 27)}
    fields = [cell("ddr", "DDR", "2025-04-26", kind="date"),
              cell("dpa", "DATE PRÉVUE D'ACCOUCHEMENT", "2026-01-31", kind="date")]
    for (col, (day, ga)), w in zip(cols.items(), weights):
        fields += [cell(f"venue_{col}", f"Venue le | V{col}", day, col, "date"),
                   cell(f"age_{col}", f"Age probable | V{col}", ga, col, "weeks"),
                   cell(f"poids_{col}", f"Poids (kg) | V{col}", w, col, "weight"),
                   cell(f"ta_{col}", f"TA | V{col}", "12/7" if col == 6 else "104/74", col),
                   cell(f"vih_{col}", f"Sérologie VIH | V{col}", "Neg" if col == 2 else None, col,
                        status="KNOWN" if col == 2 else "NOT_PROVIDED")]
    fields.append(cell("rdv_2", "Rendez-vous | V2", rdv, 2, "date"))
    return {f["key"]: f for f in fields}


def test_page_des_visites_reconnue_et_mise_en_serie():
    fields = antenatal()
    assert suivi.page_type_from_labels(fields) == "grossesse_actuelle"
    s = suivi.series("grossesse_actuelle", fields)
    assert s["facts"]["lmp"]["value"] == "2025-04-26"
    assert [v["column"] for v in s["visits"]] == [2, 5, 6]
    first, _, last = s["visits"]
    assert (first["date"], first["gaWeeks"], first["appointment"]) == ("2025-07-20", 12, "2025-08-17")
    assert first["values"]["weight"]["value"] == 58.8
    assert first["values"]["hiv"]["code"] == "neg"
    assert last["values"]["bp"]["value"] == [120, 70]                       # « 12/7 » en cmHg


def test_valeur_sans_colonne_n_est_pas_placee():
    fields = {"p": cell("p", "Poids (kg)", 60000, kind="weight")}             # ancienne lecture, sans colonne
    assert suivi.series("grossesse_actuelle", fields) is None


def test_pages_post_partum_reconnues():
    mother = [cell("t", "T°", "37.2"), cell("p", "Pouls", "83"), cell("l", "Etat des lochies | Fade", True, kind="checkbox"),
              cell("j", "Entre le 7ème et 8ème jour après l'accouchement", True, kind="checkbox")]
    assert suivi.page_type_from_labels(mother) == "postpartum_precoce_mere"
    baby = [cell("a", "Age", "43 jours"), cell("pc", "Périmètre crânien", 37, kind="length"),
            cell("al", "Allaitement | mixte", True, kind="checkbox")]
    assert suivi.page_type_from_labels(baby) == "postpartum_tardif_nouveau_ne"


# ---------------- cohérence de la lecture ----------------

def alerts_of(fields, page_type="grossesse_actuelle"):
    return {key: a for (_, key), a in coherence.check_record([(0, page_type, fields)], TODAY).items()}


def test_page_coherente_sans_alerte():
    assert alerts_of(antenatal()) == {}


def test_rendez_vous_mal_lu_avant_la_visite():
    found = alerts_of(antenatal(rdv="2025-01-29"))                           # « 29/1/2025 » pour 29/11
    assert [a["code"] for a in found["rdv_2"]] == ["appointment_before_visit"]
    assert "à vérifier sur le papier" in found["rdv_2"][0]["text"]


def test_chiffre_isole_tres_loin_des_visites_voisines():
    found = alerts_of(antenatal(weights=(58800, 82700, 64300)))              # 6 lu 8
    assert found["poids_5"][0]["code"] == "spike"
    assert "poids_2" not in found and "poids_6" not in found


def test_dpa_qui_ne_colle_pas_a_la_ddr():
    fields = antenatal()
    fields["dpa"]["value"] = "2026-03-31"
    assert alerts_of(fields)["dpa"][0]["code"] == "edd_lmp"


def test_age_gestationnel_qui_ne_colle_pas_a_la_ddr():
    fields = antenatal()
    fields["age_5"]["value"] = 32                                           # 22 lu 32
    assert alerts_of(fields)["age_5"][0]["code"] == "ga_lmp"


def test_gestite_parite_et_cases_qui_s_excluent():
    ident = {k: cell(k, k, v, kind="integer") for k, v in (("gestation", 2), ("parite", 3), ("obst_avortement_nombre", 0))}
    assert alerts_of(ident, "identification_antecedents")["parite"][0]["code"] == "parity_gravidity"
    birth = {k: cell(k, k, True, kind="checkbox") for k in ("mode_voie_basse_non_instrumentale", "mode_cesarienne_urgence")}
    found = alerts_of(birth, "accouchement")
    assert set(found) == set(birth) and found["mode_cesarienne_urgence"][0]["code"] == "two_modes"


def test_alerte_rend_le_champ_a_verifier_sauf_s_il_est_deja_verifie():
    fields = antenatal(rdv="2025-01-29")
    assert coherence.apply(fields, alerts_of(fields))
    rdv = fields["rdv_2"]
    assert (rdv["status"], rdv["reason"]) == ("NEEDS_REVIEW", "incoherent") and rdv["alerts"]
    # La sage-femme a regardé le papier : jamais d'alerte sur un champ confirmé.
    fields["rdv_2"].update(origin="CONFIRMED", status="KNOWN")
    coherence.apply(fields, alerts_of(fields))
    assert "alerts" not in fields["rdv_2"] and fields["rdv_2"]["status"] == "KNOWN"


def test_alerte_levee_rend_son_statut_au_champ():
    fields = antenatal(weights=(58800, 82700, 64300))
    coherence.apply(fields, alerts_of(fields))
    assert fields["poids_5"]["status"] == "NEEDS_REVIEW"
    fields["poids_5"]["value"] = 62700                                      # relu
    coherence.apply(fields, alerts_of(fields))
    assert fields["poids_5"]["status"] == "KNOWN" and "alerts" not in fields["poids_5"] and "reason" not in fields["poids_5"]


# ---------------- dans la base ----------------

@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(store, "CAPTURES", tmp_path / "captures")
    monkeypatch.setattr(store, "KEY_FILE", tmp_path / "key")
    monkeypatch.setattr(store, "_initialized", False)
    monkeypatch.setattr(store, "_fernet", None)


def antenatal_pred(weights=(58.8, 82.7, 64.3)):
    """Sortie de dayone.extract pour une page « Grossesse actuelle » (cellules avec leur colonne)."""
    out = []
    for col, day, ga, w in ((2, "2025-07-20", 12, weights[0]), (5, "2025-09-28", 22, weights[1]), (6, "2025-11-01", 27, weights[2])):
        for label, kind, value in ((f"Venue le | V{col}", "date", day), (f"Age probable | V{col}", "weeks", ga),
                                   (f"Poids (kg) | V{col}", "weight", int(w * 1000)), (f"HU (cm) | V{col}", "length", ga - 4)):
            out.append({"id": f"{label.split()[0].lower()}_{col}", "label": label, "kind": kind, "value": value,
                        "status": "KNOWN", "confidence": 0.95, "source": "ocr", "colonne": col})
    return {"title": "GROSSESSE ACTUELLE", "fields": out}


def test_dossier_lu_puis_controle_et_corrige(tmp_store):
    rid = store.create_record("AMN-40", "SF-014", [b"photo"])
    store.process_record(rid, extract=lambda data, use_model=True: antenatal_pred())
    page = store.snapshot(str)["records"][rid]["pages"][0]
    assert page["pageType"] == "grossesse_actuelle"
    weight = page["fields"]["poids_5"]
    assert weight["column"] == 5 and weight["status"] == "NEEDS_REVIEW" and weight["alerts"][0]["code"] == "spike"
    assert [v["values"]["weight"]["value"] for v in page["series"]["visits"]] == [58.8, 82.7, 64.3]

    f = store.set_field(rid, 0, "poids_5", "SF-014", value=62700, status="KNOWN")
    assert f["origin"] == "CORRECTED" and "alerts" not in f
    page = store.snapshot(str)["records"][rid]["pages"][0]
    assert not any(x.get("alerts") for x in page["fields"].values())
    store.validate(rid)                                                     # plus rien à vérifier


# ---------------- agrégats anonymes ----------------

def test_agregats_du_jeu_synthetique():
    a = aggregates.build("synthetic")
    assert a["women"] == 200 and not a.get("suppressed")
    tests = {t["test"]: t for t in a["panels"]["tests"]}
    assert set(tests) == {"hiv", "syphilis", "hcv"}                        # pas d'Ag HBs dans ce jeu
    assert all(c is None or c == 0 or c >= aggregates.K for t in tests.values() for k, c in t.items() if k != "test")
    bins = a["panels"]["bp"]["systolic"]["bins"]
    assert sum(b["count"] or 0 for b in bins) <= a["women"]


def test_registre_trop_petit_rien_n_est_montre(tmp_store):
    a = aggregates.build("registry")
    assert a["suppressed"] and a["panels"] == {}
