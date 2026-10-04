"""Base de données locale (SQLite) et opérations sur les dossiers.

- Un seul fichier `dayone.db`, créé au premier lancement. Rien à installer.
- Chiffré au repos : les valeurs lues (champs) et les photos (dossier `captures/`) sont
  chiffrées avec la clé `.device_secure_key` (Fernet). Le code patiente reste en clair :
  c'est un pseudonyme choisi par la sage-femme, nécessaire pour retrouver le dossier.
- Aucun nom, téléphone, CIN ni adresse : la lecture (dayone.extract) les retire des champs et
  donne leurs zones (`zones_masquees`), noircies sur la photo servie à l'affichage.
  L'original chiffré ne sort jamais par l'API.
- La lecture n'utilise pas de gabarit : chaque champ arrive avec son libellé et son type.
  Ce module les range dans le contrat du tableau de bord (section, type de page) en les
  comparant aux fiches de référence (schema/*.json), sans rien changer à la lecture.
- Les formats renvoyés sont ceux du contrat du tableau de bord (web/src/contract/types.ts).

Cycle de vie : mêmes états et mêmes transitions que web/src/contract/lifecycle.ts.
"""

import json
import os
import re
import secrets
import sys
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from cryptography.fernet import Fernet

from dayone import coherence, suivi
from dayone import page as page_image
from dayone import privacy
from dayone.dataset import ROOT
from dayone.normalize import fold, infer_kind, parse, special_word
from dayone.privacy import is_record_label
from dayone.schema import REFERENCE_PAGE_TYPES, reference_fields

DB_PATH = Path(os.environ.get("DAYONE_DB", ROOT / "dayone.db"))
CAPTURES = Path(os.environ.get("DAYONE_CAPTURES", ROOT / "captures"))
KEY_FILE = Path(os.environ.get("DAYONE_KEY_FILE", ROOT / ".device_secure_key"))

TRANSITIONS = {
    "CAPTURED": ("PENDING_AI", "MANUAL_REVIEW_REQUIRED"),
    "PENDING_AI": ("AI_PROCESSED", "PROCESSING_FAILED"),
    "AI_PROCESSED": ("NEEDS_REVIEW",),
    "NEEDS_REVIEW": ("VALIDATED", "CAPTURED", "MANUAL_REVIEW_REQUIRED"),
    "MANUAL_REVIEW_REQUIRED": ("VALIDATED", "CAPTURED"),
    "PROCESSING_FAILED": ("PENDING_AI", "MANUAL_REVIEW_REQUIRED", "CAPTURED"),
    "VALIDATED": ("PATIENT_LINKED", "SUSPECTED_DUPLICATE"),
    "SUSPECTED_DUPLICATE": ("PATIENT_LINKED",),
    "PATIENT_LINKED": ("SAVED",),
    "SAVED": ("SYNCED", "SYNC_FAILED"),
    "SYNC_FAILED": ("SYNCED", "SAVED"),
    "SYNCED": (),
}
TO_REVIEW = ("NEEDS_REVIEW", "ILLEGIBLE")

SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    id TEXT PRIMARY KEY,           -- aléatoire, jamais dérivé de données personnelles
    code TEXT NOT NULL,            -- code écrit par la sage-femme sur le registre
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS visits (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    date TEXT NOT NULL,
    midwife_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY,
    midwife_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    state TEXT NOT NULL,
    patient_code TEXT NOT NULL,    -- vide tant que la sage-femme ne l'a pas donné
    patient_id TEXT REFERENCES patients(id),
    visit_id TEXT REFERENCES visits(id),
    failure_reason TEXT,
    failure_at TEXT,
    validated_at TEXT,
    final_enc BLOB                 -- résultat final approuvé (JSON chiffré, voir final_json)
);
CREATE TABLE IF NOT EXISTS record_events (    -- historique des états (traçabilité)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL REFERENCES records(id),
    state TEXT NOT NULL,
    at TEXT NOT NULL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS pages (
    id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES records(id),
    idx INTEGER NOT NULL,
    page_type TEXT,                -- inconnu tant que la page n'est pas lue
    captured_at TEXT NOT NULL,
    original_path TEXT NOT NULL,   -- photo d'origine chiffrée (jamais servie)
    view_path TEXT,                -- page redressée, zones personnelles noircies, chiffrée
    image_w INTEGER,
    image_h INTEGER,
    fields_enc BLOB,               -- champs lus (JSON chiffré)
    supersedes TEXT,
    title TEXT,                    -- titre lu en haut de la fiche (chiffré : il peut contenir une valeur)
    error TEXT                     -- pourquoi la page n'a pas pu être lue
);
CREATE INDEX IF NOT EXISTS idx_records_patient ON records(patient_id);
CREATE INDEX IF NOT EXISTS idx_visits_patient ON visits(patient_id);
CREATE INDEX IF NOT EXISTS idx_pages_record ON pages(record_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def uid(prefix: str) -> str:
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return prefix + "_" + "".join(secrets.choice(alphabet) for _ in range(8))


# ---------------- chiffrement ----------------

_fernet: Fernet | None = None


def fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        if not KEY_FILE.exists():
            KEY_FILE.write_bytes(Fernet.generate_key())
            KEY_FILE.chmod(0o600)
        _fernet = Fernet(KEY_FILE.read_bytes().strip())
    return _fernet


def _write_encrypted(data: bytes, name: str) -> str:
    CAPTURES.mkdir(parents=True, exist_ok=True)
    path = CAPTURES / f"{name}.enc"
    path.write_bytes(fernet().encrypt(data))
    return str(path)


def _encrypt_text(text: str | None) -> str | None:
    return fernet().encrypt(text.encode()).decode() if text else None


def read_encrypted(path: str) -> bytes:
    return fernet().decrypt(Path(path).read_bytes())


# ---------------- connexion ----------------

_init_lock = threading.Lock()
_initialized = False
ADDED_COLUMNS = {
    "pages": {"title": "TEXT", "error": "TEXT"},
    "records": {"validated_at": "TEXT", "final_enc": "BLOB"},
}


@contextmanager
def db():
    global _initialized
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with _init_lock:
            if not _initialized:
                conn.execute("PRAGMA journal_mode = WAL")
                conn.executescript(SCHEMA)
                # Base créée avant ces colonnes : on les ajoute (rien n'est perdu)
                for table, cols in ADDED_COLUMNS.items():
                    have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
                    for col, kind in cols.items():
                        if col not in have:
                            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")
                _initialized = True
        yield conn
        conn.commit()
    finally:
        conn.close()


def counts() -> dict:
    with db() as c:
        return {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("patients", "visits", "records")}


# ---------------- cycle de vie ----------------

class TransitionError(ValueError):
    pass


def _move(c, record_id: str, to: str, note: str | None = None) -> None:
    state = c.execute("SELECT state FROM records WHERE id = ?", (record_id,)).fetchone()["state"]
    if to not in TRANSITIONS[state]:
        raise TransitionError(f"Transition refusée : {state} → {to}")
    c.execute("UPDATE records SET state = ? WHERE id = ?", (to, record_id))
    c.execute("INSERT INTO record_events (record_id, state, at, note) VALUES (?, ?, ?, ?)",
              (record_id, to, now(), note))


# ---------------- champs ----------------

MIN_REFERENCE_MATCHES = 3        # libellés communs avec une fiche de référence pour la reconnaître
OTHER_SECTION = "Autres champs lus"  # champ lu absent des fiches de référence
UNKNOWN_PAGE = "unknown"


@lru_cache
def _reference_labels() -> dict:
    """{type de page: {libellé replié: champ de référence}}."""
    return {pt: {fold(f.label): f for f in reference_fields(pt)} for pt in REFERENCE_PAGE_TYPES}


def page_type_of(pred: dict) -> str:
    """Fiche de référence dont la page lue partage le plus de libellés ; sinon une autre page du registre
    reconnue à ses lignes imprimées (« Venue le », « HU (cm) », « Pouls »…, dayone/suivi.py) ; `unknown` sinon."""
    labels = {fold(f["label"]) for f in pred["fields"]}
    scores = {pt: len(labels & ref.keys()) for pt, ref in _reference_labels().items()}
    best = max(scores, key=scores.get)
    if scores[best] >= MIN_REFERENCE_MATCHES:
        return best
    return suivi.page_type_from_labels(pred["fields"]) or UNKNOWN_PAGE


def fields_from_prediction(pred: dict, page_index: int, at: str) -> dict:
    """Sortie de dayone.extract (liste de champs) -> champs du contrat, indexés par clé.

    Un champ dont le libellé est celui d'une fiche de référence prend sa clé et sa section
    (« age », « Identification ») : le résumé patiente et la liaison s'en servent.
    Les autres gardent l'identifiant donné par la lecture, dans « Autres champs lus ».
    """
    ref = _reference_labels().get(page_type_of(pred), {})
    out = {}
    for p in pred["fields"]:
        known = ref.get(fold(p["label"]))
        key = known.id if known and known.id not in out else p["id"]
        while key in out:
            key += "_"
        origin = "MANUAL" if p.get("source") == "humain" else "AI"
        field = {
            "key": key, "label": p["label"], "kind": p.get("kind", "text"),
            "section": known.group if known else OTHER_SECTION,
            "value": p["value"], "status": p["status"], "confidence": p["confidence"],
            "origin": origin, "method": p.get("source"), "page": page_index,
            "history": [{"at": at, "by": "AI", "origin": origin, "value": p["value"], "status": p["status"]}],
        }
        # Détails de la lecture, utiles à la sage-femme : cases proposées, raison du doute, lecture d'origine
        # et colonne du tableau (une visite par colonne dans « Grossesse actuelle »)
        for src, dst in (("options", "options"), ("raison", "reason"), ("valeur_lue", "readValue"),
                         ("colonne", "column")):
            if p.get(src) is not None:
                field[dst] = p[src]
        out[key] = field
    return out


def _load_fields(row) -> dict:
    return json.loads(fernet().decrypt(row["fields_enc"])) if row["fields_enc"] else {}


def _save_fields(c, page_id: str, fields: dict) -> None:
    blob = fernet().encrypt(json.dumps(fields, ensure_ascii=False).encode())
    c.execute("UPDATE pages SET fields_enc = ? WHERE id = ?", (blob, page_id))


# Dossier encore en vérification : ses champs peuvent changer de statut. Un dossier validé est figé.
OPEN_STATES = ("CAPTURED", "PENDING_AI", "AI_PROCESSED", "NEEDS_REVIEW", "MANUAL_REVIEW_REQUIRED")


def _recheck(c, record_id: str) -> None:
    """Contrôles de cohérence de la lecture sur toutes les pages lues du dossier (dayone/coherence.py).

    Une valeur lue par l'IA qui contredit le reste du registre passe « à vérifier » avec son explication ;
    l'agent WhatsApp la fait donc vérifier. Une correction qui lève la contradiction rend son statut au champ.
    """
    state = c.execute("SELECT state FROM records WHERE id = ?", (record_id,)).fetchone()["state"]
    if state not in OPEN_STATES:
        return
    rows = c.execute("""SELECT * FROM pages WHERE record_id = ? AND fields_enc IS NOT NULL ORDER BY idx""",
                     (record_id,)).fetchall()
    pages = [(r["idx"], _page_type(r["page_type"], fields), fields) for r in rows for fields in [_load_fields(r)]]
    alerts = coherence.check_record(pages)
    for row, (idx, _, fields) in zip(rows, pages):
        if coherence.apply(fields, {key: a for (i, key), a in alerts.items() if i == idx}):
            _save_fields(c, row["id"], fields)


def recheck_open_records() -> int:
    """Au démarrage : dossiers lus avant l'ajout des contrôles, encore en vérification."""
    with db() as c:
        ids = [r["id"] for r in c.execute(
            f"SELECT id FROM records WHERE state IN ({','.join('?' * len(OPEN_STATES))})", OPEN_STATES)]
        for record_id in ids:
            _recheck(c, record_id)
    return len(ids)


def _page_type(stored: str | None, fields: dict) -> str:
    """Type enregistré ; une page lue avant la reconnaissance des autres pages du registre est reconnue ici."""
    if stored and stored != UNKNOWN_PAGE:
        return stored
    return (suivi.page_type_from_labels(fields) if fields else None) or UNKNOWN_PAGE


# ---------------- capture et lecture ----------------

MAX_CODE_LENGTH = 20


def clean_code(code: str) -> str:
    code = code.strip().upper()
    if len(code) > MAX_CODE_LENGTH:
        raise ValueError(f"Code patiente trop long ({MAX_CODE_LENGTH} caractères au plus)")
    return code


def create_record(patient_code: str, midwife_id: str, photos: list[bytes]) -> str:
    """Enregistre la capture (photos chiffrées) et la met en attente de lecture.

    Le code patiente peut être vide : l'agent WhatsApp crée le dossier dès la 1re photo et le
    demande ensuite (set_code).
    """
    at = now()
    record_id = uid("rec")
    with db() as c:
        c.execute("INSERT INTO records (id, midwife_id, created_at, state, patient_code) VALUES (?, ?, ?, ?, ?)",
                  (record_id, midwife_id, at, "CAPTURED", clean_code(patient_code)))
        c.execute("INSERT INTO record_events (record_id, state, at) VALUES (?, ?, ?)", (record_id, "CAPTURED", at))
        for i, data in enumerate(photos):
            page_id = uid("pg")
            c.execute("INSERT INTO pages (id, record_id, idx, captured_at, original_path) VALUES (?, ?, ?, ?, ?)",
                      (page_id, record_id, i, at, _write_encrypted(data, page_id + "_original")))
        _move(c, record_id, "PENDING_AI")
    return record_id


def add_page(record_id: str, photo: bytes) -> int:
    """Ajoute une page au dossier (photo chiffrée tout de suite) ; elle sera lue en arrière-plan.

    Pendant la lecture d'autres pages le dossier reste PENDING_AI ; s'il était déjà lu, il y revient.
    """
    with db() as c:
        state = c.execute("SELECT state FROM records WHERE id = ?", (record_id,)).fetchone()["state"]
        if state not in ("PENDING_AI", "CAPTURED") and "CAPTURED" not in TRANSITIONS[state]:
            raise TransitionError(f"Dossier {state} : on ne peut plus y ajouter de page")
        idx = c.execute("SELECT COALESCE(MAX(idx), -1) + 1 FROM pages WHERE record_id = ?", (record_id,)).fetchone()[0]
        page_id = uid("pg")
        c.execute("INSERT INTO pages (id, record_id, idx, captured_at, original_path) VALUES (?, ?, ?, ?, ?)",
                  (page_id, record_id, idx, now(), _write_encrypted(photo, page_id + "_original")))
        if state != "PENDING_AI":
            if state != "CAPTURED":
                _move(c, record_id, "CAPTURED", note=f"ADD page {idx}")
            _move(c, record_id, "PENDING_AI")
    return idx


def set_code(record_id: str, code: str) -> str:
    """Code patiente écrit sur le registre, donné après la capture. Modifiable tant que la patiente n'est pas choisie."""
    code = clean_code(code)
    if not code:
        raise ValueError("Code patiente vide")
    with db() as c:
        rec = c.execute("SELECT patient_id FROM records WHERE id = ?", (record_id,)).fetchone()
        if rec["patient_id"]:
            raise TransitionError("La patiente est déjà choisie : le code ne change plus")
        c.execute("UPDATE records SET patient_code = ? WHERE id = ?", (code, record_id))
        c.execute("INSERT INTO record_events (record_id, state, at, note) SELECT id, state, ?, 'CODE' FROM records WHERE id = ?",
                  (now(), record_id))
    return code


_process_lock = threading.Lock()   # une lecture à la fois : PaddleOCR et le modèle sont lourds
busy: set[str] = set()


if sys.platform == "win32":
    # Paddle 3.x sous Windows : l'accélération oneDNN plante (« ConvertPirAttribute2RuntimeAttribute
    # not support »). Le processus PaddleOCR (dayone/ocr.py) hérite de cette variable.
    os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "False")


def extractor():
    """La lecture : dayone.extract, ou les sorties enregistrées si DAYONE_DEMO_EXTRACT=1."""
    if os.environ.get("DAYONE_DEMO_EXTRACT") == "1":
        from api.demo import extract_page
    else:
        from dayone.extract import extract_page
    return extract_page


def process_record(record_id: str, extract=None, use_model: bool = True) -> None:
    """Lit les pages pas encore lues (dayone.extract), stocke les champs chiffrés et la vue masquée.

    Une page déjà lue n'est pas relue : les corrections faites dessus sont gardées quand on
    remplace la photo d'une autre page. Une page illisible garde son erreur (`pages.error`).
    """
    if extract is None:
        extract = extractor()
    with _process_lock:
        busy.add(record_id)
        try:
            with db() as c:
                pages = c.execute("""SELECT * FROM pages WHERE record_id = ? AND fields_enc IS NULL AND error IS NULL
                                     ORDER BY idx""", (record_id,)).fetchall()
            results, errors = [], []
            for p in pages:
                data = read_encrypted(p["original_path"])
                try:
                    pred = extract(data, use_model=use_model)
                    results.append((p, pred, _masked_view(data, pred)))
                except (ValueError, RuntimeError) as e:     # pas une fiche, image illisible, OCR indisponible…
                    errors.append((p, str(e)))
            at = now()
            with db() as c:
                for p, message in errors:
                    c.execute("UPDATE pages SET error = ? WHERE id = ?", (message, p["id"]))
                for p, pred, view in results:
                    view_path, size = (None, (None, None))
                    if view is not None:
                        ok, jpg = cv2.imencode(".jpg", view, [cv2.IMWRITE_JPEG_QUALITY, 85])
                        view_path = _write_encrypted(jpg.tobytes(), p["id"] + "_view") if ok else None
                        size = (view.shape[1], view.shape[0])
                    c.execute("""UPDATE pages SET page_type = ?, view_path = ?, image_w = ?, image_h = ?, title = ?,
                                 error = NULL WHERE id = ?""",
                              (page_type_of(pred), view_path, size[0], size[1], _encrypt_text(pred.get("title")), p["id"]))
                    _save_fields(c, p["id"], fields_from_prediction(pred, p["idx"], at))
                if results:
                    _recheck(c, record_id)
                state = c.execute("SELECT state FROM records WHERE id = ?", (record_id,)).fetchone()["state"]
                waiting = c.execute("""SELECT COUNT(*) FROM pages WHERE record_id = ? AND fields_enc IS NULL
                                       AND error IS NULL""", (record_id,)).fetchone()[0]
                if state != "PENDING_AI" or waiting:
                    return          # une page ajoutée entre-temps : sa propre lecture finira le travail
                read = c.execute("SELECT COUNT(*) FROM pages WHERE record_id = ? AND fields_enc IS NOT NULL",
                                 (record_id,)).fetchone()[0]
                if not read:
                    c.execute("UPDATE records SET failure_reason = ?, failure_at = ? WHERE id = ?",
                              ("LAYOUT", at, record_id))
                    _move(c, record_id, "PROCESSING_FAILED", note=(errors[0][1] if errors else None))
                    return
                c.execute("UPDATE records SET failure_reason = NULL, failure_at = NULL WHERE id = ?", (record_id,))
                _move(c, record_id, "AI_PROCESSED")
                _move(c, record_id, "NEEDS_REVIEW")
        finally:
            busy.discard(record_id)


def _masked_view(data: bytes, pred: dict) -> np.ndarray | None:
    """Page redressée, zones personnelles noircies : la même image que l'interface de lecture.

    Sans `zones_masquees` dans la sortie, on ne sait pas quoi cacher : aucune image n'est produite.
    """
    if "zones_masquees" not in pred:
        return None
    try:
        return privacy.redact(page_image.prepare(page_image.load_image(data)), pred["zones_masquees"])
    except (ValueError, cv2.error):
        return None


def pending_records() -> list[str]:
    with db() as c:
        return [r["id"] for r in c.execute("SELECT id FROM records WHERE state = 'PENDING_AI' ORDER BY created_at")]


def retry(record_id: str) -> None:
    """Relire les pages qui n'ont pas pu l'être (OCR indisponible au moment de la capture…)."""
    with db() as c:
        _move(c, record_id, "PENDING_AI", note="RETRY")
        c.execute("UPDATE pages SET error = NULL WHERE record_id = ? AND fields_enc IS NULL", (record_id,))


def replace_page(record_id: str, page_index: int, photo: bytes) -> None:
    """Nouvelle photo d'une page (floue, mal cadrée…) : seule cette page sera relue.

    L'ancienne photo chiffrée est gardée sur disque (traçabilité) ; ses champs sont effacés.
    """
    with db() as c:
        row = _page(c, record_id, page_index)
        state = c.execute("SELECT state FROM records WHERE id = ?", (record_id,)).fetchone()["state"]
        if "CAPTURED" not in TRANSITIONS[state]:
            raise TransitionError(f"Transition refusée : {state} → CAPTURED")
        path = _write_encrypted(photo, uid(row["id"] + "_original"))
        c.execute("""UPDATE pages SET original_path = ?, captured_at = ?, fields_enc = NULL, view_path = NULL,
                     page_type = NULL, title = NULL, error = NULL, image_w = NULL, image_h = NULL WHERE id = ?""",
                  (path, now(), row["id"]))
        _move(c, record_id, "CAPTURED", note=f"RETAKE page {page_index}")
        _move(c, record_id, "PENDING_AI")


def drop_page(record_id: str, page_index: int) -> None:
    """Retire une page illisible du dossier (la sage-femme ne la reprendra pas). Une page lue reste."""
    with db() as c:
        row = _page(c, record_id, page_index)
        if row["fields_enc"] is not None:
            raise TransitionError("Seule une page qui n'a pas pu être lue peut être retirée")
        if c.execute("SELECT COUNT(*) FROM pages WHERE record_id = ?", (record_id,)).fetchone()[0] == 1:
            raise TransitionError("C'est la seule page du dossier")
        c.execute("DELETE FROM pages WHERE id = ?", (row["id"],))
        c.execute("INSERT INTO record_events (record_id, state, at, note) SELECT id, state, ?, ? FROM records WHERE id = ?",
                  (now(), f"DROP page {page_index}", record_id))


# ---------------- vérification (faite par la sage-femme sur WhatsApp) ----------------

def _page(c, record_id: str, page_index: int):
    row = c.execute("SELECT * FROM pages WHERE record_id = ? AND idx = ?", (record_id, page_index)).fetchone()
    if row is None:
        raise KeyError(f"page {page_index} introuvable")
    return row


def set_field(record_id: str, page_index: int, key: str, by: str,
              value=None, status: str | None = None, confirm: bool = False) -> dict:
    """Confirme la valeur lue, ou la remplace (value + status). Garde la valeur de l'IA."""
    with db() as c:
        row = _page(c, record_id, page_index)
        fields = _load_fields(row)
        f = fields[key]
        if confirm:
            f["origin"] = "MANUAL" if f["origin"] == "MANUAL" else "CONFIRMED"
            f["status"] = "NOT_PROVIDED" if f["value"] is None else "KNOWN"
        else:
            if f["origin"] == "AI" and "aiValue" not in f:
                f["aiValue"] = f["value"]
            same = value == f["value"] and status == f["status"]
            f["origin"] = "MANUAL" if f["origin"] == "MANUAL" else ("CONFIRMED" if same else "CORRECTED")
            f["value"], f["status"] = value, status
        # La sage-femme a regardé le papier : l'alerte de cohérence de ce champ est levée.
        f.pop("alerts", None)
        f.pop("coherence", None)
        if f.get("reason") == "incoherent":
            f.pop("reason")
        f["history"].append({"at": now(), "by": by, "origin": f["origin"], "value": f["value"], "status": f["status"]})
        _save_fields(c, row["id"], fields)
        _recheck(c, record_id)          # une correction peut lever (ou révéler) une incohérence ailleurs
        return f


ADDED_SECTION = "Ajoutés par la sage-femme"


def add_field(record_id: str, page_index: int, label: str, text: str, by: str) -> dict:
    """Champ oublié par la lecture, ajouté par la sage-femme (étiquette + valeur). Jamais une donnée personnelle."""
    label = " ".join(label.split())[:80]
    text = text.strip()[:120]
    if len(label) < 2:
        raise ValueError("Nom du champ trop court")
    if privacy.is_personal(label, text):
        raise ValueError("Donnée personnelle (nom, CIN, téléphone, adresse) : elle n'est jamais enregistrée")
    kind = infer_kind(label)
    if not text or text == "-":
        value, status = None, "NOT_PROVIDED"
    elif special_word(text) == "unknown":
        value, status = None, "UNKNOWN"
    else:
        value, _ = parse(kind, text)
        value, status = (value if value is not None else text), "KNOWN"
    with db() as c:
        row = _page(c, record_id, page_index)
        fields = _load_fields(row)
        key = re.sub(r"[^a-z0-9]+", "_", fold(label)).strip("_")[:60] or "champ"
        while key in fields:
            key += "_"
        at = now()
        fields[key] = {
            "key": key, "label": label, "kind": kind, "section": ADDED_SECTION,
            "value": value, "status": status, "confidence": 1.0, "origin": "MANUAL", "method": "humain",
            "page": page_index, "history": [{"at": at, "by": by, "origin": "MANUAL", "value": value, "status": status}],
        }
        _save_fields(c, row["id"], fields)
        return fields[key]


def validate(record_id: str) -> None:
    with db() as c:
        for row in c.execute("SELECT * FROM pages WHERE record_id = ?", (record_id,)).fetchall():
            if row["fields_enc"] is None:
                raise TransitionError("Une page n'a pas pu être lue : la reprendre ou la retirer")
            if any(f["status"] in TO_REVIEW for f in _load_fields(row).values()):
                raise TransitionError("Des champs restent à vérifier")
        _move(c, record_id, "VALIDATED")
        at = now()
        c.execute("UPDATE records SET validated_at = ? WHERE id = ?", (at, record_id))
        _store_final(c, record_id)


# ---------------- résultat final ----------------

FINAL_FORMAT = "dayone.record.v1"
FINAL_FIELD_KEYS = ("key", "label", "kind", "section", "value", "status", "confidence", "origin", "aiValue")


def _build_final(c, record_id: str) -> dict:
    """Ce que la sage-femme a approuvé, indépendant de l'interface : un JSON stable à conserver ou exporter."""
    r = c.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
    pages = []
    for p in c.execute("SELECT * FROM pages WHERE record_id = ? ORDER BY idx", (record_id,)).fetchall():
        fields = [{k: f[k] for k in FINAL_FIELD_KEYS if k in f} for f in _load_fields(p).values()]
        pages.append({"index": p["idx"], "page_type": p["page_type"] or UNKNOWN_PAGE,
                      "title": fernet().decrypt(p["title"].encode()).decode() if p["title"] else None,
                      "captured_at": p["captured_at"], "fields": fields})
    linked_at = c.execute("""SELECT at FROM record_events WHERE record_id = ? AND state = 'PATIENT_LINKED'
                             ORDER BY id DESC LIMIT 1""", (record_id,)).fetchone()
    return {
        "format": FINAL_FORMAT, "record_id": r["id"], "patient_code": r["patient_code"],
        "patient_id": r["patient_id"], "visit_id": r["visit_id"], "midwife_id": r["midwife_id"],
        "captured_at": r["created_at"], "validated_at": r["validated_at"],
        "linked_at": linked_at["at"] if linked_at else None, "state": r["state"], "pages": pages,
    }


def _store_final(c, record_id: str) -> None:
    final = _build_final(c, record_id)
    blob = fernet().encrypt(json.dumps(final, ensure_ascii=False).encode())
    c.execute("UPDATE records SET final_enc = ? WHERE id = ?", (blob, record_id))


def final_json(record_id: str) -> dict | None:
    """Résultat final approuvé (None tant que le dossier n'est pas validé)."""
    with db() as c:
        row = c.execute("SELECT final_enc FROM records WHERE id = ?", (record_id,)).fetchone()
    return json.loads(fernet().decrypt(row["final_enc"])) if row and row["final_enc"] else None


# ---------------- liaison patiente ----------------

LOOKALIKE = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "S": "5", "Z": "2", "B": "8", "G": "6"}


