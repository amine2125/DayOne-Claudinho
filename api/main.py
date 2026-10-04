"""API locale autour du moteur de lecture `dayone/` et de la base `dayone.db`.

Lancement : .venv/bin/uvicorn api.main:app --port 8000
Puis http://localhost:8000/docs pour essayer les routes.

- Le tableau de bord (web/) lit /api/snapshot et les images masquées.
- L'agent WhatsApp (whatsapp-bot/) appelle les routes /api/records : capture, suivi de la
  lecture, reprise d'une page, vérification des champs, validation et choix de la patiente.

Sans PaddleOCR ni Ollama sur la machine : DAYONE_DEMO_EXTRACT=1 rejoue des sorties enregistrées.
"""

import importlib.util
import threading
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api import store
from dayone import ocr, vlm
from dayone.extract import THRESHOLD, NotAFormError
from dayone.schema import REFERENCE_PAGE_TYPES, STATUSES

MAX_UPLOAD_BYTES = 15 * 1024 * 1024


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Photos reçues mais pas encore lues (serveur arrêté entre-temps) : on les lit au démarrage.
    pending = store.pending_records()
    if pending:
        threading.Thread(target=lambda: [store.process_record(r) for r in pending], daemon=True).start()
    yield


app = FastAPI(title="DayOne — lecture du registre", version="1.1.0", lifespan=lifespan)

# Le tableau de bord web (web/) appelle cette API depuis le navigateur : seulement depuis cette machine.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _read(file: UploadFile) -> bytes:
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image trop lourde (15 Mo maximum)")
    return data


def _record_or_404(record_id: str) -> None:
    with store.db() as c:
        if not c.execute("SELECT 1 FROM records WHERE id = ?", (record_id,)).fetchone():
            raise HTTPException(404, "Dossier introuvable")


def _ocr_status() -> tuple[bool, str]:
    if importlib.util.find_spec("paddleocr") is None:
        return False, "PaddleOCR absent"
    return (True, "ok") if ocr.models_ready() else (False, "modèles PaddleOCR non téléchargés (python -m dayone.ocr --download)")


@app.get("/health")
def health() -> dict:
    demo = store.extractor().__module__ == "api.demo"
    ocr_ok, ocr_msg = (True, "démo : sorties enregistrées") if demo else _ocr_status()
    model_ok, model_msg = vlm.available()
    return {
        "ok": ocr_ok,
        "ocr": ocr_msg,
        "demo": demo,
        "model": vlm.DEFAULT_MODEL,
        "model_status": model_msg,
        "model_available": model_ok,
        "database": {"file": store.DB_PATH.name, **store.counts()},
        "page_types": list(REFERENCE_PAGE_TYPES),
    }


@app.post("/extract")
def extract(
    file: UploadFile = File(..., description="Photo d'une fiche (JPEG/PNG)"),
    use_model: bool = Form(True, description="Relire les valeurs douteuses avec le modèle local (Ollama)"),
) -> dict:
    """Lecture seule, sans rien enregistrer : photo -> sortie de dayone.extract telle quelle."""
    try:
        return store.extractor()(_read(file), use_model=use_model, threshold=THRESHOLD,
                                 source_name=file.filename or "")
    except NotAFormError as e:           # pas une fiche de santé, ou presque aucun texte
        raise HTTPException(422, str(e)) from e
    except ValueError as e:              # image illisible
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:            # PaddleOCR ou modèle local indisponible
        raise HTTPException(503, str(e)) from e


# ---------------- tableau de bord ----------------

@app.get("/api/snapshot")
def snapshot() -> dict:
    """Patientes, visites et dossiers, au format du contrat du tableau de bord."""
    return store.snapshot(lambda page_id: f"/api/pages/{page_id}/image")


@app.get("/api/pages/{page_id}/image")
def page_image(page_id: str) -> Response:
    """Page redressée, zones personnelles noircies. La photo d'origine n'est jamais servie."""
    data = store.view_image(page_id)
    if data is None:
        raise HTTPException(404, "Pas d'image affichable pour cette page")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


# ---------------- dossiers (utilisées par l'agent WhatsApp) ----------------

