"""
web/services/state_controller.py
================================
State Controller service for candidate-driven pipeline updates in JobTracker.

Handles:
1. `parse_status_update`: Instructor / LLM extraction of event type and detected deadlines
   from candidate-pasted text, validated against the non-linear `VALID_TRANSITIONS` DAG.
2. `apply_manual_update`: Commits validated manual text drop transitions with `source = MANUAL_DROP`.
3. `apply_manual_override`: Direct status override bypassing transition validation with `source = MANUAL_OVERRIDE`
   (zero LLM cost, supports backward corrections like OA_PENDING -> APPLIED).
"""

from datetime import datetime, timezone
import logging
import os
import re
from typing import Any, Optional, Union
import uuid

from sqlalchemy.orm import Session

from db.models import Application, ApplicationStatus, EventSource, PipelineEvent
from db.session import SessionLocal
from web.services.schemas import JobEvent
from worker.agent_state import ApplicationEventType
from worker.state_machine import evaluate_transition

logger = logging.getLogger("state_controller")


# ==============================================================================
# 1. Status Update Parser
# ==============================================================================

def parse_status_update(
    raw_text: str,
    current_status: Union[str, ApplicationStatus],
    client: Optional[Any] = None,
) -> JobEvent:
    """
    Parses candidate-pasted status update text using Instructor (with heuristic fallback).
    Validates that the extracted event is a legal transition from current_status.
    
    Args:
        raw_text: Pasted text from recruiter, email, portal, or messaging.
        current_status: Current status of the target application.
        client: Optional pre-configured instructor client.
        
    Returns:
        JobEvent schema containing event_type, detected_deadline, confidence, and notes.
        
    Raises:
        ValueError if raw_text is empty or if transition is blocked by the state DAG.
    """
    if not raw_text or not raw_text.strip():
        raise ValueError("Status update text cannot be empty.")

    curr_status_str = (
        current_status.value if isinstance(current_status, ApplicationStatus) else str(current_status).upper()
    )

    extracted_event: Optional[JobEvent] = None
    api_key = os.getenv("OPENAI_API_KEY")

    # 1. Attempt Instructor / OpenAI extraction
    if api_key and client is not False:
        try:
            import instructor
            from openai import OpenAI

            instructor_client = client or instructor.from_openai(OpenAI(api_key=api_key))
            extracted_event = instructor_client.chat.completions.create(
                model="gpt-4o-mini",
                response_model=JobEvent,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an expert career agent extracting job progression events from recruiter messages, emails, or portal updates. "
                            "Classify event_type as one of: OA_RECEIVED, INTERVIEW_INVITE, OFFER, REJECTED, APPLICATION_RECEIVED, or STATUS_UPDATE. "
                            "Extract any explicit deadline, interview date/time, or assessment expiry as an ISO 8601 string if present."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Extract career event from this update text:\n\n{raw_text}",
                    },
                ],
                temperature=0.0,
                max_retries=2,
            )
        except Exception as exc:
            logger.warning("Instructor extraction failed; falling back to heuristic parsing: %s", exc)

    # 2. Heuristic fallback for offline, fast, or error conditions
    if not extracted_event:
        lower = raw_text.lower()

        if any(w in lower for w in ["regret", "not moving forward", "another candidate", "unfortunately", "rejected", "rejection"]):
            event_type = ApplicationEventType.REJECTED.value
        elif any(w in lower for w in ["offer letter", "pleased to offer", "congratulations on your offer", "compensation package", "offer"]):
            event_type = ApplicationEventType.OFFER.value
        elif any(w in lower for w in ["interview", "discussion", "technical screen", "system design", "zoom", "google meet", "round"]):
            event_type = ApplicationEventType.INTERVIEW_INVITE.value
        elif any(w in lower for w in ["assessment", "coding challenge", "hackerrank", "codility", "testgorilla", "online test", "oa"]):
            event_type = ApplicationEventType.OA_RECEIVED.value
        elif any(w in lower for w in ["application received", "successfully applied", "thank you for applying"]):
            event_type = ApplicationEventType.APPLICATION_RECEIVED.value
        else:
            event_type = ApplicationEventType.STATUS_UPDATE.value

        # Heuristic deadline / interview date extraction
        deadline = None
        date_pattern = re.search(r'\b(?:on|by|at|before)\s+([A-Za-z0-9\s,:]+?(?:[0-9]{4}|[0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?))\b', raw_text, re.IGNORECASE)
        if date_pattern:
            deadline = date_pattern.group(1).strip()

        extracted_event = JobEvent(
            event_type=event_type,
            detected_deadline=deadline,
            confidence="MEDIUM",
            notes=f"Extracted via heuristic: {event_type}",
        )

    # 3. Validate transition against VALID_TRANSITIONS DAG
    decision = evaluate_transition(
        current_status=curr_status_str,
        event_type=extracted_event.event_type,
        body_snippet=raw_text[:200],
    )

    if not decision.is_valid:
        raise ValueError(
            f"Invalid transition from {curr_status_str} to {extracted_event.event_type}: {decision.note}"
        )

    return extracted_event


