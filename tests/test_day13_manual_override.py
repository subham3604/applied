"""
tests/test_day13_manual_override.py
===================================
Test suite for Phase 2 Day 13: Manual Update Drop + Direct Status Override.

Validates:
1. `parse_status_update`:
   - Text extraction of `event_type` and `detected_deadline`
   - Transition validation enforcing non-linear `VALID_TRANSITIONS` DAG
   - Rejection of illegal backward transitions via manual drop
2. `apply_manual_update`:
   - Updates `applications.current_status` in PostgreSQL
   - Appends `PipelineEvent` row with `source = EventSource.MANUAL_DROP`
3. `apply_manual_override`:
   - Bypasses DAG transition rules for candidate force corrections (e.g. OA_PENDING -> APPLIED)
   - Appends `PipelineEvent` row with `source = EventSource.MANUAL_OVERRIDE`
   - Zero LLM calls (zero API cost)
4. Deliverable check:
   - Distinct `event_source` values recorded in audit trail for manual drops vs direct overrides
"""

from datetime import datetime, timezone
from unittest.mock import patch
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
    parse_status_update,
)


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


# ==============================================================================
# 1. Parsing & Transition Validation Tests
# ==============================================================================

def test_parse_status_update_interview_invitation():
    """
    Pasting interview invitation text must detect INTERVIEW_INVITE
    and validate legal progression from APPLIED.
    """
    raw_text = "Hi Subham, we would like to invite you for a technical interview on Sep 22 at 2PM via Google Meet."
    event = parse_status_update(raw_text, current_status=ApplicationStatus.APPLIED)

    assert event.event_type == "INTERVIEW_INVITE"
    assert event.detected_deadline is not None
    assert "09-22" in event.detected_deadline or "Sep 22" in event.detected_deadline


def test_parse_status_update_assessment_invite():
    """
    Pasting coding challenge invitation text must detect OA_RECEIVED
    and validate legal progression from APPLIED.
    """
    raw_text = "Please complete the HackerRank coding assessment by Sunday 11:59 PM."
    event = parse_status_update(raw_text, current_status="APPLIED")

    assert event.event_type == "OA_RECEIVED"
    assert event.detected_deadline is not None


def test_parse_status_update_blocked_backward_transition():
    """
    Manual text drop cannot regress an application status (e.g. from REJECTED)
    because it enforces VALID_TRANSITIONS.
    """
    raw_text = "We would love to schedule a follow-up interview on Friday."
    # Current status is REJECTED (terminal, 0 allowed outgoing transitions)
    with pytest.raises(ValueError) as exc_info:
        parse_status_update(raw_text, current_status=ApplicationStatus.REJECTED)

    assert "Invalid transition" in str(exc_info.value)
    assert "blocked by state machine DAG" in str(exc_info.value)


def test_parse_status_update_empty_text_raises_error():
    """Empty or whitespace text must raise ValueError."""
    with pytest.raises(ValueError) as exc_info:
        parse_status_update("   ", current_status="APPLIED")
    assert "cannot be empty" in str(exc_info.value)


# ==============================================================================
# 2. Manual Drop & Direct Override Integration Tests
# ==============================================================================

def test_apply_manual_update_writes_manual_drop_event(db_session):
    """
    Applying a manual text drop:
    - Mutates application current_status from APPLIED to INTERVIEW_ROUND
    - Inserts PipelineEvent with source = MANUAL_DROP
    """
    app = Application(
        id=uuid.uuid4(),
        company_name="Acme Corp",
        canonical_company_name="acme",
        role_title="Backend Engineer",
        source_platform="Direct",
        current_status=ApplicationStatus.APPLIED,
        applied_at=datetime.now(timezone.utc),
    )
    db_session.add(app)
    db_session.commit()

    try:
        raw_text = "Received an email: Your technical interview is scheduled on Sep 22 at 2PM."
        event = apply_manual_update(app.id, raw_text=raw_text, db=db_session)

        # Verify PipelineEvent attributes
        assert event.application_id == app.id
        assert event.from_status == ApplicationStatus.APPLIED
        assert event.to_status == ApplicationStatus.INTERVIEW_ROUND
        assert event.source == EventSource.MANUAL_DROP
        assert event.raw_payload == raw_text

        # Verify Application table mutation
        db_session.refresh(app)
        assert app.current_status == ApplicationStatus.INTERVIEW_ROUND

    finally:
        db_session.delete(app)
        db_session.commit()


