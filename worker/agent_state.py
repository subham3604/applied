"""
worker/agent_state.py
=====================
State definitions and event schemas for the LangGraph autonomous email agent.

Defines:
- ApplicationEventType: Standard enum of career pipeline email event types.
- ParsedEmailEvent: Pydantic schema for extracted email entities.
- AgentState: TypedDict defining the shared state flowing across all LangGraph nodes.
"""

from datetime import datetime
from enum import Enum
from typing import Any, List, Optional, TypedDict

from pydantic import BaseModel, Field


# ==============================================================================
# Email Event Enums and Pydantic Schemas
# ==============================================================================

class ApplicationEventType(str, Enum):
    """Canonical classification of career pipeline email events."""
    APPLICATION_RECEIVED = "APPLICATION_RECEIVED"  # Receipt confirmation (no status change)
    OA_RECEIVED = "OA_RECEIVED"                    # Online coding assessment / test invite
    INTERVIEW_INVITE = "INTERVIEW_INVITE"          # Screening / technical / behavioral round
    OFFER = "OFFER"                                # Offer letter or compensation package
    REJECTED = "REJECTED"                          # Application rejection notification
    STATUS_UPDATE = "STATUS_UPDATE"                # Recruiter viewed / activity update


class ParsedEmailEvent(BaseModel):
    """Structured event extracted from job-related email body."""
    company_raw: str = Field(
        ...,
        description="Company name as explicitly stated in the email text."
    )
    role_title: Optional[str] = Field(
        default=None,
        description="Explicit job title if mentioned; None if absent (never hallucinated)."
    )
    event_type: ApplicationEventType = Field(
        ...,
        description="Type of application progression event."
    )
    deadline: Optional[str] = Field(
        default=None,
        description="ISO 8601 deadline date/time if explicitly mentioned in email."
    )


# ==============================================================================
# LangGraph Agent State
# ==============================================================================

class AgentState(TypedDict):
    """
    Shared mutable state passed across all nodes in the LangGraph state machine.
    Conforms strictly to Section 5 of SYSTEM_DESIGN.md.
    """
    # Ingestion Metadata
    raw_email_text: str
    email_received_at: datetime
    sender: str
    subject: str

    # Node 0: Relevance Gate
    is_relevant: bool
    relevance_category: Optional[str]
    relevance_reason: Optional[str]

    # Node 1 & 2: Extraction & Schema Validation
    parsed_event: Optional[dict]
    validation_errors: List[str]
    retry_count: int

    # Node 3: Entity Resolution
    matched_application_id: Optional[str]
    resolution_confidence: str  # "HIGH" | "LOW" | "AMBIGUOUS" | "NONE"
    resolution_note: str
    is_new_application: bool
    candidate_apps: Optional[List[Any]]

    # Node 6 & 8: State Machine & Commit
    current_status: Optional[str]
    target_status: Optional[str]
    transition_note: Optional[str]
    status_changed: bool
    committed: bool
    db_session: Optional[Any]

    # Error Handling & Dead Letter Logging
    dead_letter_reason: Optional[str]
    execution_path: List[str]  # Audit trail recording node execution order
