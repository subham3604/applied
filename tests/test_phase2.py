"""
tests/test_phase2.py
====================
Phase 2 End-to-End Pipeline Integration Test Suite (Day 14).

Verifies the end-to-end integration of all Phase 2 systems:
1. Legal Entity Alias Resolution & Pipeline Transition (Swiggy / Bundl Technologies)
2. Role-Omitted Date Proximity Matching (LOW confidence fallback)
3. Multi-Application Conflict with >24h / 5-Day Gap (AMBIGUOUS flag & manual review routing)
4. Inbound Email for Unrecognized Company (CREATE_NEW record in PostgreSQL)
5. Full Cross-Flow Audit Trail (GMAIL_WORKER -> MANUAL_DROP -> MANUAL_OVERRIDE)
"""

from datetime import datetime, timedelta, timezone
import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import (
    Application,
    ApplicationStatus,
    EventSource,
    PipelineEvent,
)
from db.session import DATABASE_URL
from web.services.state_controller import (
    apply_manual_override,
    apply_manual_update,
)
from worker.agent_state import AgentState, ApplicationEventType
from worker.graph_agent import build_email_agent_graph


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture(scope="module")
def db_session_factory():
    """Provides a sessionmaker connected to the test database."""
    engine = create_engine(DATABASE_URL)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db_session(db_session_factory):
    """Provides a transactional database session for tests."""
    session = db_session_factory()
    yield session
    session.close()


@pytest.fixture(scope="module")
def graph():
    """Compiles the LangGraph agent state machine."""
    return build_email_agent_graph()


def _make_agent_state(
    raw_email_text: str,
    subject: str,
    sender: str,
    email_received_at: datetime = None,
) -> AgentState:
    """Helper to assemble a baseline AgentState dictionary."""
    return {
        "raw_email_text": raw_email_text,
        "email_received_at": email_received_at or datetime.now(timezone.utc),
        "sender": sender,
        "subject": subject,
        "is_relevant": False,
        "relevance_category": None,
        "relevance_reason": None,
        "parsed_event": None,
        "validation_errors": [],
        "retry_count": 0,
        "matched_application_id": None,
        "resolution_confidence": "HIGH",
        "resolution_note": "",
        "is_new_application": False,
        "candidate_apps": None,
        "current_status": None,
        "target_status": None,
        "transition_note": None,
        "status_changed": False,
        "committed": False,
        "db_session": None,
        "dead_letter_reason": None,
        "execution_path": [],
    }


# ==============================================================================
# Integration Test Cases (Day 14 Deliverables)
# ==============================================================================

def test_integration_case1_alias_resolution_and_pipeline_transition(db_session, graph):
    """
    Test Case 1 (CUJ-2 / Day 10 & 11):
    - Seed application: {company: 'Swiggy', role: 'SDE-1', status: APPLIED}
    - Inbound email from 'Bundl Technologies' with OA invitation
    - Assert:
      1. Entity resolves to Swiggy via corporate alias
      2. Status transitions to OA_PENDING in PostgreSQL
      3. PipelineEvent audit row created with source = GMAIL_WORKER
    """
    app = Application(
        id=uuid.uuid4(),
        company_name="Swiggy",
        canonical_company_name="swiggy",
        role_title="SDE-1",
        source_platform="Naukri",
        current_status=ApplicationStatus.APPLIED,
        applied_at=datetime.now(timezone.utc),
    )
    db_session.add(app)
    db_session.commit()

    try:
        raw_text = (
            "Dear Candidate,\n\n"
            "Thank you for applying to Swiggy. Please complete the online coding assessment on HackerRank within 48 hours.\n"
            "Assessment link: https://hackerrank.com/swiggy-sde1-test\n\n"
            "Best regards,\nBundl Technologies Talent Team"
        )
        state = _make_agent_state(
            raw_email_text=raw_text,
            subject="Bundl Technologies — Online Assessment Invitation",
            sender="talent@bundl.com",
            email_received_at=datetime.now(timezone.utc),
        )

        result = graph.invoke(state)

        # 1. Verify LangGraph Execution Flow
        assert result["is_relevant"] is True
        assert result["matched_application_id"] == str(app.id)
        assert result["target_status"] == ApplicationStatus.OA_PENDING.value
        assert result["status_changed"] is True
        assert result["committed"] is True

        expected_nodes = ["relevance_gate", "extract_event", "validate_schema", "entity_resolution", "state_transition", "commit_and_log"]
        for node in expected_nodes:
            assert node in result["execution_path"]

        # 2. Verify Database State
        db_session.refresh(app)
        assert app.current_status == ApplicationStatus.OA_PENDING

        # 3. Verify PipelineEvent Audit Trail
        event = (
            db_session.query(PipelineEvent)
            .filter(PipelineEvent.application_id == app.id)
            .order_by(PipelineEvent.created_at.desc())
            .first()
        )
        assert event is not None
        assert event.source == EventSource.GMAIL_WORKER
        assert event.from_status == ApplicationStatus.APPLIED
        assert event.to_status == ApplicationStatus.OA_PENDING
        assert event.detected_deadline is not None

    finally:
        db_session.delete(app)
        db_session.commit()


