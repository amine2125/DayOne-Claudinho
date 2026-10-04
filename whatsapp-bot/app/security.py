"""Security and webhook signature verification."""

import hashlib
import hmac
import logging

logger = logging.getLogger(__name__)


def mask_phone(phone: str | None) -> str:
    """Return a log-safe phone number (only the last 4 digits).

    DayOne ne garde aucune donnée personnelle : le numéro complet ne va jamais dans les logs.
    """
    if not phone:
        return "?"
    return f"***{phone[-4:]}"


def verify_signature(payload: bytes, signature_header: str | None, app_secret: str) -> bool:
    """Verify Meta's X-Hub-Signature-256 header against the raw request body.

    Args:
        payload: The raw request body in bytes.
        signature_header: The X-Hub-Signature-256 header (format: 'sha256=<hash>').
        app_secret: The Meta App Secret configured in developers.facebook.com.

    Returns:
        True if valid, False otherwise.
    """
    if not app_secret:
        # Refuser plutôt que laisser passer : sans secret, n'importe qui pourrait simuler Meta
        logger.error("APP_SECRET is not configured. Rejecting webhook.")
        return False

    if not signature_header:
        logger.warning("Missing X-Hub-Signature-256 header in request.")
        return False

    prefix = "sha256="
    if not signature_header.startswith(prefix):
        logger.warning("Invalid X-Hub-Signature-256 header format. Expected 'sha256=...'.")
        return False

    received_sig = signature_header[len(prefix):]
    expected_sig = hmac.new(
        key=app_secret.encode("utf-8"),
        msg=payload,
        digestmod=hashlib.sha256
    ).hexdigest()

    is_valid = hmac.compare_digest(expected_sig, received_sig)
    if not is_valid:
        logger.warning("Invalid signature: payload does not match X-Hub-Signature-256.")

    return is_valid
