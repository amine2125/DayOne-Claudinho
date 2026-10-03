"""Score de confiance final : produit de facteurs explicables, sans aucune valeur issue d'un LLM.

    score = c_ocr × f_qualité × f_localisation × f_validation

- c_ocr          : min des scores PaddleOCR des tokens de la valeur (maillon le plus faible)
- f_qualité      : 1.0 (BONNE) / 0.9 (MOYENNE)          -- les images REJETEE n'arrivent pas ici
- f_localisation : 1.0 libellé + même ligne / cellule, 0.95 dessous, 0.85 motif sans libellé,
                   × score du libellé si reconnu en flou (ex: 0.88)
- f_validation   : 0.8 ** nb_avertissements (max 2) : virgule supposée, cmHg converti,
                   valeur inhabituelle, correction de caractère...

L'accord du VLM ne modifie PAS le score : c'est un signal binaire qui change le SEUIL
(tau_known_vlm_agree), seuil lui-même calibré sur le jeu de dev. Un désaccord force A_REVISER.
Le score n'est pas une probabilité tant qu'il n'est pas calibré (cf. eval/evaluate.py).
"""
from __future__ import annotations

from app.schemas.models import ConfidenceSignals, Localisation, QualityLevel

QUALITY_FACTOR = {QualityLevel.BONNE: 1.0, QualityLevel.MOYENNE: 0.9, QualityLevel.REJETEE: 0.0}
LOCALISATION_FACTOR = {
    Localisation.INLINE: 1.0,
    Localisation.RIGHT: 1.0,
    Localisation.TABLE: 1.0,
    Localisation.BELOW: 0.95,
    Localisation.PATTERN: 0.85,
    Localisation.NOT_FOUND: 0.0,
}
WARNING_FACTOR = 0.8


def compute_confidence(ocr_conf: float | None, quality: QualityLevel, localisation: Localisation,
                       label_score: float = 100.0, n_warnings: int = 0,
                       vlm_agreement: bool | None = None) -> tuple[float, ConfidenceSignals]:
    f_q = QUALITY_FACTOR[quality]
    f_loc = LOCALISATION_FACTOR[localisation] * (label_score / 100 if localisation != Localisation.PATTERN else 1.0)
    f_val = WARNING_FACTOR ** min(n_warnings, 2)
    c_ocr = ocr_conf if ocr_conf is not None else 1.0
    score = max(0.0, min(1.0, c_ocr * f_q * f_loc * f_val))
    return round(score, 3), ConfidenceSignals(
        ocr=None if ocr_conf is None else round(ocr_conf, 3), quality=f_q,
        localisation=round(f_loc, 3), validation=round(f_val, 3), vlm_agreement=vlm_agreement)
