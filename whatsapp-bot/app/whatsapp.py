"""WhatsApp client over the Vonage Messages API."""

import logging
import re
import secrets
import time
from typing import Tuple
from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.security import mask_phone

logger = logging.getLogger(__name__)

# Limite de longueur d'un message texte WhatsApp
MAX_TEXT_LENGTH = 4096


def _auth() -> httpx.BasicAuth:
    settings = get_settings()
    return httpx.BasicAuth(settings.VONAGE_API_KEY, settings.VONAGE_API_SECRET)


def _message(to: str, **content) -> dict:
    """Corps commun à tous les envois WhatsApp de l'API Messages."""
    return {"channel": "whatsapp", "from": get_settings().VONAGE_WHATSAPP_NUMBER, "to": to, **content}


async def _post(client: httpx.AsyncClient, payload: dict) -> None:
    response = await client.post(get_settings().messages_url, json=payload)
    if response.is_error:
        # Le corps de l'erreur Vonage explique la cause (identifiants, numéro non autorisé dans le sandbox…)
        logger.error("Vonage send error %s: %s", response.status_code, response.text[:300])
    response.raise_for_status()


async def download_media(media_url: str) -> Tuple[bytes, str]:
    """Download an inbound media file from the URL given in the Vonage webhook.

    Vonage garde le média 48 h derrière une URL unique ; elle se lit sans identifiants tant que
    « Enhanced Inbound Media Security » n'est pas activé sur l'application Vonage.

    Args:
        media_url: The `image.url` received in the webhook.

    Returns:
        tuple[bytes, str]: Tuple containing binary content and mime type (e.g. image/jpeg).

    Raises:
        httpx.HTTPError: If the download fails.
    """
    if urlparse(media_url).scheme != "https":
        raise ValueError("Media URL must use https")

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True) as client:
        response = await client.get(media_url)
        if response.status_code in (401, 403):
            logger.error("Media download refused (%s): is Enhanced Inbound Media Security enabled?",
                         response.status_code)
        response.raise_for_status()
        content = response.content
        mime_type = response.headers.get("content-type", "image/jpeg").split(";")[0].strip()

    logger.info("Media downloaded successfully: size_bytes=%d, mime_type=%s", len(content), mime_type)
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
    """Send a plain text message to a WhatsApp user via the Vonage Messages API.

    Messages longer than 4096 characters are sent in several parts.

    Args:
        to: Destination WhatsApp phone number in international format.
        body: Text content of the message.

    Raises:
        httpx.HTTPError: If Vonage returns an error.
    """
    async with httpx.AsyncClient(auth=_auth(), timeout=httpx.Timeout(15.0, connect=5.0)) as client:
        for chunk in split_message(body):
            await _post(client, _message(to, message_type="text", text=chunk))
    logger.info("Message sent successfully to %s", mask_phone(to))


async def send_buttons(to: str, body: str, buttons: list[tuple[str, str]]) -> None:
    """Send a message with up to 3 reply buttons.

    Le clic revient dans le webhook comme un message `reply` portant l'id du bouton.
    Si Vonage refuse le message interactif, le même texte part sans boutons : les mots
    (« terminé », « annuler »…) marchent aussi.

    Args:
        to: Destination WhatsApp phone number.
        body: Message text (1024 characters max).
        buttons: (id, title) pairs; title is 20 characters max.
    """
    interactive = {
        "type": "button",
        "body": {"text": body[:1024]},
        "action": {
            "buttons": [
                {"type": "reply", "reply": {"id": bid, "title": title[:20]}}
                for bid, title in buttons[:3]
            ]
        },
    }
    payload = _message(to, message_type="custom", custom={"type": "interactive", "interactive": interactive})

    try:
        async with httpx.AsyncClient(auth=_auth(), timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            await _post(client, payload)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403):
            raise
        # « ✅ Terminé » → « Terminé » : le mot que la conversation reconnaît
        words = " ou ".join("*" + re.sub(r"^\W+", "", title) + "*" for _, title in buttons[:3])
        await send_text(to, f"{body}\n\n👉 Répondez {words}.")
        return
    logger.info("Buttons sent successfully to %s", mask_phone(to))


