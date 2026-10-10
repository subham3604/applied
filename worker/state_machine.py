"""
worker/state_machine.py
=======================
Non-linear Application State Machine DAG for JobTracker.

Implements the transition rules defined in Section 7 of SYSTEM_DESIGN.md:
- APPLIED: [OA_PENDING, INTERVIEW_ROUND, OFFER, REJECTED, WITHDRAWN]
- OA_PENDING: [INTERVIEW_ROUND, OFFER, REJECTED, WITHDRAWN]
- INTERVIEW_ROUND: [INTERVIEW_ROUND, OFFER, REJECTED, WITHDRAWN]
- OFFER: [REJECTED, WITHDRAWN]
- REJECTED: [] (terminal)
- WITHDRAWN: [] (terminal)

Key Features:
- APPLICATION_RECEIVED preserves current status (APPLIED) without regression.
- Repeating INTERVIEW_ROUND (Round 2, 3, etc.) logs new pipeline event without status mutation.
- Rescinded offers (OFFER -> REJECTED) supported.
- Illegal/backward transitions blocked deterministically.
"""

from dataclasses import dataclass
import logging
import re
from typing import Dict, List, Optional, Union

from db.models import ApplicationStatus
from worker.agent_state import ApplicationEventType

logger = logging.getLogger("state_machine")


# ==============================================================================
# Non-linear Valid Transition Graph (SYSTEM_DESIGN.md Section 7)
# ==============================================================================

VALID_TRANSITIONS: Dict[str, List[str]] = {
    "APPLIED": [
        "OA_PENDING",        # standard pipeline
        "INTERVIEW_ROUND",   # company skips OA directly to interview
        "OFFER",             # expedited / referral offer
        "REJECTED",          # immediate rejection
        "WITHDRAWN",         # candidate withdrew
    ],
    "OA_PENDING": [
        "INTERVIEW_ROUND",   # passed OA
        "OFFER",             # direct offer after OA
        "REJECTED",          # failed OA or cut
        "WITHDRAWN",
    ],
    "INTERVIEW_ROUND": [
        "INTERVIEW_ROUND",   # repeating round (Round 2, 3, etc.)
        "OFFER",             # passed interview loop
        "REJECTED",          # rejected after interviews
        "WITHDRAWN",
    ],
    "OFFER": [
        "REJECTED",          # offer rescinded by company
        "WITHDRAWN",         # candidate declines offer
    ],
    "REJECTED": [],          # terminal state
    "WITHDRAWN": [],         # terminal state
}

# Mapping from incoming email event type to target application status
EVENT_TO_TARGET_STATUS: Dict[ApplicationEventType, Optional[ApplicationStatus]] = {
    ApplicationEventType.APPLICATION_RECEIVED: ApplicationStatus.APPLIED,
    ApplicationEventType.OA_RECEIVED: ApplicationStatus.OA_PENDING,
    ApplicationEventType.INTERVIEW_INVITE: ApplicationStatus.INTERVIEW_ROUND,
    ApplicationEventType.OFFER: ApplicationStatus.OFFER,
    ApplicationEventType.REJECTED: ApplicationStatus.REJECTED,
    ApplicationEventType.STATUS_UPDATE: None,  # informative update, status unchanged
}


@dataclass
class TransitionDecision:
    """Represents the outcome of an application state transition evaluation."""
    is_valid: bool
    from_status: str
    to_status: str
    status_changed: bool
    note: str
    is_terminal: bool = False


# ==============================================================================
# Helper Utilities
# ==============================================================================

def detect_source_platform(sender: str = "", body_snippet: str = "") -> str:
    """Identifies the hiring portal or system source from email metadata or text snippets."""
    sender_lower = (sender or "").lower()
    body_lower = (body_snippet or "").lower()

    # Priority 1: Direct sender domain check
    if re.search(r"@(?:[a-z0-9\-]+\.)?naukri(?:\.com)?\b", sender_lower):
        return "Naukri"
    if re.search(r"@(?:[a-z0-9\-]+\.)?linkedin(?:\.com)?\b", sender_lower):
        return "LinkedIn"
    if re.search(r"@(?:[a-z0-9\-]+\.)?indeed(?:\.com)?\b", sender_lower):
        return "Indeed"
    if re.search(r"@(?:[a-z0-9\-]+\.)?(?:wellfound\.com|angel\.co|angellist\.com)\b", sender_lower):
        return "Wellfound"
    if re.search(r"@(?:[a-z0-9\-]+\.)?greenhouse(?:\.io)?\b", sender_lower):
        return "Greenhouse"
    if re.search(r"@(?:[a-z0-9\-]+\.)?lever(?:\.co)?\b", sender_lower):
        return "Lever"
    if re.search(r"@(?:[a-z0-9\-]+\.)?myworkday(?:jobs)?\.com\b", sender_lower):
        return "Workday"
    if re.search(r"@(?:[a-z0-9\-]+\.)?smartrecruiters(?:\.com)?\b", sender_lower):
        return "SmartRecruiters"
    if re.search(r"@(?:[a-z0-9\-]+\.)?ashby(?:hq)?(?:\.com)?\b", sender_lower):
        return "Ashby"

    # Priority 2: Text body signals (avoiding generic social media footer matches)
    combined = f"{sender_lower} {body_lower}"
    if re.search(r"\bnaukri(?:\.com)?\b", combined):
        return "Naukri"
    if re.search(r"\b(?:applied (?:on|via) linkedin|via linkedin|linkedin application|linkedin jobs?|jobs-noreply@linkedin)\b", combined) or "linkedin.com" in sender_lower:
        return "LinkedIn"
    if re.search(r"\bindeed(?:\.com)?\b", combined):
        return "Indeed"
    if re.search(r"\bwellfound\b|\bangel\.co\b|\bangellist\b", combined):
        return "Wellfound"
    if re.search(r"\bgreenhouse(?:\.io)?\b", combined):
        return "Greenhouse"
    if re.search(r"\blever\.co\b|\blever\b", combined):
        return "Lever"
    if re.search(r"\bmyworkday(?:jobs)?\.com\b|\bworkday\b", combined):
        return "Workday"
    if re.search(r"\bsmartrecruiters(?:\.com)?\b", combined):
        return "SmartRecruiters"
    if re.search(r"\bashby(?:hq)?(?:\.com)?\b", combined):
        return "Ashby"
    return "Direct"



