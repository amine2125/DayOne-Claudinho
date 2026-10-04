"""Security: Vonage webhook signature verification, log-safe phone numbers."""

import base64
import hashlib
import hmac
import json
import logging
import time

logger = logging.getLogger(__name__)

# Au-delà, un webhook rejoué échapperait au dédoublonnage (1 h) : on le refuse
MAX_TOKEN_AGE_SECONDS = 3600


def mask_phone(phone: str | None) -> str:
    """Return a log-safe phone number (only the last 4 digits).

    DayOne ne garde aucune donnée personnelle : le numéro complet ne va jamais dans les logs.
    """
    if not phone:
        return "?"
    return f"***{phone[-4:]}"


def _b64url_decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def _payload_hash_matches(payload: bytes, payload_hash: object) -> bool:
    """Le claim `payload_hash` est le SHA-256 du corps envoyé par Vonage."""
    if not isinstance(payload_hash, str):
        return False
    bodies = [payload]
    try:
        # Vonage hache le JSON compact : le corps re-sérialisé couvre un éventuel écart d'espaces
        bodies.append(json.dumps(json.loads(payload), separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    except ValueError:
        pass
    expected = payload_hash.lower()
    return any(hmac.compare_digest(hashlib.sha256(body).hexdigest(), expected) for body in bodies)


def verify_signature(payload: bytes, authorization: str | None, signature_secret: str) -> bool:
    """Verify the JWT that Vonage puts in the Authorization header of every Messages API webhook.

    Le JWT est signé en HMAC-SHA256 avec le secret de signature du compte (Dashboard → Settings) ;
    son claim `payload_hash` lie la signature au corps de la requête.

    Args:
        payload: The raw request body in bytes.
        authorization: The Authorization header (format: 'Bearer <jwt>').
        signature_secret: The Vonage signature secret.

    Returns:
        True if valid, False otherwise.
    """
    if not signature_secret:
        # Refuser plutôt que laisser passer : sans secret, n'importe qui pourrait simuler Vonage
        logger.error("VONAGE_SIGNATURE_SECRET is not configured. Rejecting webhook.")
        return False

    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        logger.warning("Missing or malformed Authorization header in webhook (expected 'Bearer <jwt>').")
        return False

    try:
        header_b64, claims_b64, signature_b64 = token.strip().split(".")
        header = json.loads(_b64url_decode(header_b64))
        claims = json.loads(_b64url_decode(claims_b64))
        signature = _b64url_decode(signature_b64)
    except ValueError:
        logger.warning("Invalid webhook JWT format.")
        return False
    if not isinstance(header, dict) or not isinstance(claims, dict) or header.get("alg") != "HS256":
        logger.warning("Unexpected webhook JWT header or claims (HS256 expected).")
        return False

    expected_sig = hmac.new(
        key=signature_secret.encode("utf-8"),
        msg=f"{header_b64}.{claims_b64}".encode("ascii"),
        digestmod=hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(expected_sig, signature):
        logger.warning("Invalid signature: webhook JWT not signed with VONAGE_SIGNATURE_SECRET.")
        return False

    issued_at = claims.get("iat")
    if not isinstance(issued_at, (int, float)) or abs(time.time() - issued_at) > MAX_TOKEN_AGE_SECONDS:
        logger.warning("Webhook JWT is too old or has no 'iat' claim.")
        return False

    if not _payload_hash_matches(payload, claims.get("payload_hash")):
        logger.warning("Invalid signature: payload does not match the JWT payload_hash.")
        return False

    return True
