import pytest
from pathlib import Path

from db.session import SessionLocal
from db.models import Application, PipelineEvent, ApplicationStatus, EventSource
from web.services.schemas import JobApplication, ExtractionResult
from web.services.extraction import extract_job_with_repair, parse_job_description
from web.services.db_writer import insert_application

DATA_DIR = Path(__file__).parent / "data"


def test_sparse_jd_trips_circuit_breaker():
    """Deliberately bad JD (few words, no company or role) must trip circuit breaker gracefully without crashing."""
    bad_jd = "We are hiring developers. Good culture. Great benefits."
    result: ExtractionResult = extract_job_with_repair(bad_jd, max_retries=3)

    assert result.success is False
    assert result.data is None
    assert result.circuit_broken is True
    assert result.retry_count == 3
    assert any(k in result.error.lower() for k in ["sparse", "failed", "company", "role", "invalid"])


def test_empty_jd_returns_clean_failure():
    """Empty or whitespace JD returns graceful error without unhandled exception."""
    result: ExtractionResult = extract_job_with_repair("   \n\t  ")

    assert result.success is False
    assert result.circuit_broken is True
    assert "empty" in result.error.lower()


def test_valid_jd_extraction_result():
    """Valid JD returns successful ExtractionResult with populated data."""
    raw_text = (DATA_DIR / "jd_naukri_backend.txt").read_text(encoding="utf-8")
    result: ExtractionResult = extract_job_with_repair(raw_text, force_fallback=True)

    assert result.success is True
    assert result.circuit_broken is False
    assert result.data is not None
    assert isinstance(result.data, JobApplication)
    assert result.data.canonical_company_name in ["bundl", "swiggy"]


def test_full_insert_application_to_db():
    """Test full flow: extract JD -> insert_application -> verify Application and PipelineEvent in PostgreSQL."""
    raw_text = (DATA_DIR / "jd_naukri_backend.txt").read_text(encoding="utf-8")
    job = parse_job_description(raw_text, force_fallback=True)

    db = SessionLocal()
    app_id = None
    try:
        app_id = insert_application(job=job, raw_text=raw_text, source=EventSource.MANUAL_DROP, db=db)
        assert app_id is not None

        # Verify Application row in DB
        saved_app = db.query(Application).filter_by(id=app_id).first()
        assert saved_app is not None
        assert saved_app.company_name == job.company_name
        assert saved_app.canonical_company_name == job.canonical_company_name
        assert saved_app.role_title == job.role_title
        assert saved_app.current_status == ApplicationStatus.APPLIED
        assert saved_app.experience_required_yrs == 3.0
        assert saved_app.job_description_raw == raw_text

        # Verify initial PipelineEvent audit row
        assert len(saved_app.pipeline_events) == 1
        event: PipelineEvent = saved_app.pipeline_events[0]
        assert event.from_status is None
        assert event.to_status == ApplicationStatus.APPLIED
        assert event.source == EventSource.MANUAL_DROP
        assert event.raw_payload == raw_text
        assert event.llm_confidence == "HIGH"

    finally:
        # Clean up test row
        if app_id:
            row = db.query(Application).filter_by(id=app_id).first()
            if row:
                db.delete(row)
                db.commit()
        db.close()
