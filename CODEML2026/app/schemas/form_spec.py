"""Schéma prédéfini du formulaire : quels champs, quels libellés, quel format attendu.

C'est LE fichier à adapter quand on voit les vrais registres du hackathon.
Les bornes `hard_*` détectent une ERREUR D'EXTRACTION probable (ex: poids 680 kg),
jamais un diagnostic. Les bornes `soft_*` marquent une valeur rare -> confiance réduite.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FieldKind(str, Enum):
    INT = "int"
    FLOAT = "float"
    ENUM = "enum"
    BLOOD_PRESSURE = "blood_pressure"      # composite -> systolique + diastolique
    BLOOD_GROUP = "blood_group"            # composite -> groupe + rhésus
    GESTA_PARA = "gesta_para"              # composite "G3P2" -> gestite + parite
    GESTATIONAL_AGE = "gestational_age"
    DATE = "date"
    TEXT = "text"                          # texte court (région, "RAS"...) : peut être CONNU
    CODE = "code"                          # N° de fiche = code patiente pseudonyme
    FREE_TEXT = "free_text"                # texte libre : toujours relu


@dataclass(frozen=True)
class FieldSpec:
    key: str
    kind: FieldKind
    labels: tuple[str, ...]                 # libellés FR / AR / EN + abréviations
    unit: str | None = None
    hard_min: float | None = None
    hard_max: float | None = None
    soft_min: float | None = None
    soft_max: float | None = None
    enum_map: dict[str, str] = field(default_factory=dict)   # variante normalisée -> valeur canonique
    outputs: tuple[str, ...] = ()           # pour les composites : champs produits
    send_to_vlm: bool = True
    display: str = ""                       # libellé lisible pour la sage-femme


SEROLOGY_MAP = {
    "neg": "NEGATIF", "negatif": "NEGATIF", "negative": "NEGATIF", "negat": "NEGATIF",
    "-": "NEGATIF", "(-)": "NEGATIF", "n": "NEGATIF", "سلبي": "NEGATIF", "سلبية": "NEGATIF",
    "pos": "POSITIF", "positif": "POSITIF", "positive": "POSITIF",
    "+": "POSITIF", "(+)": "POSITIF", "p": "POSITIF", "ايجابي": "POSITIF", "إيجابي": "POSITIF",
    "ايجابية": "POSITIF", "إيجابية": "POSITIF",
}

DELIVERY_MAP = {
    "vb": "VOIE_BASSE", "avb": "VOIE_BASSE", "voie basse": "VOIE_BASSE", "normal": "VOIE_BASSE",
    "accouchement normal": "VOIE_BASSE", "vaginal": "VOIE_BASSE", "eutocique": "VOIE_BASSE",
    "ولادة طبيعية": "VOIE_BASSE", "طبيعية": "VOIE_BASSE", "طبيعي": "VOIE_BASSE",
    "cesarienne": "CESARIENNE", "ces": "CESARIENNE", "cs": "CESARIENNE", "c/s": "CESARIENNE",
    "caesarean": "CESARIENNE", "cesarean": "CESARIENNE", "c-section": "CESARIENNE",
    "قيصرية": "CESARIENNE", "عملية قيصرية": "CESARIENNE",
    "forceps": "INSTRUMENTALE", "ventouse": "INSTRUMENTALE", "instrumental": "INSTRUMENTALE",
    "instrumentale": "INSTRUMENTALE",
}

YES_NO_MAP = {"oui": "OUI", "o": "OUI", "yes": "OUI", "non": "NON", "no": "NON", "نعم": "OUI", "لا": "NON"}
TEST_MAP = {**SEROLOGY_MAP, "immune": "IMMUNE", "immunisee": "IMMUNE", "non immune": "NON_IMMUNE",
            "non immunisee": "NON_IMMUNE"}
SEX_MAP = {"f": "F", "feminin": "F", "fille": "F", "female": "F", "انثى": "F",
           "m": "M", "masculin": "M", "garcon": "M", "male": "M", "ذكر": "M"}

FORM_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("date_consultation", FieldKind.DATE,
              ("date", "date consultation", "date de consultation", "التاريخ", "تاريخ"),
              send_to_vlm=True),
    FieldSpec("age", FieldKind.INT, ("age", "âge", "age (ans)", "العمر", "السن"),
              unit="ans", hard_min=10, hard_max=60, soft_min=14, soft_max=50),
    FieldSpec("poids_kg", FieldKind.FLOAT, ("poids", "pds", "weight", "الوزن"),
              unit="kg", hard_min=25, hard_max=200, soft_min=38, soft_max=140),
    FieldSpec("tension_arterielle", FieldKind.BLOOD_PRESSURE,
              ("ta", "t.a", "t a", "tension", "tension arterielle", "pa", "bp",
               "blood pressure", "ضغط الدم", "الضغط"),
              unit="mmHg", outputs=("tension_systolique", "tension_diastolique")),
    FieldSpec("temperature", FieldKind.FLOAT, ("temperature", "temp", "t°", "t", "الحرارة", "درجة الحرارة"),
              unit="°C", hard_min=33, hard_max=43, soft_min=35, soft_max=41),
    FieldSpec("age_gestationnel", FieldKind.GESTATIONAL_AGE,
              ("age gestationnel", "ag", "terme", "sa", "gestational age", "عمر الحمل", "مدة الحمل"),
              unit="SA", hard_min=3, hard_max=45, soft_min=5, soft_max=43),
    FieldSpec("hauteur_uterine_cm", FieldKind.FLOAT,
              ("hauteur uterine", "hu", "h.u", "fundal height", "ارتفاع الرحم"),
              unit="cm", hard_min=5, hard_max=50, soft_min=10, soft_max=42),
    FieldSpec("bcf_bpm", FieldKind.INT,
              ("bcf", "b.c.f", "bruits du coeur", "fhr", "fetal heart rate", "نبض الجنين", "دقات قلب الجنين"),
              unit="bpm", hard_min=50, hard_max=230, soft_min=100, soft_max=180),
    FieldSpec("vih", FieldKind.ENUM, ("vih", "hiv", "sida", "فيروس نقص المناعة"), enum_map=SEROLOGY_MAP),
    FieldSpec("syphilis", FieldKind.ENUM, ("syphilis", "tpha", "vdrl", "rpr", "الزهري"), enum_map=SEROLOGY_MAP),
    FieldSpec("hepatite_c", FieldKind.ENUM, ("hepatite c", "vhc", "hcv", "hep c", "التهاب الكبد c"),
              enum_map=SEROLOGY_MAP),
    FieldSpec("gesta_para", FieldKind.GESTA_PARA, ("gp", "g/p", "gestite parite"),
              outputs=("gestite", "parite"), send_to_vlm=True),
    FieldSpec("gestite", FieldKind.INT, ("gestite", "geste", "g", "gravidity", "عدد الحمل"),
              hard_min=1, hard_max=25, soft_max=15),
    FieldSpec("parite", FieldKind.INT, ("parite", "pare", "p", "parity", "عدد الولادات"),
              hard_min=0, hard_max=25, soft_max=14),
    FieldSpec("groupe_rhesus", FieldKind.BLOOD_GROUP,
              ("groupe sanguin", "groupe", "gs", "gs rh", "gs/rh", "groupage", "blood group",
               "فصيلة الدم", "الزمرة الدموية"),
              outputs=("groupe_sanguin", "rhesus")),
    FieldSpec("mode_accouchement", FieldKind.ENUM,
              ("mode accouchement", "mode d'accouchement", "accouchement", "voie", "delivery",
               "طريقة الولادة", "نوع الولادة"),
              enum_map=DELIVERY_MAP),
    FieldSpec("complications", FieldKind.FREE_TEXT,
              ("complications", "complication", "observations", "obs", "remarques", "مضاعفات", "ملاحظات"),
              send_to_vlm=False),   # toujours relu par la sage-femme : inutile de dépenser un appel VLM
)

FIELDS_BY_KEY: dict[str, FieldSpec] = {f.key: f for f in FORM_FIELDS}

# Champs finaux exposés dans le JSON (composites éclatés). L'ordre sert à l'affichage.
OUTPUT_FIELDS: tuple[str, ...] = (
    "date_consultation", "age", "poids_kg", "tension_systolique", "tension_diastolique",
    "temperature", "age_gestationnel", "hauteur_uterine_cm", "bcf_bpm",
    "vih", "syphilis", "hepatite_c", "gestite", "parite", "groupe_sanguin", "rhesus",
    "mode_accouchement", "complications",
)

# Pour un champ de sortie, quel(s) spec(s) peut le produire (le composite passe en premier).
PRODUCERS: dict[str, tuple[str, ...]] = {
    "tension_systolique": ("tension_arterielle",),
    "tension_diastolique": ("tension_arterielle",),
    "gestite": ("gesta_para", "gestite"),
    "parite": ("gesta_para", "parite"),
    "groupe_sanguin": ("groupe_rhesus",),
    "rhesus": ("groupe_rhesus",),
}

# Libellés des zones nominatives : on les reconnaît pour NE PAS les extraire et masquer la zone.
PII_LABELS: tuple[str, ...] = (
    "nom", "prenom", "nom et prenom", "nom prenom", "name", "first name", "surname",
    "adresse", "address", "domicile", "quartier", "douar",
    "telephone", "tel", "tél", "gsm", "phone", "mobile",
    "cin", "c.i.n", "cni", "carte nationale", "n° cin", "id", "passport", "passeport",
    "conjoint", "epoux", "mari", "nom du mari", "husband", "spouse",
    "date de naissance", "ddn", "ne le", "nee le", "date of birth", "dob",   # quasi-identifiant
    "nom/prenom de la parturiente", "nom/prenom", "patiente", "mere", "profession",
    "vu par", "examen fait par", "sage-femme",
    "تاريخ الازدياد", "تاريخ الميلاد",
    "الاسم", "الإسم", "النسب", "الاسم العائلي", "الاسم الشخصي", "العنوان", "الهاتف", "رقم الهاتف",
    "رقم البطاقة", "البطاقة الوطنية", "الزوج", "اسم الزوج",
)

DISPLAY_NAMES: dict[str, str] = {
    "date_consultation": "Date", "age": "Âge", "poids_kg": "Poids",
    "tension_systolique": "TA systolique", "tension_diastolique": "TA diastolique",
    "temperature": "Température", "age_gestationnel": "Âge gestationnel",
    "hauteur_uterine_cm": "Hauteur utérine", "bcf_bpm": "BCF", "vih": "VIH",
    "syphilis": "Syphilis", "hepatite_c": "Hépatite C", "gestite": "Gestité", "parite": "Parité",
    "groupe_sanguin": "Groupe sanguin", "rhesus": "Rhésus",
    "mode_accouchement": "Mode d'accouchement", "complications": "Complications",
}

OUTPUT_UNITS: dict[str, str] = {
    "age": "ans", "poids_kg": "kg", "tension_systolique": "mmHg", "tension_diastolique": "mmHg",
    "temperature": "°C", "age_gestationnel": "SA", "hauteur_uterine_cm": "cm", "bcf_bpm": "bpm",
}