def normalize_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def code_distance(a: str, b: str) -> int:
    """Distance d'édition, en confondant les caractères que l'écriture mélange (O/0, I/1, S/5…)."""
    x = "".join(LOOKALIKE.get(ch, ch) for ch in normalize_code(a))
    y = "".join(LOOKALIKE.get(ch, ch) for ch in normalize_code(b))
    prev = list(range(len(y) + 1))
    for i, cx in enumerate(x, 1):
        cur = [i]
        for j, cy in enumerate(y, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (cx != cy)))
        prev = cur
    return prev[-1]


def _number(fields: dict, key: str):
    v = fields.get(key, {}).get("value")
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _record_fields(c, record_id: str) -> dict:
    out = {}
    for row in c.execute("SELECT * FROM pages WHERE record_id = ? ORDER BY idx", (record_id,)).fetchall():
        out.update(_load_fields(row))
    return out


def candidates(record_id: str) -> list[dict]:
    """Patientes plausibles pour ce dossier. Propose seulement : la sage-femme décide."""
    with db() as c:
        rec = c.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        mine = _record_fields(c, record_id)
        out = []
        if not rec["patient_code"]:
            return out
        for p in c.execute("SELECT * FROM patients").fetchall():
            d = code_distance(rec["patient_code"], p["code"])
            if d > 1:
                continue
            reasons = [{"kind": "SAME_CODE"} if d == 0 else {"kind": "SIMILAR_CODE", "distance": d}]
            theirs = {}
            for r in c.execute("SELECT id FROM records WHERE patient_id = ? ORDER BY created_at", (p["id"],)):
                theirs.update(_record_fields(c, r["id"]))
            age, their_age = _number(mine, "age"), _number(theirs, "age")
            if age is not None and their_age is not None and abs(age - their_age) <= 1:
                reasons.append({"kind": "SAME_AGE" if age == their_age else "CLOSE_AGE", "age": their_age})
            g = _number(mine, "gestation")
            if g is not None and g == _number(theirs, "gestation"):
                reasons.append({"kind": "SAME_GESTATION", "gestation": g})
            out.append({"patientId": p["id"], "code": p["code"], "reasons": reasons,
                        "score": (10 if d == 0 else 5) + len(reasons)})
        return sorted(out, key=lambda x: -x["score"])


