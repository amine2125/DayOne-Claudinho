"""Configuration module loading environment variables."""

from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

SANDBOX_MESSAGES_URL = "https://messages-sandbox.nexmo.com/v1/messages"


class Settings(BaseSettings):
    # Vonage Messages API (canal WhatsApp)
    VONAGE_API_KEY: str = ""
    VONAGE_API_SECRET: str = ""
    # Secret de signature du compte : vérifie le JWT des webhooks. Sans lui, tout est refusé
    VONAGE_SIGNATURE_SECRET: str = ""
    # Numéro WhatsApp Business (ou celui du sandbox), format international sans « + »
    VONAGE_WHATSAPP_NUMBER: str = ""
    VONAGE_SANDBOX: bool = False
    VONAGE_API_HOST: str = "https://api.nexmo.com"
    # Adresse publique de ce serveur (celle du webhook) : Vonage y récupère les PDF envoyés
    PUBLIC_BASE_URL: str = ""

    # Clé du HMAC qui identifie la sage-femme sans son numéro : la changer change ses identifiants
    MIDWIFE_ID_SECRET: str = ""

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
    def messages_url(self) -> str:
        """Returns the Vonage Messages API endpoint (sandbox or production)."""
        if self.VONAGE_SANDBOX:
            return SANDBOX_MESSAGES_URL
        return f"{self.VONAGE_API_HOST.rstrip('/')}/v1/messages"


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
