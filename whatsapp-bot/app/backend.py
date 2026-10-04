"""Client de notre API d'analyse (OUR_API_URL) et d'enregistrement (CONFIRM_URL)."""

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class AnalysisError(Exception):
    """Échec d'analyse d'une page ; le message est destiné à l'utilisateur."""


def _auth_headers() -> dict:
    key = get_settings().OUR_API_KEY
    return {"Authorization": f"Bearer {key}", "X-API-Key": key} if key else {}


def _extract_page(data) -> dict | None:
    """Accepte la sortie DayOne brute, ou enveloppée dans `prediction` / `result`."""
    if not isinstance(data, dict):
        return None
    for candidate in (data, data.get("prediction"), data.get("result")):
        if isinstance(candidate, dict) and isinstance(candidate.get("fields"), dict):
            return candidate
    return None


async def analyze_page(image_bytes: bytes, mime_type: str, user_phone: str, caption: str | None = None) -> dict:
    """Envoie une photo à OUR_API_URL et retourne la page analysée (format DayOne).

    Raises:
        AnalysisError: message prêt à être montré à l'utilisateur.
    """
    settings = get_settings()
    if not settings.OUR_API_URL:
        logger.error("OUR_API_URL is not configured in settings.")
        raise AnalysisError("Le service d'analyse n'est pas encore configuré.")

    ext = "png" if "png" in mime_type else "jpg"
    files = {"file": (f"page.{ext}", image_bytes, mime_type)}
    data = {"user_phone": user_phone}
    if caption:
        data["caption"] = caption

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.OUR_API_TIMEOUT, connect=10.0)) as client:
            logger.info("Forwarding image to backend API: %s", settings.OUR_API_URL)
            response = await client.post(settings.OUR_API_URL, files=files, data=data, headers=_auth_headers())
    except httpx.TimeoutException:
        logger.error("Timeout while calling backend API (%s)", settings.OUR_API_URL)
        raise AnalysisError("La lecture a pris trop de temps.") from None
    except httpx.HTTPError as exc:
        logger.error("Failed to reach backend API (%s): %s", settings.OUR_API_URL, exc)
        raise AnalysisError("Le service d'analyse est injoignable.") from None

    if 400 <= response.status_code < 500:
        # Erreur « métier » (photo floue, page non reconnue…) : l'API explique, on relaie
        logger.warning("Backend API refused the page (%s): %s", response.status_code, response.text[:200])
        try:
            detail = response.json().get("detail")
        except Exception:
            detail = None
        raise AnalysisError(detail if isinstance(detail, str) and detail else "La page n'a pas pu être lue.")
    if response.is_error:
        logger.error("Backend API returned status error %s: %s", response.status_code, response.text[:200])
        raise AnalysisError("Une erreur est survenue pendant la lecture.")

    try:
        page = _extract_page(response.json())
    except ValueError:
        page = None
    if page is None:
        logger.error("Backend API returned an unexpected payload: %s", response.text[:200])
        raise AnalysisError("La réponse du service d'analyse est inattendue.")
    return page


async def save_record(user_phone: str, pages: list[dict]) -> bool:
    """Transmet le registre confirmé à CONFIRM_URL (si configurée). Retourne False en cas d'échec."""
    settings = get_settings()
    if not settings.CONFIRM_URL:
        logger.info("CONFIRM_URL not configured: confirmed record kept in conversation only.")
        return True
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            response = await client.post(
                settings.CONFIRM_URL,
                json={"user_phone": user_phone, "pages": pages},
                headers=_auth_headers(),
            )
            response.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        logger.error("Failed to save confirmed record to CONFIRM_URL: %s", exc)
        return False
