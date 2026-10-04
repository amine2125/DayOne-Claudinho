"""Configuration module loading environment variables."""

import os
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Meta WhatsApp Cloud API credentials
    WHATSAPP_TOKEN: str = ""
    PHONE_NUMBER_ID: str = ""
    APP_SECRET: str = ""
    # Pas de valeur par défaut : un jeton devinable permettrait à n'importe qui d'abonner le webhook
    VERIFY_TOKEN: str = ""
    GRAPH_API_VERSION: str = "v21.0"

    # Backend API URL (la route qui reçoit et traite les photos)
    OUR_API_URL: str = "http://localhost:8080/analyze"
    OUR_API_KEY: str | None = None
    # L'analyse DayOne (OCR + modèle local) peut dépasser 30 s sur une page complète
    OUR_API_TIMEOUT: float = 120.0
    # Où envoyer le registre une fois confirmé (optionnel : sans URL, il reste dans la conversation)
    CONFIRM_URL: str | None = None

    # Conversation
    SCHEMA_DIR: str = ""  # vide = dossier schema/ de DayOne
    SESSION_TTL_SECONDS: int = 2 * 3600
    MAX_PAGES: int = 10

    # Server settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def graph_api_url(self) -> str:
        """Returns base Meta Graph API URL."""
        return f"https://graph.facebook.com/{self.GRAPH_API_VERSION}"


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
