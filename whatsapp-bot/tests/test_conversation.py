"""Parcours WhatsApp de bout en bout, contre la vraie API DayOne (api/main.py) lancée dans le test.

Seuls Meta (envoi/téléchargement) est simulé. La lecture est le mode démo de l'API : elle rejoue
les vraies sorties de dayone.extract enregistrées dans outputs/predictions/.
"""

import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))   # à la fin : `app` reste le paquet du bot, pas app.py de la racine

import api.main as api_main  # noqa: E402
from api import store  # noqa: E402
from app import backend, conversation, render  # noqa: E402
from app.config import get_settings  # noqa: E402

PHONE = "33612345678"


class FakeWhatsApp:
    """Remplace Meta : enregistre ce que le bot envoie, fournit les photos."""

    def __init__(self):
        self.sent: list[str] = []
        self.buttons: list[list[str]] = []
        self.documents: list[tuple[str, bytes]] = []

    async def send_text(self, to, body):
        self.sent.append(body)

    async def send_buttons(self, to, body, buttons):
        self.sent.append(body)
        self.buttons.append([bid for bid, _ in buttons])

    async def send_document(self, to, data, filename, caption=""):
        self.documents.append((filename, data))
        self.sent.append(caption)

    async def send_list(self, to, body, button, rows):
        self.sent.append(body)
        self.buttons.append([rid for rid, _ in rows])

    @property
    def menu(self) -> list[str]:
        """Ids des choix cliquables du dernier menu envoyé."""
        return self.buttons[-1] if self.buttons else []

    async def download_media(self, media_id):
        return media_id.encode(), "image/jpeg"   # octets = id du média : choisit la sortie démo

    @property
    def last(self) -> str:
        return self.sent[-1]

    def since(self, start: int) -> str:
        return "\n".join(self.sent[start:])


@pytest.fixture
def wa(monkeypatch, tmp_path):
    monkeypatch.setenv("WHATSAPP_TOKEN", "test")
    monkeypatch.setenv("PHONE_NUMBER_ID", "123")
    monkeypatch.setenv("APP_SECRET", "secret")
    monkeypatch.setenv("DAYONE_DEMO_EXTRACT", "1")
    get_settings.cache_clear()
    # Base temporaire
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(store, "CAPTURES", tmp_path / "captures")
    monkeypatch.setattr(store, "KEY_FILE", tmp_path / "key")
    monkeypatch.setattr(store, "_initialized", False)
    monkeypatch.setattr(store, "_fernet", None)
    # Le bot parle à l'API en mémoire (les tâches de fond finissent avant la réponse)
    monkeypatch.setattr(backend, "_client", lambda timeout=30.0: httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api_main.app), base_url="http://dayone"))
    monkeypatch.setattr(backend, "POLL_SECONDS", 0)
    fake = FakeWhatsApp()
    for name in ("send_text", "send_buttons", "send_list", "send_document", "download_media"):
        monkeypatch.setattr(conversation, name, getattr(fake, name))
    conversation._sessions.clear()
    return fake


async def text(body: str):
    await conversation.handle_text(PHONE, body)


async def photo(media_id: str = "page-a"):
    await conversation.handle_image(PHONE, media_id, None)


async def start_review(wa, pages=("page-a",), code="AMN-27"):
    for media in pages:
        await photo(media)
    await text("btn_done")
    await text(code)


def session():
    return conversation.get_session(PHONE)


def state():
    return session().state


def db_record():
    return store.record(session().record["id"], str)


def fail_on(bad: bytes):
    """Lecture qui refuse une photo précise (comme dayone.extract sur une image floue)."""
    from api.demo import extract_page

    def extract(data, use_model=True, **kw):
        if data == bad:
            raise ValueError("Presque aucun texte sur cette image : ce n'est pas une fiche à lire.")
        return extract_page(data, use_model=use_model, **kw)
    return lambda: extract


# --- Photos et code ---

@pytest.mark.asyncio
async def test_greeting_and_help(wa):
    await text("bonjour")
    assert "Envoyez la photo" in wa.last
    await text("/aide")
    assert "Commandes" in wa.last


