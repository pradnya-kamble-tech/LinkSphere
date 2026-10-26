
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "LinkSphere API"
    app_version: str = "0.1.0"
    environment: str = "development"

    database_url: str
    secret_key: str

    # Session security
    access_token_expire_minutes: int = 30
    session_cookie_name: str = "linksphere_session"
    session_cookie_secure: bool = False
    session_max_age_seconds: int = 1800

    # Application URLs
    frontend_url: str = "http://localhost:5173"
    backend_url: str = "http://localhost:8000"

    # Resend email delivery
    resend_api_key: str = ""
    email_from: str = "LinkSphere <onboarding@resend.dev>"

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""

    # GitHub OAuth
    github_client_id: str = ""
    github_client_secret: str = ""

    # Passwordless email token settings
    email_login_token_expire_minutes: int = 15
    email_verification_token_expire_minutes: int = 15

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
