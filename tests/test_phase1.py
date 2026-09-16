import uuid
from pathlib import Path
import pytest
from sqlalchemy.orm import Session

from db.models import Application, ApplicationStatus, PipelineEvent, ResumeSnapshot
from db.session import SessionLocal
from web.services.pipeline import PipelineResult, process_raw_jd
from web.services.resume_generator import (
    get_active_resume_snapshot,
    save_resume_snapshot,
)

DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def db():
    session = SessionLocal()
    yield session
    session.close()


# ==============================================================================
# 1. End-to-End Ingestion, Extraction, RAG & Resume Verification
# ==============================================================================

def test_end_to_end_pipeline_naukri_backend(db: Session):
    """
    Test Phase 1 ingestion on Naukri Backend JD:
    Raw Text -> Extraction (Swiggy) -> DB Application -> pgvector RAG -> Grounded Resume -> ResumeSnapshot
    """
    raw_text = (DATA_DIR / "jd_naukri_backend.txt").read_text(encoding="utf-8")
    result: PipelineResult = process_raw_jd(raw_text, db=db)

    assert result.success is True
    assert result.application_id is not None
    assert result.company_name == "Swiggy"
    assert "Backend" in result.role_title or "SDE" in result.role_title
    assert result.canonical_company_name == "swiggy"
    assert len(result.primary_tech_stack) > 0
    assert result.resume_snapshot_id is not None
    assert result.guard_passed is True

    # Validate Pinned Resume Sections
    assert "Subham Yadav" in result.markdown_resume
    assert "GlobalLogic (Client: Google)" in result.markdown_resume
    assert "Accenture" in result.markdown_resume
    assert "Indian Institute of Technology Ropar" in result.markdown_resume
    assert "CGPA: 7.27" in result.markdown_resume
    assert "400+ DSA" in result.markdown_resume

    # Verify Database Rows
    try:
        app_row = db.query(Application).filter_by(id=result.application_id).first()
        assert app_row is not None
        assert app_row.company_name == "Swiggy"
        assert app_row.current_status == ApplicationStatus.APPLIED

        snapshot_row = db.query(ResumeSnapshot).filter_by(id=result.resume_snapshot_id).first()
        assert snapshot_row is not None
        assert snapshot_row.is_active is True
        assert snapshot_row.is_user_edited is False
        assert snapshot_row.application_id == result.application_id

        # Verify initial audit event
        events = db.query(PipelineEvent).filter_by(application_id=result.application_id).all()
        assert len(events) >= 1
        assert events[0].to_status == ApplicationStatus.APPLIED
    finally:
        # Cleanup
        app_to_delete = db.query(Application).filter_by(id=result.application_id).first()
        if app_to_delete:
            db.delete(app_to_delete)
            db.commit()


def test_end_to_end_pipeline_naukri_ai(db: Session):
    """
    Test Phase 1 ingestion on Naukri AI Systems JD:
    Extraction (Zomato) -> RAG selects Autonomous Career Pipeline & Genesis -> Grounded Resume
    """
    raw_text = (DATA_DIR / "jd_naukri_ai.txt").read_text(encoding="utf-8")
    result: PipelineResult = process_raw_jd(raw_text, db=db)

    assert result.success is True
    assert result.application_id is not None
    assert result.company_name == "Zomato"
    assert "AI Systems Engineer" in result.role_title
    assert result.guard_passed is True
    assert len(result.projects_used) == 2

    # Verify AI-specific project was matched
    assert any("career pipeline" in p.lower() for p in result.projects_used)

    try:
        app_row = db.query(Application).filter_by(id=result.application_id).first()
        assert app_row is not None
    finally:
        app_to_delete = db.query(Application).filter_by(id=result.application_id).first()
        if app_to_delete:
            db.delete(app_to_delete)
            db.commit()


