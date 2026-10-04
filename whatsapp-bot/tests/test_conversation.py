"""Tests du flux de conversation : photos → lecture → menu → correction → confirmation."""

import copy
import json
from pathlib import Path

import httpx
import pytest

from app import backend, conversation, render
from app.config import get_settings

PHONE = "33612345678"
PREDICTIONS = Path(__file__).resolve().parents[2] / "outputs" / "predictions"
SAMPLE = json.loads((PREDICTIONS / "page_02_identification_antecedents.json").read_text(encoding="utf-8"))


class FakeWhatsApp:
    """Remplace Meta et notre API : enregistre ce que le bot envoie."""

    def __init__(self):
        self.sent: list[str] = []
        self.buttons: list[list[str]] = []
        self.analyses = 0
        self.saved: list[list[dict]] = []
        self.next_pages: list = []  # pages (ou exceptions) renvoyées par l'API, dans l'ordre

    async def send_text(self, to, body):
        self.sent.append(body)

    async def send_buttons(self, to, body, buttons):
        self.sent.append(body)
        self.buttons.append([bid for bid, _ in buttons])

    async def download_media(self, media_id):
        return b"jpeg-bytes", "image/jpeg"

    async def analyze_page(self, image_bytes, mime_type, user_phone, caption=None):
        self.analyses += 1
        result = self.next_pages.pop(0) if self.next_pages else copy.deepcopy(SAMPLE)
        if isinstance(result, Exception):
            raise result
        return result

    async def save_record(self, user_phone, pages):
        self.saved.append(pages)
        return True

    @property
    def last(self) -> str:
        return self.sent[-1]

    def all_since(self, start: int) -> str:
        return "\n".join(self.sent[start:])


@pytest.fixture
def wa(monkeypatch):
    monkeypatch.setenv("WHATSAPP_TOKEN", "test")
    monkeypatch.setenv("PHONE_NUMBER_ID", "123")
    get_settings.cache_clear()
    fake = FakeWhatsApp()
    for name in ("send_text", "send_buttons", "download_media", "analyze_page", "save_record"):
        monkeypatch.setattr(conversation, name, getattr(fake, name))
    conversation._sessions.clear()
    return fake


async def text(body: str):
    await conversation.handle_text(PHONE, body)


async def photo(caption: str | None = None):
    await conversation.handle_image(PHONE, "media-1", caption)


async def start_review(wa, pages: int = 1):
    for _ in range(pages):
        await photo()
    await text("btn_done")


def state():
    return conversation.get_session(PHONE).state


# --- Réception des photos ---

@pytest.mark.asyncio
async def test_greeting_and_help(wa):
    await text("bonjour")
    assert "Envoyez la photo" in wa.last
    await text("/aide")
    assert "Commandes" in wa.last


@pytest.mark.asyncio
async def test_photos_are_grouped_until_done(wa):
    await photo()
    assert "Page 1 reçue" in wa.last and wa.buttons[-1] == ["btn_done", "btn_cancel"]
    await photo()
    assert "Page 2 reçue" in wa.last
    assert wa.analyses == 0  # rien n'est lu avant « Terminé »

    start = len(wa.sent)
    await text("Terminé")
    out = wa.all_since(start)
    assert "2 page(s) regroupée(s)" in out
    assert "Page 1/2 · Identification et antécédents" in wa.last
    assert "1️⃣ Confirmer" in wa.last and "4️⃣ Reprendre" in wa.last
    assert wa.analyses == 2
    assert state() == conversation.State.REVIEW


@pytest.mark.asyncio
async def test_text_while_collecting_reminds_done_button(wa):
    await photo()
    await text("et maintenant ?")
    assert "Terminé" in wa.last and state() == conversation.State.COLLECTING


# --- Menu ---

@pytest.mark.asyncio
async def test_review_lists_uncertain_fields(wa):
    await start_review(wa)
    _, uncertain = render.counts(SAMPLE)
    assert uncertain, "l'exemple doit contenir un champ à vérifier"
    assert f"⚠️ {len(uncertain)} à vérifier" in wa.last
    assert uncertain[0].label in wa.last


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["7", "bonjour", "", "1 2"])
async def test_invalid_option_is_refused_and_menu_resent(wa, answer):
    await start_review(wa)
    start = len(wa.sent)
    await text(answer)
    out = wa.all_since(start)
    assert "n'est pas une des options" in out
    assert "1️⃣ Confirmer" in wa.last
    assert state() == conversation.State.REVIEW


