"""Contrôles de vraisemblance.

IMPORTANT : ces règles servent UNIQUEMENT à détecter une erreur probable d'extraction
(chiffre mal lu, colonne décalée). Elles ne produisent jamais de diagnostic, de triage
ni de recommandation clinique. Une valeur hors bornes n'est pas "anormale" : elle est
"à relire".
"""
from __future__ import annotations

from dataclasses import dataclass

from app.schemas.form_spec import FIELDS_BY_KEY

# Bornes des champs de sortie qui ne sont pas des specs directes (composites)
_OUTPUT_BOUNDS: dict[str, tuple[float, float, float, float]] = {
    # key: (hard_min, hard_max, soft_min, soft_max)
    "tension_systolique": (50, 260, 80, 200),
    "tension_diastolique": (25, 160, 40, 130),
}


@dataclass
class RangeCheck:
    hard_ok: bool
    warning: str | None = None


def check_range(output_key: str, value: object) -> RangeCheck:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return RangeCheck(hard_ok=True)
    if output_key in _OUTPUT_BOUNDS:
        hmin, hmax, smin, smax = _OUTPUT_BOUNDS[output_key]
    elif (spec := FIELDS_BY_KEY.get(output_key)) is not None:
        hmin, hmax, smin, smax = spec.hard_min, spec.hard_max, spec.soft_min, spec.soft_max
    else:
        return RangeCheck(hard_ok=True)
    if (hmin is not None and value < hmin) or (hmax is not None and value > hmax):
        return RangeCheck(hard_ok=False, warning="valeur_impossible_erreur_extraction_probable")
    if (smin is not None and value < smin) or (smax is not None and value > smax):
        return RangeCheck(hard_ok=True, warning="valeur_inhabituelle_a_verifier")
    return RangeCheck(hard_ok=True)


def cross_field_conflicts(values: dict[str, object]) -> list[tuple[tuple[str, ...], str]]:
    """Incohérences entre champs -> les champs concernés passent en A_REVISER."""
    conflicts: list[tuple[tuple[str, ...], str]] = []
    s, d = values.get("tension_systolique"), values.get("tension_diastolique")
    if isinstance(s, (int, float)) and isinstance(d, (int, float)) and s <= d:
        conflicts.append((("tension_systolique", "tension_diastolique"), "systolique_inferieure_a_diastolique"))
    g, p = values.get("gestite"), values.get("parite")
    if isinstance(g, int) and isinstance(p, int) and p > g:
        conflicts.append((("gestite", "parite"), "parite_superieure_a_gestite"))
    return conflicts
