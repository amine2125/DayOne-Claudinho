"""File d'attente hors-ligne (Offline Queue) et gestionnaire de cycle de vie (FSM).

Permet à l'application de fonctionner à 100% sans connexion Internet dans les dispensaires ruraux.
Gère l'intégralité des états prescrits par le cahier des charges DayOne :
  CAPTURED -> PENDING_AI -> AI_PROCESSED -> NEEDS_REVIEW -> VALIDATED -> PATIENT_MATCHED -> REGISTERED -> SYNCED
  + États d'échec & alertes : FAILED_PROCESSING, FAILED_SYNC, SUSPECTED_DUPLICATE, MANUAL_REVIEW_REQUIRED.

Tous les fichiers images et données JSON locales sont chiffrés au repos via LocalEncryptionManager.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from contextlib import contextmanager

from app.privacy.encryption import crypto_manager


class RecordState(str, Enum):
    CAPTURED = "CAPTURED"
    PENDING_AI = "PENDING_AI"
    AI_PROCESSED = "AI_PROCESSED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    VALIDATED = "VALIDATED"
    PATIENT_MATCHED = "PATIENT_MATCHED"
    REGISTERED = "REGISTERED"
    SYNCED = "SYNCED"
    FAILED_PROCESSING = "FAILED_PROCESSING"
    FAILED_SYNC = "FAILED_SYNC"
    SUSPECTED_DUPLICATE = "SUSPECTED_DUPLICATE"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


@dataclass
class QueueItem:
    id_uuid: str
    midwife_id: str
    state: RecordState
    image_hash_sha256: str
    image_path: str
    extracted_data_json: str | None
    created_at: float
    updated_at: float
    retry_count: int = 0
    patient_id: str | None = None


class OfflineQueue:
    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = Path(__file__).resolve().parents[2] / "offline_records.db"
        self.db_path = Path(db_path)
        self._init_db()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS queue_captures (
                    id_uuid TEXT PRIMARY KEY,
                    midwife_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    image_hash_sha256 TEXT NOT NULL,
                    image_path TEXT NOT NULL,
                    extracted_data_json TEXT,
                    patient_id TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    retry_count INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    action_id TEXT PRIMARY KEY,
                    record_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    details_json TEXT,
                    timestamp REAL NOT NULL
                )
            """)
            conn.commit()

    def enqueue_capture(self, midwife_id: str, image_bytes: bytes, image_dir: Path | None = None) -> QueueItem:
        """Enregistre une nouvelle capture photo chiffrée en mode hors-ligne."""
        img_hash = hashlib.sha256(image_bytes).hexdigest()
        item_id = str(uuid.uuid4())
        now = time.time()

        if image_dir is None:
            image_dir = self.db_path.parent / "offline_captures"
        image_dir.mkdir(parents=True, exist_ok=True)
        img_path = image_dir / f"{item_id}.enc"

        # Chiffrement AES-GCM / Fernet de l'image au repos
        encrypted_bytes = crypto_manager.encrypt_bytes(image_bytes)
        img_path.write_bytes(encrypted_bytes)

        # Vérification anti-doublon immédiate
        state = RecordState.CAPTURED
        with self._get_connection() as conn:
            existing = conn.execute(
                "SELECT id_uuid FROM queue_captures WHERE image_hash_sha256 = ? LIMIT 1",
                (img_hash,),
            ).fetchone()
            if existing:
                state = RecordState.SUSPECTED_DUPLICATE

            item = QueueItem(
                id_uuid=item_id,
                midwife_id=midwife_id,
                state=state,
                image_hash_sha256=img_hash,
                image_path=str(img_path),
                extracted_data_json=None,
                created_at=now,
                updated_at=now,
            )

            conn.execute("""
                INSERT INTO queue_captures (id_uuid, midwife_id, state, image_hash_sha256,
                                           image_path, extracted_data_json, patient_id,
                                           created_at, updated_at, retry_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (item.id_uuid, item.midwife_id, item.state.value, item.image_hash_sha256,
                  item.image_path, item.extracted_data_json, item.patient_id,
                  item.created_at, item.updated_at, item.retry_count))
            self._log_audit(conn, item_id, "CAPTURE_ENQUEUED_ENCRYPTED", {
                "hash": img_hash,
                "duplicate": bool(existing),
            })
            conn.commit()

        return item

    def get_image_bytes(self, item_id: str) -> bytes | None:
        """Récupère et déchiffre l'image d'origine pour consultation autorisée."""
        item = self.get_item(item_id)
        if not item or not Path(item.image_path).exists():
            return None
        raw_cipher = Path(item.image_path).read_bytes()
        return crypto_manager.decrypt_bytes(raw_cipher)

    def transition_state(self, item_id: str, new_state: RecordState,
                         extracted_data: dict | list | None = None,
                         patient_id: str | None = None) -> None:
        """Fait progresser l'état dans la machine à états finis FSM."""
        now = time.time()
        encrypted_json = None
        if extracted_data is not None:
            plain_json = json.dumps(extracted_data, ensure_ascii=False)
            encrypted_json = crypto_manager.encrypt_text(plain_json)

        with self._get_connection() as conn:
            if encrypted_json and patient_id:
                conn.execute("""
                    UPDATE queue_captures
                    SET state = ?, extracted_data_json = ?, patient_id = ?, updated_at = ?
                    WHERE id_uuid = ?
                """, (new_state.value, encrypted_json, patient_id, now, item_id))
            elif encrypted_json:
                conn.execute("""
                    UPDATE queue_captures
                    SET state = ?, extracted_data_json = ?, updated_at = ?
                    WHERE id_uuid = ?
                """, (new_state.value, encrypted_json, now, item_id))
            elif patient_id:
                conn.execute("""
                    UPDATE queue_captures
                    SET state = ?, patient_id = ?, updated_at = ?
                    WHERE id_uuid = ?
                """, (new_state.value, patient_id, now, item_id))
            else:
                conn.execute("""
                    UPDATE queue_captures
                    SET state = ?, updated_at = ?
                    WHERE id_uuid = ?
                """, (new_state.value, now, item_id))

            self._log_audit(conn, item_id, f"TRANSITION_{new_state.value}", {"patient_id": patient_id})
            conn.commit()

    def get_pending_items(self, state: RecordState = RecordState.PENDING_AI) -> list[QueueItem]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM queue_captures WHERE state = ? ORDER BY created_at ASC",
                                (state.value,)).fetchall()
            return [self._row_to_item(r) for r in rows]

    def get_all_items(self, limit: int = 50) -> list[QueueItem]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM queue_captures ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return [self._row_to_item(r) for r in rows]

    def get_item(self, item_id: str) -> QueueItem | None:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM queue_captures WHERE id_uuid = ?", (item_id,)).fetchone()
            return self._row_to_item(row) if row else None

    def sync_with_server(self, online_check: bool = True) -> tuple[int, int]:
        """Simule la synchronisation dès que la connectivité réseau est rétablie."""
        if not online_check:
            return 0, 0

        synced_count, failed_count = 0, 0
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM queue_captures
                WHERE state IN ('REGISTERED', 'PATIENT_MATCHED', 'VALIDATED')
            """).fetchall()

            for r in rows:
                item_id = r["id_uuid"]
                try:
                    now = time.time()
                    conn.execute("UPDATE queue_captures SET state = ?, updated_at = ? WHERE id_uuid = ?",
                                 (RecordState.SYNCED.value, now, item_id))
                    self._log_audit(conn, item_id, "SYNC_SUCCESS", {"server": "central_cloud_moh"})
                    synced_count += 1
                except Exception:
                    conn.execute("UPDATE queue_captures SET state = ?, retry_count = retry_count + 1 WHERE id_uuid = ?",
                                 (RecordState.FAILED_SYNC.value, item_id))
                    failed_count += 1
            conn.commit()
        return synced_count, failed_count

    def _log_audit(self, conn: sqlite3.Connection, record_id: str, action: str, details: dict) -> None:
        conn.execute("""
            INSERT INTO audit_log (action_id, record_id, action_type, details_json, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (str(uuid.uuid4()), record_id, action, json.dumps(details), time.time()))

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> QueueItem:
        raw_json = row["extracted_data_json"]
        decrypted_json = crypto_manager.decrypt_text(raw_json) if raw_json else None
        return QueueItem(
            id_uuid=row["id_uuid"],
            midwife_id=row["midwife_id"],
            state=RecordState(row["state"]),
            image_hash_sha256=row["image_hash_sha256"],
            image_path=row["image_path"],
            extracted_data_json=decrypted_json,
            patient_id=row["patient_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            retry_count=row["retry_count"],
        )
