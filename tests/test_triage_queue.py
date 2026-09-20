import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from db.models import Application, ApplicationStatus, InboundTriageItem
from web.main import app, get_db

def test_triage_endpoints_with_mock():
    mock_db = MagicMock()
    app_id = uuid.uuid4()
    triage_id = uuid.uuid4()

    mock_app = Application(
        id=app_id,
        company_name="Swiggy",
        canonical_company_name="swiggy",
        role_title="Backend Engineer",
        source_platform="Direct",
        primary_tech_stack=[],
        current_status=ApplicationStatus.APPLIED,
        applied_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    mock_item = InboundTriageItem(
        id=triage_id,
        source="GMAIL_WORKER",
        sender="recruiting@bundltechnologies.com",
        subject="Next steps regarding your application at Bundl Technologies (Swiggy)",
        raw_body="Interview invite",
        detected_company="Bundl Technologies",
        detected_role="Full Stack Engineer",
        suggested_stage="INTERVIEW_ROUND",
        resolution_confidence="AMBIGUOUS",
        resolution_note="Multiple active applications under alias Bundl / Swiggy.",
        candidate_application_ids=[str(app_id)],
        status="PENDING",
        created_at=datetime.now(timezone.utc),
    )

    # Mock get_attention_items query
    mock_query = MagicMock()
    mock_query.filter.return_value.order_by.return_value.all.return_value = [mock_item]
    
    # Mock individual queries
    def query_side_effect(model):
        m = MagicMock()
        if model == InboundTriageItem:
            m.filter.return_value.first.return_value = mock_item
            m.filter.return_value.order_by.return_value.all.return_value = [mock_item]
        elif model == Application:
            m.filter.return_value.first.return_value = mock_app
            m.filter.return_value.all.return_value = [mock_app]
            m.order_by.return_value.limit.return_value.all.return_value = [mock_app]
        return m

    mock_db.query.side_effect = query_side_effect

    def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        # 1. GET /api/attention
        res = client.get("/api/attention")
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert data[0]["id"] == str(triage_id)
        assert data[0]["detected_company"] == "Bundl Technologies"

        # 2. POST /api/attention/{id}/assign
        assign_res = client.post(
            f"/api/attention/{triage_id}/assign",
            json={"application_id": str(app_id), "new_status": "INTERVIEW_ROUND", "note": "Assigned in test"},
        )
        assert assign_res.status_code == 200
        assert assign_res.json()["success"] is True
        assert mock_item.status == "RESOLVED"
        assert mock_app.current_status == ApplicationStatus.INTERVIEW_ROUND

        # 3. POST /api/attention/{id}/dismiss
        dismiss_res = client.post(f"/api/attention/{triage_id}/dismiss")
        assert dismiss_res.status_code == 200
        assert dismiss_res.json()["success"] is True
        assert mock_item.status == "DISMISSED"

    app.dependency_overrides.clear()
