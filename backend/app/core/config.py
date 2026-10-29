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

    SHORT_LINK_BASE_URL: str = "http://localhost:8001"

    # Database connection pool (configurable to prevent exhausting PostgreSQL max_connections)
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_PRE_PING: bool = True

    # OAuth endpoints (configurable for local mocking and testing)
    GOOGLE_AUTH_URL: str = "https://accounts.google.com/o/oauth2/v2/auth"
    GOOGLE_TOKEN_URL: str = "https://oauth2.googleapis.com/token"
    GOOGLE_CERTS_URL: str = "https://www.googleapis.com/oauth2/v3/certs"
    GITHUB_AUTH_URL: str = "https://github.com/login/oauth/authorize"
    GITHUB_TOKEN_URL: str = "https://github.com/login/oauth/access_token"
    GITHUB_USER_URL: str = "https://api.github.com/user"
    GITHUB_EMAILS_URL: str = "https://api.github.com/user/emails"

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
