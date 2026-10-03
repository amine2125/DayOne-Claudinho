import tempfile
from pathlib import Path
from app.messaging.dialogue import WhatsAppDialogueManager, DialogueState
from app.offline.queue import OfflineQueue
from app.patient_linking.linker import PatientLinker


def test_dialogue_manual_entry():
    with tempfile.TemporaryDirectory() as tmpdir:
        q = OfflineQueue(db_path=Path(tmpdir) / "offline.db")
        l = PatientLinker(db_path=Path(tmpdir) / "patients.db")
        dm = WhatsAppDialogueManager(queue=q, linker=l)

        # 1. Demande de passage en mode manuel
        r1 = dm.handle_text_message("SF-01", "manuel")
        assert "Mode Saisie Manuelle" in r1["reply"]

        # 2. Envoi des données manuelles
        r2 = dm.handle_text_message("SF-01", "Patiente 24 ans, G2P1, 32 SA, TA 120/80, 65 kg, BCF 142, Groupe A+")
        assert "enregistré" in r2["reply"].lower()
        assert "PAT-" in r2["patient_id"]

        # Vérifier dans le linker
        history = l.get_patient_history(r2["patient_id"])
        assert len(history) == 1


def test_dialogue_correction():
    with tempfile.TemporaryDirectory() as tmpdir:
        q = OfflineQueue(db_path=Path(tmpdir) / "offline.db")
        l = PatientLinker(db_path=Path(tmpdir) / "patients.db")
        dm = WhatsAppDialogueManager(queue=q, linker=l)
        sess = dm.get_session("SF-01")
        sess.extracted_records = [{"tension_systolique": 110, "tension_diastolique": 70}]

        # Corriger la tension
        r = dm.handle_text_message("SF-01", "TA 140/90")
        assert "140/90 mmHg" in r["reply"]
        assert sess.extracted_records[0]["tension_systolique"] == 140
        assert sess.extracted_records[0]["tension_diastolique"] == 90

        # Corriger le poids
        r_w = dm.handle_text_message("SF-01", "poids 72")
        assert "72 kg" in r_w["reply"]
        assert sess.extracted_records[0]["poids_kg"] == 72.0


def test_dialogue_cancel_retake():
    with tempfile.TemporaryDirectory() as tmpdir:
        q = OfflineQueue(db_path=Path(tmpdir) / "offline.db")
        l = PatientLinker(db_path=Path(tmpdir) / "patients.db")
        dm = WhatsAppDialogueManager(queue=q, linker=l)
        sess = dm.get_session("SF-01")
        sess.state = DialogueState.WAITING_CONFIRMATION

        r = dm.handle_text_message("SF-01", "reprendre")
        assert "annulée" in r["reply"]
        assert sess.state == DialogueState.IDLE