# ==============================================================================
# Core Transition Evaluation Engine
# ==============================================================================

def evaluate_transition(
    current_status: Union[str, ApplicationStatus],
    event_type: Union[str, ApplicationEventType],
    sender: str = "",
    company_name: str = "",
    body_snippet: str = "",
) -> TransitionDecision:
    """
    Evaluates whether an incoming event can transition the application state.
    
    Args:
        current_status: Current status of the application record.
        event_type: Parsed event type from incoming email.
        sender: Sender email address for source attribution.
        company_name: Name of the company for audit logging.
        body_snippet: Snippet of email text for context.
        
    Returns:
        TransitionDecision with validated to_status, status_changed flag, and audit note.
    """
    curr_status_str = (
        current_status.value if isinstance(current_status, ApplicationStatus) else str(current_status).upper()
    )
    
    if isinstance(event_type, str):
        try:
            event_type_enum = ApplicationEventType(event_type)
        except ValueError:
            logger.warning("Unrecognized ApplicationEventType string: %s", event_type)
            return TransitionDecision(
                is_valid=False,
                from_status=curr_status_str,
                to_status=curr_status_str,
                status_changed=False,
                note=f"Unrecognized event type '{event_type}'; status unchanged."
            )
    else:
        event_type_enum = event_type

    source = detect_source_platform(sender, body_snippet)
    source_attribution = source if source != "Direct" else (company_name or "company")

    # 1. APPLICATION_RECEIVED: Receipt confirmation preserves APPLIED without regression
    if event_type_enum == ApplicationEventType.APPLICATION_RECEIVED:
        if curr_status_str == ApplicationStatus.APPLIED.value:
            note = f"Application receipt confirmed by {source_attribution}"
            return TransitionDecision(
                is_valid=True,
                from_status=curr_status_str,
                to_status=curr_status_str,
                status_changed=False,
                note=note,
            )
        else:
            note = (
                f"Application receipt confirmed late by {source_attribution} "
                f"after status had progressed to {curr_status_str}; status preserved."
            )
            return TransitionDecision(
                is_valid=True,
                from_status=curr_status_str,
                to_status=curr_status_str,
                status_changed=False,
                note=note,
            )

    # 2. STATUS_UPDATE: Viewed notification or activity ping
    if event_type_enum == ApplicationEventType.STATUS_UPDATE:
        note = f"Application activity update received from {source_attribution}; status unchanged."
        return TransitionDecision(
            is_valid=True,
            from_status=curr_status_str,
            to_status=curr_status_str,
            status_changed=False,
            note=note,
        )

    # 3. Mapped progression events (OA_RECEIVED, INTERVIEW_INVITE, OFFER, REJECTED)
    target_status_enum = EVENT_TO_TARGET_STATUS.get(event_type_enum)
    if not target_status_enum:
        return TransitionDecision(
            is_valid=False,
            from_status=curr_status_str,
            to_status=curr_status_str,
            status_changed=False,
            note=f"No mapped target status for event {event_type_enum.value}."
        )

    target_status_str = target_status_enum.value

    # Subcase: Repeating INTERVIEW_ROUND
    if curr_status_str == ApplicationStatus.INTERVIEW_ROUND.value and target_status_str == ApplicationStatus.INTERVIEW_ROUND.value:
        note = f"Next interview round scheduled via {source_attribution}."
        return TransitionDecision(
            is_valid=True,
            from_status=curr_status_str,
            to_status=target_status_str,
            status_changed=False,  # DB status column remains INTERVIEW_ROUND
            note=note,
        )

    # Subcase: Duplicate event on same status (e.g. repeated OA reminder)
    if curr_status_str == target_status_str:
        note = f"Duplicate {target_status_str} notification from {source_attribution}; state unchanged."
        return TransitionDecision(
            is_valid=True,
            from_status=curr_status_str,
            to_status=target_status_str,
            status_changed=False,
            note=note,
        )

    # Subcase: Valid transition defined in DAG
    allowed_next_states = VALID_TRANSITIONS.get(curr_status_str, [])
    if target_status_str in allowed_next_states:
        is_terminal = (target_status_str in ["REJECTED", "WITHDRAWN"])
        note = f"Pipeline progressed from {curr_status_str} to {target_status_str} via {source_attribution}."
        return TransitionDecision(
            is_valid=True,
            from_status=curr_status_str,
            to_status=target_status_str,
            status_changed=True,
            note=note,
            is_terminal=is_terminal,
        )

    # Subcase: Blocked illegal or backward transition
    warning_note = (
        f"Invalid transition from {curr_status_str} to {target_status_str} "
        f"blocked by state machine DAG."
    )
    logger.warning(warning_note)
    return TransitionDecision(
        is_valid=False,
        from_status=curr_status_str,
        to_status=curr_status_str,
        status_changed=False,
        note=warning_note,
    )
