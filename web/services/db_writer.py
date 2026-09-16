import logging
import uuid
from typing import Optional
from sqlalchemy.orm import Session

from db.session import SessionLocal
from db.models import Application, PipelineEvent, ApplicationStatus, EventSource
from web.services.schemas import JobApplication

logger = logging.getLogger("db_writer")


def insert_application(
    job: JobApplication,
    raw_text: str,
    source: EventSource = EventSource.MANUAL_DROP,
    db: Optional[Session] = None,
) -> uuid.UUID:
    """
    Atomically insert an extracted JobApplication and its initial PipelineEvent audit row.
    
    Args:
        job: Validated JobApplication Pydantic schema.
        raw_text: Original raw text dump for audit preservation.
        source: Ingestion source (defaults to MANUAL_DROP).
        db: Optional existing SQLAlchemy session. If None, a new session is managed.
        
    Returns:
        UUID of the newly created Application record.
    """
    managed_session = False
    if db is None:
        db = SessionLocal()
        managed_session = True

    try:
        app_id = uuid.uuid4()
        
        # 1. Create Application record
        new_app = Application(
            id=app_id,
            company_name=job.company_name,
            canonical_company_name=job.canonical_company_name,
            role_title=job.role_title,
            source_platform=job.source_platform or "Direct",
            job_description_raw=raw_text,
            primary_tech_stack=job.primary_tech_stack,
            experience_required_yrs=job.experience_required_yrs,
            location=job.location,
            current_status=ApplicationStatus.APPLIED,
        )
        db.add(new_app)

        # 2. Append initial PipelineEvent audit record
        initial_event = PipelineEvent(
            id=uuid.uuid4(),
            application_id=app_id,
            from_status=None,
            to_status=ApplicationStatus.APPLIED,
            source=source,
            raw_payload=raw_text,
            resolution_note="Initial application logged via ingestion engine",
            llm_confidence="HIGH",
        )
        db.add(initial_event)

        # Commit atomically
        db.commit()
        db.refresh(new_app)
        logger.info("Inserted application %s for %s (%s)", app_id, job.company_name, job.role_title)
        return app_id

    except Exception as exc:
        db.rollback()
        logger.error("Failed to insert application: %s", exc, exc_info=True)
        raise exc
    finally:
        if managed_session:
            db.close()
