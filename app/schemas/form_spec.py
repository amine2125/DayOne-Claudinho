"""Schéma prédéfini du formulaire : spécifications des champs, libellés et extraction intégrale.

Mode Local Intégral : Tous les champs (Identifiants, Clinique, Antécédents, Administratif)
sont extraits comme des données de premier ordre sans aucun masquage.
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
    TEXT = "text"                          # texte court (Nom, CIN, Adresse, Ville...)
    CODE = "code"                          # N° de fiche, Code
    FREE_TEXT = "free_text"                # texte libre / observations


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
    enum_map: dict[str, str] = field(default_factory=dict)
    outputs: tuple[str, ...] = ()
    send_to_vlm: bool = True
    display: str = ""


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
    "voie basse non instrumentale": "VOIE_BASSE", "voie basse instrumentale": "INSTRUMENTALE",
    "ولادة طبيعية": "VOIE_BASSE", "طبيعية": "VOIE_BASSE", "طبيعي": "VOIE_BASSE",
    "cesarienne": "CESARIENNE", "ces": "CESARIENNE", "cs": "CESARIENNE", "c/s": "CESARIENNE",
    "caesarean": "CESARIENNE", "cesarean": "CESARIENNE", "c-section": "CESARIENNE",
    "cesarienne programmee": "CESARIENNE", "urgence": "CESARIENNE",
    "قيصرية": "CESARIENNE", "عملية قيصرية": "CESARIENNE",
    "forceps": "INSTRUMENTALE", "ventouse": "INSTRUMENTALE", "instrumental": "INSTRUMENTALE",
    "instrumentale": "INSTRUMENTALE",
}

YES_NO_MAP = {
    "oui": "OUI", "o": "OUI", "yes": "OUI", "1": "OUI", "x": "OUI", "区": "OUI", "v": "OUI", "vrai": "OUI", "نعم": "OUI",
    "non": "NON", "no": "NON", "0": "NON", "لا": "NON",
    "ras": "NON", "aucun": "NON", "aucune": "NON", "neant": "NON", "néant": "NON", "pas": "NON", "neg": "NON",
}

EDUCATION_MAP = {
    "0": 0, "sans": 0, "aucun": 0, "aucune": 0, "primaire": 0, "none": 0, "primary": 0, "بدون": 0, "ابتدائي": 0,
    "1": 1, "secondaire": 1, "college": 1, "collège": 1, "lycee": 1, "lycée": 1, "ycee": 1, "(ycee": 1, "secondary": 1, "إعدادي": 1, "تأهيلي": 1, "ثانوي": 1,
    "2": 2, "superieur": 2, "supérieur": 2, "universite": 2, "université": 2, "universitaire": 2, "etudiante": 2, "étudiante": 2, "higher": 2, "جامعي": 2, "عالي": 2,
}

TEST_MAP = {**SEROLOGY_MAP, "immune": "IMMUNE", "immunisee": "IMMUNE", "non immune": "NON_IMMUNE",
            "non immunisee": "NON_IMMUNE"}
SEX_MAP = {"f": "F", "feminin": "F", "fille": "F", "female": "F", "انثى": "F",
           "m": "M", "masculin": "M", "garcon": "M", "male": "M", "ذكر": "M"}

FORM_FIELDS: tuple[FieldSpec, ...] = (
    # --- 1. IDENTITÉ & COORDONNÉES PATIENTE & ADMINISTRATIF (NON MASQUÉS) ---
    FieldSpec("nom_parturiente", FieldKind.TEXT,
              ("nom/prenom de la parturiente", "nom/prenom", "nom et prenom", "nom prenom",
               "nom de la parturiente", "mere -", "mere", "patiente :", "nom :", "prenom :",
               "الاسم", "الإسم", "النسب", "الاسم العائلي", "الاسم الشخصي"),
              display="Nom/Prénom de la parturiente"),
    FieldSpec("cin", FieldKind.TEXT,
              ("cin :", "cin", "c.i.n", "cni", "carte nationale", "n° cin", "id", "رقم البطاقة", "البطاقة الوطنية"),
              display="CIN"),
    FieldSpec("code_patiente", FieldKind.CODE,
              ("n° de la fiche", "n° fiche", "code patiente", "fiche n°", "dossier n°", "fiche :",
               "n de la fiche", "رقم البطاقة", "رقم الاستمارة"),
              display="N° de fiche"),
    FieldSpec("telephone", FieldKind.TEXT,
              ("telephone :", "telephone", "tel", "tél", "gsm", "phone", "mobile", "الهاتف", "رقم الهاتف"),
              display="Téléphone"),
    FieldSpec("adresse", FieldKind.TEXT,
              ("adresse :", "adresse", "address", "domicile", "quartier", "douar", "العنوان"),
              display="Adresse"),
    FieldSpec("nom_conjoint", FieldKind.TEXT,
              ("nom du mari :", "nom du mari", "nom de l'epoux", "conjoint", "epoux", "époux", "mari",
               "husband", "spouse", "الزوج", "اسم الزوج"),
              display="Nom du mari / conjoint"),
    FieldSpec("profession_patiente", FieldKind.TEXT,
              ("profession :", "profession", "metier", "travail", "المهنة"),
              display="Profession de la patiente"),
    FieldSpec("profession_conjoint", FieldKind.TEXT,
              ("profession du mari", "profession mari", "profession conjoint", "مهنة الزوج"),
              display="Profession du conjoint"),
    FieldSpec("region", FieldKind.TEXT,
              ("region :", "region", "région", "الجهة"),
              display="Région"),
    FieldSpec("province", FieldKind.TEXT,
              ("province :", "province", "prefecture", "préfecture", "الإقليم", "العمالة"),
              display="Province"),
    FieldSpec("etablissement_sanitaire", FieldKind.TEXT,
              ("nom de l'etablissement sanitaire :", "nom de I'etablissement sanitaire :",
               "nom de l'etablissement sanitaire", "nom de I'etablissement sanitaire",
               "etablissement sanitaire", "centre de sante", "csca", "csu", "formation sanitaire"),
              display="Établissement sanitaire"),
    FieldSpec("type_etablissement_sanitaire", FieldKind.TEXT,
              ("type de I'etablissement sanitaire :", "type de l'etablissement sanitaire :",
               "type de l'etablissement sanitaire", "type etablissement"),
              display="Type d'établissement"),
    FieldSpec("grossesse_a_risque", FieldKind.ENUM,
              ("grossesse classee a risque :", "grossesse classee a risque", "grossesse a risque", "grossesse risque"),
              enum_map=YES_NO_MAP, display="Grossesse à risque"),
    FieldSpec("type_risque", FieldKind.TEXT,
              ("si grossesse a risque, preciserletype de risque :", "si grossesse a risque, preciser le type de risque :",
               "si grossesse a risque", "type de risque"),
              display="Type de risque"),
    FieldSpec("date_naissance", FieldKind.DATE,
              ("date de naissance", "ddn", "ne le", "nee le", "date of birth", "dob",
               "تاريخ الازدياد", "تاريخ الميلاد"),
              display="Date de naissance"),

    # --- 2. DONNÉES CLINIQUES DE SUIVI PRÉNATAL ---
    FieldSpec("date_consultation", FieldKind.DATE,
              ("venue le", "date consultation", "date de consultation", "date de la consultation :",
               "date de la consultation", "date de la visite", "visite le", "التاريخ", "تاريخ"),
              send_to_vlm=True, display="Date de consultation"),
    FieldSpec("age", FieldKind.INT, ("age :", "age", "âge", "age (ans)", "العمر", "السن"),
              unit="ans", hard_min=10, hard_max=60, soft_min=14, soft_max=50, display="Âge"),
    FieldSpec("poids_kg", FieldKind.FLOAT, ("poids :", "poids", "pds", "weight", "الوزن"),
              unit="kg", hard_min=25, hard_max=200, soft_min=38, soft_max=140, display="Poids"),
    FieldSpec("tension_arterielle", FieldKind.BLOOD_PRESSURE,
              ("ta", "t.a", "t a", "tension", "tension arterielle", "pa", "bp",
               "blood pressure", "ضغط الدم", "الضغط"),
              unit="mmHg", outputs=("tension_systolique", "tension_diastolique"), display="Tension artérielle"),
    FieldSpec("temperature", FieldKind.FLOAT,
              ("temperature", "temp", "to", "t°", "t", "الحرارة", "درجة الحرارة"),
              unit="°C", hard_min=33, hard_max=43, soft_min=35, soft_max=41, display="Température"),
    FieldSpec("pouls_bpm", FieldKind.INT,
              ("pouls", "pulse", "pulsation", "النبض"),
              unit="bpm", hard_min=40, hard_max=180, display="Pouls"),
    FieldSpec("age_gestationnel", FieldKind.GESTATIONAL_AGE,
              ("age gestationnel", "age gest", "age probable", "terme", "sa", "gestational age", "عمر الحمل", "مدة الحمل"),
              unit="SA", hard_min=3, hard_max=45, soft_min=5, soft_max=43, display="Âge gestationnel"),
    FieldSpec("hauteur_uterine_cm", FieldKind.FLOAT,
              ("hauteur uterine", "hu", "h.u", "fundal height", "ارتفاع الرحم"),
              unit="cm", hard_min=5, hard_max=50, soft_min=10, soft_max=42, display="Hauteur utérine"),
    FieldSpec("bcf_bpm", FieldKind.INT,
              ("bcf", "b.c.f", "bruits du coeur", "fhr", "fetal heart rate", "نبض الجنين", "دقات قلب الجنين"),
              unit="bpm", hard_min=50, hard_max=230, soft_min=100, soft_max=180, display="BCF"),

    # --- 3. DÉPISTAGES & ANALYSES SÉROLOGIQUES ---
    FieldSpec("vih", FieldKind.ENUM, ("vih", "hiv", "sida", "فيروس نقص المناعة"),
              enum_map=SEROLOGY_MAP, display="VIH"),
    FieldSpec("syphilis", FieldKind.ENUM, ("syphilis", "tpha", "vdrl", "rpr", "الزهري"),
              enum_map=SEROLOGY_MAP, display="Syphilis"),
    FieldSpec("hepatite_c", FieldKind.ENUM,
              ("hepatite c", "vhc", "hcv", "hep c", "ag hbs", "aghbs", "hbs", "ag-hbs", "التهاب الكبد c"),
              enum_map=SEROLOGY_MAP, display="Hépatite C / B"),
    FieldSpec("proteinurie", FieldKind.ENUM,
              ("proteinurie", "protéinurie", "albuminurie", "alb", "albumine", "زلال"),
              enum_map=SEROLOGY_MAP, display="Protéinurie / Albuminurie"),
    FieldSpec("glycemie", FieldKind.FLOAT,
              ("glycemie", "glycémie", "glycemie a jeun", "fasting glucose", "ga", "التحليلة السكر"),
              hard_min=30, hard_max=400, display="Glycémie"),
    FieldSpec("hemoglobine", FieldKind.FLOAT,
              ("hemoglobine", "hémoglobine", "hb", "خضاب الدم"),
              hard_min=3.0, hard_max=20.0, display="Hémoglobine"),

    # --- 4. HISTOIRE OBSTÉTRICALE & ANTÉCÉDENTS ---
    FieldSpec("gesta_para", FieldKind.GESTA_PARA, ("gp", "g/p", "gestite parite"),
              outputs=("gestite", "parite"), send_to_vlm=True, display="Gesta/Para"),
    FieldSpec("gestite", FieldKind.INT, ("gestation :", "gestation", "gestite", "geste", "g", "gravidity", "عدد الحمل"),
              hard_min=1, hard_max=25, soft_max=15, display="Gestité"),
    FieldSpec("parite", FieldKind.INT, ("parite :", "parite", "parité", "pare", "p", "parity", "عدد الولادات"),
              hard_min=0, hard_max=25, soft_max=14, display="Parité"),
    FieldSpec("enfants_vivants", FieldKind.INT,
              ("nombre d'enfants vivants :", "enfants vivants", "enfants en vie", "ev", "living children", "أطفال أحياء"),
              hard_min=0, hard_max=25, display="Enfants vivants"),
    FieldSpec("avortements", FieldKind.INT,
              ("avortement", "avortements", "fausse couche", "abortions", "إجهاض"),
              hard_min=0, hard_max=20, display="Avortements"),
    FieldSpec("groupe_rhesus", FieldKind.BLOOD_GROUP,
              ("groupe sanguin", "groupe", "gs", "gs rh", "gs/rh", "groupage", "blood group",
               "فصيلة الدم", "الزمرة الدموية"),
              outputs=("groupe_sanguin", "rhesus"), display="Groupe / Rhésus"),
    FieldSpec("education_level", FieldKind.ENUM,
              ("niveau d'instruction :", "niveau d'instruction", "instruction", "scolarite", "education"),
              enum_map=EDUCATION_MAP, display="Niveau d'instruction"),
    FieldSpec("consanguinite", FieldKind.ENUM,
              ("consanguinite", "consanguinité", "consanguin", "قرابة"),
              enum_map=YES_NO_MAP, display="Consanguinité"),
    FieldSpec("grossesse_desiree", FieldKind.ENUM,
              ("grossesse deesiree", "grossesse desiree", "grossesse désirée", "grossesse souhaitee", "حمل مرغوب فيه"),
              enum_map=YES_NO_MAP, display="Grossesse désirée"),
    FieldSpec("hta_chronique", FieldKind.ENUM,
              ("hta", "h.t.a", "hypertension", "arterial hypertension"),
              enum_map=YES_NO_MAP, display="HTA chronique"),
    FieldSpec("diabete", FieldKind.ENUM,
              ("diabete", "diabète", "diabetes", "السكري"),
              enum_map=YES_NO_MAP, display="Diabète"),
    FieldSpec("cesarienne_anterieure", FieldKind.ENUM,
              ("cesarienne anterieure", "atcd cesarienne", "uterus cicatriciel"),
              enum_map=YES_NO_MAP, display="Césarienne antérieure"),
    FieldSpec("imc", FieldKind.FLOAT,
              ("imc", "bmi", "indice de masse corporelle"),
              hard_min=10, hard_max=70, display="IMC"),
    FieldSpec("ddr", FieldKind.DATE,
              ("ddr", "date des dernieres regles", "date des dernières règles", "dernieres regles"),
              display="DDR"),
    FieldSpec("dpa", FieldKind.DATE,
              ("dpa", "date prevue d'accouchement", "date prévue d'accouchement"),
              display="DPA"),

    # --- 5. ACCOUCHEMENT & NOUVEAU-NÉ ---
    FieldSpec("date_accouchement", FieldKind.DATE,
              ("date de I'accouchement :", "date de l'accouchement :", "date de l'accouchement", "date accouchement"),
              display="Date d'accouchement"),
    FieldSpec("lieu_accouchement", FieldKind.TEXT,
              ("maison d'accouchement", "maternite", "clinique privee", "a domicile", "lieu accouchement"),
              display="Lieu d'accouchement"),
    FieldSpec("mode_accouchement", FieldKind.ENUM,
              ("mode de I'accouchement :", "mode de l'accouchement :", "mode accouchement", "mode d'accouchement",
               "modalite d'extraction", "modalité d'extraction", "voie", "delivery", "طريقة الولادة", "نوع الولادة"),
              enum_map=DELIVERY_MAP, display="Mode d'accouchement"),
    FieldSpec("complications", FieldKind.FREE_TEXT,
              ("presence de complications", "complications", "complication", "observations", "obs", "remarques", "مضاعفات"),
              send_to_vlm=False, display="Complications"),
    FieldSpec("sexe_nouveau_ne", FieldKind.ENUM,
              ("sexe", "sexe bebe", "sexe du nouveau-ne", "جنس المولود"),
              enum_map=SEX_MAP, display="Sexe du nouveau-né"),
    FieldSpec("poids_naissance", FieldKind.INT,
              ("poids nouveau-ne(s)", "poids de naissance", "poids bebe", "poids nouveau-ne", "وزن الولادة"),
              hard_min=400, hard_max=7000, display="Poids de naissance"),
    FieldSpec("perimetre_cranien", FieldKind.FLOAT,
              ("perimetre cranien", "périmètre crânien", "pc", "محيط الرأس"),
              hard_min=20.0, hard_max=50.0, display="Périmètre crânien"),
    FieldSpec("allaitement", FieldKind.ENUM,
              ("allaitement", "allaitement maternel", "mise au sein", "رضاعة"),
              enum_map=YES_NO_MAP, display="Allaitement"),
    FieldSpec("transfert", FieldKind.ENUM,
              ("transfert", "reference", "evacuation", "تحويل"),
              enum_map=YES_NO_MAP, display="Transfert"),
    FieldSpec("vaccin_rubeole", FieldKind.TEXT,
              ("vaccinee contre la rubeole", "vaccinée contre la rubéole", "rubeole"),
              display="Vaccin rubéole"),
    FieldSpec("vaccin_hepatite_b", FieldKind.TEXT,
              ("vaccinee contre I'hepatite b", "vaccinee contre l'hepatite b", "vaccin hepatite b"),
              display="Vaccin hépatite B"),
    FieldSpec("frottis_cervical", FieldKind.TEXT,
              ("frottis cervical / iva", "frottis cervical", "frottis", "iva"),
              display="Frottis cervical / IVA"),
    FieldSpec("taille_cm", FieldKind.FLOAT,
              ("taille :", "taille (cm)", "taille"),
              unit="cm", hard_min=100.0, hard_max=220.0, display="Taille mère"),
    FieldSpec("taille_naissance", FieldKind.FLOAT,
              ("taille bebe", "taille nouveau-ne", "taille n-ne"),
              unit="cm", hard_min=20.0, hard_max=70.0, display="Taille nouveau-né"),
    FieldSpec("poids_avant_grossesse", FieldKind.FLOAT,
              ("poids habituel", "poids avant grossesse"),
              unit="kg", hard_min=30.0, hard_max=200.0, display="Poids avant grossesse"),
    FieldSpec("heure_accouchement", FieldKind.TEXT,
              ("heure de I'accouchement :", "heure de l'accouchement :", "heure accouchement"),
              display="Heure d'accouchement"),
    FieldSpec("conjonctives", FieldKind.TEXT,
              ("etat des conjonctives :", "etat des conjonctives", "conjonctives :", "conjonctives"),
              display="État des conjonctives"),
)

FIELDS_BY_KEY: dict[str, FieldSpec] = {f.key: f for f in FORM_FIELDS}

# Champs finaux exposés dans le JSON (composites éclatés)
OUTPUT_FIELDS: tuple[str, ...] = (
    # Identité & Administratif
    "nom_parturiente", "cin", "code_patiente", "telephone", "adresse", "nom_conjoint",
    "profession_patiente", "profession_conjoint", "region", "province",
    "etablissement_sanitaire", "type_etablissement_sanitaire", "grossesse_a_risque",
    "type_risque", "date_naissance",
    # Suivi clinique prénatal
    "date_consultation", "age", "poids_kg", "taille_cm", "poids_avant_grossesse",
    "tension_systolique", "tension_diastolique",
    "temperature", "pouls_bpm", "age_gestationnel", "hauteur_uterine_cm", "bcf_bpm",
    # Dépistages & Laboratoire
    "vih", "syphilis", "hepatite_c", "proteinurie", "glycemie", "hemoglobine",
    "groupe_sanguin", "rhesus",
    # Antécédents obstétricaux
    "gestite", "parite", "enfants_vivants", "avortements", "education_level", "consanguinite",
    "grossesse_desiree", "hta_chronique", "diabete", "cesarienne_anterieure", "imc", "ddr", "dpa",
    # Accouchement & Nouveau-né
    "date_accouchement", "heure_accouchement", "lieu_accouchement", "mode_accouchement", "complications",
    "sexe_nouveau_ne", "poids_naissance", "taille_naissance", "perimetre_cranien",
    "allaitement", "transfert", "conjonctives",
    "vaccin_rubeole", "vaccin_hepatite_b", "frottis_cervical",
)

PRODUCERS: dict[str, tuple[str, ...]] = {
    "tension_systolique": ("tension_arterielle",),
    "tension_diastolique": ("tension_arterielle",),
    "gestite": ("gesta_para", "gestite"),
    "parite": ("gesta_para", "parite"),
    "groupe_sanguin": ("groupe_rhesus",),
    "rhesus": ("groupe_rhesus",),
}

# Mode Local : aucun libellé n'est interdit ni masqué
PII_LABELS: tuple[str, ...] = ()

DISPLAY_NAMES: dict[str, str] = {
    f.key: (f.display or f.key) for f in FORM_FIELDS
}
DISPLAY_NAMES.update({
    "tension_systolique": "TA systolique",
    "tension_diastolique": "TA diastolique",
    "gestite": "Gestité",
    "parite": "Parité",
    "groupe_sanguin": "Groupe sanguin",
    "rhesus": "Rhésus",
})

OUTPUT_UNITS: dict[str, str] = {
    "age": "ans", "poids_kg": "kg", "taille_cm": "cm", "taille_naissance": "cm",
    "poids_avant_grossesse": "kg", "tension_systolique": "mmHg", "tension_diastolique": "mmHg",
    "temperature": "°C", "pouls_bpm": "bpm", "age_gestationnel": "SA", "hauteur_uterine_cm": "cm",
    "bcf_bpm": "bpm", "imc": "kg/m²", "glycemie": "mg/dL", "hemoglobine": "g/dL", "poids_naissance": "g",
    "perimetre_cranien": "cm",
}