@pytest.mark.asyncio
async def test_emoji_choice_is_understood(wa):
    await start_review(wa)
    await text("3️⃣")
    assert "Valeurs lues" in wa.sent[-2]


@pytest.mark.asyncio
async def test_view_values_shows_labels_not_empty_fields(wa):
    await start_review(wa)
    await text("3")
    values = wa.sent[-2]
    assert "Âge : *31*" in values
    assert "Grossesse désirée : *Oui*" in values
    assert "Consanguinité" not in values  # case vide : non affichée


@pytest.mark.asyncio
async def test_confirm_all_pages_sends_clean_summary(wa):
    await start_review(wa, pages=2)
    await text("1")
    assert "Page 1 confirmée" in wa.sent[-2] and "Page 2/2" in wa.last
    await text("1")
    assert "Registre confirmé" in wa.last and "Âge : *31*" in wa.last
    assert len(wa.saved) == 1 and len(wa.saved[0]) == 2
    assert state() == conversation.State.IDLE  # nouvelle session


@pytest.mark.asyncio
async def test_save_failure_keeps_record(wa, monkeypatch):
    async def failing_save(user_phone, pages):
        return False
    monkeypatch.setattr(conversation, "save_record", failing_save)
    await start_review(wa)
    await text("1")
    assert "n'a pas pu être enregistré" in wa.last
    assert state() == conversation.State.REVIEW


# --- Correction ---

@pytest.mark.asyncio
async def test_correct_a_field(wa):
    await start_review(wa)
    await text("2")
    assert "Quel champ corriger" in wa.last and "1. Âge : *31*" in wa.last

    await text("999")
    assert "n'est pas un numéro de champ" in wa.last
    assert state() == conversation.State.CHOOSE_FIELD

    await text("1")  # Âge
    assert "Âge" in wa.last and "actuel : 31" in wa.last
    await text("trente")
    assert "Format non reconnu" in wa.last
    assert state() == conversation.State.EDIT_VALUE

    await text("35")
    assert "✅ *Âge* : 35" in wa.sent[-2]
    assert state() == conversation.State.REVIEW
    field = conversation.get_session(PHONE).page["fields"]["age"]
    assert field == {"value": 35, "status": "KNOWN", "confidence": 1.0, "source": "sage-femme", "previous": 31}


@pytest.mark.asyncio
async def test_zero_is_a_value_and_retour_goes_back(wa):
    await start_review(wa)
    pdef = render.page_def_for(SAMPLE)
    number = next(f.number for f in pdef.fields if f.kind == "integer" and f.id != "age")
    await text("2")
    await text(str(number))
    await text("0")  # 0 est une vraie valeur, pas « revenir »
    assert state() == conversation.State.REVIEW
    assert conversation.get_session(PHONE).page["fields"][pdef.by_number(number).id]["value"] == 0

    await text("2")
    await text(str(number))
    await text("retour")
    assert state() == conversation.State.REVIEW and "1️⃣ Confirmer" in wa.last


@pytest.mark.asyncio
async def test_resolving_uncertain_field_clears_warning(wa):
    await start_review(wa)
    _, uncertain = render.counts(SAMPLE)
    for fdef in uncertain:
        await text("2")
        await text(str(fdef.number))
        await text("?")
    assert "Aucune incertitude restante" in wa.last


@pytest.mark.asyncio
async def test_show_all_fields_includes_empty_ones(wa):
    await start_review(wa)
    await text("2")
    await text("tout")
    assert "Consanguinité" in wa.last


# --- Reprise et erreurs d'analyse ---

@pytest.mark.asyncio
async def test_retake_photo_replaces_page(wa):
    await start_review(wa)
    await text("4")
    assert "nouvelle photo de la page 1" in wa.last
    assert state() == conversation.State.RETAKE
    await photo()
    assert wa.analyses == 2
    assert state() == conversation.State.REVIEW and "Page 1/1" in wa.last


