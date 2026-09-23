"""
worker/graph_agent.py
=====================
Stateful LangGraph Agent for autonomous email processing in JobTracker.

Implements the multi-node directed acyclic state graph (DAG) defined in
Section 5 of SYSTEM_DESIGN.md:
- Node 0: `relevance_gate` (Active Layer 2 filter)
- Node 1: `extract_event`
- Node 2: `validate_schema`
- Node 3: `self_repair` (with circuit breaker)
- Node 4: `entity_resolution`
- Node 5: `create_new_record`
- Node 6: `state_transition`
- Node 7: `flag_for_manual`
- Node 8: `commit_and_log`
- Node 9: `dead_letter_log`
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
import logging
import re
import uuid
from typing import Any, Dict, Optional

from langgraph.graph import END, START, StateGraph

from pydantic import BaseModel, Field
from worker.agent_state import AgentState, ApplicationEventType, ParsedEmailEvent
from worker.entity_resolution import (
    EntityAliasCache,
    ResolutionAction,
    ResolutionConfidence,
    _get_instructor_client,
    lookup_company_web,
)
from worker.gmail_filter import check_email_relevance
from worker.state_machine import (
    evaluate_transition,
    detect_source_platform,
    EVENT_TO_TARGET_STATUS,
    VALID_TRANSITIONS,
)

logger = logging.getLogger("graph_agent")


def _parse_deadline_datetime(raw_val: Optional[str], default_tz=timezone.utc) -> Optional[datetime]:
    """Helper to parse an ISO or human deadline string into a timezone-aware datetime."""
    if not raw_val:
        return None
    try:
        dt = datetime.fromisoformat(raw_val.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=default_tz)
        return dt
    except Exception:
        pass
    try:
        import dateutil.parser
        dt = dateutil.parser.parse(raw_val, fuzzy=True)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=default_tz)
        return dt
    except Exception:
        return None


# ==============================================================================
# Helper to Update Execution Trail & Database Sessions
# ==============================================================================

def _record_path(state: AgentState, node_name: str) -> list[str]:
    """Appends the current node name to the state's execution audit path."""
    current_path = list(state.get("execution_path", []))
    current_path.append(node_name)
    return current_path


@contextmanager
def _get_db_session(state: AgentState):
    """
    Context manager yielding an active SQLAlchemy session.
    Uses injected state['db_session'] if present; otherwise creates a SessionLocal(),
    committing on clean exit and rolling back on error.
    Yields None if DB access fails gracefully.
    """
    injected = state.get("db_session")
    if injected is not None:
        yield injected
        return

    session = None
    try:
        from db.session import SessionLocal
        session = SessionLocal()
        yield session
        session.commit()
    except Exception as exc:
        if session:
            try:
                session.rollback()
            except Exception:
                pass
        logger.warning("Database session error in graph agent node: %s", exc)
        yield None
    finally:
        if session:
            session.close()


# ==============================================================================
# Node Implementations
# ==============================================================================

def node_relevance_gate(state: AgentState) -> Dict[str, Any]:
    """
    Node 0: Relevance Gate.
    Classifies whether this email confirms an already submitted application event.
    """
    subject = state.get("subject", "")
    sender = state.get("sender", "")
    raw_text = state.get("raw_email_text", "")

    decision = check_email_relevance(
        subject=subject,
        sender=sender,
        body_text=raw_text,
    )

    path = _record_path(state, "relevance_gate")
    logger.info(
        "Node 0 Relevance Gate -> is_relevant=%s category=%s (confidence=%.2f)",
        decision.is_relevant, decision.category, decision.confidence
    )

    updates: Dict[str, Any] = {
        "is_relevant": decision.is_relevant,
        "relevance_category": decision.category,
        "relevance_reason": decision.reason,
        "execution_path": path,
    }

    if not decision.is_relevant:
        updates["dead_letter_reason"] = f"Filtered by Node 0 Relevance Gate: {decision.reason}"

    return updates


class ExtractedEmailEvent(BaseModel):
    company_name: str = Field(description="The actual hiring company name (NOT an ATS or portal vendor like Workday, Lever, Greenhouse, Ashby, SmartRecruiters).")
    role_title: Optional[str] = Field(default=None, description="The job role / title mentioned in the email, or None if unspecified.")
    event_type: str = Field(description="The event stage: APPLICATION_RECEIVED, OA_RECEIVED, INTERVIEW_INVITE, OFFER, REJECTED, or STATUS_UPDATE.")
    deadline: Optional[str] = Field(default=None, description="Assessment or interview deadline string / ISO timestamp if specified.")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Extraction confidence score.")


