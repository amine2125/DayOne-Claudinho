"""Gestionnaire de dialogue conversationnel WhatsApp (Conversational Verification Engine).

Conforme à la tâche #3 et #6 du cahier des charges DayOne :
  - Présentation des données extraites avec confiance par champ
  - Boutons / Choix : Confirmer / Corriger / Reprendre la photo
  - Questions de suivi ciblées pour les champs incertains (À_RÉVISER / ILLISIBLE)
  - Saisie manuelle directe assistée par IA si la photo est absente ou illisible
  - Choix de rapprochement explicite : [Patiente 1] [Patiente 2] [Aucune, créer] [Je ne sais pas]
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum

from app.clinical.alerts import evaluate_clinical_risks
from app.offline.queue import OfflineQueue, RecordState
from app.patient_linking.linker import MatchCandidate, PatientLinker
from app.schemas.form_spec import DISPLAY_NAMES, FIELDS_BY_KEY, OUTPUT_UNITS
from app.schemas.models import ExtractionResponse, FieldStatus
from app.validators.parsers import (
    parse_blood_group,
    parse_blood_pressure,
    parse_gesta_para,
    parse_gestational_age,
    parse_number,
)


class DialogueState(str, Enum):
    IDLE = "IDLE"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    WAITING_FIELD_ANSWER = "WAITING_FIELD_ANSWER"
    WAITING_PATIENT_SELECTION = "WAITING_PATIENT_SELECTION"
    MANUAL_ENTRY_MODE = "MANUAL_ENTRY_MODE"


@dataclass
class ConversationSession:
    midwife_id: str
    state: DialogueState = DialogueState.IDLE
    current_item_id: str | None = None
    extracted_records: list[dict] = field(default_factory=list)
    pending_questions: list[str] = field(default_factory=list)   # Liste des clés de champs incertains
    current_question_key: str | None = None
    candidates: list[MatchCandidate] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)


class WhatsAppDialogueManager:
    """Moteur conversationnel intelligent adapté au contexte clinique rural."""

    def __init__(self, queue: OfflineQueue | None = None, linker: PatientLinker | None = None):
        self.queue = queue or OfflineQueue()
        self.linker = linker or PatientLinker()
        self.sessions: dict[str, ConversationSession] = {}

    def get_session(self, midwife_id: str) -> ConversationSession:
        if midwife_id not in self.sessions:
            self.sessions[midwife_id] = ConversationSession(midwife_id=midwife_id)
        return self.sessions[midwife_id]

    def handle_image_received(self, midwife_id: str, image_bytes: bytes, resp: ExtractionResponse) -> dict:
        """Traite la réception d'une photo et amorce le dialogue de vérification."""
        sess = self.get_session(midwife_id)

        # Enregistrement FSM hors-ligne chiffré
        item = self.queue.enqueue_capture(midwife_id, image_bytes)
        sess.current_item_id = item.id_uuid

        # 1. Vérification qualité photo
        if resp.needs_retake:
            self.queue.transition_state(item.id_uuid, RecordState.FAILED_PROCESSING)
            sess.state = DialogueState.IDLE
            return {
                "reply": (
                    f"📷 *Photo non exploitable*\n\n"
                    f"⚠️ *Problème :* {resp.retake_reason or 'Image illisible'}\n"
                    f"• Netteté : {resp.quality.blur_score:.0f}\n"
                    f"• Luminosité : {resp.quality.brightness:.0f}\n\n"
                    f"👉 Merci de reprendre une photo plus nette et bien centrée.\n"
                    f"*(Vous pouvez aussi taper 'manuel' pour une saisie directe)*"
                ),
                "item_id": item.id_uuid,
                "status": "RETAKE_NEEDED",
            }

        # 2. Collecte des données extraites et détection des doutes
        records_list = []
        uncertain_keys = []
        for r in resp.records:
            r_clean = {k: v.value for k, v in r.fields.items() if v.value is not None}
            if r_clean:
                records_list.append(r_clean)
            for k, v in r.fields.items():
                if v.status in (FieldStatus.A_REVISER, FieldStatus.ILLISIBLE):
                    uncertain_keys.append(k)

        sess.extracted_records = records_list
        clean_first = records_list[0] if records_list else {}

        # 3. Rapprochement patiente (Tâche 6)
        candidates = self.linker.find_matches(clean_first)
        sess.candidates = candidates

        # 4. Détection des alertes cliniques
        clinical_alerts = []
        for rec in records_list:
            clinical_alerts.extend(evaluate_clinical_risks(rec))

        # 5. Construction du message d'accueil
        lines = []
        if len(resp.records) > 1:
            lines.append(f"📋 *Tableau prénatal analysé ({len(resp.records)} visites détectées)*\n")
            for idx, rec in enumerate(records_list, 1):
                sub = []
                if "date_consultation" in rec: sub.append(f"📅 {rec['date_consultation']}")
                if "age_gestationnel" in rec: sub.append(f"⏱️ {rec['age_gestationnel']} SA")
                if "tension_systolique" in rec: sub.append(f"💓 {rec['tension_systolique']}/{rec.get('tension_diastolique', '')}")
                if "bcf_bpm" in rec: sub.append(f"❤️ BCF {rec['bcf_bpm']}")
                lines.append(f"  • *Visite #{idx}* : {' | '.join(sub)}")
        else:
            lines.append("📋 *Registre analysé en local* (0 coût, 0 cloud)\n")
            lines.append("📌 *Données extraites :*")
            if "date_consultation" in clean_first: lines.append(f"  • Date : {clean_first['date_consultation']}")
            if "age_gestationnel" in clean_first: lines.append(f"  • Terme : {clean_first['age_gestationnel']} SA")
            if "tension_systolique" in clean_first: lines.append(f"  • Tension : {clean_first['tension_systolique']}/{clean_first.get('tension_diastolique', '')} mmHg")
            if "poids_kg" in clean_first: lines.append(f"  • Poids : {clean_first['poids_kg']} kg")
            if "bcf_bpm" in clean_first: lines.append(f"  • BCF : {clean_first['bcf_bpm']} bpm")
            if "groupe_sanguin" in clean_first: lines.append(f"  • Groupe : {clean_first['groupe_sanguin']} {clean_first.get('rhesus', '')}")

        # Bannière d'alerte clinique si danger
        if clinical_alerts:
            lines.append("\n🚨 *ALERTES CLINIQUES DÉTECTÉES :*")
            for ca in clinical_alerts[:2]:
                lines.append(f"  • [{ca.severity.value}] *{ca.title}* : {ca.message}")
                lines.append(f"    👉 *Action :* {ca.action_recommandee}")

        # Sécurité PII
        lines.append("\n🔒 *Confidentialité :* Noms, CIN, adresse et téléphone noircis.")

        # Rapprochement patiente avec choix explicites (Tâche 6)
        lines.append("\n🔍 *Rapprochement patiente :*")
        if candidates:
            lines.append(f"  [1] Lier à {candidates[0].profile.patient_id} ({candidates[0].confidence_level}, {', '.join(candidates[0].matching_criteria)})")
            if len(candidates) > 1:
                lines.append(f"  [2] Lier à {candidates[1].profile.patient_id} ({candidates[1].confidence_level})")
            lines.append("  [3] Aucune correspondance (Créer nouveau dossier)")
            lines.append("  [4] Je ne sais pas (Mettre en attente)")
            sess.state = DialogueState.WAITING_PATIENT_SELECTION
        else:
            lines.append("  🆕 Nouveau profil (aucune patiente concordante)")
            lines.append("  👉 Répondez *1* pour Valider et Créer le dossier.")
            sess.state = DialogueState.WAITING_CONFIRMATION

        # Doutes ou questions de suivi (Tâche 3)
        if uncertain_keys:
            sess.pending_questions = uncertain_keys
            lines.append(f"\n⚠️ *{len(uncertain_keys)} champ(s) incertain(s)*")
            lines.append("Vous pouvez aussi corriger directement (ex: 'TA 140/90' ou 'terme 34 SA').")

        lines.append("\nOptions : *[1]* Confirmer | *[Corriger]* | *[Reprendre]*")
        self.queue.transition_state(item.id_uuid, RecordState.AI_PROCESSED, extracted_data=records_list)

        return {
            "reply": "\n".join(lines),
            "item_id": item.id_uuid,
            "status": "AI_PROCESSED",
            "clinical_alerts": [ca.code for ca in clinical_alerts],
        }

    def handle_text_message(self, midwife_id: str, text: str) -> dict:
        """Traite les réponses conversationnelles et commandes de la sage-femme."""
        sess = self.get_session(midwife_id)
        msg = text.strip()
        msg_lower = msg.lower()

        # 1. Commande globale d'aide
        if msg_lower in ("aide", "help", "?"):
            return {
                "reply": (
                    "ℹ️ *Commandes disponibles :*\n"
                    "• *1* ou *valider* : Confirmer et enregistrer le dossier.\n"
                    "• *corriger [champ] [valeur]* : Ex 'TA 130/80', 'poids 65', 'terme 36 SA'.\n"
                    "• *reprendre* : Annuler et reprendre une nouvelle photo.\n"
                    "• *manuel* : Passer en saisie manuelle complète sans photo.\n"
                    "• *statut* : Afficher l'état du dossier en cours."
                )
            }

        # 2. Commande 'reprendre la photo'
        if msg_lower in ("reprendre", "reprendre photo", "refaire", "annuler"):
            if sess.current_item_id:
                self.queue.transition_state(sess.current_item_id, RecordState.FAILED_PROCESSING)
            sess.state = DialogueState.IDLE
            sess.current_item_id = None
            return {"reply": "🔄 Photo annulée. Veuillez envoyer une nouvelle photo bien cadrée du registre."}

        # 3. Commande 'saisie manuelle'
        if msg_lower.startswith("manuel") or msg_lower.startswith("saisie manuelle"):
            sess.state = DialogueState.MANUAL_ENTRY_MODE
            return {
                "reply": (
                    "📝 *Mode Saisie Manuelle Activé*\n\n"
                    "Veuillez entrer les données sous forme libre, par exemple :\n"
                    "_Âge 26, G2P1, 34 SA, TA 120/80, Poids 68kg, BCF 140, Groupe O+_\n\n"
                    "Tapez *annuler* pour quitter la saisie manuelle."
                )
            }

        # 4. Traitement du Mode Saisie Manuelle
        if sess.state == DialogueState.MANUAL_ENTRY_MODE:
            parsed_data = self._parse_free_text_entry(msg)
            if not parsed_data:
                return {
                    "reply": "⚠️ Aucun champ médical reconnu. Veuillez indiquer au moins l'âge, la TA ou le terme (ex: '28 ans, TA 12/8, 30 SA')."
                }

            # Création du profil et de la visite
            p = self.linker.create_patient(
                code_patiente=parsed_data.get("code_patiente"),
                age=parsed_data.get("age"),
                gestite=parsed_data.get("gestite"),
                parite=parsed_data.get("parite"),
                groupe_sanguin=parsed_data.get("groupe_sanguin"),
                rhesus=parsed_data.get("rhesus"),
            )
            self.linker.link_record(p.patient_id, f"MANUAL_{int(time.time())}", parsed_data)
            alerts = evaluate_clinical_risks(parsed_data)
            sess.state = DialogueState.IDLE

            alert_text = ""
            if alerts:
                alert_text = "\n🚨 *Alertes :* " + ", ".join([f"{a.title} ({a.message})" for a in alerts])

            return {
                "reply": (
                    f"✅ *Dossier saisi manuellement et enregistré !*\n\n"
                    f"🆔 Patiente : `{p.patient_id}`\n"
                    f"📊 Champs enregistrés : {len(parsed_data)}\n"
                    f"{alert_text}\n"
                    f"💾 Sauvegardé dans la base locale sécurisée."
                ),
                "patient_id": p.patient_id,
            }

        # 5. Choix de rapprochement patiente ou validation (Tâche 6)
        if msg in ("1", "oui", "valider", "confirmer", "lier 1", "patiente 1"):
            if sess.candidates:
                return self._finalize_linking(sess, sess.candidates[0].profile.patient_id)
            return self._create_new_patient_and_link(sess)

        if msg in ("2", "lier 2", "patiente 2") and len(sess.candidates) > 1:
            return self._finalize_linking(sess, sess.candidates[1].profile.patient_id)

        if msg in ("2", "3", "aucune", "creer", "créer", "nouveau"):
            return self._create_new_patient_and_link(sess)

        if msg in ("4", "je ne sais pas", "attente", "doute"):
            if sess.current_item_id:
                self.queue.transition_state(sess.current_item_id, RecordState.MANUAL_REVIEW_REQUIRED)
            sess.state = DialogueState.IDLE
            return {
                "reply": "⏸️ Dossier mis en attente pour vérification ultérieure au centre de santé."
            }

        # 6. Tentative de correction par mot-clé (ex: 'TA 140/90', 'terme 34 SA', 'poids 70')
        corrected = self._try_apply_correction(sess, msg)
        if corrected:
            field_name, new_val = corrected
            return {
                "reply": (
                    f"✏️ *Champ mis à jour avec succès !*\n"
                    f"• {DISPLAY_NAMES.get(field_name, field_name)} : *{new_val}*\n\n"
                    f"👉 Répondez *1* pour valider définitivement, ou continuez vos corrections."
                )
            }

        return {
            "reply": (
                "❓ Je n'ai pas compris votre message.\n"
                "Tapez *1* pour valider, *corriger [champ]* pour modifier, ou *aide*."
            )
        }

    def _finalize_linking(self, sess: ConversationSession, patient_id: str) -> dict:
        """Associe les enregistrements au profil patiente existant."""
        for idx, rec in enumerate(sess.extracted_records):
            rec_id = f"{sess.current_item_id or 'REC'}_{idx}"
            self.linker.link_record(patient_id, rec_id, rec)

        if sess.current_item_id:
            self.queue.transition_state(sess.current_item_id, RecordState.PATIENT_MATCHED, patient_id=patient_id)
            self.queue.transition_state(sess.current_item_id, RecordState.VALIDATED, patient_id=patient_id)

        history = self.linker.get_patient_history(patient_id)
        sess.state = DialogueState.IDLE

        return {
            "reply": (
                f"✅ *Dossier patiente enregistré avec succès !*\n\n"
                f"🆔 **ID Patiente :** `{patient_id}`\n"
                f"📈 **Visites enregistrées :** {len(sess.extracted_records)} (Total dossier : {len(history)})\n"
                f"🔒 Chiffrement local actif. Prêt pour la synchronisation dès retour réseau."
            ),
            "patient_id": patient_id,
            "status": "VALIDATED",
        }

    def _create_new_patient_and_link(self, sess: ConversationSession) -> dict:
        """Crée un nouveau profil patiente pseudonymisé et lie les visites."""
        first_rec = sess.extracted_records[0] if sess.extracted_records else {}
        p = self.linker.create_patient(
            code_patiente=first_rec.get("code_patiente"),
            age=first_rec.get("age"),
            gestite=first_rec.get("gestite"),
            parite=first_rec.get("parite"),
            groupe_sanguin=first_rec.get("groupe_sanguin"),
            rhesus=first_rec.get("rhesus"),
        )
        return self._finalize_linking(sess, p.patient_id)

    def _try_apply_correction(self, sess: ConversationSession, text: str) -> tuple[str, any] | None:
        """Parse une tentative de correction clinique par la sage-femme."""
        if not sess.extracted_records:
            sess.extracted_records.append({})
        rec = sess.extracted_records[0]

        # 1. Tension artérielle (ex: 'TA 130/80' ou '12/8' ou '130 80')
        bp = parse_blood_pressure(text, FIELDS_BY_KEY["tension_arterielle"])
        if bp.value:
            s = bp.value["tension_systolique"]
            d = bp.value["tension_diastolique"]
            rec["tension_systolique"] = s
            rec["tension_diastolique"] = d
            return "tension_systolique", f"{s}/{d} mmHg"

        # 2. Poids (ex: 'poids 68' ou 'pds 72.5')
        m_poids = re.search(r"\b(?:poids|pds)\s*[:=]?\s*(\d+(?:[.,]\d+)?)\b", text, re.IGNORECASE)
        if m_poids:
            w = float(m_poids.group(1).replace(",", "."))
            rec["poids_kg"] = w
            return "poids_kg", f"{w:g} kg"

        # 3. Âge gestationnel / Terme (ex: 'terme 34 sa' ou 'sa 34')
        ga = parse_gestational_age(text, FIELDS_BY_KEY["age_gestationnel"])
        if ga.value:
            rec["age_gestationnel"] = ga.value
            return "age_gestationnel", f"{ga.value:g} SA"

        # 4. Hauteur utérine (ex: 'hu 28' ou 'hauteur 30')
        m_hu = re.search(r"\b(?:hu|hauteur)\s*[:=]?\s*(\d+(?:[.,]\d+)?)\b", text, re.IGNORECASE)
        if m_hu:
            h = float(m_hu.group(1).replace(",", "."))
            rec["hauteur_uterine_cm"] = h
            return "hauteur_uterine_cm", f"{h:g} cm"

        # 5. BCF (ex: 'bcf 140' ou 'coeur 145')
        m_bcf = re.search(r"\b(?:bcf|coeur|fhr)\s*[:=]?\s*(\d{2,3})\b", text, re.IGNORECASE)
        if m_bcf:
            b = int(m_bcf.group(1))
            rec["bcf_bpm"] = b
            return "bcf_bpm", f"{b} bpm"

        # 6. Groupe sanguin & Rhésus (ex: 'groupe A+' ou 'O neg')
        bg = parse_blood_group(text, FIELDS_BY_KEY["groupe_rhesus"])
        if bg.value:
            g = bg.value["groupe_sanguin"]
            r = bg.value["rhesus"]
            rec["groupe_sanguin"] = g
            rec["rhesus"] = r
            return "groupe_sanguin", f"{g} {r}"

        # 7. Gestité / Parité (ex: 'G3P2')
        gp = parse_gesta_para(text, FIELDS_BY_KEY["gesta_para"])
        if gp.value:
            g = gp.value["gestite"]
            p = gp.value["parite"]
            rec["gestite"] = g
            rec["parite"] = p
            return "gestite", f"G{g}P{p}"

        return None

    def _parse_free_text_entry(self, text: str) -> dict:
        """Extrait l'ensemble des constantes médicales saisies au clavier par la sage-femme."""
        data = {}

        # Âge
        m_age = re.search(r"\b(?:age|âge)?\s*(\d{2})\s*(?:ans|a)\b", text, re.IGNORECASE)
        if m_age:
            data["age"] = int(m_age.group(1))

        # Tension
        bp = parse_blood_pressure(text, FIELDS_BY_KEY["tension_arterielle"])
        if bp.value:
            data["tension_systolique"] = bp.value["tension_systolique"]
            data["tension_diastolique"] = bp.value["tension_diastolique"]

        # Gesta / Para
        gp = parse_gesta_para(text, FIELDS_BY_KEY["gesta_para"])
        if gp.value:
            data["gestite"] = gp.value["gestite"]
            data["parite"] = gp.value["parite"]

        # Terme SA
        ga = parse_gestational_age(text, FIELDS_BY_KEY["age_gestationnel"])
        if ga.value:
            data["age_gestationnel"] = ga.value

        # Poids
        m_p = re.search(r"\b(\d{2,3}(?:[.,]\d+)?)\s*(?:kg|kilos)\b", text, re.IGNORECASE)
        if m_p:
            data["poids_kg"] = float(m_p.group(1).replace(",", "."))

        # BCF
        m_bcf = re.search(r"\b(?:bcf|coeur)\s*[:=]?\s*(\d{2,3})\b", text, re.IGNORECASE)
        if m_bcf:
            data["bcf_bpm"] = int(m_bcf.group(1))

        # Groupe
        bg = parse_blood_group(text, FIELDS_BY_KEY["groupe_rhesus"])
        if bg.value:
            data["groupe_sanguin"] = bg.value["groupe_sanguin"]
            data["rhesus"] = bg.value["rhesus"]

        return data
