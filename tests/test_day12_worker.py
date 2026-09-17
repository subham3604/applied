"""
tests/test_day12_worker.py
==========================
Test suite for Phase 2 Day 12: APScheduler + Background Worker Service.

Validates:
1. APScheduler CronTrigger configuration (daily at hour=8, minute=0).
2. Autonomous poll cycle execution:
   - Reading `last_checked_at` from `worker_config`
   - Fetching emails and dispatching to LangGraph
   - Updating application status and inserting PipelineEvent
   - Advancing `last_checked_at` upon completion
3. Zero emails case (graceful completion and timestamp advancement).
4. Missing / expired credentials resilience (no crash loop, logs warning).
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import uuid
import pytest
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import (
    Application,
    ApplicationStatus,
    PipelineEvent,
    WorkerConfig,
)
from db.session import DATABASE_URL
from worker.gmail_poller import EmailMessage, WORKER_CONFIG_LAST_CHECKED_KEY, get_worker_last_checked_at
from worker.worker import (
    create_worker_scheduler,
    run_poll_cycle,
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
# 1. Scheduler Configuration Tests
# ==============================================================================

def test_worker_scheduler_configuration(db_session_factory):
    """
    Verify that create_worker_scheduler sets up APScheduler with
    a CronTrigger firing daily at 08:00 UTC.
    """
    scheduler = create_worker_scheduler(
        cron_hour=8,
        cron_minute=0,
        timezone_str="UTC",
        session_factory=db_session_factory,
    )

    jobs = scheduler.get_jobs()
    assert len(jobs) == 1

    job = jobs[0]
    assert job.id == "gmail_daily_poll"
    assert isinstance(job.trigger, CronTrigger)

    # Verify trigger fields for hour 8 and minute 0
    trigger_str = str(job.trigger)
    assert "hour='8'" in trigger_str
    assert "minute='0'" in trigger_str
    assert str(job.trigger.timezone) == "UTC"


# ==============================================================================
# 2. Polling Cycle Execution Tests
# ==============================================================================

def test_poll_cycle_with_zero_emails(db_session_factory, db_session):
    """
    When no emails match the query, the poll cycle should complete cleanly
    and advance last_checked_at to the current timestamp.
    """
    with patch("worker.worker.fetch_new_emails", return_value=[]):
        before_run = datetime.now(timezone.utc) - timedelta(seconds=1)
        summary = run_poll_cycle(session_factory=db_session_factory)
        after_run = datetime.now(timezone.utc) + timedelta(seconds=1)

        assert summary["processed"] == 0
        assert summary["relevant"] == 0
        assert summary["committed"] == 0
        assert summary["dead_letter"] == 0

        # Verify last_checked_at in DB
        db_last_checked = get_worker_last_checked_at(db_session)
        assert before_run <= db_last_checked <= after_run


def test_poll_cycle_with_candidate_emails_langgraph_traversal(db_session_factory, db_session):
    """
    Inject mock candidate emails into run_poll_cycle:
    - Verifies message passes into LangGraph
    - Verifies application record matching and pipeline event creation
    - Verifies last_checked_at timestamp advancement
    """
    app_id = uuid.uuid4()
    app = Application(
        id=app_id,
        company_name="Zyntrix Software",
        canonical_company_name="zyntrix",
        role_title="Software Developer",
        source_platform="Direct",
        current_status=ApplicationStatus.APPLIED,
        applied_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    db_session.add(app)
    db_session.commit()

    try:
        now_dt = datetime.now(timezone.utc)
        mock_email = EmailMessage(
            message_id="msg_test_001",
            thread_id="th_test_001",
            sender="hr@zyntrixsoftware.com",
            recipient="candidate@gmail.com",
            subject="Application Received - Software Developer | Zyntrix Software",
            received_at=now_dt,
            snippet="We have received your application...",
            body_text=(
                "Dear Subham,\n\n"
                "We have received your application for Software Developer at Zyntrix Software. "
                "Our hiring team is reviewing your profile."
            ),
        )

        with patch("worker.worker.fetch_new_emails", return_value=[mock_email]):
            summary = run_poll_cycle(session_factory=db_session_factory, now_dt=now_dt)

            assert summary["processed"] == 1
            assert summary["relevant"] == 1
            assert summary["committed"] == 1
            assert summary["dead_letter"] == 0

            # Verify PipelineEvent was committed in DB
            event = (
                db_session.query(PipelineEvent)
                .filter(PipelineEvent.application_id == app_id)
                .order_by(PipelineEvent.created_at.desc())
                .first()
            )
            assert event is not None
            assert event.from_status == ApplicationStatus.APPLIED
            assert event.to_status == ApplicationStatus.APPLIED
            assert "Zyntrix Software" in event.raw_payload

    finally:
        db_session.delete(app)
        db_session.commit()


def test_poll_cycle_graceful_missing_credentials(db_session_factory):
    """
    When Gmail credentials are absent or fetch raises an error,
    the worker must log a warning and return without crashing.
    """
    with patch("worker.worker.fetch_new_emails", side_effect=RuntimeError("Credentials not configured")):
        summary = run_poll_cycle(session_factory=db_session_factory)
        assert summary["processed"] == 0
        assert summary["committed"] == 0


def test_poll_cycle_advances_historical_timestamp(db_session_factory, db_session):
    """
    If worker_config has a stale lookback timestamp (e.g. 5 days ago),
    running a poll cycle should advance it forward to the current time.
    """
    stale_dt = datetime.now(timezone.utc) - timedelta(days=5)
    db_session.merge(WorkerConfig(key=WORKER_CONFIG_LAST_CHECKED_KEY, value=stale_dt.isoformat()))
    db_session.commit()

    with patch("worker.worker.fetch_new_emails", return_value=[]):
        run_poll_cycle(session_factory=db_session_factory)

        new_last_checked = get_worker_last_checked_at(db_session)
        assert new_last_checked > stale_dt
        # Should be within the last 10 seconds
        assert (datetime.now(timezone.utc) - new_last_checked).total_seconds() < 10
