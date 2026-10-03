"""API FastAPI. Lancer : uvicorn app.main:app --reload  puis ouvrir http://localhost:8000"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from app.analytics.dashboard import EpidemiologyDashboard
from app.clinical.alerts import evaluate_clinical_risks
from app.messaging.dialogue import WhatsAppDialogueManager
from app.messaging.webhook import WhatsAppCloudWebhookHandler
from app.ocr.engine import get_engine
from app.offline.queue import OfflineQueue, RecordState
from app.patient_linking.linker import PatientLinker
from app.pipeline import extract
from app.schemas.models import ExtractionResponse, FieldStatus
from app.sessions.booklet_session import BookletSessionManager
from app.settings import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("registre")

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
_engine_error: str | None = None

queue = OfflineQueue()
linker = PatientLinker()
session_mgr = BookletSessionManager(linker=linker)
dash = EpidemiologyDashboard(linker=linker)
dialogue_mgr = WhatsAppDialogueManager(queue=queue, linker=linker)
webhook_handler = WhatsAppCloudWebhookHandler(dialogue_mgr=dialogue_mgr)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _engine_error
    try:
        get_engine()            # charge les modèles OCR au démarrage, pas à la 1re requête
    except Exception as exc:    # paddle absent, modèle introuvable... l'API reste up pour /health
        _engine_error = f"{type(exc).__name__}: {exc}"
        log.error("Moteur OCR indisponible : %s", _engine_error)
    yield


app = FastAPI(
    title="Registre obstétrical — Extraction & Suivi Longitudinal (DayOne CodeML)",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health() -> dict:
    info = {
        "ok": _engine_error is None,
        "ocr_engine": settings.ocr_engine,
        "ocr_error": _engine_error,
        "vlm_enabled": settings.vlm_enabled,
        "vlm_model": settings.vlm_model,
        "vlm_available": False,
        "encryption": "AES_FERNET_ACTIVE",
        "offline_ready": True,
    }
    from app.vlm.ollama_client import vlm_available
    info["vlm_available"] = vlm_available()
    return info


@app.post("/extract", response_model=ExtractionResponse)
def extract_endpoint(
    file: UploadFile = File(..., description="Photo d'une page de registre (JPEG/PNG)"),
    use_vlm: bool | None = Form(None, description="Forcer/désactiver le second lecteur local"),
    debug: bool = Form(False, description="Renvoie l'image de travail (zones nominatives noircies)"),
) -> ExtractionResponse:
    if _engine_error:
        raise HTTPException(503, f"Moteur OCR indisponible : {_engine_error}")
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image trop lourde (max 15 Mo)")
    try:
        return extract(data, use_vlm=use_vlm, debug=debug)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ==========================================
# GESTION HORS-LIGNE & FILE D'ATTENTE (FSM)
# ==========================================

@app.get("/api/queue")
def get_queue_items(limit: int = 50) -> list[dict]:
    """Retourne la liste des captures récentes et leur statut dans la file."""
    items = queue.get_all_items(limit=limit)
    return [
        {
            "id": it.id_uuid,
            "midwife_id": it.midwife_id,
            "state": it.state.value,
            "image_hash": it.image_hash_sha256[:10] + "...",
            "patient_id": it.patient_id,
            "retry_count": it.retry_count,
            "created_at": it.created_at,
            "updated_at": it.updated_at,
        }
        for it in items
    ]


@app.post("/api/queue/sync")
def sync_queue() -> dict:
    """Déclenche la synchronisation vers le serveur central dès le retour du réseau."""
    synced, failed = queue.sync_with_server(online_check=True)
    return {"synced_count": synced, "failed_count": failed}


# ==========================================
# DOSSIER PATIENTE LONGITUDINAL (ANONYME)
# ==========================================

@app.get("/api/patients")
def list_patients() -> list[dict]:
    """Liste les profils patientes pseudonymisés."""
    with linker._get_connection() as conn:
        rows = conn.execute("SELECT * FROM patients ORDER BY created_at DESC LIMIT 50").fetchall()
        return [dict(r) for r in rows]


@app.get("/api/patients/{patient_id}/timeline")
def get_patient_timeline(patient_id: str) -> dict:
    """Retourne l'historique complet des consultations d'une parturiente."""
    with linker._get_connection() as conn:
        patient = conn.execute("SELECT * FROM patients WHERE patient_id = ?", (patient_id,)).fetchone()
        if not patient:
            raise HTTPException(404, "Patiente introuvable")
    history = linker.get_patient_history(patient_id)
    return {
        "profile": dict(patient),
        "visits": history,
    }


# ==========================================
# TABLEAU DE BORD ÉPIDÉMIOLOGIQUE (BONUS)
# ==========================================

@app.get("/api/analytics/epidemiology")
def get_epidemiology_kpis() -> dict:
    """Retourne les indicateurs de santé publique anonymisés (HTA, Anémie, Dépistages, Accouchements)."""
    return dash.compute_summary_kpis()


# ==========================================
# SESSIONS MULTIPAGES & RENUMÉRISATION (TÂCHE 7)
# ==========================================

@app.post("/api/booklet/session")
def start_booklet_session(midwife_id: str = Form("SF-OUARZAZATE-01")) -> dict:
    """Démarre une nouvelle session multipages pour un carnet maternel (Pages 1 à 8)."""
    sess = session_mgr.start_session(midwife_id=midwife_id)
    return {
        "session_id": sess.session_id,
        "midwife_id": sess.midwife_id,
        "created_at": sess.created_at,
    }


@app.post("/api/booklet/scan")
def scan_booklet_page(
    session_id: str = Form(...),
    page_number: int | None = Form(None),
    file: UploadFile = File(...),
    use_vlm: bool = Form(False),
) -> dict:
    """Numérise une page du carnet de santé maternel, détecte les diffs en cas de re-scan."""
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image trop volumineuse")
    return session_mgr.process_page_scan(
        session_id=session_id,
        image_bytes=data,
        page_number=page_number,
        use_vlm=use_vlm,
    )


@app.post("/api/booklet/finalize")
def finalize_booklet_session(session_id: str = Form(...)) -> dict:
    """Clôture la session du carnet, consolide le profil, lie les visites et génère l'export FHIR."""
    try:
        return session_mgr.finalize_booklet(session_id=session_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


# ==========================================
# AGENT WHATSAPP CONVERSATIONNEL
# ==========================================

@app.post("/api/whatsapp/simulate")
def simulate_whatsapp(
    file: UploadFile | None = File(None),
    midwife_id: str = Form("SF-OUARZAZATE-01"),
    message_text: str = Form(""),
    last_item_id: str | None = Form(None),
    use_vlm: bool = Form(False),
) -> dict:
    """Simulateur de webhook WhatsApp conversationnel pour sage-femme en zone rurale."""
    # 1. Si la sage-femme répond par un message texte
    if message_text.strip():
        txt = message_text.strip()
        sess = dialogue_mgr.get_session(midwife_id)
        if last_item_id:
            sess.current_item_id = last_item_id

        # Vérifier si c'est une confirmation rapide '1' / '2' / 'oui'
        if last_item_id and txt in ("1", "2", "oui", "valider", "confirmer"):
            item = queue.get_item(last_item_id)
            if item and item.extracted_data_json:
                import json
                raw_data = json.loads(item.extracted_data_json)
                records_list = raw_data if isinstance(raw_data, list) else [raw_data]
                sess.extracted_records = records_list

        res = dialogue_mgr.handle_text_message(midwife_id, txt)
        if last_item_id and "item_id" not in res:
            res["item_id"] = last_item_id
        return res

    # 2. Si une nouvelle photo de registre est envoyée
    if not file:
        return {"reply": "Veuillez envoyer une photo de page de registre obstétrical."}

    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        return {"reply": "⚠️ Image trop volumineuse (max 15 Mo)."}

    # Inscription immédiate dans la file hors-ligne chiffrée
    item = queue.enqueue_capture(midwife_id, data)

    # Analyse IA locale
    resp = extract(data, use_vlm=use_vlm, debug=True)

    if resp.needs_retake:
        queue.transition_state(item.id_uuid, RecordState.FAILED_PROCESSING)
        return {
            "reply": (
                f"📷 *Photo non exploitable*\n\n"
                f"⚠️ *Problème :* {resp.retake_reason or 'Image illisible'}\n"
                f"• Netteté : {resp.quality.blur_score:.0f}\n"
                f"• Luminosité : {resp.quality.brightness:.0f}\n\n"
                f"👉 Merci de reprendre une photo plus nette et bien centrée."
            ),
            "item_id": item.id_uuid,
            "status": "RETAKE_NEEDED",
        }

    # Extraire les valeurs utiles
    records_list = []
    all_reviser = []
    all_illisible = []

    for r in resp.records:
        r_clean = {k: v.value for k, v in r.fields.items() if v.value is not None}
        if r_clean:
            records_list.append(r_clean)
        for k, v in r.fields.items():
            if v.status == FieldStatus.A_REVISER and v.raw_text:
                all_reviser.append((k, v))
            elif v.status == FieldStatus.ILLISIBLE:
                all_illisible.append((k, v))

    clean_first = records_list[0] if records_list else {}

    # Recherche patiente existante
    matches = linker.find_matches(clean_first)

    # Détection des alertes cliniques de danger
    clinical_alerts = []
    for rec in records_list:
        clinical_alerts.extend(evaluate_clinical_risks(rec))

    # Construction du message WhatsApp
    if len(resp.records) > 1:
        lines = [f"📋 *Tableau prénatal analysé ({len(resp.records)} consultations détectées)*\n"]
        for idx, rec_dict in enumerate(records_list, 1):
            sub = []
            if "date_consultation" in rec_dict: sub.append(f"📅 {rec_dict['date_consultation']}")
            if "age_gestationnel" in rec_dict: sub.append(f"⏱️ {rec_dict['age_gestationnel']} SA")
            if "poids_kg" in rec_dict: sub.append(f"⚖️ {rec_dict['poids_kg']} kg")
            if "tension_systolique" in rec_dict: sub.append(f"💓 {rec_dict['tension_systolique']}/{rec_dict.get('tension_diastolique', '')}")
            if "hauteur_uterine_cm" in rec_dict: sub.append(f"📏 HU {rec_dict['hauteur_uterine_cm']}cm")
            if "bcf_bpm" in rec_dict: sub.append(f"❤️ BCF {rec_dict['bcf_bpm']}")
            lines.append(f"  • *Visite #{idx}* : {' | '.join(sub)}")
        lines.append("")
    else:
        lines = ["📋 *Registre analysé en local* (0 coût, 0 cloud)\n"]
        key_metrics = []
        if "date_consultation" in clean_first:
            key_metrics.append(f"📅 Date : {clean_first['date_consultation']}")
        if "age_gestationnel" in clean_first:
            key_metrics.append(f"⏱️ Terme : {clean_first['age_gestationnel']} SA")
        if "tension_systolique" in clean_first and "tension_diastolique" in clean_first:
            key_metrics.append(f"💓 Tension : {clean_first['tension_systolique']}/{clean_first['tension_diastolique']} mmHg")
        if "poids_kg" in clean_first:
            key_metrics.append(f"⚖️ Poids : {clean_first['poids_kg']} kg")
        if "hauteur_uterine_cm" in clean_first:
            key_metrics.append(f"📏 HU : {clean_first['hauteur_uterine_cm']} cm")
        if "bcf_bpm" in clean_first:
            key_metrics.append(f"❤️ BCF : {clean_first['bcf_bpm']} bpm")
        if "groupe_sanguin" in clean_first or "rhesus" in clean_first:
            grp = f"{clean_first.get('groupe_sanguin', '')} {clean_first.get('rhesus', '')}".strip()
            key_metrics.append(f"🩸 Groupe : {grp}")
        if key_metrics:
            lines.append("📌 *Données extraites :*")
            lines.extend([f"  • {m}" for m in key_metrics])
            lines.append("")

    # Alertes cliniques
    if clinical_alerts:
        lines.append("🚨 *SIGNES D'ALERTE OBSTÉTRICALE :*")
        for ca in clinical_alerts[:2]:
            lines.append(f"  • [{ca.severity.value}] *{ca.title}* : {ca.message}")
            lines.append(f"    👉 {ca.action_recommandee}")
        lines.append("")

    # Sécurité PII
    lines.append("🔒 *Confidentialité médicale garantie :*")
    lines.append("  Nom, CIN, adresse et téléphone physiquement noircis.\n")

    # Rapprochement patiente
    if matches:
        m = matches[0]
        lines.append(f"🔍 *Patiente existante probable ({m.confidence_level}) :*")
        lines.append(f"  • Dossier : `{m.profile.patient_id}` (Code: {m.profile.code_patiente or 'N/A'})")
        lines.append(f"  • Concordance : {', '.join(m.matching_criteria)}")
        lines.append(f"  • Visites antérieures : {m.profile.records_count}")
        lines.append("\n👉 Répondez *1* pour attacher à cette patiente, ou *2* pour créer un nouveau dossier.")
    else:
        lines.append("🆕 *Nouvelle patiente (aucun dossier antérieur détecté)*")
        lines.append("👉 Répondez *1* pour créer automatiquement son dossier longitudinal.")

    # Champs douteux
    if all_reviser or all_illisible:
        lines.append(f"\n⚠️ *{len(all_reviser) + len(all_illisible)} champ(s) incertain(s) :*")
        for k, f in (all_reviser + all_illisible)[:3]:
            val = f.value or f.raw_text or "illisible"
            lines.append(f"  • {k} : {val} ({', '.join(f.reasons[:1])})")

    new_state = RecordState.NEEDS_REVIEW if (all_reviser or all_illisible) else RecordState.AI_PROCESSED
    queue.transition_state(item.id_uuid, new_state, extracted_data=records_list)

    # Initialiser la session conversationnelle
    conv_sess = dialogue_mgr.get_session(midwife_id)
    conv_sess.current_item_id = item.id_uuid
    conv_sess.extracted_records = records_list
    conv_sess.candidates = matches

    return {
        "reply": "\n".join(lines),
        "item_id": item.id_uuid,
        "status": new_state.value,
        "matches": [
            {
                "patient_id": mc.profile.patient_id,
                "score": mc.score,
                "criteria": mc.matching_criteria,
            }
            for mc in matches
        ],
        "extracted_fields": clean_first,
        "records_count": len(resp.records),
        "clinical_alerts": [ca.code for ca in clinical_alerts],
    }


# ==========================================
# WEBHOOK OFFICIEL WHATSAPP BUSINESS CLOUD API
# ==========================================

@app.get("/webhook/whatsapp")
def verify_meta_webhook(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
) -> Response:
    """Point d'entrée pour la validation du Webhook par Meta WhatsApp Cloud API."""
    challenge = webhook_handler.verify_challenge(hub_mode, hub_verify_token, hub_challenge)
    if challenge:
        return PlainTextResponse(challenge)
    raise HTTPException(403, "Verification token mismatch")


@app.post("/webhook/whatsapp")
async def handle_meta_webhook(request: Request) -> JSONResponse:
    """Réception des messages et médias transmis par WhatsApp Business Platform."""
    payload = await request.json()
    replies = webhook_handler.process_incoming_payload(payload)
    return JSONResponse(content={"status": "received", "replies_count": len(replies)})
