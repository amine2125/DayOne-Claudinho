"""Gestionnaire de sessions multipages et renumérisation (Multi-Page Booklet Session Manager).

Conforme à la tâche #7 du cahier des charges DayOne :
  "Gérer les sessions multipages et la renumérisation : les pages d'un même registre
   forment un seul document ; si un registre est rephotographié, afficher le dossier
   existant et laisser la sage-femme choisir quoi mettre à jour."
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from contextlib import contextmanager

from app.clinical.alerts import ClinicalAlert, evaluate_clinical_risks
from app.patient_linking.linker import PatientLinker, PatientProfile
from app.pipeline import extract
from app.schemas.models import ExtractionResponse, FieldStatus


@dataclass
class FieldDiff:
    key: str
    old_value: any
    new_value: any
    status: str            # "IDENTICAL" | "MODIFIED" | "ADDED" | "REMOVED"
    old_confidence: float = 0.0
    new_confidence: float = 0.0


@dataclass
class PageScanRecord:
    page_id: str
    page_number: int | None
    scanned_at: float
    extracted_fields: dict
    records_count: int
    image_hash: str


@dataclass
class BookletSession:
    session_id: str
    midwife_id: str
    created_at: float
    updated_at: float
    patient_id: str | None = None
    pages: dict[int, PageScanRecord] = field(default_factory=dict)
    consolidated_profile: dict = field(default_factory=dict)
    consolidated_visits: list[dict] = field(default_factory=list)
    pending_conflicts: list[FieldDiff] = field(default_factory=list)


class BookletSessionManager:
    def __init__(self, db_path: str | Path | None = None, linker: PatientLinker | None = None):
        if db_path is None:
            db_path = Path(__file__).resolve().parents[2] / "patients.db"
        self.db_path = Path(db_path)
        self.linker = linker or PatientLinker(db_path=self.db_path)
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
                CREATE TABLE IF NOT EXISTS booklet_sessions (
                    session_id TEXT PRIMARY KEY,
                    midwife_id TEXT NOT NULL,
                    patient_id TEXT,
                    session_data_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            conn.commit()

    def start_session(self, midwife_id: str, session_id: str | None = None) -> BookletSession:
        sid = session_id or f"SESS-{uuid.uuid4().hex[:8].upper()}"
        now = time.time()
        sess = BookletSession(
            session_id=sid,
            midwife_id=midwife_id,
            created_at=now,
            updated_at=now,
        )
        self._save_session(sess)
        return sess

    def get_session(self, session_id: str) -> BookletSession | None:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM booklet_sessions WHERE session_id = ?", (session_id,)).fetchone()
            if not row:
                return None
            data = json.loads(row["session_data_json"])
            pages = {
                int(k): PageScanRecord(**v) for k, v in data.get("pages", {}).items()
            }
            conflicts = [FieldDiff(**c) for c in data.get("pending_conflicts", [])]
            return BookletSession(
                session_id=row["session_id"],
                midwife_id=row["midwife_id"],
                patient_id=row["patient_id"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                pages=pages,
                consolidated_profile=data.get("consolidated_profile", {}),
                consolidated_visits=data.get("consolidated_visits", []),
                pending_conflicts=conflicts,
            )

    def _save_session(self, sess: BookletSession) -> None:
        payload = {
            "pages": {k: asdict(v) for k, v in sess.pages.items()},
            "consolidated_profile": sess.consolidated_profile,
            "consolidated_visits": sess.consolidated_visits,
            "pending_conflicts": [asdict(c) for c in sess.pending_conflicts],
        }
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO booklet_sessions (session_id, midwife_id, patient_id, session_data_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    patient_id = excluded.patient_id,
                    session_data_json = excluded.session_data_json,
                    updated_at = excluded.updated_at
            """, (sess.session_id, sess.midwife_id, sess.patient_id,
                  json.dumps(payload, ensure_ascii=False), sess.created_at, sess.updated_at))
            conn.commit()

    def process_page_scan(
        self,
        session_id: str,
        image_bytes: bytes,
        page_number: int | None = None,
        use_vlm: bool = False,
    ) -> dict:
        """Numérise une page du carnet de santé et gère le diff en cas de renumérisation."""
        import hashlib
        sess = self.get_session(session_id)
        if not sess:
            sess = self.start_session("SF-DEFAULT", session_id=session_id)

        # Extraction OCR locale
        resp = extract(image_bytes, use_vlm=use_vlm, debug=False)
        img_hash = hashlib.sha256(image_bytes).hexdigest()

        # Inférer le numéro de page s'il n'est pas spécifié
        if page_number is None:
            page_number = self._infer_page_type(resp)

        now = time.time()
        extracted_first = {}
        all_visits = []
        for r in resp.records:
            fields_clean = {k: v.value for k, v in r.fields.items() if v.value is not None}
            if fields_clean:
                all_visits.append(fields_clean)
        if all_visits:
            extracted_first = all_visits[0]

        # Détecter si la page a déjà été scannée (Renumérisation / Rescan)
        diffs: list[FieldDiff] = []
        is_rescan = page_number in sess.pages
        if is_rescan:
            old_scan = sess.pages[page_number]
            diffs = self._compute_diff(old_scan.extracted_fields, extracted_first)

        # Mettre à jour l'enregistrement de la page
        new_scan = PageScanRecord(
            page_id=f"PG-{uuid.uuid4().hex[:6].upper()}",
            page_number=page_number,
            scanned_at=now,
            extracted_fields=extracted_first,
            records_count=len(resp.records),
            image_hash=img_hash,
        )
        sess.pages[page_number] = new_scan
        sess.updated_at = now
        sess.pending_conflicts = [d for d in diffs if d.status == "MODIFIED"]

        # Consolider dans le profil
        self._consolidate_data(sess)
        self._save_session(sess)

        # Évaluer les alertes cliniques sur l'ensemble du carnet
        alerts = self._check_all_alerts(sess)

        return {
            "session_id": sess.session_id,
            "page_number": page_number,
            "is_rescan": is_rescan,
            "diffs": [asdict(d) for d in diffs],
            "extracted_count": len(resp.records),
            "consolidated_fields_count": len(sess.consolidated_profile),
            "total_visits_in_session": len(sess.consolidated_visits),
            "clinical_alerts": [asdict(a) for a in alerts],
        }

    def resolve_diff_field(self, session_id: str, field_key: str, chosen_value: any) -> None:
        """Permet à la sage-femme de choisir quelle valeur conserver lors d'une renumérisation."""
        sess = self.get_session(session_id)
        if not sess:
            return
        sess.consolidated_profile[field_key] = chosen_value
        sess.pending_conflicts = [d for d in sess.pending_conflicts if d.key != field_key]
        sess.updated_at = time.time()
        self._save_session(sess)

    def finalize_booklet(self, session_id: str) -> dict:
        """Clôture la session du carnet, lie ou crée la patiente et synchronise toutes les visites."""
        sess = self.get_session(session_id)
        if not sess:
            raise ValueError("Session introuvable")

        prof = sess.consolidated_profile

        # Rapprochement patiente automatique ou création
        matches = self.linker.find_matches(prof)
        if matches and matches[0].score >= 0.70:
            patient_id = matches[0].profile.patient_id
        else:
            p = self.linker.create_patient(
                code_patiente=prof.get("code_patiente"),
                age=prof.get("age"),
                gestite=prof.get("gestite"),
                parite=prof.get("parite"),
                groupe_sanguin=prof.get("groupe_sanguin"),
                rhesus=prof.get("rhesus"),
            )
            patient_id = p.patient_id

        sess.patient_id = patient_id

        # Enregistrer toutes les visites consolidées
        for idx, visit in enumerate(sess.consolidated_visits):
            self.linker.link_record(patient_id, f"{sess.session_id}_v{idx}", visit)

        sess.updated_at = time.time()
        self._save_session(sess)

        # Rapport complet
        history = self.linker.get_patient_history(patient_id)
        alerts = self._check_all_alerts(sess)

        return {
            "status": "COMPLETED",
            "patient_id": patient_id,
            "session_id": session_id,
            "pages_scanned": sorted(list(sess.pages.keys())),
            "total_visits_linked": len(sess.consolidated_visits),
            "longitudinal_history_count": len(history),
            "clinical_alerts": [asdict(a) for a in alerts],
            "fhir_bundle": self.export_fhir_bundle(sess),
        }

    def export_fhir_bundle(self, sess: BookletSession) -> dict:
        """Génère un Bundle FHIR standard (HL7 FHIR R4) pour interopérabilité hospitalière."""
        prof = sess.consolidated_profile
        patient_ref = f"Patient/{sess.patient_id or 'UNKNOWN'}"
        entries = []

        # Ressource FHIR Patient (anonymisée)
        entries.append({
            "resource": {
                "resourceType": "Patient",
                "id": sess.patient_id or "PATIENT-ANON",
                "identifier": [{"system": "urn:dispensaire:code_patiente", "value": prof.get("code_patiente") or ""}],
                "gender": "female",
            }
        })

        # Observations FHIR pour chaque visite prénatale
        for idx, v in enumerate(sess.consolidated_visits):
            obs_entry = {
                "resource": {
                    "resourceType": "Encounter",
                    "id": f"enc-{idx+1}",
                    "status": "finished",
                    "subject": {"reference": patient_ref},
                    "period": {"start": v.get("date_consultation", "")},
                }
            }
            entries.append(obs_entry)

        return {
            "resourceType": "Bundle",
            "type": "collection",
            "id": f"bundle-{sess.session_id}",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "entry": entries,
        }

    def _infer_page_type(self, resp: ExtractionResponse) -> int:
        """Détermine intelligemment le numéro de page du carnet de santé selon les champs reconnus."""
        keys = set()
        for r in resp.records:
            keys.update(r.fields.keys())

        # Page 3 : Tableau de consultations prénatales multiples
        if len(resp.records) > 1 or {"age_gestationnel", "hauteur_uterine_cm", "bcf_bpm"}.intersection(keys):
            return 3
        # Page 4 : Accouchement
        if "mode_accouchement" in keys or "sexe_nouveau_ne" in keys:
            return 4
        # Page 5 : Postpartum / Nouveau-né
        if "allaitement" in keys or "perimetre_cranien" in keys or "poids_naissance" in keys:
            return 5
        # Page 2 : Antécédents médicaux et obstétricaux
        if {"gestite", "parite", "groupe_sanguin", "hta_chronique", "diabete"}.intersection(keys):
            return 2
        # Page 1 : Couverture / Code fiche
        if "code_patiente" in keys or "age" in keys:
            return 1
        return 1

    def _compute_diff(self, old_data: dict, new_data: dict) -> list[FieldDiff]:
        diffs = []
        all_keys = set(old_data.keys()).union(set(new_data.keys()))
        for k in all_keys:
            old_val = old_data.get(k)
            new_val = new_data.get(k)
            if old_val == new_val:
                status = "IDENTICAL"
            elif old_val is None:
                status = "ADDED"
            elif new_val is None:
                status = "REMOVED"
            else:
                status = "MODIFIED"
            diffs.append(FieldDiff(key=k, old_value=old_val, new_value=new_val, status=status))
        return diffs

    def _consolidate_data(self, sess: BookletSession) -> None:
        """Fusionne les données des différentes pages du livret dans le dossier unique."""
        profile = {}
        visits = []

        # Parcourir les pages dans l'ordre croissant 1 à 8
        for pnum in sorted(sess.pages.keys()):
            p_data = sess.pages[pnum].extracted_fields
            # 1. Enrichir le profil statique
            for k in ("code_patiente", "age", "gestite", "parite", "groupe_sanguin", "rhesus",
                      "education_level", "consanguinite", "hta_chronique", "diabete",
                      "avortements", "enfants_vivants", "cesarienne_anterieure", "imc"):
                if k in p_data and p_data[k] is not None:
                    profile[k] = p_data[k]

            # 2. Si c'est la page 3 ou s'il y a des visites prénatales
            if pnum == 3:
                # Ajouter les visites détectées
                if p_data:
                    visits.append(p_data)

            # 3. Éléments d'accouchement / nouveau-né
            for k in ("mode_accouchement", "sexe_nouveau_ne", "poids_naissance",
                      "perimetre_cranien", "allaitement", "transfert"):
                if k in p_data and p_data[k] is not None:
                    profile[k] = p_data[k]

        sess.consolidated_profile.update(profile)
        if visits and not sess.consolidated_visits:
            sess.consolidated_visits = visits

    def _check_all_alerts(self, sess: BookletSession) -> list[ClinicalAlert]:
        alerts = []
        alerts.extend(evaluate_clinical_risks(sess.consolidated_profile))
        for v in sess.consolidated_visits:
            alerts.extend(evaluate_clinical_risks(v))
        # Déduplication
        seen = set()
        deduped = []
        for a in alerts:
            if a.code not in seen:
                seen.add(a.code)
                deduped.append(a)
        return deduped
