"""Unit and integration tests for the WhatsApp webhook bot (Vonage Messages API)."""

import base64
import hashlib
import hmac
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from app import whatsapp
from app.backend import midwife_id
from app.config import SANDBOX_MESSAGES_URL, get_settings
from app.main import app
from app.processor import is_duplicate_message, process_message
from app.security import mask_phone
from app.whatsapp import MAX_TEXT_LENGTH, split_message

SECRET = "test_signature_secret"


@pytest.fixture(autouse=True)
def setup_test_settings(monkeypatch):
    """Setup safe test settings."""
    monkeypatch.setenv("VONAGE_API_KEY", "abcd1234")
    monkeypatch.setenv("VONAGE_API_SECRET", "test_api_secret")
    monkeypatch.setenv("VONAGE_SIGNATURE_SECRET", SECRET)
    monkeypatch.setenv("VONAGE_WHATSAPP_NUMBER", "14157386102")
    monkeypatch.setenv("VONAGE_SANDBOX", "false")
    monkeypatch.setenv("DAYONE_API_URL", "http://test-api")
    get_settings.cache_clear()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_authorization(body: bytes, secret: str = SECRET, iat: float | None = None,
                       payload_hash: str | None = None) -> str:
    """Build the 'Bearer <jwt>' header Vonage sends with each webhook."""
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    claims = _b64(json.dumps({
        "iat": int(time.time() if iat is None else iat),
        "jti": "c5ba8f24-1a14-4c10-bfdf-3fbe8ce511b5",
        "iss": "Vonage",
        "payload_hash": payload_hash or hashlib.sha256(body).hexdigest(),
        "api_key": "abcd1234",
        "application_id": "aaaaaaaa-bbbb-4ccc-8ddd-0123456789ab",
    }).encode())
    signature = _b64(hmac.new(secret.encode(), f"{header}.{claims}".encode(), hashlib.sha256).digest())
    return f"Bearer {header}.{claims}.{signature}"


def inbound(message_uuid: str = "aaaaaaaa-bbbb-4ccc-8ddd-0123456789ab", **content) -> dict:
    """An inbound WhatsApp message as Vonage posts it."""
    return {
        "channel": "whatsapp",
        "message_uuid": message_uuid,
        "to": "14157386102",
        "from": "33612345678",
        "timestamp": "2026-10-04T12:14:25Z",
        "profile": {"name": "Sage-femme"},
        "message_type": "text",
        "text": "bonjour",
        **content,
    }


def post(client: TestClient, path: str, payload: dict, **jwt_options) -> httpx.Response:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return client.post(path, content=body, headers={
        "Authorization": make_authorization(body, **jwt_options),
        "Content-Type": "application/json",
    })


# --- Signature ---

def test_signed_inbound_message_is_processed():
    """A WhatsApp message signed by Vonage is handed to the background processing."""
    client = TestClient(app)
    with patch("app.main.process_message", new_callable=AsyncMock) as mock_process:
        response = post(client, "/webhooks/inbound", inbound(message_uuid="uuid-signed"))
    assert response.status_code == 200
    mock_process.assert_awaited_once()
    assert mock_process.await_args.args[0]["text"] == "bonjour"


def test_post_webhook_invalid_signature():
    """Verify that POST requests with missing or bad signatures are rejected (401)."""
    client = TestClient(app)
    body = json.dumps(inbound()).encode("utf-8")

    # Sans header
    assert client.post("/webhooks/inbound", content=body).status_code == 401
    # Signé avec un autre secret
    bad = client.post("/webhooks/inbound", content=body,
                      headers={"Authorization": make_authorization(body, secret="wrong_secret")})
    assert bad.status_code == 401
    # Pas un JWT
    garbage = client.post("/webhooks/inbound", content=body, headers={"Authorization": "Bearer abc.def"})
    assert garbage.status_code == 401
    # Les statuts sont signés de la même façon
    assert client.post("/webhooks/status", content=body).status_code == 401


def test_tampered_body_is_rejected():
    """A valid JWT does not cover another body: payload_hash binds it to the original request."""
    client = TestClient(app)
    original = json.dumps(inbound(text="1")).encode("utf-8")
    tampered = json.dumps(inbound(text="annuler")).encode("utf-8")
    response = client.post("/webhooks/inbound", content=tampered,
                           headers={"Authorization": make_authorization(original)})
    assert response.status_code == 401


