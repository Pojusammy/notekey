"""Storage abstraction — local filesystem for dev, Supabase Storage for production."""

import os
import tempfile
import uuid
from pathlib import Path

from app.core.config import settings


def upload_file(content: bytes, filename: str) -> str:
    """Upload file bytes and return a storage key/path."""
    file_id = str(uuid.uuid4())
    ext = Path(filename).suffix.lower()
    storage_key = f"{file_id}{ext}"

    if settings.STORAGE_BACKEND == "supabase":
        from supabase import create_client

        client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
        client.storage.from_(settings.SUPABASE_BUCKET).upload(
            path=storage_key,
            file=content,
            file_options={"content-type": "application/octet-stream"},
        )
        return storage_key
    else:
        upload_dir = Path(settings.UPLOAD_DIR)
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / storage_key
        file_path.write_bytes(content)
        return str(file_path)


def download_to_tempfile(storage_key: str) -> str:
    """Download a file to a local temp path for processing. Returns the temp path."""
    if settings.STORAGE_BACKEND == "supabase":
        from supabase import create_client

        client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
        data = client.storage.from_(settings.SUPABASE_BUCKET).download(storage_key)
        ext = Path(storage_key).suffix
        tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
        tmp.write(data)
        tmp.close()
        return tmp.name
    else:
        # Local storage — the key IS the file path already
        if os.path.isfile(storage_key):
            return storage_key
        # Fall back to checking inside UPLOAD_DIR
        candidate = Path(settings.UPLOAD_DIR) / storage_key
        if candidate.is_file():
            return str(candidate)
        return storage_key


def is_local_path(storage_key: str) -> bool:
    """Check if the storage key is a local file path (not a cloud key)."""
    return settings.STORAGE_BACKEND == "local"
