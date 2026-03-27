from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    APP_NAME: str = "NoteKey API"
    DEBUG: bool = False
    PORT: int = 8000

    # Database (Supabase Postgres or any Postgres)
    DATABASE_URL: str = "postgresql+asyncpg://notekey:notekey@localhost:5432/notekey"

    # Storage — "local" for dev, "supabase" for production
    STORAGE_BACKEND: str = "local"
    UPLOAD_DIR: str = "./uploads"

    # Supabase Storage (used when STORAGE_BACKEND=supabase)
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""
    SUPABASE_BUCKET: str = "uploads"

    # Upload limits
    MAX_UPLOAD_SIZE_MB: int = 100

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
