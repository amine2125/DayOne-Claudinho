"""Module d'analyse épidémiologique et tableau de bord de santé publique (Zero-PII Analytics).

Conforme au bonus du cahier des charges DayOne :
  "Tableau de bord simple d'agrégats anonymisés (tension, température, VIH/syphilis/hépatite C)
   illustrant l'usage épidémiologique des données."
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from contextlib import contextmanager

from app.patient_linking.linker import PatientLinker


class EpidemiologyDashboard:
    def __init__(self, db_path: str | Path | None = None, linker: PatientLinker | None = None):
        if db_path is None:
            db_path = Path(__file__).resolve().parents[2] / "patients.db"
        self.db_path = Path(db_path)
        self.linker = linker or PatientLinker(db_path=self.db_path)

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def compute_summary_kpis(self) -> dict:
        """Calcule les agrégats de santé maternelle et périnatale pour la région/province."""
        with self._get_connection() as conn:
            # 1. Nombre total de patientes
            row_p = conn.execute("SELECT COUNT(*) as cnt FROM patients").fetchone()
            total_patients = row_p["cnt"] if row_p else 0

            # 2. Nombre total de consultations
            row_v = conn.execute("SELECT COUNT(*) as cnt FROM patient_visits").fetchone()
            total_visits = row_v["cnt"] if row_v else 0

            # 3. Récupérer toutes les données de visites
            visit_rows = conn.execute("SELECT data_json FROM patient_visits").fetchall()
            patient_rows = conn.execute("SELECT age, gestite, parite, groupe_sanguin, rhesus FROM patients").fetchall()

        # Dépouillement des indicateurs cliniques
        hta_count = 0
        hta_total = 0
        anemia_count = 0
        anemia_total = 0
        vih_pos = 0
        syphilis_pos = 0
        hepc_pos = 0
        serology_total = 0
        cesarean_count = 0
        vaginal_count = 0
        breastfeeding_count = 0
        delivery_total = 0
        transfer_count = 0

        term_preterm = 0
        term_normal = 0
        term_post = 0

        for r in visit_rows:
            try:
                v = json.loads(r["data_json"])
            except Exception:
                continue

            # HTA
            sys_val = v.get("tension_systolique")
            dia_val = v.get("tension_diastolique")
            if sys_val is not None and dia_val is not None:
                hta_total += 1
                try:
                    if float(sys_val) >= 140 or float(dia_val) >= 90:
                        hta_count += 1
                except (ValueError, TypeError):
                    pass

            # Anémie (Hb < 11 g/dL)
            hb_val = v.get("hemoglobine")
            if hb_val is not None:
                anemia_total += 1
                try:
                    if float(hb_val) < 11.0:
                        anemia_count += 1
                except (ValueError, TypeError):
                    pass

            # Sérologies
            vih = str(v.get("vih") or "").upper()
            syph = str(v.get("syphilis") or "").upper()
            hepc = str(v.get("hepatite_c") or "").upper()
            if vih in ("POSITIF", "POS", "+"): vih_pos += 1
            if syph in ("POSITIF", "POS", "+"): syphilis_pos += 1
            if hepc in ("POSITIF", "POS", "+"): hepc_pos += 1
            if vih or syph or hepc: serology_total += 1

            # Mode accouchement
            mode = str(v.get("mode_accouchement") or "").upper()
            if mode == "CESARIENNE":
                cesarean_count += 1
                delivery_total += 1
            elif mode in ("VOIE_BASSE", "EUTOCIQUE", "NORMAL"):
                vaginal_count += 1
                delivery_total += 1

            # Allaitement
            allait = str(v.get("allaitement") or "").upper()
            if allait in ("OUI", "1", "VRAI"):
                breastfeeding_count += 1

            # Transfert maternité de référence
            transf = str(v.get("transfert") or "").upper()
            if transf in ("OUI", "1", "VRAI"):
                transfer_count += 1

            # Âge gestationnel
            sa = v.get("age_gestationnel")
            if sa is not None:
                try:
                    sa_f = float(sa)
                    if sa_f < 37:
                        term_preterm += 1
                    elif sa_f <= 41:
                        term_normal += 1
                    else:
                        term_post += 1
                except (ValueError, TypeError):
                    pass

        # Calcul des pourcentages
        def _pct(num: int, denom: int) -> float:
            return round((num / denom) * 100, 1) if denom > 0 else 0.0

        return {
            "overview": {
                "total_patients": total_patients,
                "total_visits": total_visits,
                "visits_per_patient": round(total_visits / max(total_patients, 1), 1),
            },
            "maternal_health": {
                "hta_prevalence_pct": _pct(hta_count, hta_total),
                "hta_cases": hta_count,
                "hta_screened": hta_total,
                "anemia_prevalence_pct": _pct(anemia_count, anemia_total),
                "anemia_cases": anemia_count,
                "anemia_screened": anemia_total,
                "transfers_count": transfer_count,
            },
            "infectious_screening": {
                "vih_positive_cases": vih_pos,
                "vih_positivity_pct": _pct(vih_pos, serology_total),
                "syphilis_positive_cases": syphilis_pos,
                "syphilis_positivity_pct": _pct(syphilis_pos, serology_total),
                "hepatitis_c_positive_cases": hepc_pos,
                "hepatitis_c_positivity_pct": _pct(hepc_pos, serology_total),
                "total_screened": serology_total,
            },
            "delivery_and_birth": {
                "cesarean_rate_pct": _pct(cesarean_count, delivery_total),
                "vaginal_delivery_rate_pct": _pct(vaginal_count, delivery_total),
                "total_recorded_deliveries": delivery_total,
                "early_breastfeeding_pct": _pct(breastfeeding_count, max(delivery_total, 1)),
                "gestational_age_distribution": {
                    "preterm_under_37_sa": term_preterm,
                    "term_37_to_41_sa": term_normal,
                    "postterm_over_41_sa": term_post,
                },
            },
        }