# ==============================================================================
# 2. Apply Manual Update Drop (MANUAL_DROP)
# ==============================================================================

def apply_manual_update(
    application_id: Union[str, uuid.UUID],
    raw_text: str,
    db: Optional[Session] = None,
    client: Optional[Any] = None,
) -> PipelineEvent:
    """
    Applies a candidate manual update drop.
    Parses update text via parse_status_update(), validates transition against state machine DAG,
    updates application current_status, and writes a PipelineEvent row with source = MANUAL_DROP.
    """
    managed = False
    if db is None:
        db = SessionLocal()
        managed = True

    try:
        app_uuid = uuid.UUID(str(application_id))
        app = db.query(Application).filter(Application.id == app_uuid).first()
        if not app:
            raise ValueError(f"Application {application_id} not found.")

        old_status = app.current_status
        job_event = parse_status_update(raw_text, current_status=old_status, client=client)
        decision = evaluate_transition(old_status, job_event.event_type, body_snippet=raw_text[:200])

        # Update application status if changed
        if decision.status_changed:
            app.current_status = ApplicationStatus(decision.to_status)
            app.updated_at = datetime.now(timezone.utc)
            db.add(app)

        # Parse detected deadline into datetime if possible
        deadline_dt = None
        if job_event.detected_deadline:
            try:
                deadline_dt = datetime.fromisoformat(job_event.detected_deadline.replace("Z", "+00:00"))
            except Exception:
                pass

        event = PipelineEvent(
            id=uuid.uuid4(),
            application_id=app.id,
            from_status=old_status,
            to_status=ApplicationStatus(decision.to_status),
            detected_deadline=deadline_dt,
            source=EventSource.MANUAL_DROP,
            raw_payload=raw_text,
            resolution_note=job_event.notes or decision.note,
            llm_confidence=job_event.confidence,
            created_at=datetime.now(timezone.utc),
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        logger.info(
            "Applied manual update for %s: %s -> %s (Event ID: %s)",
            app.company_name, old_status.value, decision.to_status, event.id
        )
        return event

    except Exception:
        db.rollback()
        raise
    finally:
        if managed:
            db.close()


# ==============================================================================
# 3. Direct Status Override (MANUAL_OVERRIDE)
# ==============================================================================

def apply_manual_override(
    application_id: Union[str, uuid.UUID],
    new_status: Union[str, ApplicationStatus],
    note: str = "",
    db: Optional[Session] = None,
) -> PipelineEvent:
    """
    Direct Status Override (CUJ-4).
    Zero-LLM candidate action bypassing state machine DAG validation.
    Accepts any new status (including backward corrections like OA_PENDING -> APPLIED).
    Writes PipelineEvent with source = MANUAL_OVERRIDE.
    """
    managed = False
    if db is None:
        db = SessionLocal()
        managed = True

    try:
        app_uuid = uuid.UUID(str(application_id))
        app = db.query(Application).filter(Application.id == app_uuid).first()
        if not app:
            raise ValueError(f"Application {application_id} not found.")

        old_status = app.current_status
        target_status_enum = (
            new_status if isinstance(new_status, ApplicationStatus) else ApplicationStatus(str(new_status).upper())
        )

        # Update application status
        app.current_status = target_status_enum
        app.updated_at = datetime.now(timezone.utc)
        db.add(app)

        event = PipelineEvent(
            id=uuid.uuid4(),
            application_id=app.id,
            from_status=old_status,
            to_status=target_status_enum,
            detected_deadline=None,
            source=EventSource.MANUAL_OVERRIDE,
            raw_payload=note or "Direct status override by user",
            resolution_note="Manual status override applied by candidate",
            llm_confidence=None,  # Zero-LLM direct candidate action
            created_at=datetime.now(timezone.utc),
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        logger.info(
            "Applied manual override for %s: %s -> %s (Note: '%s')",
            app.company_name, old_status.value, target_status_enum.value, note
        )
        return event

    except Exception:
        db.rollback()
        raise
    finally:
        if managed:
            db.close()
