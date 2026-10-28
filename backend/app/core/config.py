from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+psycopg://linksphere_user:linksphere_dev_password@localhost:5434/linksphere_db"
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:5174"
    FRONTEND_ORIGIN: str = "http://localhost:5173"
    ENVIRONMENT: str = "local"  # local, test, production

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    SESSION_SECRET: str = ""

    SESSION_LIFETIME_DAYS: int = 7
    SESSION_IDLE_TIMEOUT_HOURS: int = 24

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def cookie_secure(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    def validate_secrets(self) -> None:
        """Validate that all required credentials exist. Never logs secret values."""
        if self.ENVIRONMENT.lower() == "test":
            return
        required_vars = [
            ("GOOGLE_CLIENT_ID", self.GOOGLE_CLIENT_ID),
            ("GOOGLE_CLIENT_SECRET", self.GOOGLE_CLIENT_SECRET),
            ("GITHUB_CLIENT_ID", self.GITHUB_CLIENT_ID),
            ("GITHUB_CLIENT_SECRET", self.GITHUB_CLIENT_SECRET),
            ("SESSION_SECRET", self.SESSION_SECRET),
        ]
        missing = [name for name, val in required_vars if not val or not val.strip()]
        if missing:
            raise RuntimeError(
                f"ConfigurationError: Missing required environment variable(s): {', '.join(missing)}"
            )


settings = Settings()
settings.validate_secrets()
