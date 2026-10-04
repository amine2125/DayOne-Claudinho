"""Conversation WhatsApp autour d'un registre : photos → lecture → vérification → confirmation.

États d'une conversation (un par numéro) :

    IDLE ──photo──▶ COLLECTING ──« Terminé »──▶ lecture ──▶ REVIEW (page i/n)
                     (photos suivantes)                       │ 1 Confirmer → page suivante ou fin
                                                              │ 2 Corriger  → CHOOSE_FIELD → EDIT_VALUE → REVIEW
                                                              │ 3 Voir      → liste des valeurs → REVIEW
                                                              │ 4 Reprendre → RETAKE ──photo──▶ REVIEW
                                                              └ 5 Ignorer (page illisible seulement)

« annuler » remet la conversation à zéro depuis n'importe quel état.
Les sessions vivent en mémoire : un redémarrage du serveur les efface.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum

from app import render
from app.backend import AnalysisError, analyze_page, save_record
from app.config import get_settings
from app.security import mask_phone
from app.whatsapp import download_media, send_buttons, send_text

logger = logging.getLogger(__name__)

BTN_DONE = "btn_done"
BTN_CANCEL = "btn_cancel"
COLLECT_BUTTONS = [(BTN_DONE, "✅ Terminé"), (BTN_CANCEL, "❌ Annuler")]

DONE_WORDS = {BTN_DONE, "terminé", "termine", "terminer", "fini", "fin", "ok", "c'est tout"}
CANCEL_WORDS = {BTN_CANCEL, "annuler", "/annuler", "stop"}
HELP_WORDS = {"/aide", "/help", "/start", "aide"}
BACK = "0"
# Dans la saisie d'une valeur, « 0 » peut être une vraie réponse (0 avortement) : on revient avec « retour »
BACK_WORD = "retour"


class State(str, Enum):
    IDLE = "idle"
    COLLECTING = "collecting"
    REVIEW = "review"
    CHOOSE_FIELD = "choose_field"
    EDIT_VALUE = "edit_value"
    RETAKE = "retake"


@dataclass
class Session:
    state: State = State.IDLE
    photos: list[tuple[bytes, str, str | None]] = field(default_factory=list)  # (octets, mime, légende)
    pages: list[dict] = field(default_factory=list)  # pages lues ; une page en échec porte "error"
    current: int = 0
    edit_field: render.FieldDef | None = None
    updated_at: float = field(default_factory=time.time)

    @property
    def page(self) -> dict:
        return self.pages[self.current]


_sessions: dict[str, Session] = {}
_locks: dict[str, asyncio.Lock] = {}


def get_session(phone: str) -> Session:
    session = _sessions.get(phone)
    if session is None or time.time() - session.updated_at > get_settings().SESSION_TTL_SECONDS:
        session = _sessions[phone] = Session()
    session.updated_at = time.time()
    return session


def reset_session(phone: str) -> None:
    _sessions.pop(phone, None)


def _lock(phone: str) -> asyncio.Lock:
    # Un message à la fois par utilisateur : deux photos envoyées d'un coup ne se marchent pas dessus
    return _locks.setdefault(phone, asyncio.Lock())


def parse_choice(text: str) -> int | None:
    """« 2 », « 2. », « 2️⃣ » → 2 ; sinon None."""
    clean = text.replace("️", "").replace("⃣", "").strip().rstrip(".)")
    return int(clean) if re.fullmatch(r"\d{1,3}", clean) else None


# --- Textes fixes ---

HELP_TEXT = (
    "🤖 *Assistant registre DayOne*\n\n"
    "📸 Envoyez la photo d'une page du registre (une ou plusieurs pages), puis appuyez sur *Terminé*.\n"
    "Je lis chaque page, puis vous pouvez :\n"
    "1️⃣ confirmer · 2️⃣ corriger un champ · 3️⃣ voir les valeurs · 4️⃣ reprendre la photo\n\n"
    "⚙️ *Commandes* : */aide* · */status* · *annuler*"
)
STATUS_TEXT = "🟢 *Service en ligne* : le bot WhatsApp est opérationnel."
GREETING_TEXT = (
    "👋 Bonjour ! Envoyez la photo d'une page du registre pour commencer.\n"
    "Tapez */aide* pour en savoir plus."
)


# --- Points d'entrée ---

async def handle_text(phone: str, text: str) -> None:
    """Message texte ou clic sur un bouton (son id arrive comme texte)."""
    async with _lock(phone):
        await _handle_text(phone, text)


async def handle_image(phone: str, media_id: str, caption: str | None) -> None:
    # Téléchargement immédiat, hors verrou : l'URL Meta expire après ~5 minutes
    try:
        image = await download_media(media_id)
    except Exception as exc:
        logger.error("Media download failed for %s: %s", mask_phone(phone), exc)
        await send_text(to=phone, body="⚠️ Impossible de récupérer la photo. Renvoyez-la, s'il vous plaît.")
        return
    async with _lock(phone):
        await _handle_image(phone, image, caption)


# --- Texte ---

async def _handle_text(phone: str, text: str) -> None:
    session = get_session(phone)
    norm = text.strip().lower()

    if norm in HELP_WORDS:
        await send_text(to=phone, body=HELP_TEXT)
        return
    if norm == "/status":
        await send_text(to=phone, body=STATUS_TEXT)
        return
    if norm in CANCEL_WORDS:
        had_work = session.state != State.IDLE
        reset_session(phone)
        await send_text(
            to=phone,
            body="🗑️ Registre annulé. Envoyez une photo pour recommencer." if had_work
            else "Rien à annuler. Envoyez une photo pour commencer.",
        )
        return
    if norm.startswith("/"):
        await send_text(
            to=phone,
            body=f"❓ Commande inconnue `{norm.split()[0]}`. Tapez */aide* pour voir les commandes.",
        )
        return

    if session.state == State.IDLE:
        await send_text(to=phone, body=GREETING_TEXT)
    elif session.state == State.COLLECTING:
        if norm in DONE_WORDS:
            await _read_pages(phone, session)
        else:
            await send_buttons(
                phone,
                f"📄 {len(session.photos)} page(s) reçue(s). Envoyez la page suivante, "
                "ou appuyez sur *Terminé* pour lancer la lecture.",
                COLLECT_BUTTONS,
            )
    elif session.state == State.REVIEW:
        await _on_menu_choice(phone, session, text)
    elif session.state == State.CHOOSE_FIELD:
        await _on_field_choice(phone, session, text)
    elif session.state == State.EDIT_VALUE:
        await _on_new_value(phone, session, text)
    elif session.state == State.RETAKE:
        if norm in (BACK, BACK_WORD) and "error" not in session.page:
            session.state = State.REVIEW
            await _send_current_page(phone, session)
        else:
            back = " Tapez *0* pour revenir au menu." if "error" not in session.page else ""
            await send_text(to=phone, body=f"📷 J'attends la nouvelle photo de la page {session.current + 1}.{back}")


# --- Photos ---

async def _handle_image(phone: str, image: tuple[bytes, str], caption: str | None) -> None:
    session = get_session(phone)
    image_bytes, mime_type = image

    if session.state in (State.IDLE, State.COLLECTING):
        if len(session.photos) >= get_settings().MAX_PAGES:
            await send_buttons(
                phone,
                f"⚠️ {get_settings().MAX_PAGES} pages au maximum par registre. Appuyez sur *Terminé* pour lancer la lecture.",
                COLLECT_BUTTONS,
            )
            return
        session.photos.append((image_bytes, mime_type, caption))
        session.state = State.COLLECTING
        await send_buttons(
            phone,
            f"📄 Page {len(session.photos)} reçue. Envoyez les pages suivantes du même registre, "
            "puis appuyez sur *Terminé*.",
            COLLECT_BUTTONS,
        )
    elif session.state == State.RETAKE:
        await send_text(to=phone, body=f"🔎 Nouvelle photo reçue, je relis la page {session.current + 1}…")
        session.pages[session.current] = await _analyze(phone, image_bytes, mime_type, caption)
        session.state = State.REVIEW
        await _send_current_page(phone, session)
    else:
        await send_text(
            to=phone,
            body=f"📷 Une vérification est en cours (page {session.current + 1}/{len(session.pages)}). "
                 "Terminez-la d'abord, ou tapez *annuler* pour recommencer.",
        )


async def _analyze(phone: str, image_bytes: bytes, mime_type: str, caption: str | None) -> dict:
    try:
        return await analyze_page(image_bytes, mime_type, phone, caption)
    except AnalysisError as exc:
        return {"error": str(exc)}


async def _read_pages(phone: str, session: Session) -> None:
    photos, session.photos = session.photos, []  # on libère les images dès la lecture
    await send_text(
        to=phone,
        body=f"📂 {len(photos)} page(s) regroupée(s) en un seul registre. Je les lis et je reviens vers vous…",
    )
    session.pages = [await _analyze(phone, *photo) for photo in photos]
    session.current = 0
    session.state = State.REVIEW
    await _send_current_page(phone, session)


async def _send_current_page(phone: str, session: Session) -> None:
    total = len(session.pages)
    if "error" in session.page:
        body = render.failed_page_text(session.page, session.current, total)
    else:
        body = render.review_text(session.page, session.current, total)
    await send_text(to=phone, body=body)


# --- Menu d'une page ---

async def _on_menu_choice(phone: str, session: Session, text: str) -> None:
    choice = parse_choice(text)
    failed = "error" in session.page
    valid = (4, 5) if failed else (1, 2, 3, 4)

    if choice not in valid:
        options = ", ".join(str(v) for v in valid[:-1]) + f" ou {valid[-1]}"
        await send_text(to=phone, body=f"❌ « {text.strip()[:30]} » n'est pas une des options proposées. Répondez {options}.")
        await _send_current_page(phone, session)
        return

    if choice == 1:
        session.page["confirmed"] = True
        await _next_page(phone, session, f"✅ Page {session.current + 1} confirmée.")
    elif choice == 2:
        session.state = State.CHOOSE_FIELD
        await send_text(to=phone, body=_field_list_text(session.page))
    elif choice == 3:
        await send_text(
            to=phone,
            body=f"📋 *Valeurs lues · page {session.current + 1}/{len(session.pages)}*\n\n{render.values_text(session.page)}",
        )
        await _send_current_page(phone, session)
    elif choice == 4:
        session.state = State.RETAKE
        back = "\nTapez *0* pour revenir au menu." if not failed else ""
        await send_text(
            to=phone,
            body=f"📷 Envoyez une nouvelle photo de la page {session.current + 1} (bien à plat, sans reflet).{back}",
        )
    elif choice == 5:
        session.pages.pop(session.current)
        if not session.pages:
            reset_session(phone)
            await send_text(to=phone, body="🗑️ Page ignorée. Aucune page à enregistrer : envoyez une photo pour recommencer.")
            return
        await _next_page(phone, session, "🗑️ Page ignorée.", advance=False)


async def _next_page(phone: str, session: Session, note: str, advance: bool = True) -> None:
    if advance:
        session.current += 1
    if session.current < len(session.pages):
        session.state = State.REVIEW
        await send_text(to=phone, body=note)
        await _send_current_page(phone, session)
        return

    # Toutes les pages sont confirmées : on enregistre puis on envoie le récapitulatif
    if not advance:
        await send_text(to=phone, body=note)  # « Page ignorée » : sinon l'utilisateur ne le saurait pas
    if not await save_record(phone, session.pages):
        session.current = len(session.pages) - 1
        session.state = State.REVIEW
        await send_text(
            to=phone,
            body="⚠️ Le registre n'a pas pu être enregistré. Répondez *1* pour réessayer, ou *annuler*.",
        )
        return
    logger.info("Record confirmed by %s (%d page(s))", mask_phone(phone), len(session.pages))
    await send_text(to=phone, body=render.final_text(session.pages))
    reset_session(phone)


# --- Correction d'un champ ---

def _field_list_text(page: dict, include_empty: bool = False) -> str:
    footer = "\n\nTapez *0* pour revenir au menu."
    if not include_empty:
        footer = "\n\nTapez *tout* pour voir aussi les champs vides, *0* pour revenir au menu."
    return (
        "✏️ *Quel champ corriger ?* Répondez avec son numéro.\n"
        "(⚠️ = à vérifier)\n\n"
        f"{render.values_text(page, include_empty=include_empty)}{footer}"
    )


async def _on_field_choice(phone: str, session: Session, text: str) -> None:
    norm = text.strip().lower()
    if norm in (BACK, BACK_WORD):
        session.state = State.REVIEW
        await _send_current_page(phone, session)
        return
    if norm == "tout":
        await send_text(to=phone, body=_field_list_text(session.page, include_empty=True))
        return

    pdef = render.page_def_for(session.page)
    number = parse_choice(text)
    fdef = pdef.by_number(number) if number is not None else None
    if fdef is None:
        await send_text(
            to=phone,
            body=f"❌ « {text.strip()[:30]} » n'est pas un numéro de champ de cette page (1 à {len(pdef.fields)}). "
                 "Répondez avec le numéro, ou *0* pour revenir.",
        )
        return

    session.edit_field = fdef
    session.state = State.EDIT_VALUE
    current = render.format_value(fdef.kind, session.page["fields"].get(fdef.id, {}))
    await send_text(
        to=phone,
        body=f"✏️ *{fdef.label}* (actuel : {current})\n"
             f"Envoyez la nouvelle valeur : {render.KIND_HINTS.get(fdef.kind, 'une valeur')}.\n"
             "Tapez *?* si l'information est inconnue, *-* si la case est vide, *retour* pour revenir.",
    )


async def _on_new_value(phone: str, session: Session, text: str) -> None:
    fdef = session.edit_field
    if text.strip().lower() == BACK_WORD or fdef is None:
        session.state = State.REVIEW
        session.edit_field = None
        await _send_current_page(phone, session)
        return
    try:
        value, status = render.parse_value(fdef.kind, text)
    except ValueError as exc:
        await send_text(
            to=phone,
            body=f"❌ Format non reconnu pour *{fdef.label}*. Attendu : {exc}.\nRéessayez, ou tapez *retour* pour revenir.",
        )
        return

    fields = session.page["fields"]
    previous = fields.get(fdef.id, {}).get("value")
    fields[fdef.id] = {"value": value, "status": status, "confidence": 1.0, "source": "sage-femme", "previous": previous}
    session.state = State.REVIEW
    session.edit_field = None
    await send_text(to=phone, body=f"✅ *{fdef.label}* : {render.format_value(fdef.kind, fields[fdef.id])}")
    await _send_current_page(phone, session)
