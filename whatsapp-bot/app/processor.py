"""Aiguillage des messages WhatsApp entrants vers la conversation."""

import collections
import logging
import time

from app import conversation
from app.security import mask_phone
from app.whatsapp import mark_as_read, send_text

logger = logging.getLogger(__name__)

# Cache de dédoublonnage en mémoire (taille maximale 2000 IDs avec timestamp)
MAX_DEDUP_SIZE = 2000
DEDUP_TTL_SECONDS = 3600  # 1 heure
_processed_messages: collections.OrderedDict[str, float] = collections.OrderedDict()


def is_duplicate_message(message_id: str) -> bool:
    """Check if message_id was already processed and maintain bounded cache."""
    now = time.time()

    # Nettoyage périodique si le cache dépasse la taille max
    if len(_processed_messages) > MAX_DEDUP_SIZE:
        while _processed_messages and len(_processed_messages) > (MAX_DEDUP_SIZE // 2):
            _processed_messages.popitem(last=False)

    if message_id in _processed_messages:
        # Vérifier si toujours valide selon le TTL
        timestamp = _processed_messages[message_id]
        if now - timestamp < DEDUP_TTL_SECONDS:
            return True
        else:
            del _processed_messages[message_id]

    _processed_messages[message_id] = now
    return False


def interactive_reply_id(message: dict) -> str:
    """Id du bouton (ou de la ligne de liste) cliqué par l'utilisateur."""
    return message.get("reply", {}).get("id", "")


async def process_message(message: dict) -> None:
    """Entry point to process a single incoming WhatsApp message in background.

    Never raises: a failure (Vonage down, wrong credentials…) is logged, the server keeps running.
    """
    try:
        await _process_message(message)
    except Exception as exc:
        logger.exception("Failed to handle message %s: %s", message.get("message_uuid"), exc)


async def _process_message(message: dict) -> None:
    message_id = message.get("message_uuid")
    user_phone = message.get("from")
    msg_type = message.get("message_type")

    if not message_id or not user_phone:
        logger.warning("Received invalid message payload (id=%s, type=%s)", message_id, msg_type)
        return

    logger.info("Processing message: id=%s, from=%s, type=%s", message_id, mask_phone(user_phone), msg_type)

    # Marquer comme lu (bonne pratique UX)
    await mark_as_read(message_id)

    if msg_type == "image":
        image_info = message.get("image", {})
        media_url = image_info.get("url")
        if not media_url:
            logger.error("Message type is image but media url is missing (id=%s)", message_id)
            await send_text(to=user_phone, body="⚠️ Impossible de récupérer la photo. Veuillez réessayer.")
            return
        await conversation.handle_image(user_phone, media_url, image_info.get("caption"))

    elif msg_type == "text":
        await conversation.handle_text(user_phone, message.get("text", ""))

    elif msg_type == "reply":
        await conversation.handle_text(user_phone, interactive_reply_id(message))

    else:
        logger.info("Unsupported message type '%s' from %s", msg_type, mask_phone(user_phone))
        await send_text(
            to=user_phone,
            body="ℹ️ Ce type de message n'est pas supporté. Merci d'envoyer une photo ou du texte."
        )
