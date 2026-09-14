import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.session import DATABASE_URL
from db.models import (
    Application,
    ApplicationStatus,
    ResumeSnapshot,
    PipelineEvent,
    EventSource,
    MasterExperienceVault,
    WorkerConfig,
)

# Test session fixture
@pytest.fixture(scope="module")
def db_session():
    engine = create_engine(DATABASE_URL)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()


def test_create_application_and_cascade_delete(db_session):
    """Test creating an application with linked resume and events, then verify cascade deletion."""
    test_app = Application(
        id=uuid.uuid4(),
        company_name="Swiggy Technologies",
        canonical_company_name="swiggy",
        role_title="Backend Engineer (SDE-2)",
        source_platform="Naukri",
        job_description_raw="Looking for experienced Python, PostgreSQL, and Redis engineers.",
        primary_tech_stack=["Python", "PostgreSQL", "Redis"],
        experience_required_yrs=3.0,
        location="Bengaluru, India",
        current_status=ApplicationStatus.APPLIED,
    )
    db_session.add(test_app)
    db_session.commit()

    # Link a resume snapshot
    test_snapshot = ResumeSnapshot(
        id=uuid.uuid4(),
        application_id=test_app.id,
        markdown_content="# John Doe\n## Backend Experience\n- Built microservices...",
        retrieved_vault_ids=[str(uuid.uuid4())],
        is_user_edited=False,
        is_active=True,
    )
    db_session.add(test_snapshot)

    # Link a pipeline event
    test_event = PipelineEvent(
        id=uuid.uuid4(),
        application_id=test_app.id,
        from_status=None,
        to_status=ApplicationStatus.APPLIED,
        source=EventSource.MANUAL_DROP,
        raw_payload="User pasted JD directly from Naukri portal",
        resolution_note="Manual drop direct entry",
        llm_confidence="HIGH",
    )
    db_session.add(test_event)
    db_session.commit()

    app_id = test_app.id

    # Verify query
    saved_app = db_session.query(Application).filter_by(id=app_id).first()
    assert saved_app is not None
    assert saved_app.company_name == "Swiggy Technologies"
    assert saved_app.canonical_company_name == "swiggy"
    assert saved_app.current_status == ApplicationStatus.APPLIED
    assert len(saved_app.resume_snapshots) == 1
    assert len(saved_app.pipeline_events) == 1

    # Delete the application
    db_session.delete(saved_app)
    db_session.commit()

    # Verify cascade deletion on snapshots and events
    assert db_session.query(Application).filter_by(id=app_id).first() is None
    assert db_session.query(ResumeSnapshot).filter_by(application_id=app_id).first() is None
    assert db_session.query(PipelineEvent).filter_by(application_id=app_id).first() is None


def test_worker_config_key_value(db_session):
    """Test setting and retrieving worker configuration (e.g. last_checked_at)."""
    test_key = "test_last_checked_at"
    test_val = "2026-09-14T08:00:00Z"

    # Upsert pattern
    config = db_session.query(WorkerConfig).filter_by(key=test_key).first()
    if not config:
        config = WorkerConfig(key=test_key, value=test_val)
        db_session.add(config)
    else:
        config.value = test_val
    db_session.commit()

    retrieved = db_session.query(WorkerConfig).filter_by(key=test_key).first()
    assert retrieved is not None
    assert retrieved.value == test_val

    # Clean up
    db_session.delete(retrieved)
    db_session.commit()


def test_master_experience_vault_vector_similarity(db_session):
    """Verify that pgvector IVFFlat index and cosine distance queries work on seeded vault."""
    vault_count = db_session.query(MasterExperienceVault).count()
    assert vault_count > 0, "Vault should have been seeded with bullets"

    # Retrieve first record and search nearest neighbors
    first = db_session.query(MasterExperienceVault).first()
    assert first.embedding is not None
    assert len(first.embedding) == 1536

    top_neighbors = db_session.query(MasterExperienceVault).order_by(
        MasterExperienceVault.embedding.cosine_distance(first.embedding)
    ).limit(3).all()

    assert len(top_neighbors) >= 1
    # The nearest neighbor to itself should be itself
    assert top_neighbors[0].id == first.id
