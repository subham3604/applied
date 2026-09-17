import logging
import uuid
from typing import Any, List, Optional
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.models import Application, EventSource, ResumeSnapshot
from db.session import SessionLocal
from web.services.db_writer import insert_application
from web.services.extraction import extract_job_with_repair
from web.services.resume_generator import (
    ResumeGenerationResult,
    generate_tailored_resume,
    save_resume_snapshot,
)
from web.services.schemas import ExtractionResult, JobApplication

logger = logging.getLogger("pipeline_service")


class PipelineResult(BaseModel):
    """Encapsulates the complete outcome of ingesting a job description into Phase 1."""
    success: bool = Field(..., description="True if extraction, DB storage, and resume tailoring succeeded")
    application_id: Optional[uuid.UUID] = Field(None, description="UUID of created Application row")
    company_name: Optional[str] = Field(None, description="Company name extracted from JD")
    role_title: Optional[str] = Field(None, description="Exact role title extracted from JD")
    canonical_company_name: Optional[str] = Field(None, description="Normalized lowercase alphanumeric company name")
    source_platform: Optional[str] = Field(None, description="Source platform: Naukri, LinkedIn, Direct, etc.")
    location: Optional[str] = Field(None, description="Job location extracted from JD")
    primary_tech_stack: List[str] = Field(default_factory=list, description="Extracted core technologies")
    resume_snapshot_id: Optional[uuid.UUID] = Field(None, description="UUID of active ResumeSnapshot row")
    markdown_resume: Optional[str] = Field(None, description="Assembled grounded Markdown resume")
    projects_used: List[str] = Field(default_factory=list, description="Projects selected by hierarchical RAG")
    retrieved_vault_ids: List[str] = Field(default_factory=list, description="Master vault bullet IDs utilized")
    guard_passed: bool = Field(False, description="True if 0 hallucinations detected")
    circuit_broken: bool = Field(False, description="True if self-repair circuit breaker tripped on malformed input")
    extraction_retries: int = Field(0, description="Self-repair retry attempts during extraction")
    error: Optional[str] = Field(None, description="Error explanation if unsuccessful")


def process_raw_jd(
    raw_text: str,
    source_platform: Optional[str] = None,
    source: EventSource = EventSource.MANUAL_DROP,
    db: Optional[Session] = None,
) -> PipelineResult:
    """
    Unified end-to-end Phase 1 pipeline entrypoint:
    1. Extracts structured fields via LLM with self-repair loop and circuit breaker.
    2. Inserts Application record and audit PipelineEvent into PostgreSQL.
    3. Runs pgvector RAG to tailor cohesive projects and prioritized skills.
    4. Deterministically synthesizes an ATS-compliant Markdown resume with pinned invariants.
    5. Runs anti-hallucination token guard.
    6. Persists active ResumeSnapshot in PostgreSQL.
    
    Args:
        raw_text: Raw unstructured job description text.
        source_platform: Optional platform override (e.g. 'Naukri', 'LinkedIn').
        source: Ingestion source enum (defaults to MANUAL_DROP).
        db: Optional existing SQLAlchemy session. If None, manages a new session.
        
    Returns:
        PipelineResult with all relational identifiers, extracted data, and resume content.
    """
    if not raw_text or not raw_text.strip():
        return PipelineResult(
            success=False,
            circuit_broken=True,
            error="Job description text cannot be empty or whitespace.",
        )

    managed_session = False
    if db is None:
        db = SessionLocal()
        managed_session = True

    try:
        # Step 1: Extract structured job application with self-repair
        logger.info("Executing structured extraction with self-repair...")
        extraction: ExtractionResult = extract_job_with_repair(raw_text)

        if not extraction.success or not extraction.data:
            logger.warning("Extraction unsuccessful: %s (circuit_broken=%s)", extraction.error, extraction.circuit_broken)
            return PipelineResult(
                success=False,
                circuit_broken=extraction.circuit_broken,
                extraction_retries=extraction.retry_count,
                error=extraction.error or "Failed to extract structured data from job description.",
            )

        job: JobApplication = extraction.data
        if source_platform:
            job.source_platform = source_platform

        # Step 2: Persist Application to PostgreSQL
        logger.info("Writing application record for %s (%s) to PostgreSQL...", job.company_name, job.role_title)
        app_id = insert_application(
            job=job,
            raw_text=raw_text,
            source=source,
            db=db,
        )

        # Step 3 & 4: Retrieve RAG projects, skills, and synthesize grounded resume
        logger.info("Generating tailored grounded resume for application %s...", app_id)
        resume_res: ResumeGenerationResult = generate_tailored_resume(
            jd_text=raw_text,
            top_n_projects=2,
            bullets_per_project=3,
            db=db,
        )

        # Step 5: Save active resume snapshot
        logger.info("Saving active resume snapshot for application %s...", app_id)
        snapshot: ResumeSnapshot = save_resume_snapshot(
            application_id=app_id,
            markdown_content=resume_res.markdown_content,
            vault_ids=resume_res.retrieved_vault_ids,
            is_user_edited=False,
            db=db,
        )

        return PipelineResult(
            success=True,
            application_id=app_id,
            company_name=job.company_name,
            role_title=job.role_title,
            canonical_company_name=job.canonical_company_name,
            source_platform=job.source_platform,
            location=job.location,
            primary_tech_stack=job.primary_tech_stack,
            resume_snapshot_id=snapshot.id,
            markdown_resume=resume_res.markdown_content,
            projects_used=resume_res.projects_used,
            retrieved_vault_ids=resume_res.retrieved_vault_ids,
            guard_passed=resume_res.guard_passed,
            circuit_broken=False,
            extraction_retries=extraction.retry_count,
        )

    except Exception as exc:
        logger.error("Pipeline failure while processing job description: %s", exc, exc_info=True)
        return PipelineResult(
            success=False,
            circuit_broken=False,
            error=str(exc),
        )
    finally:
        if managed_session:
            db.close()
