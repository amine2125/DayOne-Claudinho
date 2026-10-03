"""Module de liaison patiente anonyme (Multi-Criteria Record Linker).

Associe les visites successives d'une même femme au fil de sa grossesse,
sans JAMAIS stocker ni utiliser de données nominatives directes (Nom, CIN, Téléphone).
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PatientProfile:
    patient_id: str                # Identifiant pseudonyme interne (UUID)
    code_patiente: str | None      # Code figurant sur le registre (ex: 2026-823-001)
    age: int | None
    gestite: int | None
    parite: int | None
    groupe_sanguin: str | None
    rhesus: str | None
    records_count: int = 1
    created_at: float = 0.0


@dataclass
class MatchCandidate:
    profile: PatientProfile
    score: float                   # 0.0 à 1.0
    matching_criteria: list[str]
    confidence_level: str          # "HAUTE" | "MOYENNE" | "FAIBLE"


class PatientLinker:
    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = Path(__file__).resolve().parents[2] / "patients.db"
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
                CREATE TABLE IF NOT EXISTS patients (
                    patient_id TEXT PRIMARY KEY,
                    code_patiente TEXT,
                    age INTEGER,
                    gestite INTEGER,
                    parite INTEGER,
                    groupe_sanguin TEXT,
                    rhesus TEXT,
                    records_count INTEGER DEFAULT 1,
                    created_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS patient_visits (
                    visit_id TEXT PRIMARY KEY,
                    patient_id TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    visit_date TEXT,
                    gestational_age_sa REAL,
                    data_json TEXT NOT NULL,
                    linked_at REAL NOT NULL,
                    FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
                )
            """)
            conn.commit()

    def create_patient(self, code_patiente: str | None, age: int | None,
                       gestite: int | None, parite: int | None,
                       groupe_sanguin: str | None, rhesus: str | None) -> PatientProfile:
        import time
        patient_id = f"PAT-{uuid.uuid4().hex[:8].upper()}"
        now = time.time()
        profile = PatientProfile(
            patient_id=patient_id,
            code_patiente=code_patiente,
            age=age,
            gestite=gestite,
            parite=parite,
            groupe_sanguin=groupe_sanguin,
            rhesus=rhesus,
            records_count=1,
            created_at=now,
        )
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO patients (patient_id, code_patiente, age, gestite, parite,
                                     groupe_sanguin, rhesus, records_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (profile.patient_id, profile.code_patiente, profile.age, profile.gestite,
                  profile.parite, profile.groupe_sanguin, profile.rhesus, profile.records_count,
                  profile.created_at))
            conn.commit()
        return profile

    def find_matches(self, fields: dict) -> list[MatchCandidate]:
        """Recherche probabiliste des patientes candidates correspondant à un enregistrement."""
        code = fields.get("code_patiente")
        age = fields.get("age")
        gestite = fields.get("gestite")
        parite = fields.get("parite")
        groupe = fields.get("groupe_sanguin")
        rhesus = fields.get("rhesus")

        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM patients").fetchall()

        candidates: list[MatchCandidate] = []
        for r in rows:
            score = 0.0
            reasons = []

            # 1. Correspondance Code Fiche (Poids 0.50)
            if code and r["code_patiente"] and str(code).strip() == str(r["code_patiente"]).strip():
                score += 0.50
                reasons.append("Code fiche identique")

            # 2. Groupe sanguin & Rhésus (Poids 0.20)
            if groupe and r["groupe_sanguin"] and str(groupe).upper() == str(r["groupe_sanguin"]).upper():
                score += 0.10
                reasons.append("Groupe sanguin concordant")
            if rhesus and r["rhesus"] and str(rhesus).upper() == str(r["rhesus"]).upper():
                score += 0.10
                reasons.append("Rhésus concordant")

            # 3. Antécédents obstétricaux Gestité / Parité (Poids 0.15)
            if gestite is not None and r["gestite"] is not None:
                diff_g = abs(int(gestite) - int(r["gestite"]))
                if diff_g == 0:
                    score += 0.08
                    reasons.append("Gestité identique")
                elif diff_g == 1:
                    score += 0.04

            if parite is not None and r["parite"] is not None:
                diff_p = abs(int(parite) - int(r["parite"]))
                if diff_p == 0:
                    score += 0.07
                    reasons.append("Parité identique")

            # 4. Âge de la parturiente (Poids 0.15)
            if age is not None and r["age"] is not None:
                diff_a = abs(int(age) - int(r["age"]))
                if diff_a == 0:
                    score += 0.15
                    reasons.append("Âge identique")
                elif diff_a <= 1:
                    score += 0.10
                    reasons.append("Âge proche (±1 an)")

            if score >= 0.40:
                conf = "HAUTE" if score >= 0.75 else ("MOYENNE" if score >= 0.55 else "FAIBLE")
                prof = PatientProfile(
                    patient_id=r["patient_id"],
                    code_patiente=r["code_patiente"],
                    age=r["age"],
                    gestite=r["gestite"],
                    parite=r["parite"],
                    groupe_sanguin=r["groupe_sanguin"],
                    rhesus=r["rhesus"],
                    records_count=r["records_count"],
                    created_at=r["created_at"],
                )
                candidates.append(MatchCandidate(prof, round(score, 2), reasons, conf))

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:3]  # Retourne au maximum les 3 meilleures correspondances

    def link_record(self, patient_id: str, record_id: str, visit_data: dict) -> None:
        """Attache une visite clinique au profil patiente et incrémente le compteur de visites."""
        import time
        now = time.time()
        visit_id = f"VIS-{uuid.uuid4().hex[:8].upper()}"
        data_json = json.dumps(visit_data, ensure_ascii=False)
        date_val = str(visit_data.get("date_consultation") or "")
        sa_val = float(visit_data.get("age_gestationnel") or 0.0)

        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO patient_visits (visit_id, patient_id, record_id, visit_date,
                                           gestational_age_sa, data_json, linked_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (visit_id, patient_id, record_id, date_val, sa_val, data_json, now))
            conn.execute("""
                UPDATE patients SET records_count = records_count + 1 WHERE patient_id = ?
            """, (patient_id,))
            conn.commit()

    def get_patient_history(self, patient_id: str) -> list[dict]:
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM patient_visits WHERE patient_id = ? ORDER BY gestational_age_sa ASC, linked_at ASC
            """, (patient_id,)).fetchall()
            return [dict(r) for r in rows]