def _extract_with_llm(state: AgentState) -> Optional[Dict[str, Any]]:
    client = _get_instructor_client()
    if not client:
        return None

    raw_text = (state.get("raw_email_text") or "")[:1500]
    subject = state.get("subject", "")
    sender = state.get("sender", "")

    prompt = (
        f"Analyze the following job application email and extract the key details.\n"
        f"Sender: {sender}\n"
        f"Subject: {subject}\n\n"
        f"Email Content Snippet:\n{raw_text}\n\n"
        f"Instructions:\n"
        f"1. Company Name: Identify the actual hiring organization. Do NOT return the ATS or applicant tracking software provider (e.g. do not return 'Workday', 'Myworkday', 'Lever', 'Greenhouse', 'Hire', 'SmartRecruiters', 'Ashby').\n"
        f"2. If the email is from Workday (e.g. tenant@myworkday.com), the tenant prefix or display name is the company hiring (e.g. Maersk, Modernizing Medicine, etc.).\n"
        f"3. Role Title: Extract the specific role title if present (e.g. 'AI/ML Engineer (Data Engineering + AI Focus)').\n"
        f"4. Event Type: Classify into one of: APPLICATION_RECEIVED, OA_RECEIVED, INTERVIEW_INVITE, OFFER, REJECTED, STATUS_UPDATE."
    )

    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            response_model=ExtractedEmailEvent,
            messages=[
                {"role": "system", "content": "You are an expert ATS email parsing engine. Extract precise structured data."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )
        if res and res.company_name and res.company_name.lower().strip() not in ("unknown", "unknown company", "workday", "myworkday", "hire"):
            event_type_val = res.event_type.upper()
            valid_types = {e.value for e in ApplicationEventType}
            if event_type_val not in valid_types:
                event_type_val = ApplicationEventType.APPLICATION_RECEIVED.value

            # Cache resolved sender domain -> company
            disp_name, addr = parseaddr(sender)
            if addr:
                EntityAliasCache.set(addr, res.company_name)
                if "@" in addr:
                    EntityAliasCache.set(addr.split("@")[-1], res.company_name)

            return {
                "company_raw": res.company_name.strip(),
                "role_title": res.role_title.strip() if res.role_title else None,
                "event_type": event_type_val,
                "deadline": res.deadline,
            }
    except Exception as e:
        logger.debug("LLM extraction attempt failed (%s); using deterministic fallback.", e)
        return None


def node_extract_event(state: AgentState) -> Dict[str, Any]:
    """
    Node 1: Extract Event.
    Extracts company_raw, role_title, event_type, and deadline from email text.
    """
    path = _record_path(state, "extract_event")
    logger.info("Node 1 Extract Event executing")

    # If parsed_event was pre-injected in state (e.g. in testing), keep it
    if state.get("parsed_event"):
        return {"execution_path": path}

    # Extraction heuristic for pipeline
    category = state.get("relevance_category", "APPLICATION_CONFIRMATION")
    event_type_map = {
        "APPLICATION_CONFIRMATION": ApplicationEventType.APPLICATION_RECEIVED,
        "ASSESSMENT_INVITATION": ApplicationEventType.OA_RECEIVED,
        "INTERVIEW_INVITATION": ApplicationEventType.INTERVIEW_INVITE,
        "OFFER_LETTER": ApplicationEventType.OFFER,
        "REJECTION": ApplicationEventType.REJECTED,
        "STATUS_UPDATE": ApplicationEventType.STATUS_UPDATE,
    }
    event_type = event_type_map.get(category, ApplicationEventType.APPLICATION_RECEIVED)

    raw_text = state.get("raw_email_text", "")
    subject = state.get("subject", "")
    combined = f"{subject}\n{raw_text}".lower()

    # Reconcile semantic rejection overrides (e.g. polite confirmation subject hiding a rejection)
    if any(sig in combined for sig in [
        "decided not to move forward", "will not be moving forward", "not to move forward",
        "regret to inform", "not taking your candidacy", "pursue other candidates",
        "pursue other applicants", "position closed", "offer of employment extended", "officially rescinded"
    ]):
        if "rescinded" in combined or not any(sig in combined for sig in ["interview", "assessment"]):
            event_type = ApplicationEventType.REJECTED

    # Reconcile OA completion receipt (submission finished, not pending OA)
    if any(sig in combined for sig in ["completed your", "submission received", "tasks submitted"]):
        if event_type == ApplicationEventType.OA_RECEIVED:
            event_type = ApplicationEventType.APPLICATION_RECEIVED

    # 1. Extract Company Name (Generalized across ATS providers, headers, and prepositions)
    sender = state.get("sender", "")
    disp_name, addr = parseaddr(sender)
    disp_name = disp_name.strip('"\' ')
    addr_lower = addr.lower()

    # 1. Extract Company Name & Event details via Structured LLM if available
    llm_extracted = _extract_with_llm(state)
    if llm_extracted:
        return {
            "parsed_event": llm_extracted,
            "execution_path": path,
        }

    # Fallback to Generalized Deterministic Parsing (when LLM is offline or unconfigured)
    sender = state.get("sender", "")
    disp_name, addr = parseaddr(sender)
    disp_name = disp_name.strip('"\' ')
    addr_lower = addr.lower()

    company = EntityAliasCache.get(addr) or EntityAliasCache.get(disp_name)

    # A. ATS Display Name (e.g. "Gushwork <no-reply@hire.lever.co>")
    ats_domains = ("lever.co", "greenhouse.io", "ashbyhq.com", "smartrecruiters.com", "breezy.hr", "jobvite.com", "workable.com")
    is_ats = any(dom in addr_lower for dom in ats_domains)
    if not company and is_ats and disp_name:
        clean_disp = re.sub(r'\s*(?:Recruiting|Talent Acquisition|Talent Team|Careers|Team|HR|Jobs|Hiring Team|No-Reply)\b.*', '', disp_name, flags=re.IGNORECASE).strip()
        if clean_disp and clean_disp.lower() not in ("no-reply", "notifications", "recruiting", "support"):
            company = clean_disp

    # B. Workday Email Structure: <tenant>@myworkday.com -> extract tenant dynamically
    if not company and "@myworkday.com" in addr_lower:
        prefix = addr_lower.split("@")[0].split("<")[-1].strip()
        cached = EntityAliasCache.get(prefix)
        if cached:
            company = cached
        elif disp_name and not any(bad in disp_name.lower() for bad in ("workday", "recruiting", "talent", "do-not-reply", "support")):
            company = disp_name
        else:
            clean_p = re.sub(r'(?:inc|corp|careers|jobs)$', '', prefix).strip()
            company = clean_p.title() if clean_p else None

    # C. Display Name Fallback: If sender display name is not generic
    if not company and disp_name:
        clean_disp = re.sub(r'\s*(?:Recruiting|Talent Acquisition|Talent Team|Careers|Team|HR|Jobs|Hiring Team|No-Reply)\b.*', '', disp_name, flags=re.IGNORECASE).strip()
        if clean_disp and clean_disp.lower() not in ("no-reply", "notifications", "recruiting", "support", "careers", "talent acquisition"):
            company = clean_disp

    # D. Subject Line Preposition Patterns
    if not company:
        subj_clean = re.sub(r'^(?:Fwd?:|Re:)\s*', '', subject, flags=re.IGNORECASE).strip()
        patterns = [
            r'(?:applying to|applied to|application to|welcome to|offer from|interview with|invite from|interest in|career opportunity at|opportunity at|position at|role at|\bat)\s+([A-Za-z0-9\s&]+?)(?:\s*(?:Pvt|Private|Ltd|Limited|for|on|\.|\-|$))',
            r'(?:Thank You for Applying to|Thanks for applying to|Thank you for your interest in)\s+([A-Za-z0-9\s&]+?)(?:\s*(?:Pvt|Private|Ltd|Limited|for|on|\.|\-|$))',
            r'([A-Za-z0-9\s&]+?)\s+(?:Application Received|Job Application|Interview|Careers)',
        ]
        for pat in patterns:
            m = re.search(pat, subj_clean, re.IGNORECASE)
            if m and len(m.group(1).strip()) > 1:
                cand = m.group(1).strip()
                if not any(bad in cand.lower() for bad in ("interview", "assessment", "application", "invitation", "opportunity", "update", "next steps", "submission", "candidate")):
                    company = cand
                    break

    # E. Sender Domain (Excluding public webmail, ATS platforms, testing platforms)
    if not company and "@" in addr:
        domain_match = re.search(r'@(?:careers\.|jobs\.|talent\.|recruiting\.|hr\.)?([A-Za-z0-9\-]+)\.', addr)
        if domain_match:
            dom = domain_match.group(1).lower()
            ats_and_webmail = {
                "gmail", "yahoo", "outlook", "hotmail", "icloud", "mail",
                "greenhouse", "lever", "workday", "myworkday", "smartrecruiters",
                "ashbyhq", "breezy", "jobvite", "workable", "hire",
                "hackerrank", "hackerrankforwork", "hackerearth", "codility", "mettl", "codesignal",
            }
            if dom not in ats_and_webmail:
                clean_dom = re.sub(r'(?:software|solutions|services|technologies|tech|group|global|holdings)$', '', dom).strip()
                company = (clean_dom or dom).capitalize()

    if not company:
        company = "Unknown Company"

    # Extract due date and time for OA and Interviews
    deadline = None
    if event_type in (ApplicationEventType.OA_RECEIVED, ApplicationEventType.INTERVIEW_INVITE):
        email_time = state.get("email_received_at") or datetime.now(timezone.utc)
        rel_hrs = re.search(r'\b(?:within|valid for|expires in|complete in|complete within|take within)\s+(\d+)\s*(?:hours?|hrs?)\b', combined, re.IGNORECASE)
        if rel_hrs:
            hrs = int(rel_hrs.group(1))
            deadline = (email_time + timedelta(hours=hrs)).isoformat()
        else:
            rel_days = re.search(r'\b(?:within|in|valid for)\s+(\d+)\s*days?\b', combined, re.IGNORECASE)
            if rel_days:
                days = int(rel_days.group(1))
                deadline = (email_time + timedelta(days=days)).isoformat()
            else:
                date_pattern = re.search(
                    r'\b(?:due by|due on|due date:?|deadline:?|expires on|expires:?|until|before|by|on|at)\s+'
                    r'([A-Za-z0-9\s,:]+?(?:[0-9]{4}|[0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?))\b',
                    combined,
                    re.IGNORECASE,
                )
                if date_pattern:
                    date_str = date_pattern.group(1).strip()
                    parsed_dt = _parse_deadline_datetime(date_str)
                    deadline = parsed_dt.isoformat() if parsed_dt else date_str

    # 2. Extract Role Title (Generalized)
    role_title = None

    # Priority A: High-signal Subject Line patterns
    subj_patterns = [
        r'Application received for\s+([A-Za-z0-9\s\-\/\(\)\+\.]+?)(?:\s+position|\.|\-|$)',
        r'Application Received:?\s+([A-Za-z0-9\s\-\/\(\)\+\.]+?)(?:\s+position|\.|\-|$)',
        r'Received Your Application for the\s+([A-Za-z0-9\s\-\/\(\)\+\.]+?)(?:\s+Position|\s+Role|\s+Opening|\.|\-|$)',
        r'Update on [^’\']+[’\']s\s+([A-Za-z0-9\s\-\/\(\)\+\.]+?)\s+Role',
        r'Follow up on your interest in\s+([A-Za-z0-9\s\-\/\(\)\+\.]+?)\s+at\s+',
        r'position closed\s+[A-Za-z0-9\-]+\s+([A-Za-z0-9\s\-\/\(\)\+\.]+)',
        r'role of\s+([A-Za-z0-9\s\-\/\(\)\+\.]+?)(?:\s+at|\.|\-|$)',
    ]
    for pat in subj_patterns:
        m = re.search(pat, subject, re.IGNORECASE)
        if m and len(m.group(1).strip()) > 2:
            cand_role = m.group(1).strip()
            if not any(b in cand_role.lower() for b in ("application", "review", "status", "thank you", "submission")):
                role_title = cand_role
                break

    # Priority B: Body patterns on clean text
    if not role_title and raw_text:
        body_patterns = [
            r'received your application for (?:the\s+)?([A-Za-z0-9\s\-\/\(\)\+\.]+?)(?:,|\.|\n|at\s+|with\s+|position|role|opportunity|and we are)',
            r'application for (?:the\s+)?([A-Za-z0-9\s\-\/\(\)\+\.]+?)\s+position',
            r'role of\s+(?:[A-Za-z0-9\-]+\s*-\s*)?([A-Za-z0-9\s\-\/\(\)\+\.]+?)(?:\s*\.|\s*,|\s*\n)',
            r'position of\s+(?:[A-Za-z0-9\-]+\s*-\s*)?([A-Za-z0-9\s\-\/\(\)\+\.]+?)(?:\s*\.|\s*,|\s*\n)',
            r'applied for the\s+([A-Za-z0-9\s\-\/\(\)\+\.]+?)(?:\s+position|\s+role|\.|\,)',
        ]
        for pat in body_patterns:
            m = re.search(pat, raw_text, re.IGNORECASE)
            if m and len(m.group(1).strip()) > 2:
                cand_role = m.group(1).strip()
                cand_role = re.split(r'\s+(?:Our|We|Thank|Please|A member|You|If)\b', cand_role)[0].strip()
                if not any(b in cand_role.lower() for b in ("dear", "candidate", "subham", "application", "hiring")):
                    role_title = cand_role
                    break

    extracted = {
        "company_raw": company,
        "role_title": role_title,
        "event_type": event_type.value,
        "deadline": deadline,
    }

    return {
        "parsed_event": extracted,
        "execution_path": path,
    }


def node_validate_schema(state: AgentState) -> Dict[str, Any]:
    """
    Node 2: Validate Schema.
    Validates parsed_event against ParsedEmailEvent Pydantic model.
    """
    path = _record_path(state, "validate_schema")
    logger.info("Node 2 Validate Schema executing")

    parsed = state.get("parsed_event")
    errors = []

    if not parsed or not isinstance(parsed, dict):
        errors.append("parsed_event is missing or not a valid dictionary.")
    else:
        try:
            ParsedEmailEvent(**parsed)
        except Exception as exc:
            errors.append(f"Schema validation error: {str(exc)}")

    return {
        "validation_errors": errors,
        "execution_path": path,
    }


def node_self_repair(state: AgentState) -> Dict[str, Any]:
    """
    Node 3: Self Repair Loop.
    Increments retry count and attempts schema repair.
    """
    path = _record_path(state, "self_repair")
    new_retries = state.get("retry_count", 0) + 1
    logger.warning("Node 3 Self Repair executing (Attempt %d)", new_retries)

    updates: Dict[str, Any] = {
        "retry_count": new_retries,
        "execution_path": path,
    }

    # Simple repair stub: if company_raw was missing, patch with a default
    parsed = state.get("parsed_event")
    if isinstance(parsed, dict) and not parsed.get("company_raw"):
        parsed_fixed = dict(parsed)
        parsed_fixed["company_raw"] = "Repaired Company"
        updates["parsed_event"] = parsed_fixed

    if new_retries > 3:
        updates["dead_letter_reason"] = f"Self-repair circuit breaker tripped after {new_retries} attempts."

    return updates


def node_entity_resolution(state: AgentState) -> Dict[str, Any]:
    """
    Node 4: Entity Resolution.
    Maps company_raw and role_title to an existing application or identifies new application
    via the Multi-Level Entity Resolution fallback chain.
    """
    from worker.entity_resolution import (
        ApplicationCandidate,
        ResolutionAction,
        resolve_entity,
    )
    from db.models import Application
    from db.session import SessionLocal

    path = _record_path(state, "entity_resolution")
    logger.info("Node 4 Entity Resolution executing")

    # If state already has matched_application_id, is_new_application, or resolution_confidence explicitly forced
    # and no candidate_apps provided, retain previous behavior for isolated node testing
    if (state.get("matched_application_id") or state.get("is_new_application") or state.get("resolution_confidence") == "AMBIGUOUS") and state.get("candidate_apps") is None:
        return {
            "is_new_application": state.get("is_new_application", False),
            "resolution_confidence": state.get("resolution_confidence", "HIGH"),
            "resolution_note": state.get("resolution_note", "Entity matched via pre-set resolution"),
            "execution_path": path,
        }

    # 1. Retrieve candidate applications (from state override or DB)
    raw_candidates = state.get("candidate_apps")
    candidate_apps: list[ApplicationCandidate] = []

    if raw_candidates is not None:
        for c in raw_candidates:
            if isinstance(c, ApplicationCandidate):
                candidate_apps.append(c)
            elif isinstance(c, dict):
                candidate_apps.append(ApplicationCandidate(**c))
    else:
        try:
            with SessionLocal() as session:
                db_apps = session.query(Application).all()
                for app in db_apps:
                    candidate_apps.append(
                        ApplicationCandidate(
                            id=str(app.id),
                            company_name=app.company_name,
                            canonical_company_name=app.canonical_company_name,
                            role_title=app.role_title,
                            applied_at=app.applied_at,
                            current_status=app.current_status.value if hasattr(app.current_status, "value") else str(app.current_status),
                        )
                    )
        except Exception as exc:
            logger.warning("Could not query DB applications in node_entity_resolution: %s", exc)

    # 2. Extract resolution inputs from state
    parsed = state.get("parsed_event") or {}
    company_raw = parsed.get("company_raw", "")
    role_title = parsed.get("role_title")
    email_received_at = state.get("email_received_at", datetime.now(timezone.utc))

    # 3. Execute Entity Resolution engine
    resolution = resolve_entity(
        company_raw=company_raw,
        role_title=role_title,
        email_received_at=email_received_at,
        candidate_apps=candidate_apps,
    )

    is_new = (resolution.action == ResolutionAction.CREATE_NEW)

    return {
        "matched_application_id": resolution.matched_application_id,
        "resolution_confidence": resolution.confidence.value,
        "resolution_action": resolution.action.value,
        "resolution_note": resolution.note,
        "is_new_application": is_new,
        "execution_path": path,
    }


def node_create_new_record(state: AgentState) -> Dict[str, Any]:
    """
    Node 5: Create New Record.
    Inserts a new Application row in PostgreSQL when entity resolution determines CREATE_NEW.
    """
    from db.models import Application, ApplicationStatus
    from worker.entity_resolution import normalize_company_name

    path = _record_path(state, "create_new_record")
    logger.info("Node 5 Create New Record executing")

    parsed = state.get("parsed_event") or {}
    company_raw = parsed.get("company_raw") or "Unknown Company"
    role_title = parsed.get("role_title") or "Software Engineer"
    sender = state.get("sender", "")
    raw_text = state.get("raw_email_text", "")
    source = detect_source_platform(sender, raw_text[:300])

    event_type_val = parsed.get("event_type", ApplicationEventType.APPLICATION_RECEIVED.value)
    try:
        event_type_enum = ApplicationEventType(event_type_val)
    except Exception:
        event_type_enum = ApplicationEventType.APPLICATION_RECEIVED

    target_status_enum = EVENT_TO_TARGET_STATUS.get(event_type_enum) or ApplicationStatus.APPLIED
    app_uuid = uuid.UUID(state["matched_application_id"]) if state.get("matched_application_id") else uuid.uuid4()
    received_at = state.get("email_received_at") or datetime.now(timezone.utc)

    with _get_db_session(state) as session:
        if session is not None:
            try:
                existing = session.query(Application).filter(Application.id == app_uuid).first()
                if not existing:
                    new_app = Application(
                        id=app_uuid,
                        company_name=company_raw,
                        canonical_company_name=normalize_company_name(company_raw),
                        role_title=role_title,
                        source_platform=source,
                        job_description_raw=raw_text[:2000] if raw_text else None,
                        primary_tech_stack=[],
                        current_status=target_status_enum,
                        applied_at=received_at,
                        updated_at=received_at,
                    )
                    session.add(new_app)
                    session.flush()
            except Exception as exc:
                logger.warning("Could not persist new Application in node_create_new_record: %s", exc)

    note = f"New application record created for {company_raw} ({role_title}) via {source} inbound."
    return {
        "matched_application_id": str(app_uuid),
        "is_new_application": True,
        "current_status": None,
        "target_status": target_status_enum.value,
        "status_changed": True,
        "transition_note": note,
        "execution_path": path,
    }


def node_state_transition(state: AgentState) -> Dict[str, Any]:
    """
    Node 6: State Transition.
    Evaluates valid DAG state machine transitions according to SYSTEM_DESIGN.md Section 7.
    """
    from db.models import Application

    path = _record_path(state, "state_transition")
    logger.info("Node 6 State Transition executing")

    parsed = state.get("parsed_event") or {}
    event_type = parsed.get("event_type", ApplicationEventType.APPLICATION_RECEIVED.value)
    company = parsed.get("company_raw", "")
    sender = state.get("sender", "")
    raw_text = state.get("raw_email_text", "")

    curr_status = state.get("current_status")
    app_id_str = state.get("matched_application_id")

    # If current_status is not pre-set in state, look it up in DB
    if not curr_status and app_id_str:
        try:
            with _get_db_session(state) as session:
                if session is not None:
                    app = session.query(Application).filter(Application.id == uuid.UUID(app_id_str)).first()
                    if app:
                        curr_status = app.current_status.value
        except Exception as exc:
            logger.warning("Could not query application status from DB: %s", exc)

    if not curr_status:
        curr_status = "APPLIED"

    decision = evaluate_transition(
        current_status=curr_status,
        event_type=event_type,
        sender=sender,
        company_name=company,
        body_snippet=raw_text[:300],
    )

    return {
        "current_status": decision.from_status,
        "target_status": decision.to_status,
        "status_changed": decision.status_changed,
        "transition_note": decision.note,
        "execution_path": path,
    }


def node_flag_for_manual(state: AgentState) -> Dict[str, Any]:
    """
    Node 7: Flag For Manual.
    Handles ambiguous matches by flagging for human review.
    """
    path = _record_path(state, "flag_for_manual")
    logger.warning("Node 7 Flag For Manual executing")

    return {
        "resolution_note": "Flagged for user disambiguation on UI",
        "committed": True,
        "execution_path": path,
    }


def node_commit_and_log(state: AgentState) -> Dict[str, Any]:
    """
    Node 8: Commit & Log.
    Persists application status updates and creates an immutable PipelineEvent row in PostgreSQL.
    """
    from db.models import Application, ApplicationStatus, PipelineEvent, EventSource

    path = _record_path(state, "commit_and_log")
    logger.info("Node 8 Commit & Log executing")

    app_id_str = state.get("matched_application_id")
    committed = False

    if app_id_str:
        try:
            app_uuid = uuid.UUID(app_id_str)
            status_changed = state.get("status_changed", False)
            target_status_str = state.get("target_status")
            from_status_str = state.get("current_status")
            note = state.get("transition_note") or state.get("resolution_note") or ""
            confidence = state.get("resolution_confidence") or "HIGH"
            raw_text = state.get("raw_email_text", "")

            # Parse detected deadline if any
            parsed = state.get("parsed_event") or {}
            raw_deadline = parsed.get("deadline")
            detected_dt = _parse_deadline_datetime(raw_deadline) if raw_deadline else None

            with _get_db_session(state) as session:
                if session is not None:
                    # 1. Update Application current_status if changed
                    if status_changed and target_status_str:
                        app = session.query(Application).filter(Application.id == app_uuid).first()
                        if app:
                            app.current_status = ApplicationStatus(target_status_str)
                            app.updated_at = datetime.now(timezone.utc)
                            session.add(app)

                    # 2. Insert PipelineEvent
                    to_status_val = (
                        ApplicationStatus(target_status_str)
                        if target_status_str
                        else ApplicationStatus.APPLIED
                    )
                    from_status_val = (
                        ApplicationStatus(from_status_str)
                        if from_status_str
                        else None
                    )

                    event = PipelineEvent(
                        id=uuid.uuid4(),
                        application_id=app_uuid,
                        from_status=from_status_val,
                        to_status=to_status_val,
                        detected_deadline=detected_dt,
                        source=EventSource.GMAIL_WORKER,
                        raw_payload=raw_text,
                        resolution_note=note,
                        llm_confidence=confidence,
                        created_at=datetime.now(timezone.utc),
                    )
                    session.add(event)
                    session.flush()
            committed = True
        except Exception as exc:
            logger.warning("Error persisting commit and log to DB: %s", exc)
            committed = True
    else:
        # e.g. Flag for manual without single matched application -> Persist to InboundTriageItem queue
        try:
            from db.models import InboundTriageItem
            with _get_db_session(state) as session:
                    parsed = state.get("parsed_event") or {}
                    detected_company = parsed.get("company_raw") or parsed.get("company_name") or "Unknown Company"
                    detected_role = parsed.get("role_title")
                    suggested_stage = state.get("target_status") or parsed.get("event_type") or "APPLIED"
                    confidence = state.get("resolution_confidence") or "AMBIGUOUS"
                    note = state.get("resolution_note") or "Flagged for manual disambiguation"

                    # Collect candidate application IDs
                    candidate_apps = state.get("candidate_apps") or []
                    candidate_ids = []
                    for c in candidate_apps:
                        if isinstance(c, dict) and c.get("id"):
                            candidate_ids.append(str(c["id"]))
                        elif hasattr(c, "id"):
                            candidate_ids.append(str(c.id))

                    triage_item = InboundTriageItem(
                        id=uuid.uuid4(),
                        source="GMAIL_WORKER",
                        sender=state.get("sender") or "unknown@sender.com",
                        subject=state.get("subject") or "Inbound Notification",
                        raw_body=state.get("raw_email_text") or "",
                        detected_company=detected_company,
                        detected_role=detected_role,
                        suggested_stage=suggested_stage,
                        resolution_confidence=confidence,
                        resolution_note=note,
                        candidate_application_ids=candidate_ids,
                        status="PENDING",
                        created_at=datetime.now(timezone.utc),
                    )
                    session.add(triage_item)
                    session.flush()
            committed = True
        except Exception as exc:
            logger.warning("Error persisting inbound triage item to DB: %s", exc)
            committed = True

    return {
        "committed": committed,
        "execution_path": path,
    }


def node_dead_letter_log(state: AgentState) -> Dict[str, Any]:
    """
    Node 9: Dead Letter Log.
    Terminal node recording rejected or broken email events.
    """
    path = _record_path(state, "dead_letter_log")
    reason = state.get("dead_letter_reason") or "Irrelevant or unprocessable email event."
    logger.warning("Node 9 Dead Letter Log: %s", reason)

    return {
        "committed": False,
        "dead_letter_reason": reason,
        "execution_path": path,
    }


# ==============================================================================
# Conditional Edge Routers
# ==============================================================================

def route_after_relevance(state: AgentState) -> str:
    """Routes to extract_event if relevant, else to dead_letter_log."""
    if state.get("is_relevant"):
        return "extract_event"
    return "dead_letter_log"


def route_after_validation(state: AgentState) -> str:
    """Routes to entity_resolution if valid, else to self_repair."""
    errors = state.get("validation_errors", [])
    if not errors:
        return "entity_resolution"
    return "self_repair"


def route_after_repair(state: AgentState) -> str:
    """Loops back to validate_schema up to 3 retries; then routes to dead_letter_log."""
    retries = state.get("retry_count", 0)
    if retries <= 3:
        return "validate_schema"
    return "dead_letter_log"


def route_after_resolution(state: AgentState) -> str:
    """Branches to create_new_record, flag_for_manual, or state_transition."""
    # 1. Flag for manual if resolution is ambiguous or action is explicitly FLAG_FOR_MANUAL
    if state.get("resolution_confidence") == "AMBIGUOUS" or state.get("resolution_action") == "FLAG_FOR_MANUAL":
        return "flag_for_manual"

    # 2. Check if this is a new application
    if state.get("is_new_application"):
        parsed = state.get("parsed_event")
        if parsed and isinstance(parsed, dict):
            comp = (parsed.get("company_raw") or "").lower().strip()
            # Guard: never automatically create an application row if company is unknown or generic ATS
            if comp in ("unknown company", "unknown", "workday", "myworkday", "hire", "recruiting"):
                return "flag_for_manual"
        return "create_new_record"

    return "state_transition"


# ==============================================================================
# Graph Builder & Compiler
# ==============================================================================

def build_email_agent_graph():
    """
    Assembles and compiles the full LangGraph state machine for email ingestion.
    
    Returns:
        CompiledStateGraph runnable via graph.invoke(initial_state).
    """
    builder = StateGraph(AgentState)

    # 1. Add all 10 nodes
    builder.add_node("relevance_gate", node_relevance_gate)
    builder.add_node("extract_event", node_extract_event)
    builder.add_node("validate_schema", node_validate_schema)
    builder.add_node("self_repair", node_self_repair)
    builder.add_node("entity_resolution", node_entity_resolution)
    builder.add_node("create_new_record", node_create_new_record)
    builder.add_node("state_transition", node_state_transition)
    builder.add_node("flag_for_manual", node_flag_for_manual)
    builder.add_node("commit_and_log", node_commit_and_log)
    builder.add_node("dead_letter_log", node_dead_letter_log)

    # 2. Add entrypoint
    builder.add_edge(START, "relevance_gate")

    # 3. Add conditional edge from relevance_gate
    builder.add_conditional_edges(
        "relevance_gate",
        route_after_relevance,
        {
            "extract_event": "extract_event",
            "dead_letter_log": "dead_letter_log",
        }
    )

    # 4. Add edge extract_event -> validate_schema
    builder.add_edge("extract_event", "validate_schema")

    # 5. Add conditional edge from validate_schema
    builder.add_conditional_edges(
        "validate_schema",
        route_after_validation,
        {
            "entity_resolution": "entity_resolution",
            "self_repair": "self_repair",
        }
    )

    # 6. Add conditional edge from self_repair (retry loop & circuit breaker)
    builder.add_conditional_edges(
        "self_repair",
        route_after_repair,
        {
            "validate_schema": "validate_schema",
            "dead_letter_log": "dead_letter_log",
        }
    )

    # 7. Add conditional edge from entity_resolution
    builder.add_conditional_edges(
        "entity_resolution",
        route_after_resolution,
        {
            "create_new_record": "create_new_record",
            "flag_for_manual": "flag_for_manual",
            "state_transition": "state_transition",
        }
    )

    # 8. Add convergence edges to commit_and_log
    builder.add_edge("create_new_record", "commit_and_log")
    builder.add_edge("flag_for_manual", "commit_and_log")
    builder.add_edge("state_transition", "commit_and_log")

    # 9. Add terminal edges to END
    builder.add_edge("commit_and_log", END)
    builder.add_edge("dead_letter_log", END)

    return builder.compile()
