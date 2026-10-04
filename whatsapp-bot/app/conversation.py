"""Conversation WhatsApp autour d'un registre, branchée sur l'API DayOne (api/main.py).

Chaque photo est envoyée à l'API dès sa réception : enregistrée (chiffrée) dans la base, puis lue
en arrière-plan pendant que la sage-femme photographie la page suivante.

    IDLE ──photo──▶ COLLECTING (dossier créé, photos suivantes ajoutées) ──« Terminé »──▶ fin de la lecture
         ──▶ ASK_CODE (code lu sur la page proposé) ──code──▶ REVIEW (page i/n)
      1 Confirmer ── page suivante, ou fin ──▶ validation (résultat final stocké) ──▶ LINK (patiente)
                                           ──▶ récapitulatif tiré du résultat final + fiche PDF (document à télécharger)
                 └─ s'il reste des doutes : CONFIRM_UNCERTAIN (1 confirmer tels quels / 2 corriger)
      2 Corriger  ──▶ CHOOSE_FIELD ──numéro──▶ EDIT_VALUE ──valeur──▶ REVIEW
      3 Voir      ──▶ liste des valeurs ──▶ REVIEW
      4 Reprendre ──▶ RETAKE ──photo──▶ relecture de cette page seule ──▶ REVIEW
      5 Ajouter   ──▶ ADD_LABEL ──nom du champ──▶ ADD_VALUE ──valeur──▶ REVIEW   (champ oublié par la lecture)
      5 Ignorer   (page illisible seulement)

Tous les choix sont cliquables (boutons jusqu'à 3 options, liste au-delà) ; taper le chiffre marche aussi.

Tout ce que la sage-femme fait passe par l'API : le tableau de bord voit le dossier en direct.
« annuler » remet la conversation à zéro ; un dossier déjà créé reste « à vérifier » sur le tableau de bord.
Les sessions vivent en mémoire : un redémarrage du bot les efface (pas les dossiers).
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum

from app import backend, render
from app.backend import ApiError
from app.config import get_settings
from app.security import mask_phone
from app.whatsapp import download_media, send_buttons, send_document, send_list, send_text

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
CODE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 \-_/]{0,19}")

# Menus cliquables : (id renvoyé au clic, titre). L'id est le chiffre qu'on pourrait aussi taper.
REVIEW_MENU = [("1", "✅ Confirmer la page"), ("2", "✏️ Corriger un champ"), ("3", "📋 Voir les valeurs"),
               ("4", "📷 Reprendre la photo"), ("5", "➕ Ajouter un champ")]
UNCERTAIN_MENU = [("1", "✅ Tout est vérifié"), ("2", "✏️ Corriger")]
MAX_BODY = 1000           # texte d'un message cliquable (limite Meta : 1024)
MAX_FIELD_ROWS = 8        # lignes « champ » dans la liste de correction (10 lignes au plus en tout)


class State(str, Enum):
    IDLE = "idle"
    COLLECTING = "collecting"
    ASK_CODE = "ask_code"
    REVIEW = "review"
    CONFIRM_UNCERTAIN = "confirm_uncertain"
    CHOOSE_FIELD = "choose_field"
    EDIT_VALUE = "edit_value"
    RETAKE = "retake"
    ADD_LABEL = "add_label"
    ADD_VALUE = "add_value"
    LINK = "link"


@dataclass
class Session:
    state: State = State.IDLE
    record_id: str | None = None      # dossier créé dès la 1re photo
    sent: int = 0                     # pages envoyées à l'API
    record: dict | None = None        # dernier état du dossier renvoyé par l'API (après lecture)
    current: int = 0                  # position de la page affichée dans record["pages"]
    edit_key: str | None = None
    new_label: str | None = None      # champ en cours d'ajout
    candidates: list[dict] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)

    @property
    def page(self) -> dict:
        return self.record["pages"][self.current]

    @property
    def total(self) -> int:
        return len(self.record["pages"]) if self.record else 0


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
    "📸 Envoyez la photo d'une page du registre (une ou plusieurs pages) : chacune est enregistrée et lue "
    "dès sa réception. Appuyez ensuite sur *Terminé* et donnez le code patiente écrit sur le registre.\n"
    "Je lis chaque page, puis vous pouvez (boutons cliquables) :\n"
    "✅ confirmer · ✏️ corriger un champ · 📋 voir les valeurs · 📷 reprendre la photo · ➕ ajouter un champ oublié\n\n"
    "⚙️ *Commandes* : */aide* · */status* · *annuler*"
)
STATUS_TEXT = "🟢 *Service en ligne* : le bot WhatsApp est opérationnel."
GREETING_TEXT = (
    "👋 Bonjour ! Envoyez la photo d'une page du registre pour commencer.\n"
    "Tapez */aide* pour en savoir plus."
)


async def _menu(phone: str, body: str, options: list[tuple[str, str]], button: str = "Choisir") -> None:
    """Choix cliquables : 3 options au plus → boutons, sinon liste. Un texte trop long part à part."""
    if len(body) > MAX_BODY:
        await send_text(to=phone, body=body)
        body = "👇 Choisissez :"
    if len(options) <= 3:
        await send_buttons(phone, body, options)
    else:
        await send_list(phone, body, button, options)


# --- Points d'entrée ---

async def handle_text(phone: str, text: str) -> None:
    """Message texte ou clic sur un bouton (son id arrive comme texte)."""
    async with _lock(phone):
        try:
            await _handle_text(phone, text)
        except ApiError as exc:
            await send_text(to=phone, body=f"⚠️ {exc}")


async def handle_image(phone: str, media_id: str, caption: str | None) -> None:
    # Téléchargement immédiat, hors verrou : l'URL Meta expire après ~5 minutes
    try:
        image = await download_media(media_id)
    except Exception as exc:
        logger.error("Media download failed for %s: %s", mask_phone(phone), exc)
        await send_text(to=phone, body="⚠️ Impossible de récupérer la photo. Renvoyez-la, s'il vous plaît.")
        return
    async with _lock(phone):
        try:
            await _handle_image(phone, image)
        except ApiError as exc:
            await send_text(to=phone, body=f"⚠️ {exc}")


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
        had_record = session.record_id is not None
        had_work = session.state != State.IDLE
        reset_session(phone)
        if had_record:
            body = "🗑️ Conversation annulée. Le dossier reste « à vérifier » sur le tableau de bord."
        elif had_work:
            body = "🗑️ Registre annulé. Envoyez une photo pour recommencer."
        else:
            body = "Rien à annuler. Envoyez une photo pour commencer."
        await send_text(to=phone, body=body)
        return
    if norm.startswith("/"):
        await send_text(
            to=phone,
            body=f"❓ Commande inconnue `{norm.split()[0]}`. Tapez */aide* pour voir les commandes.",
        )
        return

    handlers = {
        State.IDLE: _on_idle_text,
        State.COLLECTING: _on_collecting_text,
        State.ASK_CODE: _on_code,
        State.REVIEW: _on_menu_choice,
        State.CONFIRM_UNCERTAIN: _on_confirm_uncertain,
        State.CHOOSE_FIELD: _on_field_choice,
        State.EDIT_VALUE: _on_new_value,
        State.RETAKE: _on_retake_text,
        State.ADD_LABEL: _on_add_label,
        State.ADD_VALUE: _on_add_value,
        State.LINK: _on_link_choice,
    }
    await handlers[session.state](phone, session, text)


async def _on_idle_text(phone: str, session: Session, text: str) -> None:
    await send_text(to=phone, body=GREETING_TEXT)


async def _on_collecting_text(phone: str, session: Session, text: str) -> None:
    if text.strip().lower() not in DONE_WORDS:
        await send_buttons(
            phone,
            f"📄 {session.sent} page(s) enregistrée(s). Envoyez la page suivante, "
            "ou appuyez sur *Terminé* quand le registre est complet.",
            COLLECT_BUTTONS,
        )
        return
    await send_text(
        to=phone,
        body=f"📂 {session.sent} page(s) regroupée(s) en un seul registre. Je termine la lecture et je reviens vers vous…",
    )
    session.record = await backend.wait_until_read(session.record_id, session.sent)
    session.current = 0
    session.state = State.ASK_CODE
    await _ask_code(phone, session)


async def _ask_code(phone: str, session: Session) -> None:
    suggestion = session.record.get("codeSuggestion")
    if suggestion:
        await _menu(phone, f"🔖 Code patiente lu sur le registre : *{suggestion}*\n"
                           "Gardez-le, ou tapez le bon code.", [("1", "✅ Garder ce code")])
    else:
        await send_text(to=phone, body="🔖 Quel est le *code patiente* écrit sur le registre ?")


async def _on_code(phone: str, session: Session, text: str) -> None:
    suggestion = session.record.get("codeSuggestion")
    code = suggestion if suggestion and parse_choice(text) == 1 else text.strip()
    if not CODE_PATTERN.fullmatch(code):
        await send_text(
            to=phone,
            body="❌ Ce code n'est pas valide. Tapez le code patiente tel qu'écrit sur le registre "
                 "(lettres et chiffres, 20 caractères au plus), ou *annuler*.",
        )
        return
    await backend.set_code(session.record_id, code)
    await _refresh(session)
    await _show_page(phone, session)


async def _on_retake_text(phone: str, session: Session, text: str) -> None:
    norm = text.strip().lower()
    if norm in (BACK, BACK_WORD) and "error" not in session.page:
        await _show_page(phone, session)
        return
    back = " Tapez *0* pour revenir au menu." if "error" not in session.page else ""
    await send_text(to=phone, body=f"📷 J'attends la nouvelle photo de la page {session.current + 1}.{back}")


# --- Photos ---

async def _handle_image(phone: str, image: tuple[bytes, str]) -> None:
    session = get_session(phone)

    if session.state in (State.IDLE, State.COLLECTING):
        if session.sent >= get_settings().MAX_PAGES:
            await send_buttons(
                phone,
                f"⚠️ {get_settings().MAX_PAGES} pages au maximum par registre. Appuyez sur *Terminé*.",
                COLLECT_BUTTONS,
            )
            return
        # Enregistrée tout de suite dans la base (chiffrée) ; l'API la lit en arrière-plan
        if session.record_id is None:
            session.record_id = await backend.create_record(image, phone)
            logger.info("Record %s created by %s", session.record_id, mask_phone(phone))
        else:
            await backend.add_page(session.record_id, image)
        session.sent += 1
        session.state = State.COLLECTING
        await send_buttons(
            phone,
            f"📄 Page {session.sent} reçue et enregistrée, lecture en cours. "
            "Envoyez les pages suivantes du même registre, puis appuyez sur *Terminé*.",
            COLLECT_BUTTONS,
        )
    elif session.state == State.RETAKE:
        index = session.page["index"]
        await send_text(to=phone, body=f"🔎 Nouvelle photo reçue, je relis la page {session.current + 1}…")
        await backend.replace_page(session.record_id, index, image)
        await _refresh(session, wait=True)
        await _show_page(phone, session)
    elif session.state == State.ASK_CODE:
        await send_text(to=phone, body="🔖 J'attends d'abord le *code patiente* écrit sur le registre.")
    else:
        where = f" (page {session.current + 1}/{session.total})" if session.record else ""
        await send_text(
            to=phone,
            body=f"📷 Une vérification est en cours{where}. Terminez-la d'abord, "
                 "ou tapez *annuler* pour recommencer.",
        )


async def _refresh(session: Session, wait: bool = False) -> None:
    record_id = session.record_id
    session.record = await (backend.wait_until_read(record_id) if wait else backend.get_record(record_id))
    session.current = min(session.current, session.total - 1)


async def _show_page(phone: str, session: Session) -> None:
    session.state = State.REVIEW
    if "error" in session.page or not session.page.get("fields"):
        can_drop = session.total > 1
        body = render.failed_page_text(session.page, session.current, session.total, can_drop=can_drop)
        options = [("4", "📷 Reprendre la photo")] + ([("5", "🗑️ Ignorer la page")] if can_drop else [])
        await _menu(phone, body, options)
    else:
        await _menu(phone, render.review_text(session.page, session.current, session.total), REVIEW_MENU,
                    button="Que faire ?")


# --- Menu d'une page ---

async def _on_menu_choice(phone: str, session: Session, text: str) -> None:
    choice = parse_choice(text)
    failed = "error" in session.page or not session.page.get("fields")
    valid = ((4, 5) if session.total > 1 else (4,)) if failed else (1, 2, 3, 4, 5)

    if choice not in valid:
        options = " ou ".join(str(v) for v in valid) if len(valid) <= 2 else \
            ", ".join(str(v) for v in valid[:-1]) + f" ou {valid[-1]}"
        await send_text(to=phone, body=f"❌ « {text.strip()[:30]} » n'est pas une des options proposées. Répondez {options}.")
        await _show_page(phone, session)
        return

    if choice == 1:
        if render.uncertain(session.page):
            session.state = State.CONFIRM_UNCERTAIN
            await _menu(phone, render.confirm_uncertain_text(session.page), UNCERTAIN_MENU)
            return
        await _next_page(phone, session)
    elif choice == 2:
        await _ask_field(phone, session)
    elif choice == 3:
        await send_text(
            to=phone,
            body=f"📋 *Valeurs lues · page {session.current + 1}/{session.total}*\n\n{render.values_text(session.page)}",
        )
        await _show_page(phone, session)
    elif choice == 4:
        session.state = State.RETAKE
        back = "\nTapez *0* pour revenir au menu." if not failed else ""
        await send_text(
            to=phone,
            body=f"📷 Envoyez une nouvelle photo de la page {session.current + 1} (bien à plat, sans reflet).{back}",
        )
    elif choice == 5 and not failed:
        session.state = State.ADD_LABEL
        await send_text(
            to=phone,
            body="➕ *Nom du champ à ajouter*, tel qu'écrit sur la page (ex. « Groupe sanguin »).\n"
                 "Tapez *retour* pour revenir.",
        )
    elif choice == 5:
        was_last = session.current == session.total - 1
        await backend.drop_page(session.record_id, session.page["index"])
        await _refresh(session)
        await send_text(to=phone, body="🗑️ Page ignorée.")
        if was_last:
            await _finish(phone, session)   # les pages d'avant sont déjà confirmées
        else:
            await _show_page(phone, session)  # la page suivante a pris sa place


async def _on_confirm_uncertain(phone: str, session: Session, text: str) -> None:
    choice = parse_choice(text)
    if choice == 1:
        # La sage-femme a regardé le registre : les valeurs douteuses sont confirmées telles quelles
        for nf in render.uncertain(session.page):
            await backend.confirm_field(session.record_id, session.page["index"], nf.key, phone)
        await _refresh(session)
        await _next_page(phone, session)
    elif choice == 2:
        await _ask_field(phone, session)
    else:
        await send_text(to=phone, body=f"❌ « {text.strip()[:30]} » n'est pas une des options proposées. Répondez 1 ou 2.")
        await _menu(phone, render.confirm_uncertain_text(session.page), UNCERTAIN_MENU)


async def _next_page(phone: str, session: Session) -> None:
    if session.current + 1 < session.total:
        session.current += 1
        await send_text(to=phone, body=f"✅ Page {session.current} confirmée.")
        await _show_page(phone, session)
        return
    await _finish(phone, session)


async def _finish(phone: str, session: Session) -> None:
    """Toutes les pages sont vues : le dossier est validé, puis rattaché à une patiente (choix explicite)."""
    await backend.validate(session.record_id)
    session.candidates = await backend.candidates(session.record_id)
    session.state = State.LINK
    await _link_menu(phone, session)


async def _link_menu(phone: str, session: Session) -> None:
    n = len(session.candidates[:8])
    rows = [(str(i), f"👤 {c['code']}") for i, c in enumerate(session.candidates[:8], start=1)]
    rows += [(str(n + 1), "➕ Nouvelle patiente" if n else "➕ Créer la patiente"), (str(n + 2), "❓ Je ne sais pas")]
    await _menu(phone, render.link_text(session.record.get("patientCode", ""), session.candidates), rows,
                button="Choisir la patiente")


# --- Patiente ---

async def _on_link_choice(phone: str, session: Session, text: str) -> None:
    session.candidates = session.candidates[:8]   # celles proposées dans la liste cliquable
    n = len(session.candidates)
    choice = parse_choice(text)
    create, unsure = (n + 1, n + 2) if n else (1, 2)
    if choice is None or not 1 <= choice <= unsure:
        await send_text(to=phone, body=f"❌ « {text.strip()[:30]} » n'est pas une des options proposées. Répondez de 1 à {unsure}.")
        await _link_menu(phone, session)
        return

    record_id = session.record_id
    if choice == create:
        await backend.link(record_id, "CREATE")
    elif choice == unsure:
        await backend.link(record_id, "UNSURE")
    else:
        await backend.link(record_id, "EXISTING", session.candidates[choice - 1]["patientId"])
    final = await backend.get_final(record_id)   # le résultat final stocké par l'API
    body = render.final_text(final)
    if choice == unsure:
        body += "\n👤 Patiente à confirmer plus tard sur le tableau de bord."
    logger.info("Record %s validated by %s", record_id, mask_phone(phone))
    await send_text(to=phone, body=body)
    await _send_pdf(phone, record_id)
    reset_session(phone)


async def _send_pdf(phone: str, record_id: str) -> None:
    """La fiche du dossier en PDF (mise en page propre, à ouvrir et télécharger)."""
    try:
        data, filename = await backend.get_pdf(record_id)
        await send_document(phone, data, filename, caption="📄 Fiche du dossier (PDF) : appuyez pour l'ouvrir ou la télécharger.")
    except Exception as exc:   # Meta ou l'API indisponible : le dossier est déjà enregistré, on prévient seulement
        logger.error("PDF not sent for %s: %s", record_id, exc)
        await send_text(to=phone, body="⚠️ La fiche PDF n'a pas pu être envoyée. Elle reste disponible sur le tableau de bord.")


# --- Correction d'un champ ---

async def _ask_field(phone: str, session: Session, include_empty: bool = False) -> None:
    """Liste numérotée des champs (texte), puis une liste cliquable : champs à vérifier d'abord."""
    session.state = State.CHOOSE_FIELD
    await send_text(
        to=phone,
        body="✏️ *Quel champ corriger ?* Choisissez-le ci-dessous, ou tapez son numéro.\n(⚠️ = à vérifier)\n\n"
             f"{render.values_text(session.page, include_empty=include_empty)}",
    )
    shown = [nf for nf in render.numbered_fields(session.page)
             if include_empty or nf.field.get("status") in render.SHOWN_STATUSES]
    first = sorted(shown, key=lambda nf: nf.field.get("status") not in render.UNCERTAIN_STATUSES)[:MAX_FIELD_ROWS]
    rows = [(str(nf.number), f"{'⚠️ ' if nf.field.get('status') in render.UNCERTAIN_STATUSES else ''}"
                             f"{nf.number}. {nf.label}") for nf in first]
    rows.append(("0", "↩️ Retour au menu") if include_empty else ("tout", "📋 Voir aussi les vides"))
    if not include_empty:
        rows.append(("0", "↩️ Retour au menu"))
    await _menu(phone, "👇 Champ à corriger :", rows, button="Choisir le champ")


