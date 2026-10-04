"""Meta WhatsApp Cloud API client module."""

import logging
from typing import Tuple
import httpx

from app.config import get_settings
from app.security import mask_phone

logger = logging.getLogger(__name__)

# Limite de longueur d'un message texte WhatsApp
MAX_TEXT_LENGTH = 4096


async def download_media(media_id: str) -> Tuple[bytes, str]:
    """Download media file from Meta WhatsApp Cloud API.

    1. Request media URL and metadata using media_id.
    2. Download the binary stream using the temporary URL with Bearer token.

    Args:
        media_id: The WhatsApp media ID received in the webhook.

    Returns:
        tuple[bytes, str]: Tuple containing binary content and mime type (e.g. image/jpeg).

    Raises:
        httpx.HTTPError: If either request fails.
    """
    settings = get_settings()
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        # Étape 1 : Obtenir l'URL de téléchargement
        meta_url = f"{settings.graph_api_url}/{media_id}"
        meta_resp = await client.get(meta_url, headers=headers)
        meta_resp.raise_for_status()
        media_info = meta_resp.json()

        download_url = media_info.get("url")
        mime_type = media_info.get("mime_type", "image/jpeg")

        if not download_url:
            raise ValueError(f"No download URL found for media ID {media_id}")

        # Étape 2 : Télécharger les données binaires du média
        media_resp = await client.get(download_url, headers=headers)
        media_resp.raise_for_status()
        content = media_resp.content

        logger.info(
            "Media downloaded successfully: media_id=%s, size_bytes=%d, mime_type=%s",
            media_id,
            len(content),
            mime_type,
        )
        return content, mime_type


def split_message(body: str, limit: int = MAX_TEXT_LENGTH) -> list[str]:
    """Split a long text into chunks under WhatsApp's limit, preferring line breaks."""
    chunks = []
    while len(body) > limit:
        cut = body.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(body[:cut].rstrip())
        body = body[cut:].lstrip("\n")
    if body.strip():
        chunks.append(body)
    return chunks


async def send_text(to: str, body: str) -> None:
    """Send a plain text message to a WhatsApp user via Meta Cloud API.

    Messages longer than 4096 characters are sent in several parts.

    Args:
        to: Destination WhatsApp phone number in international format.
        body: Text content of the message.

    Raises:
        httpx.HTTPError: If Meta API returns an error.
    """
    settings = get_settings()
    url = f"{settings.graph_api_url}/{settings.PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
        for chunk in split_message(body):
            payload = {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": chunk},
            }
            response = await client.post(url, headers=headers, json=payload)
            if response.is_error:
                # Le corps de l'erreur Meta explique la cause (token expiré, numéro non autorisé…)
                logger.error("Meta send error %s: %s", response.status_code, response.text[:300])
            response.raise_for_status()
    logger.info("Message sent successfully to %s", mask_phone(to))


async def send_buttons(to: str, body: str, buttons: list[tuple[str, str]]) -> None:
    """Send a message with up to 3 reply buttons.

    Le clic revient dans le webhook comme un message `interactive` portant l'id du bouton.

    Args:
        to: Destination WhatsApp phone number.
        body: Message text (1024 characters max).
        buttons: (id, title) pairs; title is 20 characters max.
    """
    settings = get_settings()
    url = f"{settings.graph_api_url}/{settings.PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body[:1024]},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": bid, "title": title[:20]}}
                    for bid, title in buttons[:3]
                ]
            },
        },
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.is_error:
            logger.error("Meta send error %s: %s", response.status_code, response.text[:300])
        response.raise_for_status()
    logger.info("Buttons sent successfully to %s", mask_phone(to))


async def mark_as_read(message_id: str) -> None:
    """Mark an incoming WhatsApp message as read.

    Args:
        message_id: The ID of the message to mark as read.
    """
    settings = get_settings()
    url = f"{settings.graph_api_url}/{settings.PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            logger.debug("Message %s marked as read", message_id)
    except Exception as exc:
        logger.warning("Failed to mark message %s as read: %s", message_id, exc)