async def send_list(to: str, body: str, button: str, rows: list[tuple[str, str]]) -> None:
    """Send a list message: a button that opens up to 10 clickable rows.

    Le clic revient dans le webhook comme un message `reply` portant l'id de la ligne (comme un bouton).
    Si Vonage refuse le message interactif, les choix partent en texte numéroté.

    Args:
        to: Destination WhatsApp phone number.
        body: Message text (1024 characters max).
        button: Label of the button that opens the list (20 characters max).
        rows: (id, title) pairs, 10 at most; title is 24 characters max.
    """
    interactive = {
        "type": "list",
        "body": {"text": body[:1024]},
        "action": {
            "button": button[:20],
            "sections": [{"title": "Options", "rows": [{"id": rid, "title": title[:24]} for rid, title in rows[:10]]}],
        },
    }
    payload = _message(to, message_type="custom", custom={"type": "interactive", "interactive": interactive})
    try:
        async with httpx.AsyncClient(auth=_auth(), timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            await _post(client, payload)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403):
            raise
        choices = "\n".join(f"• *{rid}* : {title}" for rid, title in rows[:10])
        await send_text(to, f"{body}\n\n{choices}\n\n👉 Répondez avec le mot en gras.")
        return
    logger.info("List sent successfully to %s", mask_phone(to))


# Fichiers prêts à être récupérés par Vonage (GET /files/{jeton} sur ce serveur) : l'API Messages
# n'accepte un document que par URL publique. Jeton aléatoire, effacé après quelques minutes.
FILE_TTL_SECONDS = 600
_files: dict[str, tuple[float, bytes, str, str]] = {}


def take_file(token: str) -> tuple[bytes, str, str] | None:
    """Fichier déposé par send_document (octets, nom, type), s'il n'a pas expiré."""
    now = time.monotonic()
    for t in [t for t, (at, *_rest) in _files.items() if now - at > FILE_TTL_SECONDS]:
        del _files[t]
    hit = _files.get(token)
    return hit[1:] if hit else None


async def send_document(to: str, data: bytes, filename: str, caption: str = "",
                        mime_type: str = "application/pdf") -> None:
    """Send a file (the record's PDF) that the user can open and download.

    Le fichier est servi un court instant par ce serveur (PUBLIC_BASE_URL, l'adresse publique du
    webhook) et Vonage le récupère par son URL. Sans adresse publique : un texte l'indique.
    """
    base = get_settings().PUBLIC_BASE_URL.rstrip("/")
    if not base:
        await send_text(to, f"{caption}\n\n(La fiche PDF est disponible sur le tableau de bord DayOne.)")
        return
    token = secrets.token_urlsafe(24)
    _files[token] = (time.monotonic(), data, filename, mime_type)
    payload = _message(to, message_type="file",
                       file={"url": f"{base}/files/{token}", "caption": caption[:1024], "name": filename})
    async with httpx.AsyncClient(auth=_auth(), timeout=httpx.Timeout(15.0, connect=5.0)) as client:
        await _post(client, payload)
    logger.info("Document sent successfully to %s (%d bytes)", mask_phone(to), len(data))


async def mark_as_read(message_uuid: str) -> None:
    """Mark an incoming WhatsApp message as read (not available in the Vonage sandbox).

    Args:
        message_uuid: The `message_uuid` of the inbound message.
    """
    settings = get_settings()
    if settings.VONAGE_SANDBOX:
        return

    try:
        async with httpx.AsyncClient(auth=_auth(), timeout=httpx.Timeout(5.0)) as client:
            response = await client.patch(f"{settings.messages_url}/{message_uuid}", json={"status": "read"})
            response.raise_for_status()
            logger.debug("Message %s marked as read", message_uuid)
    except Exception as exc:
        logger.warning("Failed to mark message %s as read: %s", message_uuid, exc)
