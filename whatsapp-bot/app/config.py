"""Configuration module loading environment variables."""

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

    # API DayOne (api/main.py) : lecture, base des dossiers, tableau de bord
    DAYONE_API_URL: str = "http://localhost:8000"
    OUR_API_KEY: str | None = None
    # Lecture d'une page (OCR + modèle local) : jusqu'à quelques minutes sur une petite machine
    READ_TIMEOUT_PER_PAGE: float = 300.0

    # Conversation
    SESSION_TTL_SECONDS: int = 2 * 3600
    MAX_PAGES: int = 10

    # Server settings (8000 est pris par l'API DayOne)
    HOST: str = "0.0.0.0"
    PORT: int = 8001

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
