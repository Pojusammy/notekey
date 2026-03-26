import os
import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException

from app.core.config import settings
from app.schemas.schemas import UploadResponse

router = APIRouter(prefix="/api", tags=["upload"])

ALLOWED_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".aac",  # audio
    ".mp4", ".mov", ".webm",          # video
}


@router.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {ext}")

    if file.size and file.size > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(400, f"File exceeds {settings.MAX_UPLOAD_SIZE_MB}MB limit")

    file_id = str(uuid.uuid4())
    filename = f"{file_id}{ext}"

    # Local storage for V1
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / filename

    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    return UploadResponse(
        fileUrl=str(file_path),
        fileId=file_id,
    )
