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
    ai_input_cost_per_million: float = float(os.getenv("AI_INPUT_COST_PER_MILLION", "0"))
    ai_output_cost_per_million: float = float(os.getenv("AI_OUTPUT_COST_PER_MILLION", "0"))
    eval_judge_model: str = os.getenv("EVAL_JUDGE_MODEL", "gpt-4.1-mini")
    openai_temperature: float = float(os.getenv("OPENAI_TEMPERATURE", "0"))
    ai_logical_request_stale_seconds: int = int(
        os.getenv("AI_LOGICAL_REQUEST_STALE_SECONDS", "900")
    )

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    def __post_init__(self) -> None:
        if self.is_production and self.auth_disabled:
            raise ValueError("AUTH_DISABLED=true is forbidden when ENVIRONMENT=production")


settings = Settings()