@pytest.mark.asyncio
async def test_failed_page_offers_retake_or_skip(wa):
    wa.next_pages = [backend.AnalysisError("Photo trop floue."), copy.deepcopy(SAMPLE)]
    await start_review(wa, pages=2)
    assert "lecture impossible" in wa.last and "Photo trop floue." in wa.last

    await text("1")  # confirmer une page illisible : refusé
    assert "Répondez 4 ou 5" in wa.sent[-2]

    await text("5")
    assert "Page ignorée" in wa.sent[-2] and "Page 1/1" in wa.last
    await text("1")
    assert len(wa.saved[0]) == 1


@pytest.mark.asyncio
async def test_only_page_failed_and_skipped_resets(wa):
    wa.next_pages = [backend.AnalysisError("Illisible.")]
    await start_review(wa)
    await text("5")
    assert "Aucune page à enregistrer" in wa.last
    assert state() == conversation.State.IDLE


@pytest.mark.asyncio
async def test_photo_during_review_is_not_mixed_in(wa):
    await start_review(wa)
    await photo()
    assert "vérification est en cours" in wa.last
    assert wa.analyses == 1


@pytest.mark.asyncio
async def test_cancel_resets_everything(wa):
    await start_review(wa)
    await text("btn_cancel")
    assert "Registre annulé" in wa.last
    assert state() == conversation.State.IDLE


# --- Rendu et saisie ---

@pytest.mark.parametrize("kind,typed,expected", [
    ("integer", "3", (3, "KNOWN")),
    ("weight", "3250 g", (3250, "KNOWN")),
    ("date", "6/2/2026", ("2026-02-06", "KNOWN")),
    ("date", "06-02-26", ("2026-02-06", "KNOWN")),
    ("checkbox", "Oui", (True, "KNOWN")),
    ("checkbox", "non", (None, "NOT_PROVIDED")),
    ("sex", "fille", ("F", "KNOWN")),
    ("text", "aucun", ("aucun", "KNOWN")),
    ("text", "?", (None, "UNKNOWN")),
    ("text", "-", (None, "NOT_PROVIDED")),
])
def test_parse_value(kind, typed, expected):
    assert render.parse_value(kind, typed) == expected


@pytest.mark.parametrize("kind,typed", [("integer", "abc"), ("date", "31/02/2026"), ("checkbox", "peut-être"), ("sex", "x")])
def test_parse_value_rejects(kind, typed):
    with pytest.raises(ValueError):
        render.parse_value(kind, typed)


def test_format_value():
    assert render.format_value("date", {"value": "2026-02-06", "status": "KNOWN"}) == "06/02/2026"
    assert render.format_value("weight", {"value": 3250, "status": "KNOWN"}) == "3250 g"
    assert render.format_value("sex", {"value": "F", "status": "KNOWN"}) == "Féminin"
    assert render.format_value("text", {"value": None, "status": "ILLEGIBLE"}) == "illisible"


# --- Client de l'API d'analyse ---

def _mock_api(monkeypatch, handler):
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(backend.httpx, "AsyncClient", factory)
    monkeypatch.setenv("OUR_API_URL", "http://api.test/analyze")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_analyze_page_accepts_dayone_output(monkeypatch):
    _mock_api(monkeypatch, lambda req: httpx.Response(200, json={"prediction": SAMPLE}))
    page = await backend.analyze_page(b"img", "image/jpeg", PHONE)
    assert page["page_type"] == "identification_antecedents"


@pytest.mark.asyncio
async def test_analyze_page_relays_business_error(monkeypatch):
    _mock_api(monkeypatch, lambda req: httpx.Response(422, json={"detail": "Photo trop floue."}))
    with pytest.raises(backend.AnalysisError, match="Photo trop floue."):
        await backend.analyze_page(b"img", "image/jpeg", PHONE)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(500, text="boom"), httpx.Response(200, json={"ok": True})])
async def test_analyze_page_hides_server_errors(monkeypatch, response):
    _mock_api(monkeypatch, lambda req: response)
    with pytest.raises(backend.AnalysisError) as exc:
        await backend.analyze_page(b"img", "image/jpeg", PHONE)
    assert "boom" not in str(exc.value)
