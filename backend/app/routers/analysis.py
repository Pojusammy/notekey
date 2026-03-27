import asyncio
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, async_session
from app.core.storage import download_to_tempfile, is_local_path
from app.models.models import AnalysisJob, AnalysisResult
from app.schemas.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    JobStatusResponse,
    AnalysisResultResponse,
    NoteEventOut,
)
from app.services.analysis_service import analyze_melody

router = APIRouter(prefix="/api", tags=["analysis"])


def _run_analysis_sync(job_id: str, file_url: str, selected_key: str,
                       start_time: str | None, end_time: str | None,
                       song_key: str | None, starting_note: str | None) -> dict:
    """Run the CPU-heavy analysis in a sync context (called via to_thread)."""
    local_path = download_to_tempfile(file_url)
    try:
        return analyze_melody(
            file_path=local_path,
            selected_key=selected_key,
            start_time=start_time,
            end_time=end_time,
            song_key=song_key,
            starting_note=starting_note,
        )
    finally:
        if not is_local_path(file_url):
            try:
                os.unlink(local_path)
            except OSError:
                pass


async def _process_job(job_id: str, file_url: str, selected_key: str,
                       start_time: str | None, end_time: str | None,
                       song_key: str | None, starting_note: str | None):
    """Background task: update status, run analysis, persist results."""
    async with async_session() as db:
        # Mark processing
        await db.execute(
            update(AnalysisJob)
            .where(AnalysisJob.id == job_id)
            .values(status="processing")
        )
        await db.commit()

    try:
        # Run CPU-bound work in a thread so we don't block the event loop
        result_data = await asyncio.to_thread(
            _run_analysis_sync, job_id, file_url, selected_key,
            start_time, end_time, song_key, starting_note,
        )

        async with async_session() as db:
            analysis_result = AnalysisResult(
                id=uuid.uuid4(),
                job_id=job_id,
                raw_note_sequence=result_data["noteSequence"],
                solfa_sequence=result_data["solfaSequence"],
                confidence_score=result_data["confidenceScore"],
            )
            db.add(analysis_result)
            await db.execute(
                update(AnalysisJob)
                .where(AnalysisJob.id == job_id)
                .values(status="completed", completed_at=datetime.utcnow())
            )
            await db.commit()

    except Exception as exc:
        async with async_session() as db:
            await db.execute(
                update(AnalysisJob)
                .where(AnalysisJob.id == job_id)
                .values(status="failed", error_message=str(exc)[:500])
            )
            await db.commit()


@router.post("/analyze", response_model=AnalyzeResponse)
async def start_analysis(req: AnalyzeRequest, db: AsyncSession = Depends(get_db)):
    job_id = uuid.uuid4()
    job = AnalysisJob(
        id=job_id,
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

    # Fire-and-forget background processing (no Celery/Redis needed)
    asyncio.create_task(_process_job(
        str(job_id), req.fileUrl, req.selectedKey,
        req.startTime, req.endTime, req.songKey, req.startingNote,
    ))

    return AnalyzeResponse(jobId=str(job_id))


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
