import uuid
import pytest
from pathlib import Path
from sqlalchemy.orm import Session

from db.models import Application, ApplicationStatus, ResumeSnapshot
from db.session import SessionLocal
from web.services.resume_generator import (
    ResumeGenerationResult,
    extract_verbatim_entities,
    generate_tailored_resume,
    get_active_resume_snapshot,
    save_resume_snapshot,
    verify_resume_grounding,
)

DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def db():
    session = SessionLocal()
    yield session
    session.close()


# ==============================================================================
# Token Extraction & Anti-Hallucination Guard Unit Tests
# ==============================================================================

def test_extract_verbatim_entities_metrics_and_tools():
    """Verify exact extraction of numerical scales, latencies, and technical keywords."""
    sample = "Serving 10,000+ internal users with <5ms dynamic routing and 40% latency drop on Kubernetes."
    entities = extract_verbatim_entities(sample)

    assert "10,000+" in entities or "10,000" in entities
    assert "<5ms" in entities or "5ms" in entities
    assert "40%" in entities
    assert "kubernetes" in entities


def test_verify_resume_grounding_clean_resume_passes(db: Session):
    """Verify that a clean resume assembled directly from vault bullets has 0 hallucinations."""
    jd = "Cloud engineer with Kubernetes and Redis experience"
    result = generate_tailored_resume(jd, db=db)

    assert result.guard_passed is True
    assert len(result.hallucinations_detected) == 0


def test_verify_resume_grounding_catches_metric_tampering(db: Session):
    """Altering numbers/metrics from vault (e.g. 10,000+ to 99,000+) must trip the guard."""
    jd = "Cloud engineer with Kubernetes experience"
    result = generate_tailored_resume(jd, db=db)

    # Tamper with metrics
    tampered_md = result.markdown_content.replace("10,000+", "99,000+")
    bullets = [line.strip("- ") for line in result.markdown_content.splitlines() if line.startswith("- ")]

    hallucinations = verify_resume_grounding(tampered_md, bullets)
    assert any("99,000" in h for h in hallucinations)


def test_verify_resume_grounding_catches_foreign_tech(db: Session):
    """Injecting ungrounded foreign tools (e.g. AWS Lambda, Golang) must trip the guard."""
    jd = "Python engineer"
    result = generate_tailored_resume(jd, db=db)

    tampered_md = result.markdown_content + "\n- Architected serverless microservices using AWS Lambda and Golang\n"
    bullets = [line.strip("- ") for line in result.markdown_content.splitlines() if line.startswith("- ")]

    hallucinations = verify_resume_grounding(tampered_md, bullets)
    assert any("aws" in h or "golang" in h for h in hallucinations)


# ==============================================================================
# Tailored Resume Generation Tests
# ==============================================================================

def test_generate_tailored_resume_cloud_jd(db: Session):
    """Verify that a Cloud/Kubernetes JD selects Genesis and keeps pinned sections intact."""
    jd_raw = (DATA_DIR / "jd_linkedin_fullstack.txt").read_text(encoding="utf-8")
    result: ResumeGenerationResult = generate_tailored_resume(jd_raw, db=db)

    assert result.guard_passed is True
    assert len(result.projects_used) == 2
    # Verify Genesis is selected
    assert any("genesis" in p.lower() for p in result.projects_used)

    # Verify Pinned Sections are present
    assert "Subham Yadav" in result.markdown_content
    assert "GlobalLogic (Client: Google)" in result.markdown_content
    assert "Accenture" in result.markdown_content
    assert "Indian Institute of Technology Ropar" in result.markdown_content
    assert "AWARDS & ACHIEVEMENTS" in result.markdown_content
    assert "400+ DSA" in result.markdown_content


def test_generate_tailored_resume_graph_jd(db: Session):
    """Verify that a Python/Graph algorithms JD selects Urban Metro Network Finder."""
    jd = "Python Engineer with graph algorithms, spatial analysis, and BFS optimization"
    result: ResumeGenerationResult = generate_tailored_resume(jd, db=db)

    assert result.guard_passed is True
    assert any("urban metro" in p.lower() for p in result.projects_used)


def test_generate_tailored_resume_empty_input_raises_error(db: Session):
    """Empty JD must raise ValueError without crash."""
    with pytest.raises(ValueError, match="cannot be empty"):
        generate_tailored_resume("", db=db)


# ==============================================================================
# Database Persistence and Versioning Tests
# ==============================================================================

def test_save_and_retrieve_active_resume_snapshot(db: Session):
    """Test saving multiple resume snapshots, checking is_active versioning and is_user_edited flag."""
    app_id = uuid.uuid4()
    test_app = Application(
        id=app_id,
        company_name="Zomato Media",
        canonical_company_name="zomato",
        role_title="AI Systems Engineer",
        source_platform="Naukri",
        current_status=ApplicationStatus.APPLIED,
    )
    db.add(test_app)
    db.commit()

    try:
        jd_ai = (DATA_DIR / "jd_naukri_ai.txt").read_text(encoding="utf-8")
        res = generate_tailored_resume(jd_ai, db=db)

        # 1. Save initial auto-generated snapshot
        snap1 = save_resume_snapshot(
            application_id=app_id,
            markdown_content=res.markdown_content,
            vault_ids=res.retrieved_vault_ids,
            is_user_edited=False,
            db=db,
        )
        assert snap1.id is not None
        assert snap1.is_active is True
        assert snap1.is_user_edited is False

        # 2. Save user-edited draft
        edited_content = res.markdown_content + "\n<!-- User customized bullet point -->\n"
        snap2 = save_resume_snapshot(
            application_id=app_id,
            markdown_content=edited_content,
            vault_ids=res.retrieved_vault_ids,
            is_user_edited=True,
            db=db,
        )
        assert snap2.id is not None
        assert snap2.is_active is True
        assert snap2.is_user_edited is True

        # Verify snap1 is deactivated
        db.refresh(snap1)
        assert snap1.is_active is False

        # 3. Retrieve active snapshot
        active = get_active_resume_snapshot(app_id, db=db)
        assert active is not None
        assert active.id == snap2.id
        assert active.is_user_edited is True
        assert "<!-- User customized bullet point -->" in active.markdown_content

    finally:
        # Cascade delete cleans up snapshots automatically
        db.delete(test_app)
        db.commit()
        # Verify snapshots deleted
        remaining = db.query(ResumeSnapshot).filter_by(application_id=app_id).all()
        assert len(remaining) == 0
