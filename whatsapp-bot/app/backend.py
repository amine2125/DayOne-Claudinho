"""Client de l'API DayOne (api/main.py) : dossiers, lecture, vérification, liaison patiente.

Le bot ne lit rien lui-même : il envoie les photos à l'API, qui les lit avec dayone.extract,
les garde chiffrées dans la base et les montre au tableau de bord (web/).
"""

import asyncio
import hashlib
import hmac
import logging
import re
import time

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

POLL_SECONDS = 2.0
READ_STATES = ("NEEDS_REVIEW", "PROCESSING_FAILED")  # la lecture est finie dans ces états


class ApiError(Exception):
    """Échec d'un appel à l'API ; le message est destiné à l'utilisateur."""


def midwife_id(phone: str) -> str:
    """Identifiant stable de la sage-femme, sans son numéro (HMAC avec MIDWIFE_ID_SECRET : non réversible)."""
    key = (get_settings().MIDWIFE_ID_SECRET or "dayone").encode()
    return "wa-" + hmac.new(key, phone.encode(), hashlib.sha256).hexdigest()[:10]


def _client(timeout: float = 30.0) -> httpx.AsyncClient:
    settings = get_settings()
    headers = {"Authorization": f"Bearer {settings.OUR_API_KEY}"} if settings.OUR_API_KEY else {}
    return httpx.AsyncClient(base_url=settings.DAYONE_API_URL, headers=headers,
                             timeout=httpx.Timeout(timeout, connect=10.0))


async def _call(method: str, path: str, **kwargs):
    try:
        async with _client() as client:
            response = await client.request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        logger.error("DayOne API unreachable (%s %s): %s", method, path, exc)
        raise ApiError("Le service DayOne est injoignable. Réessayez dans quelques minutes.") from None
    if response.status_code in (404, 409, 413, 422):
        # Refus « métier » (transition impossible, image trop lourde…) : l'API explique, on relaie
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = None
        logger.warning("DayOne API refused %s %s (%s): %s", method, path, response.status_code, response.text[:200])
        raise ApiError(detail if isinstance(detail, str) else "La demande a été refusée.")
    if response.is_error:
        logger.error("DayOne API error %s on %s %s: %s", response.status_code, method, path, response.text[:200])
        raise ApiError("Une erreur est survenue côté DayOne. Réessayez plus tard.")
    return response.json()


def _file(name: str, photo: tuple[bytes, str]) -> tuple:
    data, mime = photo
    return (name, data, mime)


async def create_record(photo: tuple[bytes, str], phone: str) -> str:
    """Dossier créé dès la 1re photo : elle est enregistrée (chiffrée) et sa lecture commence."""
    files = [("files", _file("page1.jpg", photo))]
    return (await _call("POST", "/api/records", files=files, data={"midwife_id": midwife_id(phone)}))["id"]


async def add_page(record_id: str, photo: tuple[bytes, str]) -> int:
    """Page suivante : enregistrée tout de suite, lue en arrière-plan."""
    return (await _call("POST", f"/api/records/{record_id}/pages", files={"file": _file("page.jpg", photo)}))["index"]


async def set_code(record_id: str, code: str) -> str:
    return (await _call("POST", f"/api/records/{record_id}/code", json={"code": code}))["patientCode"]


async def get_final(record_id: str) -> dict:
    """Résultat final stocké par l'API à la validation (complété par la patiente choisie)."""
    return await _call("GET", f"/api/records/{record_id}/final")


async def get_record(record_id: str) -> dict:
    return await _call("GET", f"/api/records/{record_id}")


async def wait_until_read(record_id: str, pages: int = 1) -> dict:
    """Attend la fin de la lecture (l'API lit en arrière-plan, une page à la fois)."""
    deadline = time.monotonic() + get_settings().READ_TIMEOUT_PER_PAGE * max(pages, 1)
    while True:
        record = await get_record(record_id)
        if record["state"] in READ_STATES and not record.get("busy"):
            return record
        if time.monotonic() > deadline:
            logger.error("Reading of %s timed out (state=%s)", record_id, record["state"])
            raise ApiError("La lecture prend plus de temps que prévu. Le dossier reste visible sur le tableau de bord.")
        await asyncio.sleep(POLL_SECONDS)


async def replace_page(record_id: str, index: int, photo: tuple[bytes, str]) -> None:
    await _call("POST", f"/api/records/{record_id}/pages/{index}/photo", files={"file": _file("page.jpg", photo)})


async def drop_page(record_id: str, index: int) -> None:
    await _call("POST", f"/api/records/{record_id}/pages/{index}/drop")


async def set_field(record_id: str, index: int, key: str, phone: str, value, status: str) -> dict:
    body = {"by": midwife_id(phone), "value": value, "status": status}
    return await _call("POST", f"/api/records/{record_id}/pages/{index}/fields/{key}", json=body)


async def add_field(record_id: str, index: int, phone: str, label: str, value: str) -> dict:
    body = {"by": midwife_id(phone), "label": label, "value": value}
    return await _call("POST", f"/api/records/{record_id}/pages/{index}/fields", json=body)


async def get_pdf(record_id: str) -> tuple[bytes, str]:
    """Fiche PDF du dossier validé (octets, nom de fichier proposé par l'API)."""
    async with _client(timeout=60.0) as client:
        try:
            response = await client.get(f"/api/records/{record_id}/pdf")
        except httpx.HTTPError as exc:
            logger.error("DayOne API unreachable (GET pdf): %s", exc)
            raise ApiError("La fiche PDF n'a pas pu être préparée.") from exc
    if response.status_code != 200:
        logger.error("DayOne API error %s on GET pdf: %s", response.status_code, response.text[:200])
        raise ApiError("La fiche PDF n'a pas pu être préparée.")
    match = re.search(r'filename="([^"]+)"', response.headers.get("content-disposition", ""))
    return response.content, match.group(1) if match else f"DayOne_{record_id}.pdf"


async def confirm_field(record_id: str, index: int, key: str, phone: str) -> dict:
    body = {"by": midwife_id(phone), "confirm": True}
    return await _call("POST", f"/api/records/{record_id}/pages/{index}/fields/{key}", json=body)


async def validate(record_id: str) -> None:
    await _call("POST", f"/api/records/{record_id}/validate")


async def candidates(record_id: str) -> list[dict]:
    return await _call("GET", f"/api/records/{record_id}/candidates")


async def link(record_id: str, decision: str, patient_id: str | None = None) -> None:
    await _call("POST", f"/api/records/{record_id}/link", json={"decision": decision, "patient_id": patient_id})
