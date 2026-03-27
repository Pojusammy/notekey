"""Celery tasks for async audio processing."""

import os
import uuid
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.celery_app import celery_app
from app.core.storage import download_to_tempfile, is_local_path
from app.models.models import AnalysisJob, AnalysisResult
from app.services.analysis_service import analyze_melody

# Sync engine for Celery workers (async not needed here)
sync_engine = create_engine(
    settings.DATABASE_URL.replace("+asyncpg", "+psycopg2")
)
SyncSession = sessionmaker(bind=sync_engine)


@celery_app.task(bind=True, max_retries=2)
def process_analysis(self, job_id: str):
    """Process an uploaded file and extract the melody."""
    session: Session = SyncSession()
    local_path: str | None = None

    try:
        job = session.query(AnalysisJob).filter(AnalysisJob.id == job_id).one()
        job.status = "processing"
        session.commit()

        # Download file to local temp if stored in cloud
        local_path = download_to_tempfile(job.input_file_url)

        # Run analysis
        result_data = analyze_melody(
            file_path=local_path,
            selected_key=job.selected_key,
            start_time=job.start_time,
            end_time=job.end_time,
            song_key=job.song_key,
            starting_note=job.starting_note,
        )

        # Store result
        analysis_result = AnalysisResult(
            id=uuid.uuid4(),
            job_id=job.id,
            raw_note_sequence=result_data["noteSequence"],
            solfa_sequence=result_data["solfaSequence"],
            confidence_score=result_data["confidenceScore"],
        )
        session.add(analysis_result)

        job.status = "completed"
        job.completed_at = datetime.utcnow()
        session.commit()

    except Exception as exc:
        session.rollback()
        job = session.query(AnalysisJob).filter(AnalysisJob.id == job_id).one()
        job.status = "failed"
        job.error_message = str(exc)
        session.commit()

        raise self.retry(exc=exc, countdown=10)
    finally:
        # Clean up temp file if it was downloaded from cloud
        if local_path and not is_local_path(job.input_file_url):
            try:
                os.unlink(local_path)
            except OSError:
                pass
        session.close()
