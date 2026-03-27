import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException

from app.core.config import settings
from app.core.storage import upload_file
from app.schemas.schemas import UploadResponse

router = APIRouter(prefix="/api", tags=["upload"])

ALLOWED_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".aac",  # audio
    ".mp4", ".mov", ".webm",          # video
}


@router.post("/upload", response_model=UploadResponse)
async def upload(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {ext}")

    if file.size and file.size > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(400, f"File exceeds {settings.MAX_UPLOAD_SIZE_MB}MB limit")

    content = await file.read()
    file_id = str(uuid.uuid4())
    storage_key = upload_file(content, file.filename or f"{file_id}{ext}")

    return UploadResponse(
        fileUrl=storage_key,
        fileId=file_id,
    )
