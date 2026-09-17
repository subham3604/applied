"""
tests/test_day11_state_machine.py
=================================
Test suite for Phase 2 Day 11: Non-linear State Machine DAG + APPLICATION_RECEIVED Handling.

Validates:
1. Non-linear VALID_TRANSITIONS DAG rules:
   - APPLIED -> OA_PENDING, INTERVIEW_ROUND, OFFER, REJECTED, WITHDRAWN
   - OA_PENDING -> INTERVIEW_ROUND, OFFER, REJECTED, WITHDRAWN
   - INTERVIEW_ROUND -> INTERVIEW_ROUND (repeating), OFFER, REJECTED, WITHDRAWN
   - OFFER -> REJECTED (rescinded), WITHDRAWN
   - Terminal states (REJECTED, WITHDRAWN) have 0 outgoing transitions
2. Zero State Regression on APPLICATION_RECEIVED:
   - Status stays APPLIED (status_changed = False)
   - Audit note "Application receipt confirmed by [Source]"
3. Repeating INTERVIEW_ROUND (Round 2, 3, etc.):
   - Status unchanged, new PipelineEvent logged
4. Invalid backward transitions blocked deterministically:
   - REJECTED -> OA_PENDING blocked
   - WITHDRAWN -> INTERVIEW_ROUND blocked
5. Full DB Persistence Integration with PostgreSQL:
   - Deliverable check: Naukri confirmation email on manually-logged application
   - Rejection email on active application
   - Repeating interview round event logging
   - Automatic creation of new Application and initial PipelineEvent on CREATE_NEW
"""

from datetime import datetime, timezone
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
from worker.agent_state import AgentState, ApplicationEventType
from worker.graph_agent import build_email_agent_graph
from worker.state_machine import (
    EVENT_TO_TARGET_STATUS,
    VALID_TRANSITIONS,
    detect_source_platform,
    evaluate_transition,
)


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture(scope="module")
def db_session():
    """Provides an isolated database session for Day 11 persistence tests."""
    engine = create_engine(DATABASE_URL)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="module")
def graph():
    """Compiles the LangGraph agent once for the test module."""
    return build_email_agent_graph()


