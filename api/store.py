"""Base de données locale (SQLite) et opérations sur les dossiers.

- Un seul fichier `dayone.db`, créé au premier lancement. Rien à installer.
- Chiffré au repos : les valeurs lues (champs) et les photos (dossier `captures/`) sont
  chiffrées avec la clé `.device_secure_key` (Fernet). Le code patiente reste en clair :
  c'est un pseudonyme choisi par la sage-femme, nécessaire pour retrouver le dossier.
- Aucun nom, téléphone, CIN ni adresse : le gabarit n'a pas de zone pour eux, et la photo
  servie à l'affichage a ces zones noircies. L'original chiffré ne sort jamais par l'API.
- Les formats renvoyés sont ceux du contrat du tableau de bord (web/src/contract/types.ts).

Cycle de vie : mêmes états et mêmes transitions que web/src/contract/lifecycle.ts.
"""

import json
import os
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from cryptography.fernet import Fernet

from dayone import imaging
from dayone.dataset import ROOT
from dayone.schema import load_schema

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
    patient_code TEXT NOT NULL,
    patient_id TEXT REFERENCES patients(id),
    visit_id TEXT REFERENCES visits(id),
    failure_reason TEXT,
    failure_at TEXT
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
    supersedes TEXT
);
CREATE INDEX IF NOT EXISTS idx_records_patient ON records(patient_id);
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


def read_encrypted(path: str) -> bytes:
    return fernet().decrypt(Path(path).read_bytes())


# ---------------- connexion ----------------

_init_lock = threading.Lock()
_initialized = False


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

def _bbox(f) -> list | None:
    """Où le champ est écrit sur la page redressée ; une case à cocher inclut son libellé."""
    if f.zone:
        return list(f.zone)
    if f.box:
        cx, cy, s = f.box
        return [cx - s * 1.5, cy - s * 1.6, cx + s * 14, cy + s * 1.6]
    return None


def fields_from_prediction(pred: dict, page_index: int, at: str) -> dict:
    """Sortie de dayone.extract -> champs du contrat (section, origine, position, historique)."""
    schema = load_schema(pred["page_type"])
    out = {}
    for f in schema.fields:
        p = pred["fields"].get(f.id)
        if p is None:
            continue
        origin = "MANUAL" if p.get("source") == "humain" else "AI"
        out[f.id] = {
            "key": f.id, "section": f.group, "value": p["value"], "status": p["status"],
            "confidence": p["confidence"], "origin": origin, "method": p.get("source"),
            "bbox": _bbox(f), "page": page_index,
            "history": [{"at": at, "by": "AI", "origin": origin, "value": p["value"], "status": p["status"]}],
        }
    return out


def _load_fields(row) -> dict:
    return json.loads(fernet().decrypt(row["fields_enc"])) if row["fields_enc"] else {}


def _save_fields(c, page_id: str, fields: dict) -> None:
    blob = fernet().encrypt(json.dumps(fields, ensure_ascii=False).encode())
    c.execute("UPDATE pages SET fields_enc = ? WHERE id = ?", (blob, page_id))


# ---------------- capture et lecture ----------------

def create_record(patient_code: str, midwife_id: str, photos: list[bytes]) -> str:
    """Enregistre la capture (photos chiffrées) et la met en attente de lecture."""
    at = now()
    record_id = uid("rec")
    with db() as c:
        c.execute("INSERT INTO records (id, midwife_id, created_at, state, patient_code) VALUES (?, ?, ?, ?, ?)",
                  (record_id, midwife_id, at, "CAPTURED", patient_code.strip().upper()))
        c.execute("INSERT INTO record_events (record_id, state, at) VALUES (?, ?, ?)", (record_id, "CAPTURED", at))
        for i, data in enumerate(photos):
            page_id = uid("pg")
            c.execute("INSERT INTO pages (id, record_id, idx, captured_at, original_path) VALUES (?, ?, ?, ?, ?)",
                      (page_id, record_id, i, at, _write_encrypted(data, page_id + "_original")))
        _move(c, record_id, "PENDING_AI")
    return record_id


_process_lock = threading.Lock()   # une lecture à la fois : PaddleOCR et le modèle sont lourds
busy: set[str] = set()


