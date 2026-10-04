"""FastAPI entry point for the WhatsApp webhook server (Vonage Messages API)."""

import json
import logging
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, Response

from app.config import get_settings
from app.processor import is_duplicate_message, process_message
from app.security import mask_phone, verify_signature

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("whatsapp-bot")

app = FastAPI(
    title="WhatsApp Bot for Image Analysis",
    description="Webhook server integrating the Vonage Messages API (WhatsApp) with custom backend OCR/AI",
    version="1.0.0"
)

# Statuts Vonage qui signalent un message non remis
FAILED_STATUSES = ("rejected", "undeliverable")


@app.get("/")
async def root():
    """Healthcheck and info endpoint."""
    return {
        "status": "online",
        "service": "whatsapp-bot",
        "version": "1.0.0"
    }


async def _signed_payload(request: Request, authorization: str | None) -> dict | None:
    """JSON body of a Vonage webhook once its JWT is verified (401 otherwise); None if unreadable."""
    # Lire le body brut : le JWT signe son empreinte SHA-256
    body_bytes = await request.body()

    if not verify_signature(body_bytes, authorization, get_settings().VONAGE_SIGNATURE_SECRET):
        logger.error("Rejected webhook: invalid Vonage signature.")
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception as exc:
        logger.error("Failed to decode webhook JSON: %s", exc)
        return None
    return payload if isinstance(payload, dict) else None


@app.post("/webhooks/inbound")
async def receive_inbound(
    request: Request,
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
):
    """Vonage inbound message webhook (POST /webhooks/inbound), one message per request.

    1. Verifies the JWT in the Authorization header with VONAGE_SIGNATURE_SECRET.
    2. Responds 200 OK immediately to avoid Vonage retries.
    3. Ignores channels other than WhatsApp.
    4. Deduplicates message UUIDs.
    5. Dispatches the background processing task.
    """
    message = await _signed_payload(request, authorization)
    if message is None:
        return Response(status_code=200, content="Invalid JSON, ignored")

    if message.get("channel") != "whatsapp":
        logger.info("Ignoring inbound message on channel %s", message.get("channel"))
        return Response(status_code=200, content="EVENT_RECEIVED")

    # Dédoublonnage : Vonage renvoie le webhook s'il n'a pas eu sa réponse à temps
    message_uuid = message.get("message_uuid")
    if message_uuid and is_duplicate_message(message_uuid):
        logger.info("Ignoring duplicate message_uuid: %s", message_uuid)
        return Response(status_code=200, content="EVENT_RECEIVED")

    # Lancer le traitement en tâche d'arrière-plan, répondre 200 OK le plus vite possible
    background_tasks.add_task(process_message, message)
    return Response(status_code=200, content="EVENT_RECEIVED")


@app.post("/webhooks/status")
async def receive_status(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Vonage status webhook (POST /webhooks/status): submitted, delivered, read, rejected…

    Seuls les échecs sont journalisés : c'est là que Vonage dit pourquoi WhatsApp a refusé un message.
    """
    status = await _signed_payload(request, authorization)
    if status and status.get("status") in FAILED_STATUSES:
        logger.warning(
            "Message %s to %s %s: %s",
            status.get("message_uuid"),
            mask_phone(status.get("to")),
            status.get("status"),
            status.get("error"),
        )
    return Response(status_code=200, content="EVENT_RECEIVED")