async def _on_field_choice(phone: str, session: Session, text: str) -> None:
    norm = text.strip().lower()
    if norm in (BACK, BACK_WORD):
        await _show_page(phone, session)
        return
    if norm == "tout":
        await _ask_field(phone, session, include_empty=True)
        return

    number = parse_choice(text)
    nf = render.by_number(session.page, number) if number is not None else None
    if nf is None:
        total = len(render.numbered_fields(session.page))
        await send_text(
            to=phone,
            body=f"❌ « {text.strip()[:30]} » n'est pas un numéro de champ de cette page (1 à {total}). "
                 "Répondez avec le numéro, ou *0* pour revenir.",
        )
        return

    session.edit_key = nf.key
    session.state = State.EDIT_VALUE
    options = nf.field.get("options")
    choices = f"\nCases sur la page : {', '.join(options)}." if options else ""
    await send_text(
        to=phone,
        body=f"✏️ *{nf.label}* (actuel : {render.format_value(nf.kind, nf.field)}){choices}\n"
             f"Envoyez la nouvelle valeur : {render.KIND_HINTS.get(nf.kind, 'une valeur')}.\n"
             "Tapez *?* si l'information est inconnue, *-* si la case est vide, *retour* pour revenir.",
    )


async def _on_new_value(phone: str, session: Session, text: str) -> None:
    key = session.edit_key
    fields = session.page.get("fields", {})
    if text.strip().lower() == BACK_WORD or key not in fields:
        session.edit_key = None
        await _show_page(phone, session)
        return
    nf = next(f for f in render.numbered_fields(session.page) if f.key == key)
    try:
        value, status = render.parse_value(nf.kind, text)
    except ValueError as exc:
        await send_text(
            to=phone,
            body=f"❌ Format non reconnu pour *{nf.label}*. Attendu : {exc}.\nRéessayez, ou tapez *retour* pour revenir.",
        )
        return

    updated = await backend.set_field(session.record_id, session.page["index"], key, phone, value, status)
    fields[key] = updated
    session.edit_key = None
    await send_text(to=phone, body=f"✅ *{nf.label}* : {render.format_value(nf.kind, updated)}")
    await _show_page(phone, session)