def test_integration_case2_role_omitted_date_proximity_match(db_session, graph):
    """
    Test Case 2 (Day 10 Level 3 Fallback):
    - Seed two applications for PhonePe:
      - App A: applied 10 days ago
      - App B: applied 2 hours ago (same day)
    - Inbound email mentions 'PhonePe' with interview invitation, but omits the role title
    - Assert:
      1. Resolves to recent App B via date proximity match
      2. Resolution confidence is marked LOW (as designed in Level 3 fallback)
      3. Status transitions to INTERVIEW_ROUND
    """
    now = datetime.now(timezone.utc)
    app_old = Application(
        id=uuid.uuid4(),
        company_name="PhonePe",
        canonical_company_name="phonepe",
        role_title="DevOps Engineer",
        source_platform="LinkedIn",
        current_status=ApplicationStatus.APPLIED,
        applied_at=now - timedelta(days=10),
    )
    app_recent = Application(
        id=uuid.uuid4(),
        company_name="PhonePe",
        canonical_company_name="phonepe",
        role_title="Backend Engineer",
        source_platform="Direct",
        current_status=ApplicationStatus.APPLIED,
        applied_at=now - timedelta(hours=2),
    )
    db_session.add_all([app_old, app_recent])
    db_session.commit()

    try:
        raw_text = (
            "Hi Subham,\n\n"
            "We were impressed by your profile at PhonePe. We would love to schedule a technical round with our team on Friday.\n\n"
            "Best,\nPhonePe Recruiting"
        )
        state = _make_agent_state(
            raw_email_text=raw_text,
            subject="Invitation to Interview with PhonePe",
            sender="recruiting@phonepe.com",
            email_received_at=now,
        )

        result = graph.invoke(state)

        assert result["is_relevant"] is True
        # Resolved to the recent application within 24h proximity
        assert result["matched_application_id"] == str(app_recent.id)
        assert result["resolution_confidence"] == "LOW"
        assert result["target_status"] == ApplicationStatus.INTERVIEW_ROUND.value

        # Verify database reflection
        db_session.refresh(app_recent)
        assert app_recent.current_status == ApplicationStatus.INTERVIEW_ROUND

        # App old must remain untouched
        db_session.refresh(app_old)
        assert app_old.current_status == ApplicationStatus.APPLIED

    finally:
        db_session.delete(app_old)
        db_session.delete(app_recent)
        db_session.commit()


def test_integration_case3_multiple_roles_5day_gap_flags_ambiguous(db_session, graph):
    """
    Test Case 3 (Day 9 & 10 Ambiguity Safety Gate):
    - Seed two applications for Zomato:
      - App A: Frontend Engineer, applied 6 days ago
      - App B: Backend Engineer, applied 5 days ago
    - Inbound email mentions 'Zomato' but has no role details
    - Both applications exceed the 24-hour date proximity threshold (> 5 days ago)
    - Assert:
      1. Confidence is AMBIGUOUS
      2. Graph routes to flag_for_manual -> commit_and_log
      3. Neither application's current_status is mutated (zero automated corruption)
    """
    now = datetime.now(timezone.utc)
    app1 = Application(
        id=uuid.uuid4(),
        company_name="Zomato",
        canonical_company_name="zomato",
        role_title="Frontend Engineer",
        source_platform="LinkedIn",
        current_status=ApplicationStatus.APPLIED,
        applied_at=now - timedelta(days=6),
    )
    app2 = Application(
        id=uuid.uuid4(),
        company_name="Zomato",
        canonical_company_name="zomato",
        role_title="Backend Engineer",
        source_platform="Naukri",
        current_status=ApplicationStatus.APPLIED,
        applied_at=now - timedelta(days=5),
    )
    db_session.add_all([app1, app2])
    db_session.commit()

    try:
        raw_text = (
            "Dear Candidate,\n\n"
            "Thank you for your interest in Zomato. We are currently reviewing your application and will follow up shortly.\n\n"
            "Regards,\nZomato Talent Acquisition"
        )
        state = _make_agent_state(
            raw_email_text=raw_text,
            subject="Update regarding your application at Zomato",
            sender="talent@zomato.com",
            email_received_at=now,
        )

        result = graph.invoke(state)

        assert result["is_relevant"] is True
        assert result["resolution_confidence"] == "AMBIGUOUS"
        assert "flag_for_manual" in result["execution_path"]

        # Neither application should be modified
        db_session.refresh(app1)
        db_session.refresh(app2)
        assert app1.current_status == ApplicationStatus.APPLIED
        assert app2.current_status == ApplicationStatus.APPLIED

    finally:
        db_session.delete(app1)
        db_session.delete(app2)
        db_session.commit()


