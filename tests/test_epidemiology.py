import tempfile
from pathlib import Path
from app.analytics.dashboard import EpidemiologyDashboard
from app.patient_linking.linker import PatientLinker


def test_epidemiology_kpis():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "patients.db"
        linker = PatientLinker(db_path=db_path)
        dash = EpidemiologyDashboard(db_path=db_path, linker=linker)

        # Ajouter une patiente
        p1 = linker.create_patient("2026-F1", 28, 2, 1, "O", "POSITIF")
        linker.link_record(p1.patient_id, "V1", {
            "tension_systolique": 150,
            "tension_diastolique": 95,
            "hemoglobine": 9.5,
            "vih": "NEGATIF",
            "syphilis": "POSITIF",
            "age_gestationnel": 34.0,
            "mode_accouchement": "VOIE_BASSE",
            "allaitement": "OUI",
        })

        p2 = linker.create_patient("2026-F2", 32, 1, 0, "A", "POSITIF")
        linker.link_record(p2.patient_id, "V2", {
            "tension_systolique": 115,
            "tension_diastolique": 75,
            "hemoglobine": 12.2,
            "vih": "NEGATIF",
            "syphilis": "NEGATIF",
            "age_gestationnel": 39.0,
            "mode_accouchement": "CESARIENNE",
            "allaitement": "OUI",
        })

        kpis = dash.compute_summary_kpis()
        assert kpis["overview"]["total_patients"] == 2
        assert kpis["overview"]["total_visits"] == 2
        assert kpis["maternal_health"]["hta_cases"] == 1
        assert kpis["maternal_health"]["hta_prevalence_pct"] == 50.0
        assert kpis["maternal_health"]["anemia_cases"] == 1
        assert kpis["infectious_screening"]["syphilis_positive_cases"] == 1
        assert kpis["delivery_and_birth"]["cesarean_rate_pct"] == 50.0