def link(record_id: str, decision: str, patient_id: str | None = None) -> str | None:
    """EXISTING (patient_id), CREATE ou UNSURE. Jamais de création silencieuse : c'est un choix explicite."""
    with db() as c:
        rec = c.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        if not rec["patient_code"]:
            raise TransitionError("Donner d'abord le code patiente écrit sur le registre")
        if decision == "UNSURE":
            if rec["state"] == "VALIDATED":
                _move(c, record_id, "SUSPECTED_DUPLICATE")
                _store_final(c, record_id)
            return None
        if decision == "CREATE":
            patient_id = uid("pt")
            c.execute("INSERT INTO patients (id, code, created_at) VALUES (?, ?, ?)",
                      (patient_id, rec["patient_code"], now()))
        elif not c.execute("SELECT 1 FROM patients WHERE id = ?", (patient_id,)).fetchone():
            raise KeyError("patiente introuvable")
        day = rec["created_at"][:10]
        visit = c.execute("SELECT id FROM visits WHERE patient_id = ? AND substr(date, 1, 10) = ?",
                          (patient_id, day)).fetchone()
        visit_id = visit["id"] if visit else uid("vis")
        if not visit:
            c.execute("INSERT INTO visits (id, patient_id, date, midwife_id) VALUES (?, ?, ?, ?)",
                      (visit_id, patient_id, rec["created_at"], rec["midwife_id"]))
        # Une page déjà présente dans le dossier est remplacée dans le résumé ; l'ancienne reste dans l'historique.
        for p in c.execute("SELECT id, page_type FROM pages WHERE record_id = ?", (record_id,)).fetchall():
            if p["page_type"] in (None, UNKNOWN_PAGE):
                continue                    # deux pages non reconnues ne se remplacent pas
            old = c.execute("""SELECT pg.id FROM pages pg JOIN records r ON r.id = pg.record_id
                               WHERE r.patient_id = ? AND pg.page_type = ? ORDER BY r.created_at DESC LIMIT 1""",
                            (patient_id, p["page_type"])).fetchone()
            if old:
                c.execute("UPDATE pages SET supersedes = ? WHERE id = ?", (old["id"], p["id"]))
        c.execute("UPDATE records SET patient_id = ?, visit_id = ? WHERE id = ?", (patient_id, visit_id, record_id))
        _move(c, record_id, "PATIENT_LINKED", note=decision)
        _move(c, record_id, "SAVED")
        _move(c, record_id, "SYNCED")       # serveur local = dossier central : rien d'autre à envoyer
        if rec["validated_at"]:
            _store_final(c, record_id)      # le résultat final porte la patiente et la visite
        return patient_id