def process_record(record_id: str, extract=None, page_type: str | None = None, use_model: bool = True) -> None:
    """Lit chaque page (dayone.extract), stocke les champs chiffrés et la vue masquée."""
    if extract is None:
        from dayone.extract import extract_page as extract
    with _process_lock:
        busy.add(record_id)
        try:
            with db() as c:
                pages = c.execute("SELECT * FROM pages WHERE record_id = ? ORDER BY idx", (record_id,)).fetchall()
            results, errors = [], []
            for p in pages:
                data = read_encrypted(p["original_path"])
                try:
                    pred = extract(data, page_type=page_type, use_model=use_model)
                    results.append((p, pred, _masked_view(data, pred)))
                except (ValueError, RuntimeError) as e:     # mise en page inconnue, OCR indisponible…
                    errors.append(str(e))
            at = now()
            with db() as c:
                if not results:
                    c.execute("UPDATE records SET failure_reason = ?, failure_at = ? WHERE id = ?",
                              ("LAYOUT", at, record_id))
                    _move(c, record_id, "PROCESSING_FAILED", note=(errors[0] if errors else None))
                    return
                for p, pred, view in results:
                    view_path, size = (None, (None, None))
                    if view is not None:
                        ok, jpg = cv2.imencode(".jpg", view, [cv2.IMWRITE_JPEG_QUALITY, 85])
                        view_path = _write_encrypted(jpg.tobytes(), p["id"] + "_view") if ok else None
                        size = (view.shape[1], view.shape[0])
                    c.execute("UPDATE pages SET page_type = ?, view_path = ?, image_w = ?, image_h = ? WHERE id = ?",
                              (pred["page_type"], view_path, size[0], size[1], p["id"]))
                    _save_fields(c, p["id"], fields_from_prediction(pred, p["idx"], at))
                c.execute("UPDATE records SET failure_reason = NULL, failure_at = NULL WHERE id = ?", (record_id,))
                _move(c, record_id, "AI_PROCESSED")
                _move(c, record_id, "NEEDS_REVIEW")
        finally:
            busy.discard(record_id)


def _masked_view(data: bytes, pred: dict) -> np.ndarray | None:
    """Page redressée sur le gabarit, zones personnelles noircies. None si la page n'a pas été alignée."""
    if pred.get("mode") != "gabarit":
        return None
    img = imaging.load_image(data)
    al = imaging.align(img, pred["page_type"])
    return imaging.masked_preview(imaging.warp(img, al), pred["page_type"]) if al.ok else None


def pending_records() -> list[str]:
    with db() as c:
        return [r["id"] for r in c.execute("SELECT id FROM records WHERE state = 'PENDING_AI' ORDER BY created_at")]


def retry(record_id: str) -> None:
    with db() as c:
        _move(c, record_id, "PENDING_AI", note="RETRY")


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
        f["history"].append({"at": now(), "by": by, "origin": f["origin"], "value": f["value"], "status": f["status"]})
        _save_fields(c, row["id"], fields)
        return f


def validate(record_id: str) -> None:
    with db() as c:
        for row in c.execute("SELECT * FROM pages WHERE record_id = ?", (record_id,)).fetchall():
            if any(f["status"] in TO_REVIEW for f in _load_fields(row).values()):
                raise TransitionError("Des champs restent à vérifier")
        _move(c, record_id, "VALIDATED")


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
        if decision == "UNSURE":
            if rec["state"] == "VALIDATED":
                _move(c, record_id, "SUSPECTED_DUPLICATE")
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
            old = c.execute("""SELECT pg.id FROM pages pg JOIN records r ON r.id = pg.record_id
                               WHERE r.patient_id = ? AND pg.page_type = ? ORDER BY r.created_at DESC LIMIT 1""",
                            (patient_id, p["page_type"])).fetchone()
            if old:
                c.execute("UPDATE pages SET supersedes = ? WHERE id = ?", (old["id"], p["id"]))
        c.execute("UPDATE records SET patient_id = ?, visit_id = ? WHERE id = ?", (patient_id, visit_id, record_id))
        _move(c, record_id, "PATIENT_LINKED", note=decision)
        _move(c, record_id, "SAVED")
        _move(c, record_id, "SYNCED")       # serveur local = dossier central : rien d'autre à envoyer
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
            pages = []
            for p in c.execute("SELECT * FROM pages WHERE record_id = ? ORDER BY idx", (r["id"],)).fetchall():
                page = {"id": p["id"], "pageType": p["page_type"] or "unknown",
                        "imageSize": [p["image_w"] or 1654, p["image_h"] or 2339], "capturedAt": p["captured_at"],
                        "quality": {"ok": True}, "fields": _load_fields(p)}
                if p["view_path"]:
                    page["imageUrl"] = image_url(p["id"])
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
                visits[r["visit_id"]]["recordIds"].append(r["id"])
            if r["failure_reason"]:
                rec["failure"] = {"reason": r["failure_reason"], "at": r["failure_at"]}
            records[r["id"]] = rec
        return {"patients": patients, "visits": visits, "records": records, "busy": sorted(busy)}


def view_image(page_id: str) -> bytes | None:
    with db() as c:
        row = c.execute("SELECT view_path FROM pages WHERE id = ?", (page_id,)).fetchone()
    return read_encrypted(row["view_path"]) if row and row["view_path"] else None