@pytest.mark.asyncio
async def test_photos_grouped_then_code_then_reading(wa):
    await photo("page-a")
    assert "Page 1 reçue" in wa.last and wa.buttons[-1] == ["btn_done", "btn_cancel"]
    await photo("page-b")
    assert "Page 2 reçue" in wa.last
    await text("Terminé")
    assert "code patiente" in wa.last and state() == conversation.State.ASK_CODE

    await photo("page-c")                         # photo au mauvais moment : refusée
    assert "J'attends d'abord le *code patiente*" in wa.last

    await text("$$$")
    assert "Ce code n'est pas valide" in wa.last
    await text("amn-27")
    assert "Page 1/2" in wa.last and wa.menu == ["1", "2", "3", "4", "5"]
    rec = db_record()                             # le dossier existe dans la base du tableau de bord
    assert rec["state"] == "NEEDS_REVIEW" and rec["patientCode"] == "AMN-27" and len(rec["pages"]) == 2
    assert rec["midwifeId"].startswith("wa-") and PHONE not in rec["midwifeId"]


@pytest.mark.asyncio
async def test_each_photo_is_stored_and_read_as_soon_as_it_arrives(wa):
    await photo("page-a")
    rid = session().record_id
    rec = store.record(rid, str)                  # avant « Terminé » : déjà dans la base, déjà lu
    assert len(rec["pages"]) == 1 and rec["pages"][0]["fields"] and rec["patientCode"] == ""
    assert "enregistrée" in wa.last
    await photo("page-b")
    rec = store.record(rid, str)
    assert [p["index"] for p in rec["pages"]] == [0, 1] and all(p["fields"] for p in rec["pages"])
    assert rec["state"] == "NEEDS_REVIEW"
    photos = list(store.CAPTURES.glob("*_original.enc"))
    assert len(photos) == 2 and all(b"page-" not in f.read_bytes() for f in photos)   # chiffrées


@pytest.mark.asyncio
async def test_code_read_on_the_page_is_proposed(wa, monkeypatch):
    from api.demo import extract_page

    def with_record_number(data, use_model=True, **kw):
        pred = extract_page(data, use_model=use_model, **kw)
        pred["fields"].append({"id": "n_de_fiche", "label": "N° de fiche", "kind": "text",
                               "value": "amn-27", "status": "KNOWN", "confidence": 0.95, "source": "ocr"})
        return pred
    monkeypatch.setattr(store, "extractor", lambda: with_record_number)
    await photo()
    await text("btn_done")
    assert "Code patiente lu sur le registre : *AMN-27*" in wa.last
    await text("1")
    assert db_record()["patientCode"] == "AMN-27" and "Page 1/1" in wa.last


@pytest.mark.asyncio
async def test_final_json_is_stored_with_corrections_and_patient(wa):
    await start_review(wa)
    nf = next(f for f in render.numbered_fields(session().page) if f.kind == "integer")
    await text("2")
    await text(str(nf.number))
    await text("41")
    record_id = session().record_id
    await text("1")
    if state() == conversation.State.CONFIRM_UNCERTAIN:
        await text("1")
    await text("1")                               # créer la patiente
    final = store.final_json(record_id)
    assert final["format"] == "dayone.record.v1" and final["patient_code"] == "AMN-27"
    assert final["patient_id"] and final["visit_id"] and final["validated_at"] and final["linked_at"]
    corrected = next(f for f in final["pages"][0]["fields"] if f["key"] == nf.key)
    assert corrected["value"] == 41 and corrected["origin"] == "CORRECTED"
    assert record_id in wa.sent[-2] and "Registre enregistré" in wa.sent[-2]   # récapitulatif tiré du JSON final
    # Puis la fiche PDF, en document à télécharger
    name, pdf = wa.documents[-1]
    assert name == "DayOne_AMN-27.pdf" and pdf.startswith(b"%PDF") and "PDF" in wa.last


# --- Menu ---

@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["7", "bonjour", "", "1 2"])
async def test_invalid_option_is_refused_and_menu_resent(wa, answer):
    await start_review(wa)
    start = len(wa.sent)
    await text(answer)
    assert "n'est pas une des options" in wa.since(start)
    assert wa.menu == ["1", "2", "3", "4", "5"] and state() == conversation.State.REVIEW


@pytest.mark.asyncio
async def test_view_values_grouped_by_section(wa):
    await start_review(wa)
    await text("3️⃣")
    values = wa.sent[-2]
    assert "Valeurs lues" in values and "*" in values
    page = session().page
    shown = [nf for nf in render.numbered_fields(page) if nf.field["status"] in render.SHOWN_STATUSES]
    assert shown and f"{shown[0].number}. " in values


