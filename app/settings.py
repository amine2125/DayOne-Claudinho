"""Configuration centralisée (surchargeable par variables d'environnement REGISTRE_*).

Tous les seuils marqués "à calibrer" doivent être fixés avec eval/calibrate.py
sur le jeu de développement du hackathon, pas à l'intuition.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default):
    raw = os.getenv(f"REGISTRE_{name.upper()}")
    if raw is None:
        return default
    if isinstance(default, bool):
        return raw.lower() in ("1", "true", "yes")
    if isinstance(default, list):
        return [x.strip() for x in raw.split(",") if x.strip()]
    return type(default)(raw)


@dataclass
class Settings:
    # --- OCR ---
    ocr_engine: str = field(default_factory=lambda: _env("ocr_engine", "rapid"))   # rapid | paddle | fake
    ocr_languages: list = field(default_factory=lambda: _env("ocr_languages", ["fr", "ar"]))
    max_image_side: int = field(default_factory=lambda: _env("max_image_side", 2000))
    denoise: bool = field(default_factory=lambda: _env("denoise", False))

    # --- Qualité image (à calibrer) ---
    blur_reject: float = field(default_factory=lambda: _env("blur_reject", 35.0))
    blur_warn: float = field(default_factory=lambda: _env("blur_warn", 90.0))
    brightness_min: float = field(default_factory=lambda: _env("brightness_min", 45.0))
    washed_out_ink_min: float = field(default_factory=lambda: _env("washed_out_ink_min", 150.0))
    contrast_min: float = field(default_factory=lambda: _env("contrast_min", 60.0))
    min_labels_ratio: float = field(default_factory=lambda: _env("min_labels_ratio", 0.08))

    # --- Statuts (à calibrer) ---
    tau_known: float = field(default_factory=lambda: _env("tau_known", 0.85))
    tau_known_vlm_agree: float = field(default_factory=lambda: _env("tau_known_vlm_agree", 0.70))
    tau_illegible: float = field(default_factory=lambda: _env("tau_illegible", 0.35))
    ink_empty_max: float = field(default_factory=lambda: _env("ink_empty_max", 0.01))

    # --- VLM local (Ollama) ---
    vlm_enabled: bool = field(default_factory=lambda: _env("vlm_enabled", False))
    ollama_url: str = field(default_factory=lambda: _env("ollama_url", "http://localhost:11434"))
    vlm_model: str = field(default_factory=lambda: _env("vlm_model", "qwen2.5vl:3b"))
    vlm_timeout_s: float = field(default_factory=lambda: _env("vlm_timeout_s", 60.0))
    vlm_max_calls_per_page: int = field(default_factory=lambda: _env("vlm_max_calls_per_page", 8))
    vlm_trigger_below: float = field(default_factory=lambda: _env("vlm_trigger_below", 0.85))


settings = Settings()