def test_old_token_is_rejected():
    """A webhook replayed after the deduplication window is refused."""
    client = TestClient(app)
    response = post(client, "/webhooks/inbound", inbound(), iat=time.time() - 2 * 3600)
    assert response.status_code == 401


def test_missing_signature_secret_rejects_webhook(monkeypatch):
    """Without VONAGE_SIGNATURE_SECRET, every POST is rejected instead of skipping the check."""
    monkeypatch.setenv("VONAGE_SIGNATURE_SECRET", "")
    get_settings.cache_clear()
    client = TestClient(app)
    response = post(client, "/webhooks/inbound", inbound())
    assert response.status_code == 401


# --- Webhooks ---

def test_status_events_are_not_processed():
    """Vonage status events (submitted, delivered, read, rejected) return 200 without processing."""
    client = TestClient(app)
    status = {
        "message_uuid": "aaaaaaaa-bbbb-4ccc-8ddd-0123456789ab",
        "to": "33612345678",
        "from": "14157386102",
        "timestamp": "2026-10-04T12:14:26Z",
        "status": "rejected",
        "channel": "whatsapp",
        "error": {"type": "https://developer.vonage.com/api-errors/messages#1020", "title": 1020,
                  "detail": "Invalid params"},
    }
    with patch("app.main.process_message", new_callable=AsyncMock) as mock_process:
        response = post(client, "/webhooks/status", status)
    assert response.status_code == 200
    mock_process.assert_not_called()


def test_other_channels_are_ignored():
    client = TestClient(app)
    with patch("app.main.process_message", new_callable=AsyncMock) as mock_process:
        response = post(client, "/webhooks/inbound", inbound(message_uuid="uuid-sms", channel="sms"))
    assert response.status_code == 200
    mock_process.assert_not_called()


def test_redelivered_webhook_is_processed_once():
    client = TestClient(app)
    with patch("app.main.process_message", new_callable=AsyncMock) as mock_process:
        post(client, "/webhooks/inbound", inbound(message_uuid="uuid-retry"))
        post(client, "/webhooks/inbound", inbound(message_uuid="uuid-retry"))
    assert mock_process.await_count == 1


def test_deduplication():
    """Verify that duplicate message IDs are detected."""
    msg_id = "test_unique_msg_id_12345"
    assert is_duplicate_message(msg_id) is False
    assert is_duplicate_message(msg_id) is True


# --- Aiguillage ---

@pytest.mark.asyncio
async def test_message_types_are_routed():
    """Text, button reply and photo reach the conversation with what it needs."""
    with patch("app.processor.conversation") as conv, patch("app.processor.mark_as_read", new_callable=AsyncMock):
        conv.handle_text = AsyncMock()
        conv.handle_image = AsyncMock()

        await process_message(inbound(text="Terminé"))
        conv.handle_text.assert_awaited_with("33612345678", "Terminé")

        await process_message(inbound(message_type="reply", reply={"id": "btn_done", "title": "✅ Terminé"}))
        conv.handle_text.assert_awaited_with("33612345678", "btn_done")

        url = "https://api-eu.vonage.com/v3/media/1b456509-974c-458b-aafa-45fc48a4d976"
        await process_message(inbound(message_type="image", image={"url": url, "caption": "page 1"}))
        conv.handle_image.assert_awaited_with("33612345678", url, "page 1")


@pytest.mark.asyncio
async def test_send_failure_does_not_crash():
    """If Vonage refuses to send (wrong credentials…), the background task logs and returns."""
    msg = inbound(message_uuid="uuid-text2", text="salut")
    with patch("app.conversation.send_text", new_callable=AsyncMock) as mock_send, \
         patch("app.processor.mark_as_read", new_callable=AsyncMock):
        mock_send.side_effect = RuntimeError("401 bad credentials")
        await process_message(msg)  # ne doit pas lever


# --- Envoi par Vonage ---

