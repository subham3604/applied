"""
worker/worker.py
================
Autonomous Career Pipeline Background Worker Service for JobTracker.

Features:
- Configures APScheduler with CronTrigger(hour=8, minute=0) for daily execution.
- Reads `last_checked_at` from the PostgreSQL `worker_config` table.
- Fetches new emails matching application filters via Gmail API.
- Feeds candidate emails into the LangGraph state machine agent (Nodes 0–9).
- Atomically advances `last_checked_at` in `worker_config` upon cycle completion.
- Supports immediate startup execution via `WORKER_RUN_ON_STARTUP=true`.
- Graceful shutdown handling for container SIGTERM / SIGINT signals.
"""

from datetime import datetime, timezone
import logging
import os
import signal
import sys
from typing import Any, Callable, Dict, Optional

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from db.session import SessionLocal
from worker.gmail_poller import (
    fetch_new_emails,
    get_worker_last_checked_at,
    update_worker_last_checked_at,
)
from worker.graph_agent import build_email_agent_graph

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("worker")


# ==============================================================================
# Core Worker Execution Cycle
# ==============================================================================

def run_poll_cycle(
    session_factory: Callable = SessionLocal,
    service: Optional[Any] = None,
    graph: Optional[Any] = None,
    now_dt: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Executes a single end-to-end polling and state machine ingestion cycle.
    
    1. Reads `last_checked_at` boundary from database.
    2. Retrieves candidate emails via Layer 1 Gmail query.
    3. Invokes compiled LangGraph agent per message.
    4. Updates `last_checked_at` in `worker_config` upon successful cycle.
    
    Returns:
        Summary dict containing counts of processed, relevant, committed, and dead-lettered events.
    """
    cycle_start = now_dt or datetime.now(timezone.utc)
    logger.info("--- Starting Autonomous Worker Polling Cycle [%s] ---", cycle_start.isoformat())

    summary = {
        "processed": 0,
        "relevant": 0,
        "committed": 0,
        "dead_letter": 0,
        "last_checked_at": cycle_start,
    }

    with session_factory() as session:
        last_checked_at = get_worker_last_checked_at(session)
        logger.info("Querying emails received since: %s", last_checked_at.isoformat())

        try:
            emails = fetch_new_emails(last_checked_at=last_checked_at, service=service)
        except Exception as fetch_err:
            logger.error("Error fetching emails from Gmail API: %s", fetch_err, exc_info=True)
            summary["error"] = str(fetch_err)
            return summary

        logger.info("Discovered %d candidate email(s) for LangGraph processing.", len(emails))

        compiled_graph = graph or build_email_agent_graph()
        max_received_at = last_checked_at

        for email in emails:
            summary["processed"] += 1
            if email.received_at > max_received_at:
                max_received_at = email.received_at

            logger.info(
                "Processing message [%d/%d]: '%s' from %s",
                summary["processed"], len(emails), email.subject, email.sender
            )

            initial_state = {
                "raw_email_text": email.body_text,
                "email_received_at": email.received_at,
                "sender": email.sender,
                "subject": email.subject,
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
                "db_session": session,
                "dead_letter_reason": None,
                "execution_path": [],
            }

            try:
                result = compiled_graph.invoke(initial_state)

                if result.get("is_relevant"):
                    summary["relevant"] += 1
                if result.get("committed"):
                    summary["committed"] += 1
                    logger.info("Successfully committed pipeline event for '%s'", email.subject)
                elif "dead_letter_log" in result.get("execution_path", []):
                    summary["dead_letter"] += 1
                    logger.info(
                        "Email '%s' routed to dead_letter_log: %s",
                        email.subject, result.get("dead_letter_reason")
                    )

            except Exception as proc_err:
                logger.error(
                    "Unhandled exception processing email '%s': %s",
                    email.subject, proc_err, exc_info=True
                )

        # Update last_checked_at timestamp boundary
        update_boundary = max(max_received_at, cycle_start)
        try:
            update_worker_last_checked_at(session, update_boundary)
            summary["last_checked_at"] = update_boundary
        except Exception as db_err:
            logger.error("Failed to update last_checked_at in worker_config: %s", db_err)

    logger.info(
        "--- Finished Polling Cycle: Processed=%d, Relevant=%d, Committed=%d, DeadLetter=%d ---",
        summary["processed"], summary["relevant"], summary["committed"], summary["dead_letter"]
    )
    return summary


# ==============================================================================
# Scheduler Factory
# ==============================================================================

def create_worker_scheduler(
    cron_hour: int = 8,
    cron_minute: int = 0,
    timezone_str: str = "UTC",
    session_factory: Callable = SessionLocal,
) -> BlockingScheduler:
    """
    Configures a BlockingScheduler with a daily CronTrigger.
    
    Args:
        cron_hour: Hour of the day to trigger (default 8).
        cron_minute: Minute of the hour to trigger (default 0).
        timezone_str: Timezone identifier (default UTC).
        session_factory: SQLAlchemy session factory.
        
    Returns:
        Configured BlockingScheduler instance ready for .start().
    """
    scheduler = BlockingScheduler(timezone=timezone_str)

    trigger = CronTrigger(
        hour=cron_hour,
        minute=cron_minute,
        timezone=timezone_str,
    )

    scheduler.add_job(
        func=run_poll_cycle,
        trigger=trigger,
        args=[session_factory],
        id="gmail_daily_poll",
        name="Daily Gmail Career Pipeline Poller",
        replace_existing=True,
    )

    logger.info(
        "Configured APScheduler CronTrigger: Daily at %02d:%02d (%s)",
        cron_hour, cron_minute, timezone_str
    )
    return scheduler


# ==============================================================================
# Main Process Entrypoint
# ==============================================================================

def main():
    """Main worker service entrypoint."""
    logger.info("Initializing Autonomous Career Pipeline Worker Daemon...")

    # Read configuration from environment
    cron_hour = int(os.getenv("WORKER_CRON_HOUR", "8"))
    cron_minute = int(os.getenv("WORKER_CRON_MINUTE", "0"))
    worker_tz = os.getenv("WORKER_TIMEZONE", "UTC")
    run_on_startup = os.getenv("WORKER_RUN_ON_STARTUP", "true").lower() in ("1", "true", "yes")

    # Verify database connectivity
    try:
        with SessionLocal() as session:
            current_boundary = get_worker_last_checked_at(session)
            logger.info("Database connection healthy. Current lookback boundary: %s", current_boundary)
    except Exception as exc:
        logger.warning("Database connection check failed on startup: %s", exc)

    # If run-on-startup is enabled, execute an immediate cycle before blocking
    if run_on_startup:
        logger.info("WORKER_RUN_ON_STARTUP is enabled. Executing initial polling cycle...")
        try:
            run_poll_cycle()
        except Exception as exc:
            logger.error("Initial startup poll cycle encountered error: %s", exc, exc_info=True)

    # Initialize scheduler
    scheduler = create_worker_scheduler(
        cron_hour=cron_hour,
        cron_minute=cron_minute,
        timezone_str=worker_tz,
    )

    # Signal handlers for graceful shutdown in Docker
    def handle_shutdown(signum, frame):
        logger.info("Received signal (%d). Shutting down worker gracefully...", signum)
        if scheduler.running:
            scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    logger.info("Starting scheduler loop. Press Ctrl+C or send SIGTERM to exit.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker process terminated.")


if __name__ == "__main__":
    main()
