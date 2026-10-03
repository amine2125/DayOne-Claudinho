import tempfile
from pathlib import Path

import pytest

from app.offline.queue import OfflineQueue, RecordState
from app.patient_linking.linker import PatientLinker


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def test_offline_queue_lifecycle(tmp_dir):
    db_path = tmp_dir / "test_queue.db"
    queue = OfflineQueue(db_path)

    # 1. Enqueue capture
    fake_img = b"fake_jpeg_image_content_12345"
    item = queue.enqueue_capture("MW-042", fake_img, image_dir=tmp_dir / "captures")
    assert item.state == RecordState.CAPTURED
    assert item.midwife_id == "MW-042"

    # 2. Transition vers AI_PROCESSED
    extracted = {"poids_kg": 68.0, "tension_systolique": 120}
    queue.transition_state(item.id_uuid, RecordState.AI_PROCESSED, extracted_data=extracted)

    updated = queue.get_item(item.id_uuid)
    assert updated.state == RecordState.AI_PROCESSED
    assert "68.0" in updated.extracted_data_json

    # 3. Transition vers VALIDATED puis SYNCED
    queue.transition_state(item.id_uuid, RecordState.VALIDATED)
    synced, failed = queue.sync_with_server(online_check=True)
    assert synced == 1
    assert failed == 0

    synced_item = queue.get_item(item.id_uuid)
    assert synced_item.state == RecordState.SYNCED


def test_patient_linker_matching(tmp_dir):
    db_path = tmp_dir / "test_patients.db"
    linker = PatientLinker(db_path)

    # Créer une patiente initiale
    p1 = linker.create_patient(
        code_patiente="2026-823-001",
        age=31,
        gestite=3,
        parite=1,
        groupe_sanguin="AB",
        rhesus="NEGATIF",
    )

    # Nouvelle visite avec même code patiente et mêmes constantes
    new_visit = {
        "code_patiente": "2026-823-001",
        "age": 31,
        "gestite": 3,
        "parite": 1,
        "groupe_sanguin": "AB",
        "rhesus": "NEGATIF",
        "date_consultation": "2026-02-15",
        "age_gestationnel": 34.0,
    }

    matches = linker.find_matches(new_visit)
    assert len(matches) >= 1
    best = matches[0]
    assert best.profile.patient_id == p1.patient_id
    assert best.score >= 0.85
    assert best.confidence_level == "HAUTE"
    assert "Code fiche identique" in best.matching_criteria

    # Lier la visite
    linker.link_record(p1.patient_id, "REC-999", new_visit)
    history = linker.get_patient_history(p1.patient_id)
    assert len(history) == 1
    assert history[0]["gestational_age_sa"] == 34.0
