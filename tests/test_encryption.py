import tempfile
from pathlib import Path
from app.privacy.encryption import LocalEncryptionManager
from app.offline.queue import OfflineQueue, RecordState


def test_encryption_manager():
    with tempfile.TemporaryDirectory() as tmpdir:
        key_file = Path(tmpdir) / ".key"
        mgr = LocalEncryptionManager(key_path=key_file)
        
        # Test bytes encryption
        sample_img = b"\xff\xd8\xff\xe0\x00\x10JFIFfakeimagecontent12345"
        enc = mgr.encrypt_bytes(sample_img)
        assert enc != sample_img
        dec = mgr.decrypt_bytes(enc)
        assert dec == sample_img

        # Test text encryption
        sample_text = '{"age": 28, "ta": "120/80"}'
        enc_txt = mgr.encrypt_text(sample_text)
        assert enc_txt != sample_text
        dec_txt = mgr.decrypt_text(enc_txt)
        assert dec_txt == sample_text


def test_offline_queue_encryption():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "offline.db"
        img_dir = Path(tmpdir) / "captures"
        q = OfflineQueue(db_path=db_path)

        fake_img = b"SAMPLE_SCAN_CONTENT_OFFLINE"
        item = q.enqueue_capture("SF-01", fake_img, image_dir=img_dir)

        # Vérifier que le fichier sur disque est chiffré
        disk_bytes = Path(item.image_path).read_bytes()
        assert disk_bytes != fake_img

        # Vérifier la récupération déchiffrée
        decrypted = q.get_image_bytes(item.id_uuid)
        assert decrypted == fake_img

        # Test transition avec données chiffrées au repos
        data = {"tension_systolique": 120, "tension_diastolique": 80}
        q.transition_state(item.id_uuid, RecordState.VALIDATED, extracted_data=data, patient_id="PAT-TEST1")
        
        # Vérifier que l'item relu restitue les données déchiffrées
        fetched = q.get_item(item.id_uuid)
        assert fetched is not None
        assert fetched.state == RecordState.VALIDATED
        assert "tension_systolique" in fetched.extracted_data_json