# --- Ajout d'un champ oublié par la lecture ---

async def _on_add_label(phone: str, session: Session, text: str) -> None:
    label = " ".join(text.split())
    if label.lower() == BACK_WORD:
        await _show_page(phone, session)
        return
    if not 2 <= len(label) <= 80:
        await send_text(to=phone, body="❌ Nom de champ entre 2 et 80 caractères, s'il vous plaît (ou *retour*).")
        return
    session.new_label = label
    session.state = State.ADD_VALUE
    await send_text(
        to=phone,
        body=f"✏️ Valeur de *{label}* sur la page ?\nTapez *?* si l'information est inconnue, *-* si le champ est vide, "
             "*retour* pour revenir.",
    )


async def _on_add_value(phone: str, session: Session, text: str) -> None:
    label = session.new_label
    if text.strip().lower() == BACK_WORD or not label:
        session.new_label = None
        await _show_page(phone, session)
        return
    session.new_label = None
    try:
        added = await backend.add_field(session.record_id, session.page["index"], phone, label, text.strip())
    except ApiError as exc:
        # Refus de l'API (donnée personnelle…) : on le dit, puis retour au menu de la page
        await send_text(to=phone, body=f"⚠️ {exc}")
        await _show_page(phone, session)
        return
    await _refresh(session)
    await send_text(to=phone, body=f"✅ Champ ajouté · *{added['label']}* : "
                                   f"{render.format_value(added.get('kind', 'text'), added)}")
    await _show_page(phone, session)
