from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    APP_NAME: str = "NéoBanque Core Portal"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    PORT: int = 8000
    HOST: str = "0.0.0.0"

    # Sécurité & Tokens
    SECRET_KEY: str = "ba8f4491ad33375cf9291e268d85c5646ab8b8cc563c301fa0dabb5ec4b77e80"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    COOKIE_NAME: str = "neobank_session"
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"

    # Chiffrement PCI-DSS (AES-256 / Fernet key)
    CARD_ENCRYPTION_KEY: str = "HooHd-zYeuRqjmfbcvL3fQBr8WaHls8mVISfaIhen5A="

    # Base de données
    DATABASE_URL: str = "sqlite+aiosqlite:///./neobank.db"

    # Redis & Idempotence
    REDIS_URL: Optional[str] = "redis://localhost:6379/0"

    # Modes bancaires
    USE_MOCK_BANKING: bool = True

    # CBS - Core Banking System
    CBS_API_URL: str = "https://cbs-core.neobanque.internal/api/v1"
    CBS_MTLS_CERT_PATH: str = "./certs/cbs_client.crt"
    CBS_MTLS_KEY_PATH: str = "./certs/cbs_client.key"
    CBS_TIMEOUT_SECONDS: float = 10.0
    CBS_MAX_RETRIES: int = 3

    # CMS - Card Management System
    CMS_API_URL: str = "https://cms-switch.neobanque.internal/api/v2"
    CMS_HMAC_SECRET: str = "cms_production_secret_hmac_key_2026_banking"
    CMS_CLIENT_ID: str = "NEO_CMS_CLIENT_FR01"
    CMS_TIMEOUT_SECONDS: float = 8.0

    # Paramètres bancaires nationaux
    DEFAULT_BANK_CODE: str = "30004"
    DEFAULT_BRANCH_CODE: str = "02050"
    DEFAULT_BIC: str = "NEOBFRPPXXX"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

