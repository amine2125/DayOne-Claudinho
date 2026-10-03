"""Moteur d'alertes cliniques obstétricales (Clinical Risk & Safety Detector).

Basé sur les recommandations du Ministère de la Santé du Maroc pour le suivi prénatal
et la détection précoce des grossesses à risque (GAR).
Ne pose aucun diagnostic automatisé, mais alerte la sage-femme en temps réel sur les signes de danger.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AlertSeverity(str, Enum):
    ROUGE = "ROUGE"        # Danger vital immédiat (urgence obstétricale)
    ORANGE = "ORANGE"      # Vigilance renforcée / consultation médicale spécialisée
    JAUNE = "JAUNE"        # Facteur de risque à surveiller


@dataclass
class ClinicalAlert:
    code: str
    severity: AlertSeverity
    title: str
    message: str
    action_recommandee: str


def evaluate_clinical_risks(data: dict) -> list[ClinicalAlert]:
    """Analyse les paramètres biométriques et cliniques d'un enregistrement."""
    alerts: list[ClinicalAlert] = []

    # 1. TENSION ARTÉRIELLE & PRÉÉCLAMPSIE
    sys_val = data.get("tension_systolique")
    dia_val = data.get("tension_diastolique")
    prot_val = str(data.get("proteinurie") or "").upper()

    has_severe_hta = False
    has_mild_hta = False
    if sys_val is not None and dia_val is not None:
        try:
            s = float(sys_val)
            d = float(dia_val)
            if s >= 160 or d >= 110:
                has_severe_hta = True
            elif s >= 140 or d >= 90:
                has_mild_hta = True
        except (ValueError, TypeError):
            pass

    has_proteinuria = prot_val in ("POSITIF", "POS", "+", "++", "+++", "1", "OUI")

    if has_severe_hta and has_proteinuria:
        alerts.append(ClinicalAlert(
            code="PREECLAMPSIE_SEVERE",
            severity=AlertSeverity.ROUGE,
            title="Alerte Rouge : Prééclampsie sévère suspectée",
            message=f"Tension {sys_val}/{dia_val} mmHg avec albuminurie positive.",
            action_recommandee="Évacuation urgente vers maternité de référence (Niveau 2/3), voie veineuse, repos.",
        ))
    elif has_severe_hta or (has_mild_hta and has_proteinuria):
        alerts.append(ClinicalAlert(
            code="HTA_GRAVIDIQUE_SEVERE",
            severity=AlertSeverity.ROUGE,
            title="Hypertension artérielle sévère",
            message=f"Tension {sys_val}/{dia_val} mmHg.",
            action_recommandee="Contrôle à 15 min au repos. Avis médical urgent.",
        ))
    elif has_mild_hta:
        alerts.append(ClinicalAlert(
            code="HTA_MODEREE",
            severity=AlertSeverity.ORANGE,
            title="HTA gravidique modérée",
            message=f"Tension {sys_val}/{dia_val} mmHg.",
            action_recommandee="Recherche albuminurie, bilan d'éclampsie, repos en DLG.",
        ))

    # 2. BRUITS DU CŒUR FŒTAL (BCF)
    bcf_val = data.get("bcf_bpm")
    if bcf_val is not None:
        try:
            bcf = int(bcf_val)
            if bcf < 110:
                alerts.append(ClinicalAlert(
                    code="BRADYCARDIE_FOETALE",
                    severity=AlertSeverity.ROUGE,
                    title="Alerte Rouge : Bradycardie fœtale",
                    message=f"BCF mesuré à {bcf} bpm (< 110 bpm). Suspicion de souffrance fœtale aiguë.",
                    action_recommandee="Mise en DLG, oxygénothérapie, transfert médicalisé immédiat.",
                ))
            elif bcf > 160:
                alerts.append(ClinicalAlert(
                    code="TACHYCARDIE_FOETALE",
                    severity=AlertSeverity.ORANGE,
                    title="Tachycardie fœtale",
                    message=f"BCF mesuré à {bcf} bpm (> 160 bpm).",
                    action_recommandee="Vérifier la température maternelle (recherche chorioamniotite ou fièvre).",
                ))
        except (ValueError, TypeError):
            pass

    # 3. ANÉMIE
    hb_val = data.get("hemoglobine")
    if hb_val is not None:
        try:
            hb = float(hb_val)
            if hb < 7.0:
                alerts.append(ClinicalAlert(
                    code="ANEMIE_TRES_SEVERE",
                    severity=AlertSeverity.ROUGE,
                    title="Anémie très sévère",
                    message=f"Hémoglobine à {hb} g/dL (< 7 g/dL).",
                    action_recommandee="Transfert pour transfusion sanguine et bilan hématologique.",
                ))
            elif hb < 9.0:
                alerts.append(ClinicalAlert(
                    code="ANEMIE_SEVERE",
                    severity=AlertSeverity.ORANGE,
                    title="Anémie sévère",
                    message=f"Hémoglobine à {hb} g/dL (< 9 g/dL).",
                    action_recommandee="Supplémentation fer injectable ou forte dose per os, bilan étiologique.",
                ))
        except (ValueError, TypeError):
            pass

    # 4. HAUTEUR UTÉRINE VS ÂGE GESTATIONNEL (DISCORDANCE)
    hu_val = data.get("hauteur_uterine_cm")
    sa_val = data.get("age_gestationnel")
    if hu_val is not None and sa_val is not None:
        try:
            hu = float(hu_val)
            sa = float(sa_val)
            if sa >= 22:
                if hu < (sa - 4):
                    alerts.append(ClinicalAlert(
                        code="DISCORDANCE_HU_DEFICIT",
                        severity=AlertSeverity.ORANGE,
                        title="Suspicion de RCIU / Oligoamnios",
                        message=f"Hauteur utérine ({hu} cm) nettement inférieure au terme ({sa} SA).",
                        action_recommandee="Échographie obstétricale de croissance et doppler fœto-maternel requise.",
                    ))
                elif hu > (sa + 4):
                    alerts.append(ClinicalAlert(
                        code="DISCORDANCE_HU_EXCES",
                        severity=AlertSeverity.JAUNE,
                        title="Suspicion de macrosomie ou hydramnios",
                        message=f"Hauteur utérine ({hu} cm) nettement supérieure au terme ({sa} SA).",
                        action_recommandee="Dépistage diabète gestationnel (HGPO) et échographie morphologique.",
                    ))
        except (ValueError, TypeError):
            pass

    # 5. TESTS SÉROLOGIQUES INFECTIEUX
    vih_val = str(data.get("vih") or "").upper()
    if vih_val in ("POSITIF", "POS", "+"):
        alerts.append(ClinicalAlert(
            code="VIH_POSITIF",
            severity=AlertSeverity.ROUGE,
            title="Sérologie VIH positive",
            message="Test rapide VIH réactif.",
            action_recommandee="Protocole immédiat PTME (trithérapie ARV), confirmation Western Blot.",
        ))

    syph_val = str(data.get("syphilis") or "").upper()
    if syph_val in ("POSITIF", "POS", "+"):
        alerts.append(ClinicalAlert(
            code="SYPHILIS_POSITIVE",
            severity=AlertSeverity.ORANGE,
            title="Sérologie Syphilis positive",
            message="Test TPHA/VDRL réactif.",
            action_recommandee="Traitement immédiat par Benzathine-Pénicilline G (protocole national).",
        ))

    # 6. ANTÉCÉDENTS OBSTÉTRICAUX À RISQUE
    ces_ant = str(data.get("cesarienne_anterieure") or "").upper()
    if ces_ant in ("OUI", "1", "VRAI"):
        alerts.append(ClinicalAlert(
            code="UTERUS_CICATRICIEL",
            severity=AlertSeverity.JAUNE,
            title="Utérus cicatriciel (Césarienne antérieure)",
            message="Parturiente avec antécédent de césarienne.",
            action_recommandee="Accouchement obligatoirement en milieu chirurgicalisé.",
        ))

    parite = data.get("parite")
    if parite is not None:
        try:
            if int(parite) >= 4:
                alerts.append(ClinicalAlert(
                    code="GRANDE_MULTIPARE",
                    severity=AlertSeverity.JAUNE,
                    title="Grande multiparité (P ≥ 4)",
                    message=f"Parité élevée ({parite} accouchements antérieurs).",
                    action_recommandee="Risque accru d'hémorragie de la délivrance : anticiper utérotoniques.",
                ))
        except (ValueError, TypeError):
            pass

    return alerts
