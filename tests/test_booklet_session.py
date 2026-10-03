import tempfile
from pathlib import Path
from app.patient_linking.linker import PatientLinker
from app.sessions.booklet_session import BookletSessionManager, PageScanRecord


def test_booklet_session_flow():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_patients.db"
        linker = PatientLinker(db_path=db_path)
        mgr = BookletSessionManager(db_path=db_path, linker=linker)

        sess = mgr.start_session("SF-TEST")
        assert sess.session_id.startswith("SESS-")

        # Simuler l'ajout de la page 2 (Antécédents)
        p2_data = {
            "code_patiente": "2026-F01",
            "age": 27,
            "gestite": 3,
            "parite": 2,
            "groupe_sanguin": "O",
            "rhesus": "POSITIF",
        }
        sess.pages[2] = PageScanRecord(
            page_id="P2", page_number=2, scanned_at=1.0,
            extracted_fields=p2_data, records_count=1, image_hash="hash1"
        )
        mgr._consolidate_data(sess)
        mgr._save_session(sess)

        # Simuler l'ajout de la page 3 (Visite prénatale)
        p3_data = {
            "date_consultation": "2026-03-15",
            "age_gestationnel": 28.0,
            "tension_systolique": 120,
            "tension_diastolique": 80,
            "hauteur_uterine_cm": 27.0,
            "bcf_bpm": 140,
        }
        sess.pages[3] = PageScanRecord(
            page_id="P3", page_number=3, scanned_at=2.0,
            extracted_fields=p3_data, records_count=1, image_hash="hash2"
        )
        mgr._consolidate_data(sess)
        mgr._save_session(sess)

        # Clôture du livret
        res = mgr.finalize_booklet(sess.session_id)
        assert res["status"] == "COMPLETED"
        assert res["patient_id"].startswith("PAT-")
        assert res["total_visits_linked"] >= 1

        # Vérifier que l'historique longitudinal est bien disponible dans la DB
        history = linker.get_patient_history(res["patient_id"])
        assert len(history) >= 1

        # Vérifier l'export FHIR
        assert "fhir_bundle" in res
        assert res["fhir_bundle"]["resourceType"] == "Bundle"
