from app.mapping.labels import PII, match_label
from app.mapping.mapper import map_page
from app.schemas.models import Localisation
from tests.helpers import page, tok


def test_libelles():
    assert match_label(tok("Poids :", 0, 0, 1, 1)).spec_key == "poids_kg"
    assert match_label(tok("Poids : 68 kg", 0, 0, 1, 1)).remainder == "68 kg"
    assert match_label(tok("TA", 0, 0, 1, 1)).spec_key == "tension_arterielle"
    assert match_label(tok("Tension", 0, 0, 1, 1)).spec_key == "tension_arterielle"
    assert match_label(tok("Temperatnre", 0, 0, 1, 1)).spec_key == "temperature"       # flou
    assert match_label(tok("Tél :", 0, 0, 1, 1)).spec_key == "telephone"
    assert match_label(tok("Date de naissance", 0, 0, 1, 1)).spec_key == "date_naissance"
    assert match_label(tok("الوزن", 0, 0, 1, 1)).spec_key == "poids_kg"
    assert match_label(tok("G3P2", 0, 0, 1, 1)) is None                                 # valeur, pas libellé
    assert match_label(tok("68 kg", 0, 0, 1, 1)) is None


def test_formulaire_droite_inline_dessous_et_pii():
    p = page([
        tok("Nom :", 50, 100, 140, 130), tok("Fatima", 300, 100, 420, 130),
        tok("Poids :", 50, 200, 160, 230), tok("68 kg", 300, 198, 400, 232, 0.97),
        tok("TA : 120/80", 50, 300, 260, 330),
        tok("BCF", 50, 400, 120, 430), tok("140", 55, 440, 110, 470),
        tok("Temperature :", 50, 500, 260, 530),          # rien à droite
        tok("Age :", 900, 200, 980, 230), tok("28", 1050, 200, 1090, 230),   # 2e colonne, même ligne
    ])
    m = map_page(p)
    c = m.records[0].candidates
    assert m.layout == "formulaire"
    assert c["poids_kg"].raw_text == "68 kg" and c["poids_kg"].localisation == Localisation.RIGHT
    assert c["tension_arterielle"].raw_text == "120/80" and c["tension_arterielle"].localisation == Localisation.INLINE
    assert c["bcf_bpm"].raw_text == "140" and c["bcf_bpm"].localisation == Localisation.BELOW
    assert c["temperature"].raw_text is None and c["temperature"].zone is not None
    assert c["age"].raw_text == "28"                 # le libellé "Age" borne la zone de "Poids"
    assert c["nom_parturiente"].raw_text == "Fatima"


def test_formulaire_arabe_valeur_a_gauche():
    p = page([tok("68", 900, 100, 960, 130), tok("الوزن", 1100, 100, 1200, 130)])
    c = map_page(p).records[0].candidates
    assert c["poids_kg"].raw_text == "68"


def test_motif_sans_libelle():
    p = page([tok("Poids :", 50, 100, 160, 130), tok("70", 300, 100, 340, 130), tok("G2P1", 1200, 600, 1300, 640)])
    c = map_page(p).records[0].candidates
    assert c["gesta_para"].localisation == Localisation.PATTERN


def test_tableau_registre():
    header = [tok("Nom", 50, 100, 150, 130), tok("Age", 300, 100, 360, 130), tok("Poids", 500, 100, 590, 130),
              tok("TA", 700, 100, 740, 130), tok("VIH", 900, 100, 960, 130)]
    row1 = [tok("Amina X", 50, 180, 200, 210), tok("25", 310, 180, 350, 210), tok("61", 510, 180, 550, 210),
            tok("110/70", 690, 180, 780, 210), tok("neg", 905, 180, 955, 210)]
    row2 = [tok("Sara Y", 50, 250, 180, 280), tok("31", 310, 250, 350, 280), tok("12/8", 690, 250, 760, 280)]
    m = map_page(page(header + row1 + row2))
    assert m.layout == "tableau" and len(m.records) == 2
    r1, r2 = m.records[0].candidates, m.records[1].candidates
    assert r1["age"].raw_text == "25" and r1["tension_arterielle"].raw_text == "110/70" and r1["vih"].raw_text == "neg"
    assert r2["poids_kg"].raw_text is None                     # cellule vide -> mesure d'encre en aval
    assert "temperature" in m.absent_specs                      # colonne absente du registre
    assert r1["nom_parturiente"].raw_text == "Amina X"


def test_ligne_formulaire_sans_deux_points_nest_pas_un_tableau():
    p = page([tok("Poids", 50, 100, 140, 130), tok("68", 160, 100, 200, 130),
              tok("TA", 300, 100, 340, 130), tok("120/80", 360, 100, 460, 130),
              tok("Temp", 600, 100, 680, 130), tok("37", 700, 100, 740, 130)])
    m = map_page(p)
    assert m.layout == "formulaire"
    assert m.records[0].candidates["tension_arterielle"].raw_text == "120/80"


def test_tableau_transpose_visites():
    # Simulation Page 3: Libellés verticaux à gauche (x < 350) et 2 colonnes de visites à droite
    left = [
        tok("Date consultation", 50, 100, 250, 130),
        tok("Age gestationnel", 50, 160, 250, 190),
        tok("Poids", 50, 220, 250, 250),
        tok("TA", 50, 280, 250, 310),
    ]
    # Colonne 1 (x ~ 500)
    col1 = [
        tok("15/05/2025", 480, 100, 580, 130),
        tok("14 SA", 480, 160, 560, 190),
        tok("59.5", 480, 220, 550, 250),
        tok("110/70", 480, 280, 560, 310),
    ]
    # Colonne 2 (x ~ 750)
    col2 = [
        tok("20/07/2025", 720, 100, 820, 130),
        tok("24 SA", 720, 160, 800, 190),
        tok("63.0", 720, 220, 790, 250),
        tok("115/75", 720, 280, 800, 310),
    ]
    p = page(left + col1 + col2, w=1000, h=1000)
    m = map_page(p)
    assert m.layout == "tableau_visites"
    assert len(m.records) == 2
    r1, r2 = m.records[0].candidates, m.records[1].candidates
    assert r1["date_consultation"].raw_text == "15/05/2025"
    assert r1["age_gestationnel"].raw_text == "14 SA"
    assert r1["poids_kg"].raw_text == "59.5"
    assert r2["poids_kg"].raw_text == "63.0"

