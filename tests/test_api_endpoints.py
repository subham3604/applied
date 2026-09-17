"""
tests/test_api_endpoints.py
===========================
Integration tests for the FastAPI HTTP layer (web/main.py).
Verifies all 7 REST endpoints, serializers, error handling,
and data contracts expected by the React frontend.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import uuid
import pytest
from fastapi.testclient import TestClient

from db.models import Application, ApplicationStatus, EventSource, PipelineEvent, ResumeSnapshot
from web.main import app, get_db
from web.services.pipeline import PipelineResult


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def mock_db():
    """Provides a mock SQLAlchemy Session for fast, isolated HTTP unit tests."""
    return MagicMock()


@pytest.fixture
def client(mock_db):
    """FastAPI TestClient with overridden get_db dependency."""
    app.dependency_overrides[get_db] = lambda: mock_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def sample_application():
    """Creates a sample Application model instance with relationships populated."""
    app_id = uuid.uuid4()
    app_obj = Application(
        id=app_id,
        company_name="Swiggy",
        canonical_company_name="swiggy",
        role_title="Backend Engineer",
        source_platform="Naukri",
        location="Bengaluru, India",
        current_status=ApplicationStatus.APPLIED,
        primary_tech_stack=["Python", "FastAPI", "PostgreSQL"],
        applied_at=datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc),
    )

    # Associated ResumeSnapshot
    snapshot = ResumeSnapshot(
        id=uuid.uuid4(),
        application_id=app_id,
        markdown_content="# Subham Yadav\n\nBackend Engineer resume...",
        retrieved_vault_ids=[str(uuid.uuid4())],
        is_user_edited=False,
        is_active=True,
        created_at=datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc),
    )
    app_obj.resume_snapshots = [snapshot]

    # Associated PipelineEvent
    event = PipelineEvent(
        id=uuid.uuid4(),
        application_id=app_id,
        from_status=None,
        to_status=ApplicationStatus.APPLIED,
        detected_deadline=None,
        source=EventSource.MANUAL_DROP,
        raw_payload="Initial application submitted via portal",
        resolution_note="Applied via Naukri",
        llm_confidence="HIGH",
        created_at=datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc),
    )
    app_obj.pipeline_events = [event]

    return app_obj


# ==============================================================================
# Endpoint Tests
# ==============================================================================

def test_health_check(client):
    """GET /health must return HTTP 200 with status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_metrics(client, mock_db):
    """GET /api/metrics must return exact shape expected by frontend stats bar."""
    with patch("web.main.get_pipeline_metrics") as mock_metrics:
        mock_metrics.return_value = {
            "total": 12,
            "applied": 5,
            "pending_oa": 3,
            "active_interviews": 2,
            "offers": 1,
            "rejected": 1,
        }
        response = client.get("/api/metrics")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 12
        assert data["applied"] == 5
        assert data["pending_oa"] == 3
        assert data["active_interviews"] == 2
        assert data["offers"] == 1
        assert data["rejected"] == 1


def test_get_applications_list(client, mock_db, sample_application):
    """GET /api/applications must return array serialized to frontend Application type."""
    mock_db.query.return_value.options.return_value.order_by.return_value.all.return_value = [
        sample_application
    ]

    response = client.get("/api/applications")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1

    app_data = data[0]
    assert app_data["id"] == str(sample_application.id)
    assert app_data["company"] == "Swiggy"
    assert app_data["role"] == "Backend Engineer"
    assert app_data["stage"] == "applied"
    assert app_data["source"] == "Naukri"
    assert app_data["location"] == "Bengaluru, India"
    assert app_data["stack"] == ["Python", "FastAPI", "PostgreSQL"]
    assert "resume" in app_data
    assert "Subham Yadav" in app_data["resume"]
    assert len(app_data["timeline"]) == 1
    assert app_data["timeline"][0]["origin"] == "manual"


