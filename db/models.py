import enum
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    Column,
    String,
    Text,
    Numeric,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    CheckConstraint,
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from db.session import Base


class ApplicationStatus(str, enum.Enum):
    APPLIED = "APPLIED"
    OA_PENDING = "OA_PENDING"
    INTERVIEW_ROUND = "INTERVIEW_ROUND"
    OFFER = "OFFER"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class EventSource(str, enum.Enum):
    MANUAL_DROP = "MANUAL_DROP"
    GMAIL_WORKER = "GMAIL_WORKER"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


class VaultCategory(str, enum.Enum):
    WORK_EXPERIENCE = "WORK_EXPERIENCE"
    PROJECT = "PROJECT"
    SKILL = "SKILL"
    EDUCATION = "EDUCATION"


def utc_now():
    return datetime.now(timezone.utc)


class Application(Base):
    __tablename__ = "applications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_name = Column(String(255), nullable=False)
    canonical_company_name = Column(String(255), nullable=False)
    role_title = Column(String(255), nullable=False)
    source_platform = Column(String(100), nullable=False, default="Direct")
    job_description_raw = Column(Text, nullable=True)
    primary_tech_stack = Column(JSONB, nullable=False, default=list)
    experience_required_yrs = Column(Numeric(3, 1), nullable=True)
    location = Column(String(255), nullable=True)
    current_status = Column(
        SQLEnum(ApplicationStatus, name="application_status", native_enum=True),
        nullable=False,
        default=ApplicationStatus.APPLIED,
    )
    applied_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    # Relationships
    resume_snapshots = relationship("ResumeSnapshot", back_populates="application", cascade="all, delete-orphan")
    pipeline_events = relationship("PipelineEvent", back_populates="application", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_applications_canonical_name", "canonical_company_name"),
        Index("idx_applications_status", "current_status"),
        Index("idx_applications_applied_at", applied_at.desc()),
    )


class ResumeSnapshot(Base):
    __tablename__ = "resume_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    markdown_content = Column(Text, nullable=False)
    retrieved_vault_ids = Column(JSONB, nullable=False, default=list)
    is_user_edited = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    # Relationships
    application = relationship("Application", back_populates="resume_snapshots")

    __table_args__ = (
        Index("idx_resume_snapshots_app_id", "application_id"),
    )


class PipelineEvent(Base):
    __tablename__ = "pipeline_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    from_status = Column(
        SQLEnum(ApplicationStatus, name="application_status", native_enum=True),
        nullable=True,
    )
    to_status = Column(
        SQLEnum(ApplicationStatus, name="application_status", native_enum=True),
        nullable=False,
    )
    detected_deadline = Column(DateTime(timezone=True), nullable=True)
    source = Column(
        SQLEnum(EventSource, name="event_source", native_enum=True),
        nullable=False,
    )
    raw_payload = Column(Text, nullable=False)
    resolution_note = Column(Text, nullable=True)
    llm_confidence = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    # Relationships
    application = relationship("Application", back_populates="pipeline_events")

    __table_args__ = (
        Index("idx_pipeline_events_app_id", "application_id"),
        Index("idx_pipeline_events_created", created_at.desc()),
    )


class MasterExperienceVault(Base):
    __tablename__ = "master_experience_vault"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category = Column(String(100), nullable=False)
    title = Column(String(255), nullable=False)
    bullet_point = Column(Text, nullable=False)
    tech_tags = Column(JSONB, nullable=False, default=list)
    embedding = Column(Vector(1536), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        CheckConstraint(
            "category IN ('WORK_EXPERIENCE', 'PROJECT', 'SKILL', 'EDUCATION')",
            name="check_vault_category"
        ),
        Index(
            "idx_vault_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 10},
            postgresql_ops={"embedding": "vector_cosine_ops"}
        ),
    )


class WorkerConfig(Base):
    __tablename__ = "worker_config"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