@pytest.fixture
def vonage(monkeypatch):
    """Replaces the Vonage Messages API: records each request, answers like Vonage."""
    requests: list[httpx.Request] = []
    responses: list[httpx.Response] = []
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if responses:
            return responses.pop(0)
        return httpx.Response(202, json={"message_uuid": "aaaaaaaa-bbbb-4ccc-8ddd-0123456789ab"})

    monkeypatch.setattr(whatsapp.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    return requests, responses


@pytest.mark.asyncio
async def test_send_text_uses_messages_api(vonage):
    requests, _ = vonage
    await whatsapp.send_text("33612345678", "Bonjour")
    (request,) = requests
    assert str(request.url) == "https://api.nexmo.com/v1/messages"
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"abcd1234:test_api_secret").decode()
    assert json.loads(request.content) == {
        "channel": "whatsapp", "from": "14157386102", "to": "33612345678",
        "message_type": "text", "text": "Bonjour",
    }


@pytest.mark.asyncio
async def test_sandbox_url(vonage, monkeypatch):
    requests, _ = vonage
    monkeypatch.setenv("VONAGE_SANDBOX", "true")
    get_settings.cache_clear()
    await whatsapp.send_text("33612345678", "Bonjour")
    await whatsapp.mark_as_read("uuid-sandbox")   # pas d'accusé de lecture dans le sandbox
    assert [str(r.url) for r in requests] == [SANDBOX_MESSAGES_URL]


@pytest.mark.asyncio
async def test_send_buttons_as_interactive_message(vonage):
    requests, _ = vonage
    await whatsapp.send_buttons("33612345678", "Page 1 reçue", [("btn_done", "✅ Terminé"), ("btn_cancel", "❌ Annuler")])
    sent = json.loads(requests[0].content)
    assert sent["message_type"] == "custom" and sent["custom"]["type"] == "interactive"
    buttons = sent["custom"]["interactive"]["action"]["buttons"]
    assert [b["reply"]["id"] for b in buttons] == ["btn_done", "btn_cancel"]


@pytest.mark.asyncio
async def test_refused_buttons_fall_back_to_text(vonage):
    """If Vonage refuses the interactive message, the same text goes out with the words to type."""
    requests, responses = vonage
    responses.append(httpx.Response(422, json={"title": "Invalid message type"}))
    await whatsapp.send_buttons("33612345678", "Page 1 reçue", [("btn_done", "✅ Terminé"), ("btn_cancel", "❌ Annuler")])
    fallback = json.loads(requests[1].content)
    assert fallback["message_type"] == "text"
    assert fallback["text"].startswith("Page 1 reçue") and "*Terminé* ou *Annuler*" in fallback["text"]


@pytest.mark.asyncio
async def test_bad_credentials_are_not_hidden(vonage):
    _, responses = vonage
    responses.append(httpx.Response(401, json={"title": "Unauthorized"}))
    with pytest.raises(httpx.HTTPStatusError):
        await whatsapp.send_buttons("33612345678", "Page 1 reçue", [("btn_done", "✅ Terminé")])


@pytest.mark.asyncio
async def test_mark_as_read(vonage):
    requests, _ = vonage
    await whatsapp.mark_as_read("uuid-read")
    (request,) = requests
    assert request.method == "PATCH" and str(request.url) == "https://api.nexmo.com/v1/messages/uuid-read"
    assert json.loads(request.content) == {"status": "read"}


@pytest.mark.asyncio
async def test_download_media(vonage):
    requests, responses = vonage
    responses.append(httpx.Response(200, content=b"\xff\xd8jpeg", headers={"Content-Type": "image/jpeg"}))
    url = "https://api-eu.vonage.com/v3/media/1b456509-974c-458b-aafa-45fc48a4d976"
    assert await whatsapp.download_media(url) == (b"\xff\xd8jpeg", "image/jpeg")
    assert "Authorization" not in requests[0].headers   # aucun identifiant envoyé avec le média
    with pytest.raises(ValueError):
        await whatsapp.download_media("http://example.com/photo.jpg")


# --- Divers ---

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


def test_midwife_id_depends_on_its_own_secret(monkeypatch):
    """The midwife id keeps its key when the WhatsApp provider changes."""
    monkeypatch.setenv("MIDWIFE_ID_SECRET", "cle-1")
    get_settings.cache_clear()
    first = midwife_id("33612345678")
    monkeypatch.setenv("VONAGE_SIGNATURE_SECRET", "autre")
    get_settings.cache_clear()
    assert midwife_id("33612345678") == first and first.startswith("wa-") and "3361234" not in first
