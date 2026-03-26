from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    APP_NAME: str = "NoteKey API"
    DEBUG: bool = True
    API_PREFIX: str = "/api"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://notekey:notekey@localhost:5432/notekey"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # Storage
    STORAGE_BACKEND: str = "local"  # "local" or "s3"
    UPLOAD_DIR: str = "./uploads"
    S3_BUCKET: str = ""
    S3_REGION: str = ""
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""

    # Upload limits
    MAX_UPLOAD_SIZE_MB: int = 100

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    class Config:
        env_file = ".env"


settings = Settings()