def test_apply_manual_override_bypasses_dag(db_session):
    """
    DELIVERABLE CHECK:
    Direct manual override must force backward correction (OA_PENDING -> APPLIED)
    bypassing VALID_TRANSITIONS, with source = MANUAL_OVERRIDE.
    """
    app = Application(
        id=uuid.uuid4(),
        company_name="Zomato",
        canonical_company_name="zomato",
        role_title="Senior Backend Engineer",
        source_platform="Naukri",
        current_status=ApplicationStatus.OA_PENDING,
        applied_at=datetime.now(timezone.utc),
    )
    db_session.add(app)
    db_session.commit()

    try:
        note = "Mistakenly moved to OA; candidate did not receive OA, reverting back to APPLIED."
        event = apply_manual_override(
            application_id=app.id,
            new_status=ApplicationStatus.APPLIED,
            note=note,
            db=db_session,
        )

        # Verify PipelineEvent attributes
        assert event.application_id == app.id
        assert event.from_status == ApplicationStatus.OA_PENDING
        assert event.to_status == ApplicationStatus.APPLIED
        assert event.source == EventSource.MANUAL_OVERRIDE
        assert event.raw_payload == note
        assert event.llm_confidence is None  # Zero LLM

        # Verify Application table mutation
        db_session.refresh(app)
        assert app.current_status == ApplicationStatus.APPLIED

    finally:
        db_session.delete(app)
        db_session.commit()


def test_apply_manual_override_zero_llm_cost(db_session):
    """
    Direct override must not invoke OpenAI / Instructor (zero API cost).
    """
    app = Application(
        id=uuid.uuid4(),
        company_name="Swiggy",
        canonical_company_name="swiggy",
        role_title="Backend Engineer",
        source_platform="Direct",
        current_status=ApplicationStatus.APPLIED,
        applied_at=datetime.now(timezone.utc),
    )
    db_session.add(app)
    db_session.commit()

    try:
        with patch("openai.OpenAI") as mock_openai:
            apply_manual_override(
                application_id=app.id,
                new_status=ApplicationStatus.INTERVIEW_ROUND,
                note="Got a call from HR, interview scheduled for Monday 2PM",
                db=db_session,
            )
            # Ensure OpenAI client was never instantiated
            mock_openai.assert_not_called()

        db_session.refresh(app)
        assert app.current_status == ApplicationStatus.INTERVIEW_ROUND

    finally:
        db_session.delete(app)
        db_session.commit()


def test_deliverable_distinct_event_sources_audit_trail(db_session):
    """
    DELIVERABLE CHECK:
    Manual text drop and direct override both write correct pipeline_events rows
    with distinct event_source values (MANUAL_DROP vs MANUAL_OVERRIDE).
    """
    app = Application(
        id=uuid.uuid4(),
        company_name="TestCorp",
        canonical_company_name="testcorp",
        role_title="AI Engineer",
        source_platform="LinkedIn",
        current_status=ApplicationStatus.APPLIED,
        applied_at=datetime.now(timezone.utc),
    )
    db_session.add(app)
    db_session.commit()

    try:
        # 1. Candidate performs manual update drop
        drop_event = apply_manual_update(
            application_id=app.id,
            raw_text="Passed screening, technical round on Thursday at 3pm.",
            db=db_session,
        )
        assert drop_event.source == EventSource.MANUAL_DROP

        # 2. Candidate performs direct manual override (e.g. phone call negotiation)
        override_event = apply_manual_override(
            application_id=app.id,
            new_status=ApplicationStatus.OFFER,
            note="Verbal offer received via phone call from Director of Engineering",
            db=db_session,
        )
        assert override_event.source == EventSource.MANUAL_OVERRIDE

        # 3. Query all pipeline events for this application
        events = (
            db_session.query(PipelineEvent)
            .filter(PipelineEvent.application_id == app.id)
            .order_by(PipelineEvent.created_at.asc())
            .all()
        )

        sources = [e.source for e in events]
        assert EventSource.MANUAL_DROP in sources
        assert EventSource.MANUAL_OVERRIDE in sources

    finally:
        db_session.delete(app)
        db_session.commit()