# ---------------- lecture pour le tableau de bord ----------------

def snapshot(image_url) -> dict:
    """Tout ce que le tableau de bord affiche, au format du contrat front."""
    with db() as c:
        patients = {p["id"]: {"id": p["id"], "code": p["code"], "createdAt": p["created_at"], "visitIds": []}
                    for p in c.execute("SELECT * FROM patients")}
        visits = {}
        for v in c.execute("SELECT * FROM visits ORDER BY date"):
            visits[v["id"]] = {"id": v["id"], "patientId": v["patient_id"], "date": v["date"],
                               "midwifeId": v["midwife_id"], "recordIds": []}
            patients[v["patient_id"]]["visitIds"].append(v["id"])
        records = {}
        for r in c.execute("SELECT * FROM records ORDER BY created_at"):
            rec = _record_dict(c, r, image_url)
            if r["visit_id"]:
                visits[r["visit_id"]]["recordIds"].append(r["id"])
            records[r["id"]] = rec
        return {"patients": patients, "visits": visits, "records": records, "busy": sorted(busy)}


def _record_dict(c, r, image_url) -> dict:
    """Un dossier au format du contrat front (web/src/contract/types.ts)."""
    pages = []
    for p in c.execute("SELECT * FROM pages WHERE record_id = ? ORDER BY idx", (r["id"],)).fetchall():
        fields = _load_fields(p)
        page_type = _page_type(p["page_type"], fields)
        page = {"id": p["id"], "index": p["idx"], "pageType": page_type,
                "imageSize": [p["image_w"] or 1654, p["image_h"] or 2339], "capturedAt": p["captured_at"],
                "quality": {"ok": p["error"] is None}, "fields": fields}
        measures = suivi.series(page_type, fields)
        if measures:
            page["series"] = measures       # mesures suivies (courbes), tirées des champs à chaque lecture
        if p["title"]:
            page["title"] = fernet().decrypt(p["title"].encode()).decode()
        if p["error"]:
            page["error"] = p["error"]
        if p["view_path"]:
            page["imageUrl"] = image_url(p["id"])
            page["masked"] = True       # zones personnelles déjà noircies sur l'image servie
        if p["supersedes"]:
            page["supersedes"] = p["supersedes"]
        pages.append(page)
    history = [{"state": e["state"], "at": e["at"], **({"note": e["note"]} if e["note"] else {})}
               for e in c.execute("SELECT * FROM record_events WHERE record_id = ? ORDER BY id", (r["id"],))]
    rec = {"id": r["id"], "midwifeId": r["midwife_id"], "createdAt": r["created_at"], "state": r["state"],
           "history": history, "patientCode": r["patient_code"], "pages": pages}
    if r["patient_id"]:
        rec["patientId"] = r["patient_id"]
    if r["visit_id"]:
        rec["visitId"] = r["visit_id"]
    if r["failure_reason"]:
        rec["failure"] = {"reason": r["failure_reason"], "at": r["failure_at"]}
    if r["validated_at"]:
        rec["validatedAt"] = r["validated_at"]
    if r["final_enc"]:
        rec["hasFinal"] = True
    if not r["patient_code"]:
        suggestion = suggested_code(pages)
        if suggestion:
            rec["codeSuggestion"] = suggestion
    return rec


def suggested_code(pages: list[dict]) -> str | None:
    """N° de fiche / code lu sur une page (la lecture le garde : il relie les visites)."""
    for page in pages:
        for f in page["fields"].values():
            if f.get("value") and f.get("status") != "ILLEGIBLE" and is_record_label(f.get("label", "")):
                code = re.sub(r"[^A-Za-z0-9\-/]", "", str(f["value"])).upper()
                if 0 < len(code) <= MAX_CODE_LENGTH:
                    return code
    return None


def record(record_id: str, image_url) -> dict | None:
    """Un seul dossier (utilisé par l'agent WhatsApp pour suivre la lecture), avec `busy`."""
    with db() as c:
        r = c.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        if r is None:
            return None
        return {**_record_dict(c, r, image_url), "busy": record_id in busy}


def view_image(page_id: str) -> bytes | None:
    with db() as c:
        row = c.execute("SELECT view_path FROM pages WHERE id = ?", (page_id,)).fetchone()
    return read_encrypted(row["view_path"]) if row and row["view_path"] else None
