from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


# --- Upload ---
class UploadResponse(BaseModel):
    fileUrl: str
    fileId: str


# --- Analysis ---
class AnalyzeRequest(BaseModel):
    fileUrl: str
    selectedKey: str = "C"
    startTime: str | None = None
    endTime: str | None = None
    songKey: str | None = None
    startingNote: str | None = None
    analysisMode: str = "standard"  # "standard", "fast", or "roots"


class AnalyzeResponse(BaseModel):
    jobId: str


# --- Job Status ---
class JobStatusResponse(BaseModel):
    id: str
    status: str
    completedAt: datetime | None = None
    errorMessage: str | None = None


# --- Results ---
class NoteEventOut(BaseModel):
    noteName: str
    octave: int
    startTime: float
    duration: float
    frequency: float
    solfa: str


class AnalysisResultResponse(BaseModel):
    id: str
    noteSequence: list[NoteEventOut]
    solfaSequence: list[str]
    confidenceScore: float


# --- History ---
class SavedSessionOut(BaseModel):
    id: str
    title: str
    resultId: str
    createdAt: datetime
