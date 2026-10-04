"""FastAPI entry point for WhatsApp Webhook Server."""

import json
import logging
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse

from app.config import get_settings
from app.processor import is_duplicate_message, process_message
from app.security import verify_signature

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("whatsapp-bot")

app = FastAPI(
    title="WhatsApp Bot for Image Analysis",
    description="Webhook server integrating Meta WhatsApp Cloud API with custom backend OCR/AI",
    version="1.0.0"
)


@app.get("/")
async def root():
    """Healthcheck and info endpoint."""
    return {
        "status": "online",
        "service": "whatsapp-bot",
        "version": "1.0.0"
    }


@app.get("/webhook")
async def verify_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    """Meta Webhook verification endpoint (GET /webhook).

    Meta calls this endpoint during webhook setup with challenge verification.
    """
    settings = get_settings()

    token_ok = bool(settings.VERIFY_TOKEN) and hub_verify_token == settings.VERIFY_TOKEN
    logger.info("Webhook verification request: mode=%s, token_match=%s", hub_mode, token_ok)

    if hub_mode == "subscribe" and token_ok:
        if hub_challenge is not None:
            logger.info("Webhook verified successfully.")
            return PlainTextResponse(content=hub_challenge, status_code=200)

    logger.warning("Webhook verification failed (token mismatch or invalid mode).")
    raise HTTPException(status_code=403, detail="Verification token mismatch or invalid mode")


@app.post("/webhook")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256")
):
    """Meta Webhook notification receiver (POST /webhook).

    1. Reads raw body and validates X-Hub-Signature-256 with APP_SECRET.
    2. Responds 200 OK immediately to avoid Meta retries.
    3. Filters out status events (sent, delivered, read).
    4. Deduplicates message IDs.
    5. Dispatches background processing tasks.
    """
    settings = get_settings()

    # 1. Lire le body brut pour vérifier la signature
    body_bytes = await request.body()

    if not verify_signature(body_bytes, x_hub_signature_256, settings.APP_SECRET):
        logger.error("Rejected webhook: Invalid X-Hub-Signature-256 signature.")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # 2. Parser le payload JSON
    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception as exc:
        logger.error("Failed to decode webhook JSON: %s", exc)
        return Response(status_code=200, content="Invalid JSON, ignored")

    # 3. Extraire les entrées du webhook Meta
    entries = payload.get("entry", [])
    for entry in entries:
        for change in entry.get("changes", []):
            value = change.get("value", {})

            # Ignorer les statuts (sent, delivered, read)
            if "messages" not in value:
                continue

            messages = value.get("messages", [])
            for message in messages:
                message_id = message.get("id")

                # Dédoublonnage : ignorer si déjà traité
                if message_id and is_duplicate_message(message_id):
                    logger.info("Ignoring duplicate message_id: %s", message_id)
                    continue

                # Lancer le traitement en tâche d'arrière-plan
                background_tasks.add_task(process_message, message)

    # Répondre 200 OK le plus vite possible
    return Response(status_code=200, content="EVENT_RECEIVED")