def _make_state(
    raw_email_text: str,
    subject: str = "Job Application",
    sender: str = "recruiter@company.com",
    **kwargs
) -> AgentState:
    """Creates a baseline AgentState dictionary for testing."""
    state: AgentState = {
        "raw_email_text": raw_email_text,
        "email_received_at": datetime.now(timezone.utc),
        "sender": sender,
        "subject": subject,
        "is_relevant": True,
        "relevance_category": "APPLICATION_CONFIRMATION",
        "relevance_reason": "Testing",
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
    state.update(kwargs)
    return state


# ==============================================================================
# 1. State Machine DAG Unit Tests
# ==============================================================================

def test_valid_transitions_completeness():
    """Verify all canonical statuses and terminal states in VALID_TRANSITIONS."""
    expected_statuses = {"APPLIED", "OA_PENDING", "INTERVIEW_ROUND", "OFFER", "REJECTED", "WITHDRAWN"}
    assert set(VALID_TRANSITIONS.keys()) == expected_statuses

    # Terminal states must have empty allowed transitions
    assert VALID_TRANSITIONS["REJECTED"] == []
    assert VALID_TRANSITIONS["WITHDRAWN"] == []

    # APPLIED must allow jumping straight to INTERVIEW_ROUND (skipping OA)
    assert "INTERVIEW_ROUND" in VALID_TRANSITIONS["APPLIED"]

    # INTERVIEW_ROUND must allow repeating round
    assert "INTERVIEW_ROUND" in VALID_TRANSITIONS["INTERVIEW_ROUND"]

    # OFFER must allow rescinding to REJECTED
    assert "REJECTED" in VALID_TRANSITIONS["OFFER"]


def test_detect_source_platform():
    """Verify portal detection from sender and body snippets."""
    assert detect_source_platform("apply@naukri.com", "Job alert") == "Naukri"
    assert detect_source_platform("jobs-noreply@linkedin.com", "Application viewed") == "LinkedIn"
    assert detect_source_platform("no-reply@greenhouse.io", "Coding challenge") == "Greenhouse"
    assert detect_source_platform("jobs@lever.co", "Interview details") == "Lever"
    assert detect_source_platform("hr@myworkdayjobs.com", "Candidate portal") == "Workday"
    assert detect_source_platform("careers@google.com", "Direct interview") == "Direct"


def test_evaluate_application_received_on_applied():
    """
    APPLICATION_RECEIVED on an APPLIED application must keep status as APPLIED
    with status_changed = False and an audit note.
    """
    decision = evaluate_transition(
        current_status="APPLIED",
        event_type=ApplicationEventType.APPLICATION_RECEIVED,
        sender="notifications@naukri.com",
    )
    assert decision.is_valid is True
    assert decision.from_status == "APPLIED"
    assert decision.to_status == "APPLIED"
    assert decision.status_changed is False
    assert "Application receipt confirmed by Naukri" in decision.note


def test_evaluate_application_received_late_on_oa_pending():
    """
    A delayed APPLICATION_RECEIVED email arriving when status is already OA_PENDING
    must NOT regress status back to APPLIED.
    """
    decision = evaluate_transition(
        current_status="OA_PENDING",
        event_type=ApplicationEventType.APPLICATION_RECEIVED,
        sender="apply@linkedin.com",
    )
    assert decision.is_valid is True
    assert decision.from_status == "OA_PENDING"
    assert decision.to_status == "OA_PENDING"
    assert decision.status_changed is False
    assert "status preserved" in decision.note


def test_evaluate_interview_round_repeating():
    """
    INTERVIEW_INVITE on an application already at INTERVIEW_ROUND must be valid,
    keep status as INTERVIEW_ROUND, and set status_changed = False.
    """
    decision = evaluate_transition(
        current_status=ApplicationStatus.INTERVIEW_ROUND,
        event_type=ApplicationEventType.INTERVIEW_INVITE,
        sender="recruiting@uber.com",
        company_name="Uber",
    )
    assert decision.is_valid is True
    assert decision.from_status == "INTERVIEW_ROUND"
    assert decision.to_status == "INTERVIEW_ROUND"
    assert decision.status_changed is False
    assert "Next interview round scheduled" in decision.note


def test_evaluate_valid_forward_transitions():
    """Verify all valid progression edges in the DAG."""
    # APPLIED -> OA_PENDING
    d1 = evaluate_transition("APPLIED", ApplicationEventType.OA_RECEIVED, sender="test@hackerrank.com")
    assert d1.is_valid is True and d1.to_status == "OA_PENDING" and d1.status_changed is True

    # APPLIED -> INTERVIEW_ROUND (skip OA)
    d2 = evaluate_transition("APPLIED", ApplicationEventType.INTERVIEW_INVITE)
    assert d2.is_valid is True and d2.to_status == "INTERVIEW_ROUND" and d2.status_changed is True

    # OA_PENDING -> INTERVIEW_ROUND
    d3 = evaluate_transition("OA_PENDING", ApplicationEventType.INTERVIEW_INVITE)
    assert d3.is_valid is True and d3.to_status == "INTERVIEW_ROUND" and d3.status_changed is True

    # INTERVIEW_ROUND -> OFFER
    d4 = evaluate_transition("INTERVIEW_ROUND", ApplicationEventType.OFFER)
    assert d4.is_valid is True and d4.to_status == "OFFER" and d4.status_changed is True

    # OFFER -> REJECTED (rescinded)
    d5 = evaluate_transition("OFFER", ApplicationEventType.REJECTED)
    assert d5.is_valid is True and d5.to_status == "REJECTED" and d5.status_changed is True and d5.is_terminal is True


def test_evaluate_blocked_backward_transitions():
    """Terminal or illegal backward transitions must be blocked."""
    # REJECTED cannot transition to OA_PENDING
    d1 = evaluate_transition("REJECTED", ApplicationEventType.OA_RECEIVED)
    assert d1.is_valid is False
    assert d1.status_changed is False
    assert d1.to_status == "REJECTED"
    assert "blocked by state machine DAG" in d1.note

    # WITHDRAWN cannot transition to INTERVIEW_ROUND
    d2 = evaluate_transition("WITHDRAWN", ApplicationEventType.INTERVIEW_INVITE)
    assert d2.is_valid is False
    assert d2.status_changed is False
    assert d2.to_status == "WITHDRAWN"


# ==============================================================================
# 2. Database Persistence & LangGraph Integration Tests
# ==============================================================================

def test_deliverable_check_naukri_application_received(db_session, graph):
    """
    DELIVERABLE CHECK:
    Naukri 'You applied for 1 job' email on same-day manually-logged application:
    - Status remains APPLIED (no regression or duplication)
    - PipelineEvent row inserted with note 'Application receipt confirmed by Naukri'
    - Execution path traverses through state_transition and commit_and_log
    """
    app_id = uuid.uuid4()
    app = Application(
        id=app_id,
        company_name="Infosys",
        canonical_company_name="infosys",
        role_title="Backend Engineer",
        source_platform="Naukri",
        current_status=ApplicationStatus.APPLIED,
        applied_at=datetime.now(timezone.utc),
    )
    db_session.add(app)
    db_session.commit()

    try:
        email_body = (
            "Dear Subham,\n\n"
            "You have successfully applied for Backend Engineer at Infosys on Naukri.com. "
            "The recruiter will review your profile shortly."
        )
        state = _make_state(
            subject="You applied for 1 job at Infosys",
            sender="apply@naukri.com",
            raw_email_text=email_body,
            db_session=db_session,
        )

        result = graph.invoke(state)

        # Verify Graph Output
        assert result["is_relevant"] is True
        assert result["committed"] is True
        assert result["matched_application_id"] == str(app_id)
        assert result["current_status"] == "APPLIED"
        assert result["target_status"] == "APPLIED"
        assert result["status_changed"] is False
        assert "Application receipt confirmed by Naukri" in result["transition_note"]
        assert "state_transition" in result["execution_path"]
        assert "commit_and_log" in result["execution_path"]

        # Verify Database Persistence
        db_session.refresh(app)
        assert app.current_status == ApplicationStatus.APPLIED  # Unmutated

        # Verify Event Log
        event = (
            db_session.query(PipelineEvent)
            .filter(PipelineEvent.application_id == app_id)
            .order_by(PipelineEvent.created_at.desc())
            .first()
        )
        assert event is not None
        assert event.from_status == ApplicationStatus.APPLIED
        assert event.to_status == ApplicationStatus.APPLIED
        assert event.source == EventSource.GMAIL_WORKER
        assert "Application receipt confirmed by Naukri" in event.resolution_note
        assert "successfully applied" in event.raw_payload

    finally:
        # Cleanup
        db_session.delete(app)
        db_session.commit()


def test_rejection_email_updates_status_to_rejected(db_session, graph):
    """
    Rejection email on active application in INTERVIEW_ROUND:
    - Application current_status updated to REJECTED
    - PipelineEvent row inserted with from=INTERVIEW_ROUND, to=REJECTED
    """
    app_id = uuid.uuid4()
    app = Application(
        id=app_id,
        company_name="Zyntrix Software",
        canonical_company_name="zyntrix",
        role_title="Software Developer",
        source_platform="Direct",
        current_status=ApplicationStatus.INTERVIEW_ROUND,
        applied_at=datetime.now(timezone.utc),
    )
    db_session.add(app)
    db_session.commit()

    try:
        email_body = (
            "Dear Subham,\n\n"
            "Thank you for interviewing with Zyntrix Software for the Software Developer role. "
            "Although your qualifications are impressive, we have decided to proceed with another candidate."
        )
        state = _make_state(
            subject="Update on your application at Zyntrix",
            sender="careers@zyntrixsoftware.com",
            raw_email_text=email_body,
            relevance_category="REJECTION",
            parsed_event={
                "company_raw": "Zyntrix Software",
                "role_title": "Software Developer",
                "event_type": "REJECTED",
                "deadline": None,
            },
            matched_application_id=str(app_id),
            db_session=db_session,
        )

        result = graph.invoke(state)

        assert result["committed"] is True
        assert result["status_changed"] is True
        assert result["target_status"] == "REJECTED"

        db_session.refresh(app)
        assert app.current_status == ApplicationStatus.REJECTED

        event = (
            db_session.query(PipelineEvent)
            .filter(PipelineEvent.application_id == app_id)
            .order_by(PipelineEvent.created_at.desc())
            .first()
        )
        assert event is not None
        assert event.from_status == ApplicationStatus.INTERVIEW_ROUND
        assert event.to_status == ApplicationStatus.REJECTED

    finally:
        db_session.delete(app)
        db_session.commit()


def test_repeating_interview_round_two(db_session, graph):
    """
    Round 2 interview invitation on an application already in INTERVIEW_ROUND:
    - Application status stays INTERVIEW_ROUND (status_changed = False)
    - New PipelineEvent row inserted recording the round details
    """
    app_id = uuid.uuid4()
    app = Application(
        id=app_id,
        company_name="Swiggy",
        canonical_company_name="swiggy",
        role_title="Backend Engineer",
        source_platform="Direct",
        current_status=ApplicationStatus.INTERVIEW_ROUND,
        applied_at=datetime.now(timezone.utc),
    )
    db_session.add(app)
    db_session.commit()

    try:
        email_body = (
            "Hi Subham,\n\n"
            "Congratulations on clearing Round 1! We would like to invite you for "
            "Round 2: System Design with our Engineering Director on Friday at 3 PM IST."
        )
        state = _make_state(
            subject="Invitation: Round 2 System Design Interview with Swiggy",
            sender="talent@swiggy.in",
            raw_email_text=email_body,
            relevance_category="INTERVIEW_INVITATION",
            parsed_event={
                "company_raw": "Swiggy",
                "role_title": "Backend Engineer",
                "event_type": "INTERVIEW_INVITE",
                "deadline": None,
            },
            matched_application_id=str(app_id),
            db_session=db_session,
        )

        result = graph.invoke(state)

        assert result["committed"] is True
        assert result["status_changed"] is False
        assert result["target_status"] == "INTERVIEW_ROUND"
        assert "Next interview round scheduled" in result["transition_note"]

        db_session.refresh(app)
        assert app.current_status == ApplicationStatus.INTERVIEW_ROUND

        event = (
            db_session.query(PipelineEvent)
            .filter(PipelineEvent.application_id == app_id)
            .order_by(PipelineEvent.created_at.desc())
            .first()
        )
        assert event is not None
        assert event.from_status == ApplicationStatus.INTERVIEW_ROUND
        assert event.to_status == ApplicationStatus.INTERVIEW_ROUND
        assert "Round 2: System Design" in event.raw_payload

    finally:
        db_session.delete(app)
        db_session.commit()


def test_inbound_email_creates_new_application(db_session, graph):
    """
    When entity resolution determines CREATE_NEW:
    - Node 5 inserts a new Application row in PostgreSQL
    - Node 8 inserts initial PipelineEvent
    - matched_application_id is returned with committed = True
    """
    company_name = f"TestCorp_{uuid.uuid4().hex[:6]}"
    state = _make_state(
        subject=f"Application Acknowledged at {company_name}",
        sender="careers@testcorp.io",
        raw_email_text=f"Thank you for submitting your application to {company_name} for the Platform Engineer role.",
        is_new_application=True,
        parsed_event={
            "company_raw": company_name,
            "role_title": "Platform Engineer",
            "event_type": "APPLICATION_RECEIVED",
            "deadline": None,
        },
        db_session=db_session,
    )

    result = graph.invoke(state)

    assert result["is_new_application"] is True
    assert result["committed"] is True
    assert "create_new_record" in result["execution_path"]
    assert "commit_and_log" in result["execution_path"]

    new_app_id = uuid.UUID(result["matched_application_id"])
    new_app = db_session.query(Application).filter(Application.id == new_app_id).first()

    try:
        assert new_app is not None
        assert new_app.company_name == company_name
        assert new_app.role_title == "Platform Engineer"
        assert new_app.current_status == ApplicationStatus.APPLIED

        event = (
            db_session.query(PipelineEvent)
            .filter(PipelineEvent.application_id == new_app_id)
            .first()
        )
        assert event is not None
        assert event.to_status == ApplicationStatus.APPLIED
        assert event.source == EventSource.GMAIL_WORKER
    finally:
        if new_app:
            db_session.delete(new_app)
            db_session.commit()


def test_blocked_backward_transition_does_not_mutate_db(db_session, graph):
    """
    Attempting an illegal backward transition (e.g. OA_RECEIVED on an already REJECTED app)
    must leave the database record uncorrupted at REJECTED.
    """
    app_id = uuid.uuid4()
    app = Application(
        id=app_id,
        company_name="RejectedCorp",
        canonical_company_name="rejectedcorp",
        role_title="Backend Engineer",
        source_platform="Direct",
        current_status=ApplicationStatus.REJECTED,
        applied_at=datetime.now(timezone.utc),
    )
    db_session.add(app)
    db_session.commit()

    try:
        email_body = (
            "Dear Subham,\n\n"
            "Thank you for applying to the Backend Engineer role at RejectedCorp. "
            "As the next step in our interview process, please complete your coding assessment."
        )
        state = _make_state(
            subject="Coding Assessment: Your Application at RejectedCorp",
            sender="assessments@hackerrank.com",
            raw_email_text=email_body,
            relevance_category="ASSESSMENT_INVITATION",
            parsed_event={
                "company_raw": "RejectedCorp",
                "role_title": "Backend Engineer",
                "event_type": "OA_RECEIVED",
                "deadline": None,
            },
            matched_application_id=str(app_id),
            db_session=db_session,
        )

        result = graph.invoke(state)

        assert result["status_changed"] is False
        assert result["target_status"] == "REJECTED"
        assert "blocked by state machine DAG" in result["transition_note"]

        db_session.refresh(app)
        assert app.current_status == ApplicationStatus.REJECTED  # Uncorrupted

    finally:
        db_session.delete(app)
        db_session.commit()