@app.post("/api/records", status_code=202)
def create_record(
    background: BackgroundTasks,
    files: list[UploadFile] = File(..., description="Une ou plusieurs pages du même registre"),
    patient_code: str = Form(..., description="Code écrit sur le registre"),
    midwife_id: str = Form(..., description="Identifiant de la sage-femme"),
) -> dict:
    """Enregistre la capture tout de suite (chiffrée), puis la lit en arrière-plan."""
    if not patient_code.strip():
        raise HTTPException(422, "Code patiente vide")
    record_id = store.create_record(patient_code, midwife_id.strip(), [_read(f) for f in files])
    background.add_task(store.process_record, record_id)
    return {"id": record_id, "state": "PENDING_AI"}


@app.get("/api/records/{record_id}")
def get_record(record_id: str) -> dict:
    """Un dossier : état, pages (champs, erreur de lecture) et `busy` pendant la lecture."""
    rec = store.record(record_id, lambda page_id: f"/api/pages/{page_id}/image")
    if rec is None:
        raise HTTPException(404, "Dossier introuvable")
    return rec


@app.post("/api/records/{record_id}/pages/{page_index}/photo", status_code=202)
def replace_page(record_id: str, page_index: int, background: BackgroundTasks,
                 file: UploadFile = File(..., description="Nouvelle photo de la page")) -> dict:
    """Reprendre la photo d'une page : seule cette page est relue, les autres gardent leurs corrections."""
    _record_or_404(record_id)
    try:
        store.replace_page(record_id, page_index, _read(file))
    except KeyError as e:
        raise HTTPException(404, f"Page introuvable : {e}") from e
    except store.TransitionError as e:
        raise HTTPException(409, str(e)) from e
    background.add_task(store.process_record, record_id)
    return {"id": record_id, "state": "PENDING_AI"}


@app.post("/api/records/{record_id}/pages/{page_index}/drop")
def drop_page(record_id: str, page_index: int) -> dict:
    """Retirer une page qui n'a pas pu être lue."""
    _record_or_404(record_id)
    try:
        store.drop_page(record_id, page_index)
    except KeyError as e:
        raise HTTPException(404, f"Page introuvable : {e}") from e
    except store.TransitionError as e:
        raise HTTPException(409, str(e)) from e
    return {"id": record_id}


@app.post("/api/records/{record_id}/retry", status_code=202)
def retry(record_id: str, background: BackgroundTasks) -> dict:
    _record_or_404(record_id)
    try:
        store.retry(record_id)
    except store.TransitionError as e:
        raise HTTPException(409, str(e)) from e
    background.add_task(store.process_record, record_id)
    return {"id": record_id, "state": "PENDING_AI"}


class FieldUpdate(BaseModel):
    by: str
    confirm: bool = False
    value: str | int | float | bool | None = None
    status: Literal[STATUSES] | None = None  # type: ignore[valid-type]


@app.post("/api/records/{record_id}/pages/{page_index}/fields/{key}")
def update_field(record_id: str, page_index: int, key: str, body: FieldUpdate) -> dict:
    """Confirmer la valeur lue (confirm=true), ou la corriger (value + status)."""
    _record_or_404(record_id)
    if not body.confirm and body.status is None:
        raise HTTPException(422, "Donner confirm=true, ou value + status")
    try:
        return store.set_field(record_id, page_index, key, body.by, body.value, body.status, body.confirm)
    except KeyError as e:
        raise HTTPException(404, f"Champ ou page introuvable : {e}") from e


@app.post("/api/records/{record_id}/validate")
def validate(record_id: str) -> dict:
    _record_or_404(record_id)
    try:
        store.validate(record_id)
    except store.TransitionError as e:
        raise HTTPException(409, str(e)) from e
    return {"id": record_id, "state": "VALIDATED"}


@app.get("/api/records/{record_id}/candidates")
def candidates(record_id: str) -> list[dict]:
    """Patientes plausibles (même code ou code proche). La sage-femme choisit."""
    _record_or_404(record_id)
    return store.candidates(record_id)


class LinkChoice(BaseModel):
    decision: Literal["EXISTING", "CREATE", "UNSURE"]
    patient_id: str | None = None


@app.post("/api/records/{record_id}/link")
def link(record_id: str, body: LinkChoice) -> dict:
    _record_or_404(record_id)
    if body.decision == "EXISTING" and not body.patient_id:
        raise HTTPException(422, "patient_id requis pour EXISTING")
    try:
        patient_id = store.link(record_id, body.decision, body.patient_id)
    except store.TransitionError as e:
        raise HTTPException(409, str(e)) from e
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    return {"id": record_id, "patient_id": patient_id}
