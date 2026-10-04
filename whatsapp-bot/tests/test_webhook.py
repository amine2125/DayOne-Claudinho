"""Unit and integration tests for WhatsApp Webhook bot."""

import hashlib
import hmac
import json
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from app.config import get_settings
from app.main import app
from app.processor import is_duplicate_message, process_message
from app.security import mask_phone
from app.whatsapp import MAX_TEXT_LENGTH, split_message


@pytest.fixture(autouse=True)
def setup_test_settings(monkeypatch):
    """Setup safe test settings."""
    monkeypatch.setenv("WHATSAPP_TOKEN", "test_meta_token")
    monkeypatch.setenv("PHONE_NUMBER_ID", "123456789")
    monkeypatch.setenv("APP_SECRET", "test_app_secret")
    monkeypatch.setenv("VERIFY_TOKEN", "test_verify_token")
    monkeypatch.setenv("DAYONE_API_URL", "http://test-api")
    get_settings.cache_clear()


def make_signature(body: bytes, secret: str = "test_app_secret") -> str:
    """Generate X-Hub-Signature-256 header."""
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def test_get_webhook_verification_success():
    """Verify that Meta webhook challenge passes with correct token."""
    client = TestClient(app)
    response = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "test_verify_token",
            "hub.challenge": "1158201444",
        },
    )
    assert response.status_code == 200
    assert response.text == "1158201444"


def test_get_webhook_verification_failure():
    """Verify that Meta webhook fails when token is incorrect."""
    client = TestClient(app)
    response = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong_token",
            "hub.challenge": "1158201444",
        },
    )
    assert response.status_code == 403


def test_post_webhook_invalid_signature():
    """Verify that POST requests with missing or bad signatures are rejected (401)."""
    client = TestClient(app)
    payload = json.dumps({"entry": []}).encode("utf-8")

    # Sans header
    res_no_header = client.post("/webhook", content=payload)
    assert res_no_header.status_code == 401

    # Avec fausse signature
    res_bad_sig = client.post(
        "/webhook",
        content=payload,
        headers={"X-Hub-Signature-256": "sha256=0000000000000000000000000000000000000000000000000000000000000000"},
    )
    assert res_bad_sig.status_code == 401


def test_post_webhook_ignore_status_events():
    """Verify that Meta status events (sent, delivered, read) return 200 immediately."""
    client = TestClient(app)
    status_payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {
                                    "id": "wamid.HBgLM...",
                                    "status": "delivered",
                                    "timestamp": "1710000000",
                                    "recipient_id": "1234567890",
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    body_bytes = json.dumps(status_payload).encode("utf-8")
    sig = make_signature(body_bytes)

    with patch("app.main.is_duplicate_message") as mock_dedup:
        response = client.post(
            "/webhook",
            content=body_bytes,
            headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
        )
        assert response.status_code == 200
        mock_dedup.assert_not_called()


def test_deduplication():
    """Verify that duplicate message IDs are detected."""
    msg_id = "test_unique_msg_id_12345"
    assert is_duplicate_message(msg_id) is False
    assert is_duplicate_message(msg_id) is True


def test_missing_app_secret_rejects_webhook(monkeypatch):
    """Without APP_SECRET, every POST is rejected instead of skipping the check."""
    monkeypatch.setenv("APP_SECRET", "")
    get_settings.cache_clear()
    client = TestClient(app)
    body = json.dumps({"entry": []}).encode("utf-8")
    response = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": make_signature(body)})
    assert response.status_code == 401


def test_empty_verify_token_never_matches(monkeypatch):
    """An unset VERIFY_TOKEN must not accept an empty hub.verify_token."""
    monkeypatch.setenv("VERIFY_TOKEN", "")
    get_settings.cache_clear()
    client = TestClient(app)
    response = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "1"})
    assert response.status_code == 403


def test_split_long_message():
    """Messages over the WhatsApp limit are split on line breaks, nothing lost."""
    body = "\n".join(f"• champ_{i} : valeur" for i in range(500))
    chunks = split_message(body)
    assert len(chunks) > 1
    assert all(len(c) <= MAX_TEXT_LENGTH for c in chunks)
    assert "\n".join(chunks) == body
    assert split_message("court") == ["court"]


def test_mask_phone():
    assert mask_phone("33612345678") == "***5678"
    assert "3361234" not in mask_phone("33612345678")


@pytest.mark.asyncio
async def test_send_failure_does_not_crash():
    """If Meta refuses to send (expired token…), the background task logs and returns."""
    msg = {"id": "wamid.text2", "from": "33612345678", "type": "text", "text": {"body": "salut"}}
    with patch("app.conversation.send_text", new_callable=AsyncMock) as mock_send, \
         patch("app.processor.mark_as_read", new_callable=AsyncMock):
        mock_send.side_effect = RuntimeError("401 token expired")
        await process_message(msg)  # ne doit pas lever