@pytest.mark.asyncio
async def test_correction_is_saved_in_the_api(wa):
    await start_review(wa)
    page = session().page
    nf = next(f for f in render.numbered_fields(page) if f.kind == "integer")
    await text("2")
    assert "Quel champ corriger" in wa.sent[-2] and wa.menu[-1] == "0"   # liste cliquable : champs, puis retour
    await text("9999")
    assert "n'est pas un numéro de champ" in wa.last
    await text(str(nf.number))
    assert nf.label in wa.last
    await text("trente")
    assert "Format non reconnu" in wa.last and state() == conversation.State.EDIT_VALUE
    await text("0")                               # 0 est une vraie valeur, pas « revenir »
    assert state() == conversation.State.REVIEW

    saved = db_record()["pages"][0]["fields"][nf.key]
    assert saved["value"] == 0 and saved["origin"] in ("CORRECTED", "CONFIRMED") and saved["history"][-1]["by"].startswith("wa-")


@pytest.mark.asyncio
async def test_retour_leaves_value_entry(wa):
    await start_review(wa)
    await text("2")
    await text("1")
    await text("retour")
    assert state() == conversation.State.REVIEW and wa.menu == ["1", "2", "3", "4", "5"]


# --- Confirmation, validation, patiente ---

@pytest.mark.asyncio
async def test_confirm_with_doubts_asks_twice_then_links_new_patient(wa):
    await start_review(wa)
    doubts = render.uncertain(session().page)
    assert doubts, "la sortie démo choisie doit contenir des valeurs à vérifier"

    await text("1")
    assert "restent à vérifier" in wa.last and state() == conversation.State.CONFIRM_UNCERTAIN
    await text("8")
    assert "Répondez 1 ou 2" in wa.sent[-2]
    await text("1")                               # la sage-femme confirme ce qu'elle a vérifié
    assert "Aucune patiente suivie avec le code *AMN-27*" in wa.last
    assert db_record()["state"] == "VALIDATED"

    await text("1")                               # créer la patiente
    assert "Registre enregistré" in wa.sent[-2] and "tableau de bord" in wa.sent[-2] and wa.documents
    snap = store.snapshot(str)
    rec = next(iter(snap["records"].values()))
    assert rec["state"] == "SYNCED" and snap["patients"][rec["patientId"]]["code"] == "AMN-27"
    assert state() == conversation.State.IDLE


@pytest.mark.asyncio
async def test_second_visit_proposes_existing_patient(wa):
    await start_review(wa)
    await text("1")
    await text("1")
    await text("1")                               # 1re visite : patiente créée
    first = next(iter(store.snapshot(str)["patients"]))

    await start_review(wa, pages=("page-b",), code="AMN-27")
    await text("1")
    if state() == conversation.State.CONFIRM_UNCERTAIN:
        await text("1")
    assert "déjà suivie" in wa.last and "AMN-27 · même code" in wa.last
    await text("1")                               # la patiente proposée
    rec = db_record() if session().record else None
    linked = [r for r in store.snapshot(str)["records"].values() if r.get("patientId") == first]
    assert len(linked) == 2 and rec is None


# --- Reprise et pages illisibles ---

@pytest.mark.asyncio
async def test_retake_rereads_only_that_page(wa, monkeypatch):
    await start_review(wa, pages=("page-a", "page-b"))
    nf = next(f for f in render.numbered_fields(session().page) if f.kind == "integer")
    await text("2")
    await text(str(nf.number))
    await text("42")                              # correction sur la page 1
    await text("1")
    if state() == conversation.State.CONFIRM_UNCERTAIN:
        await text("1")
    assert "Page 2/2" in wa.last

    await text("4")
    assert state() == conversation.State.RETAKE
    await photo("page-b-nette")
    assert "Page 2/2" in wa.last and state() == conversation.State.REVIEW
    rec = db_record()
    assert rec["pages"][0]["fields"][nf.key]["value"] == 42      # correction de la page 1 gardée
    assert any("RETAKE page 1" == h.get("note") for h in rec["history"])


@pytest.mark.asyncio
async def test_unreadable_page_retake_or_skip(wa, monkeypatch):
    monkeypatch.setattr(store, "extractor", fail_on(b"page-floue"))
    await start_review(wa, pages=("page-floue", "page-a"))
    assert "lecture impossible" in wa.last and "Presque aucun texte" in wa.last
    await text("1")                               # confirmer une page illisible : refusé
    assert "Répondez 4 ou 5" in wa.sent[-2]
    await text("5")
    assert "Page ignorée" in wa.sent[-2] and "Page 1/1" in wa.last
    assert len(db_record()["pages"]) == 1


