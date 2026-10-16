from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str = "sqlite+aiosqlite:///./dev.db"
    redis_url: str = "redis://localhost:6379/0"  # memory:// = in-process fake
    jwt_secret: str = "change-me"
    jwt_expire_minutes: int = 60 * 24
    webhook_secret: str = "change-me-too"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    expose_reset_tokens: bool = False  # local only; production delivers the token by email
    telegram_bot_token: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_tls: bool = True
    public_app_url: str = "http://localhost:5173"
    news_feed_url: str = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    news_refresh_hours: int = 6


settings = Settings()
