import uuid
from datetime import datetime

from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Text, Enum, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    auth_provider = Column(String(50), default="email")
    created_at = Column(DateTime, default=datetime.utcnow)

    jobs = relationship("AnalysisJob", back_populates="user")
    sessions = relationship("SavedSession", back_populates="user")


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    job_type = Column(
        Enum("note_detection", "recording_analysis", name="job_type_enum"),
        nullable=False,
    )
    input_file_url = Column(Text, nullable=True)
    selected_key = Column(String(10), nullable=False, default="C")
    start_time = Column(String(20), nullable=True)
    end_time = Column(String(20), nullable=True)
    song_key = Column(String(10), nullable=True)
    starting_note = Column(String(10), nullable=True)
    status = Column(
        Enum("pending", "processing", "completed", "failed", name="job_status_enum"),
        nullable=False,
        default="pending",
    )
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    user = relationship("User", back_populates="jobs")
    result = relationship("AnalysisResult", back_populates="job", uselist=False)


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(
        UUID(as_uuid=True), ForeignKey("analysis_jobs.id"), nullable=False, unique=True
    )
    note_name = Column(String(10), nullable=True)
    frequency_hz = Column(Float, nullable=True)
    cents_offset = Column(Float, nullable=True)
    tonic_solfa = Column(String(10), nullable=True)
    raw_note_sequence = Column(JSON, nullable=True)
    solfa_sequence = Column(JSON, nullable=True)
    timestamps_json = Column(JSON, nullable=True)
    confidence_score = Column(Float, nullable=True)

    job = relationship("AnalysisJob", back_populates="result")
    saved_session = relationship("SavedSession", back_populates="result", uselist=False)


class SavedSession(Base):
    __tablename__ = "saved_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    title = Column(String(255), nullable=False, default="Untitled")
    result_id = Column(
        UUID(as_uuid=True),
        ForeignKey("analysis_results.id"),
        nullable=False,
    )
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="sessions")
    result = relationship("AnalysisResult", back_populates="saved_session")