def test_get_application_detail_found(client, mock_db, sample_application):
    """GET /api/applications/{id} returns single serialized application."""
    mock_db.query.return_value.options.return_value.filter.return_value.first.return_value = (
        sample_application
    )

    response = client.get(f"/api/applications/{sample_application.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(sample_application.id)
    assert data["company"] == "Swiggy"


def test_get_application_detail_not_found(client, mock_db):
    """GET /api/applications/{id} returns 404 if application does not exist."""
    mock_db.query.return_value.options.return_value.filter.return_value.first.return_value = None

    random_id = str(uuid.uuid4())
    response = client.get(f"/api/applications/{random_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Application not found"


def test_get_application_detail_invalid_uuid(client):
    """GET /api/applications/{id} returns 400 for malformed UUID."""
    response = client.get("/api/applications/invalid-not-a-uuid")
    assert response.status_code == 400
    assert "Invalid application ID format" in response.json()["detail"]


def test_parse_and_tailor_jd_success(client, mock_db):
    """POST /api/applications/parse executes process_raw_jd and returns tailored metadata."""
    mock_app_id = uuid.uuid4()
    mock_result = PipelineResult(
        success=True,
        application_id=mock_app_id,
        company_name="Google",
        canonical_company_name="google",
        role_title="Software Engineer III",
        source_platform="LinkedIn",
        location="Hyderabad, India",
        primary_tech_stack=["Go", "Kubernetes", "gRPC"],
        resume_snapshot_id=uuid.uuid4(),
        markdown_resume="# Tailored Google Resume",
        guard_passed=True,
        extraction_retries=0,
    )

    with patch("web.main.process_raw_jd", return_value=mock_result):
        payload = {
            "jd_text": "We are seeking a Software Engineer III at Google in Hyderabad with Go and Kubernetes experience.",
            "source_platform": "LinkedIn",
        }
        response = client.post("/api/applications/parse", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["application_id"] == str(mock_app_id)
        assert data["company"] == "Google"
        assert data["role"] == "Software Engineer III"
        assert data["stack"] == ["Go", "Kubernetes", "gRPC"]
        assert data["resume"] == "# Tailored Google Resume"
        assert data["guard_passed"] is True


def test_parse_and_tailor_jd_empty_validation(client):
    """POST /api/applications/parse rejects empty JD with 422."""
    response = client.post("/api/applications/parse", json={"jd_text": "   "})
    assert response.status_code == 422


def test_update_resume_success(client, mock_db):
    """PATCH /api/applications/{id}/resume marks active snapshot as user-edited."""
    app_id = uuid.uuid4()
    mock_snapshot = ResumeSnapshot(
        id=uuid.uuid4(),
        application_id=app_id,
        markdown_content="Original Markdown",
        is_active=True,
        is_user_edited=False,
    )

    mock_db.query.return_value.filter.return_value.first.return_value = mock_snapshot

    payload = {"markdown": "# User Modified Resume Content"}
    response = client.patch(f"/api/applications/{app_id}/resume", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["resume_snapshot_id"] == str(mock_snapshot.id)
    assert mock_snapshot.markdown_content == "# User Modified Resume Content"
    assert mock_snapshot.is_user_edited is True
    assert mock_db.commit.called


def test_update_resume_not_found(client, mock_db):
    """PATCH /api/applications/{id}/resume returns 404 if application missing."""
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = client.patch(f"/api/applications/{uuid.uuid4()}/resume", json={"markdown": "content"})
    assert response.status_code == 404


def test_override_status_success(client, mock_db):
    """PATCH /api/applications/{id}/status records direct override and returns frontend stage."""
    app_id = str(uuid.uuid4())
    event_id = uuid.uuid4()

    mock_event = PipelineEvent(
        id=event_id,
        to_status=ApplicationStatus.OA_PENDING,
        source=EventSource.MANUAL_OVERRIDE,
    )

    with patch("web.main.apply_manual_override", return_value=mock_event):
        payload = {"new_status": "OA_PENDING", "note": "Received HackerRank test link"}
        response = client.patch(f"/api/applications/{app_id}/status", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["new_status"] == "OA_PENDING"
        assert data["stage"] == "oa"
        assert data["event_id"] == str(event_id)


def test_portal_text_update_success(client, mock_db):
    """POST /api/applications/{id}/text-update classifies text drop and updates stage."""
    app_id = str(uuid.uuid4())
    event_id = uuid.uuid4()

    mock_event = PipelineEvent(
        id=event_id,
        to_status=ApplicationStatus.INTERVIEW_ROUND,
        source=EventSource.MANUAL_DROP,
    )

    with patch("web.main.apply_manual_update", return_value=mock_event):
        payload = {"raw_text": "Congratulations, you are shortlisted for Technical Round 1."}
        response = client.post(f"/api/applications/{app_id}/text-update", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["new_status"] == "INTERVIEW_ROUND"
        assert data["stage"] == "interview"


def test_portal_text_update_empty_rejected(client):
    """POST /api/applications/{id}/text-update rejects empty text with 422."""
    response = client.post(f"/api/applications/{uuid.uuid4()}/text-update", json={"raw_text": "  "})
    assert response.status_code == 422


def test_get_pipeline_metrics_query_logic(mock_db):
    """Directly verifies get_pipeline_metrics aggregation returns expected numbers."""
    from web.queries import get_pipeline_metrics

    # Test case 1: DB has counts
    mock_row = MagicMock()
    mock_row.total = 10
    mock_row.total_active = 9
    mock_row.applied = 4
    mock_row.pending_oa = 2
    mock_row.active_interviews = 2
    mock_row.offers = 1
    mock_row.rejected = 1
    mock_db.query.return_value.first.return_value = mock_row

    metrics = get_pipeline_metrics(mock_db)
    assert metrics == {
        "total": 10,
        "total_active": 9,
        "applied": 4,
        "pending_oa": 2,
        "active_interviews": 2,
        "offers": 1,
        "rejected": 1,
    }

    # Test case 2: DB returns empty/none
    mock_db.query.return_value.first.return_value = None
    empty_metrics = get_pipeline_metrics(mock_db)
    assert empty_metrics == {
        "total": 0,
        "total_active": 0,
        "applied": 0,
        "pending_oa": 0,
        "active_interviews": 0,
        "offers": 0,
        "rejected": 0,
    }


def test_get_worker_status(client, mock_db):
    """GET /api/worker/status returns worker active state and sync metadata."""
    mock_config = MagicMock()
    mock_config.key = "last_checked_at"
    mock_config.value = "2026-09-16T12:00:00+00:00"
    mock_config.updated_at = datetime(2026, 9, 17, 8, 0, tzinfo=timezone.utc)

    # First query for WorkerConfig, second for PipelineEvent
    mock_db.query.return_value.filter.return_value.first.side_effect = [mock_config, None]
    mock_db.query.return_value.filter.return_value.scalar.return_value = 5

    response = client.get("/api/worker/status")
    assert response.status_code == 200
    data = response.json()
    assert data["active"] is True
    assert "Daily" in data["schedule"]
    assert data["last_checked_boundary"] == "2026-09-16T12:00:00+00:00"
    assert data["total_worker_events"] == 5


