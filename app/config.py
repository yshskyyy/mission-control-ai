import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    database_path: Path = Path(
        os.getenv("DATABASE_PATH", str(BASE_DIR / "memory_data" / "mission_control.db"))
    )
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    database_url: str | None = os.getenv("DATABASE_URL")
    redis_url: str | None = os.getenv("REDIS_URL")
    jwt_secret: str = os.getenv("JWT_SECRET", "local-development-secret-change-me")
    jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))
    auth_disabled: bool = os.getenv("AUTH_DISABLED", "false").lower() == "true"
    sentry_dsn: str | None = os.getenv("SENTRY_DSN")
    otel_exporter_endpoint: str | None = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    environment: str = os.getenv("ENVIRONMENT", "development")

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


settings = Settings()