def test_end_to_end_pipeline_linkedin_fullstack(db: Session):
    """
    Test Phase 1 ingestion on LinkedIn Full Stack JD:
    Extraction (PhonePe) -> RAG selects Genesis (Kubernetes/Cloud) -> Grounded Resume
    """
    raw_text = (DATA_DIR / "jd_linkedin_fullstack.txt").read_text(encoding="utf-8")
    result: PipelineResult = process_raw_jd(raw_text, db=db)

    assert result.success is True
    assert result.application_id is not None
    assert result.company_name == "PhonePe"
    assert "Full Stack" in result.role_title
    assert result.guard_passed is True
    assert len(result.projects_used) == 2

    # Verify Cloud/K8s project was matched
    assert any("genesis" in p.lower() for p in result.projects_used)

    try:
        app_row = db.query(Application).filter_by(id=result.application_id).first()
        assert app_row is not None
    finally:
        app_to_delete = db.query(Application).filter_by(id=result.application_id).first()
        if app_to_delete:
            db.delete(app_to_delete)
            db.commit()


# ==============================================================================
# 2. Circuit Breaker & Negative Path Tests
# ==============================================================================

def test_pipeline_sparse_jd_trips_circuit_breaker(db: Session):
    """Fewer than 12 words must trip the circuit breaker without DB insertion."""
    sparse_text = "Hiring software developers urgently. Call 9999999999."
    result = process_raw_jd(sparse_text, db=db)

    assert result.success is False
    assert result.circuit_broken is True
    assert result.application_id is None
    assert result.resume_snapshot_id is None


def test_pipeline_empty_text_returns_clean_failure(db: Session):
    """Empty or whitespace text must return clean failure without throwing unhandled exceptions."""
    result = process_raw_jd("   \n   ", db=db)

    assert result.success is False
    assert result.circuit_broken is True
    assert result.application_id is None


# ==============================================================================
# 3. Snapshot Lifecycle & Cascade Integrity Tests
# ==============================================================================

def test_pipeline_user_editing_and_versioning_lifecycle(db: Session):
    """Simulate candidate UI edits: older snapshot retired, new snapshot flagged is_user_edited."""
    raw_text = (DATA_DIR / "jd_naukri_ai.txt").read_text(encoding="utf-8")
    result = process_raw_jd(raw_text, db=db)
    assert result.success is True

    app_id = result.application_id
    try:
        # Initial snapshot
        snap1 = get_active_resume_snapshot(app_id, db=db)
        assert snap1 is not None
        assert snap1.id == result.resume_snapshot_id
        assert snap1.is_active is True
        assert snap1.is_user_edited is False

        # Candidate edits the resume on Streamlit UI
        customized_content = snap1.markdown_content + "\n<!-- Candidate custom note -->\n"
        snap2 = save_resume_snapshot(
            application_id=app_id,
            markdown_content=customized_content,
            vault_ids=result.retrieved_vault_ids,
            is_user_edited=True,
            db=db,
        )

        # Verify active pointer shifted
        db.refresh(snap1)
        assert snap1.is_active is False

        active_now = get_active_resume_snapshot(app_id, db=db)
        assert active_now is not None
        assert active_now.id == snap2.id
        assert active_now.is_active is True
        assert active_now.is_user_edited is True
        assert "<!-- Candidate custom note -->" in active_now.markdown_content

    finally:
        app_to_delete = db.query(Application).filter_by(id=app_id).first()
        if app_to_delete:
            db.delete(app_to_delete)
            db.commit()


def test_pipeline_cascade_deletion_cleans_snapshots_and_events(db: Session):
    """Deleting an application record must cleanly cascade and delete snapshots & pipeline events."""
    raw_text = (DATA_DIR / "jd_naukri_ai.txt").read_text(encoding="utf-8")
    result = process_raw_jd(raw_text, db=db)
    assert result.success is True

    app_id = result.application_id

    # Verify rows exist before delete
    assert db.query(ResumeSnapshot).filter_by(application_id=app_id).count() >= 1
    assert db.query(PipelineEvent).filter_by(application_id=app_id).count() >= 1

    # Delete application
    app_row = db.query(Application).filter_by(id=app_id).first()
    db.delete(app_row)
    db.commit()

    # Verify rows are cascade deleted
    assert db.query(Application).filter_by(id=app_id).count() == 0
    assert db.query(ResumeSnapshot).filter_by(application_id=app_id).count() == 0
    assert db.query(PipelineEvent).filter_by(application_id=app_id).count() == 0
