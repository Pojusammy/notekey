import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import AnalysisJob, AnalysisResult
from app.schemas.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    JobStatusResponse,
    AnalysisResultResponse,
    NoteEventOut,
)
from app.workers.tasks import process_analysis

router = APIRouter(prefix="/api", tags=["analysis"])


@router.post("/analyze", response_model=AnalyzeResponse)
async def start_analysis(req: AnalyzeRequest, db: AsyncSession = Depends(get_db)):
    job = AnalysisJob(
        id=uuid.uuid4(),
        job_type="recording_analysis",
        input_file_url=req.fileUrl,
        selected_key=req.selectedKey,
        start_time=req.startTime,
        end_time=req.endTime,
        song_key=req.songKey,
        starting_note=req.startingNote,
        status="pending",
    )
    db.add(job)
    await db.commit()

    # Dispatch Celery task
    process_analysis.delay(str(job.id))

    return AnalyzeResponse(jobId=str(job.id))


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AnalysisJob).where(AnalysisJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")

    return JobStatusResponse(
        id=str(job.id),
        status=job.status,
        completedAt=job.completed_at,
        errorMessage=job.error_message,
    )


@router.get("/results/{job_id}", response_model=AnalysisResultResponse)
async def get_result(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AnalysisResult).where(AnalysisResult.job_id == job_id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(404, "Result not found")

    note_sequence = [NoteEventOut(**n) for n in (analysis.raw_note_sequence or [])]

    return AnalysisResultResponse(
        id=str(analysis.id),
        noteSequence=note_sequence,
        solfaSequence=analysis.solfa_sequence or [],
        confidenceScore=analysis.confidence_score or 0.0,
    )