@pytest.mark.asyncio
async def test_only_page_unreadable_must_be_retaken(wa, monkeypatch):
    monkeypatch.setattr(store, "extractor", fail_on(b"page-floue"))
    await start_review(wa, pages=("page-floue",))
    assert "lecture impossible" in wa.last and "5️⃣" not in wa.last
    await text("5")
    assert "Répondez 4" in wa.sent[-2]
    await text("4")
    await photo("page-a")
    assert "Page 1/1" in wa.last and wa.menu == ["1", "2", "3", "4", "5"]


@pytest.mark.asyncio
async def test_photo_during_review_is_not_mixed_in(wa):
    await start_review(wa)
    await photo("page-b")
    assert "vérification est en cours" in wa.last
    assert len(db_record()["pages"]) == 1


@pytest.mark.asyncio
async def test_cancel_keeps_record_for_dashboard(wa):
    await start_review(wa)
    record_id = session().record["id"]
    await text("annuler")
    assert "reste « à vérifier » sur le tableau de bord" in wa.last
    assert state() == conversation.State.IDLE
    assert store.record(record_id, str)["state"] == "NEEDS_REVIEW"


@pytest.mark.asyncio
async def test_api_down_gives_clear_message(wa, monkeypatch):
    def broken(timeout=30.0):
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("down"))),
                                 base_url="http://dayone")
    monkeypatch.setattr(backend, "_client", broken)
    await photo()                                 # la photo part tout de suite vers l'API
    assert "injoignable" in wa.last
    assert state() == conversation.State.IDLE     # rien n'est perdu : la sage-femme renvoie la photo


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


def test_link_text_shows_at_most_eight_patients():
    # Liste cliquable WhatsApp : 10 lignes au plus = 8 patientes + « nouvelle » + « je ne sais pas »
    cands = [{"patientId": f"p{i}", "code": f"C{i}", "reasons": [{"kind": "SAME_CODE"}]} for i in range(9)]
    out = render.link_text("C1", cands)
    assert "8️⃣ C7" in out and "C8" not in out


@pytest.mark.asyncio
async def test_add_missing_field(wa):
    await start_review(wa)
    before = len(session().page["fields"])
    await text("5")
    assert state() == conversation.State.ADD_LABEL and "Nom du champ" in wa.last
    await text("Groupe sanguin")
    assert state() == conversation.State.ADD_VALUE
    await text("O+")
    assert "Champ ajouté" in wa.sent[-2] and "Groupe sanguin" in wa.sent[-2]
    fields = session().page["fields"]
    assert len(fields) == before + 1
    added = next(f for f in fields.values() if f["label"] == "Groupe sanguin")
    assert added["value"] == "O+" and added["origin"] == "MANUAL" and added["status"] == "KNOWN"
    assert state() == conversation.State.REVIEW and wa.menu == ["1", "2", "3", "4", "5"]


@pytest.mark.asyncio
async def test_added_personal_field_is_refused(wa):
    await start_review(wa)
    before = len(session().page["fields"])
    await text("5")
    await text("Nom du mari")
    await text("Ahmed")
    assert "Donnée personnelle" in wa.sent[-2] and len(session().page["fields"]) == before
    assert state() == conversation.State.REVIEW


def test_midwife_id_hides_phone(monkeypatch):
    monkeypatch.setenv("APP_SECRET", "s")
    get_settings.cache_clear()
    mid = backend.midwife_id(PHONE)
    assert mid.startswith("wa-") and PHONE not in mid and mid == backend.midwife_id(PHONE)


def test_table_cells_share_one_line_per_row():
    page = {"fields": {
        "a": {"label": "HTA | Famille de la femme", "kind": "text", "section": "Antécédents", "value": "aucun", "status": "KNOWN"},
        "b": {"label": "HTA | Mari/famille", "kind": "text", "section": "Antécédents", "value": "Père", "status": "NEEDS_REVIEW"},
        "c": {"label": "Diabète | Famille de la femme", "kind": "text", "section": "Antécédents", "value": "aucun", "status": "KNOWN"},
        "d": {"label": "Age", "kind": "integer", "section": "Antécédents", "value": 31, "status": "KNOWN"},
    }}
    out = render.values_text(page)
    assert "HTA : 1. Famille de la femme *aucun* · 2. ⚠️ Mari/famille *Père*" in out
    assert "3. Diabète | Famille de la femme : *aucun*" in out and "4. Age : *31*" in out   # case seule : ligne normale


@pytest.mark.asyncio
async def test_pdf_failure_does_not_break_the_end(wa, monkeypatch):
    async def broken(*_a, **_k):
        raise backend.ApiError("panne")
    monkeypatch.setattr(backend, "get_pdf", broken)
    await conversation._send_pdf(PHONE, "rec_x")
    assert "PDF n'a pas pu être envoyée" in wa.last
