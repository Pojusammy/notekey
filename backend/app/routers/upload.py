import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

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


class PresignedUrlRequest(BaseModel):
    filename: str


class PresignedUrlResponse(BaseModel):
    signedUrl: str
    path: str
    useProxy: bool = False  # True when Supabase isn't available (dev mode)


@router.post("/upload/init", response_model=PresignedUrlResponse)
async def create_upload_url(req: PresignedUrlRequest):
    """
    Return a short-lived Supabase presigned URL so the browser can upload large files
    directly to Supabase storage — bypassing Vercel's 4.5 MB serverless body limit.
    Falls back to useProxy=True in local-storage dev mode.
    """
    ext = Path(req.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {ext}")

    # Local storage dev mode: tell the client to use the regular proxy upload
    if settings.STORAGE_BACKEND != "supabase":
        return PresignedUrlResponse(signedUrl="", path="", useProxy=True)

    from supabase import create_client
    storage_key = f"{uuid.uuid4()}{ext}"
    client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
    result = client.storage.from_(settings.SUPABASE_BUCKET).create_signed_upload_url(storage_key)

    signed_url = result.get("signedUrl") or result.get("data", {}).get("signedUrl", "")
    if not signed_url:
        raise HTTPException(500, "Could not create upload URL")

    return PresignedUrlResponse(signedUrl=signed_url, path=storage_key)