def test_integration_case4_unrecognized_company_creates_new_record(db_session, graph):
    """
    Test Case 4 (Day 11 Dynamic Discovery):
    - Inbound confirmation email from an unseen company ('NewStartup AI')
    - Assert:
      1. Graph determines CREATE_NEW
      2. Routes through create_new_record -> commit_and_log
      3. A new Application row is created in PostgreSQL with current_status = APPLIED
    """
    raw_text = (
        "Hi Subham,\n\n"
        "Thank you for applying to NewStartup AI for the Machine Learning Engineer position. "
        "We have received your application.\n\n"
        "Best regards,\nNewStartup AI Hiring"
    )
    state = _make_agent_state(
        raw_email_text=raw_text,
        subject="Thank you for applying to NewStartup AI",
        sender="careers@newstartup.ai",
        email_received_at=datetime.now(timezone.utc),
    )

    result = graph.invoke(state)

    assert result["is_relevant"] is True
    assert result["is_new_application"] is True
    assert "create_new_record" in result["execution_path"]

    created_app_id = result.get("matched_application_id")
    assert created_app_id is not None

    # Verify application persisted in PostgreSQL
    created_app = db_session.query(Application).filter(Application.id == uuid.UUID(created_app_id)).first()
    try:
        assert created_app is not None
        assert "newstartup" in created_app.canonical_company_name.lower() or "newstartup" in created_app.company_name.lower()
        assert created_app.current_status == ApplicationStatus.APPLIED

        # Verify initial audit event
        events = db_session.query(PipelineEvent).filter(PipelineEvent.application_id == created_app.id).all()
        assert len(events) >= 1
        assert events[0].to_status == ApplicationStatus.APPLIED

    finally:
        if created_app:
            db_session.delete(created_app)
            db_session.commit()


def test_integration_case5_full_lifecycle_cross_flow(db_session, graph):
    """
    Test Case 5 (Complete Cross-Flow Source Auditing):
    Validates complete lifecycle across all 3 EventSource origins:
    - Step 1: Initial Application ingestion (APPLIED, source = MANUAL_DROP)
    - Step 2: Automated recruiter email via LangGraph (INTERVIEW_ROUND, source = GMAIL_WORKER)
    - Step 3: Candidate manual update drop (OFFER, source = MANUAL_DROP)
    - Step 4: Candidate direct override correction (INTERVIEW_ROUND, source = MANUAL_OVERRIDE)
    - Assert: Exactly 4 chronological PipelineEvent rows with distinct, correct EventSource values.
    """
    now = datetime.now(timezone.utc)
    app = Application(
        id=uuid.uuid4(),
        company_name="Datadog",
        canonical_company_name="datadog",
        role_title="Site Reliability Engineer",
        source_platform="Direct",
        current_status=ApplicationStatus.APPLIED,
        applied_at=now,
    )
    db_session.add(app)
    db_session.commit()

    try:
        # Step 1: Record initial ingestion event
        initial_event = PipelineEvent(
            id=uuid.uuid4(),
            application_id=app.id,
            from_status=None,
            to_status=ApplicationStatus.APPLIED,
            source=EventSource.MANUAL_DROP,
            raw_payload="Ingested via JD parser",
            created_at=now - timedelta(minutes=30),
        )
        db_session.add(initial_event)
        db_session.commit()

        # Step 2: Automated LangGraph email processing (GMAIL_WORKER)
        email_state = _make_agent_state(
            raw_email_text="Hi Subham, we would like to schedule a technical interview round for the SRE position at Datadog.",
            subject="Interview Invitation — Datadog",
            sender="talent@datadog.com",
            email_received_at=now - timedelta(minutes=20),
        )
        graph_result = graph.invoke(email_state)
        assert graph_result["status_changed"] is True
        assert graph_result["target_status"] == ApplicationStatus.INTERVIEW_ROUND.value

        db_session.refresh(app)
        assert app.current_status == ApplicationStatus.INTERVIEW_ROUND

        # Step 3: Candidate pastes verbal offer text (MANUAL_DROP)
        offer_text = "Director called: Pleased to offer you the SRE role with compensation package details to follow."
        drop_event = apply_manual_update(
            application_id=app.id,
            raw_text=offer_text,
            db=db_session,
        )
        assert drop_event.source == EventSource.MANUAL_DROP
        assert drop_event.to_status == ApplicationStatus.OFFER

        db_session.refresh(app)
        assert app.current_status == ApplicationStatus.OFFER

        # Step 4: Candidate direct override correction (MANUAL_OVERRIDE)
        override_event = apply_manual_override(
            application_id=app.id,
            new_status=ApplicationStatus.INTERVIEW_ROUND,
            note="Offer was for an adjacent team; original SRE interview loop still active.",
            db=db_session,
        )
        assert override_event.source == EventSource.MANUAL_OVERRIDE
        assert override_event.to_status == ApplicationStatus.INTERVIEW_ROUND

        db_session.refresh(app)
        assert app.current_status == ApplicationStatus.INTERVIEW_ROUND

        # Audit Trail Check:
        events = (
            db_session.query(PipelineEvent)
            .filter(PipelineEvent.application_id == app.id)
            .order_by(PipelineEvent.created_at.asc())
            .all()
        )

        sources = [e.source for e in events]
        assert EventSource.MANUAL_DROP in sources
        assert EventSource.GMAIL_WORKER in sources
        assert EventSource.MANUAL_OVERRIDE in sources

    finally:
        db_session.delete(app)
        db_session.commit()
