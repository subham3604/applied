"""
tests/test_day9_langgraph.py
============================
Test suite for Phase 2 Day 9: LangGraph Graph Skeleton & Relevance Gate (Node 0).

Validates:
- Node 0 Relevance Gate filtering:
  - Non-relevant emails (AmbitionBox, OTPs, promotional alerts) route to dead_letter_log.
  - Relevant application emails (Zyntrix, Naukri, LinkedIn) traverse the complete graph to commit_and_log.
- Conditional edge routing:
  - Schema validation failure and self-repair retry loop.
  - Self-repair circuit breaker (>3 retries) routing to dead_letter_log.
  - Entity resolution branching to create_new_record vs state_transition vs flag_for_manual.
- Execution path audit trail recording.
"""

from datetime import datetime, timezone
import pytest

from worker.agent_state import AgentState, ApplicationEventType, ParsedEmailEvent
from worker.graph_agent import (
    build_email_agent_graph,
    route_after_relevance,
    route_after_repair,
    route_after_resolution,
    route_after_validation,
)


@pytest.fixture(scope="module")
def graph():
    """Compiles the LangGraph agent once for the test module."""
    return build_email_agent_graph()


def _make_initial_state(
    raw_email_text: str,
    subject: str = "Application Update",
    sender: str = "recruiting@company.com",
    **kwargs
) -> AgentState:
    """Helper creating a baseline AgentState dictionary."""
    state: AgentState = {
        "raw_email_text": raw_email_text,
        "email_received_at": datetime.now(timezone.utc),
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
        "status_changed": False,
        "committed": False,
        "dead_letter_reason": None,
        "execution_path": [],
    }
    state.update(kwargs)
    return state


# ==============================================================================
# 1. Node 0 Relevance Gate Traversal Tests
# ==============================================================================

def test_node0_ambitionbox_routes_to_dead_letter(graph):
    """
    AmbitionBox review nudges must be classified as NOT relevant at Node 0
    and routed directly to dead_letter_log.
    """
    state = _make_initial_state(
        subject="See what employees have to say about Infosys",
        sender="noreply@ambitionbox.com",
        raw_email_text="Share your interview experience and read company reviews on AmbitionBox.",
    )
    result = graph.invoke(state)

    assert result["is_relevant"] is False
    assert result["committed"] is False
    assert result["dead_letter_reason"] is not None
    # Must only visit relevance_gate and dead_letter_log
    assert result["execution_path"] == ["relevance_gate", "dead_letter_log"]


def test_node0_otp_code_routes_to_dead_letter(graph):
    """
    Greenhouse OTP security codes must be classified as NOT relevant at Node 0
    and routed directly to dead_letter_log.
    """
    state = _make_initial_state(
        subject="Security code for your application",
        sender="no-reply@greenhouse.io",
        raw_email_text="Your security code is 591024. Enter this code within 10 minutes to submit your application.",
    )
    result = graph.invoke(state)

    assert result["is_relevant"] is False
    assert result["committed"] is False
    assert "dead_letter_log" in result["execution_path"]
    assert "extract_event" not in result["execution_path"]
    assert result["execution_path"] == ["relevance_gate", "dead_letter_log"]


def test_node0_promotional_job_alert_routes_to_dead_letter(graph):
    """
    LinkedIn promotional job recommendation digests must be routed to dead_letter_log.
    """
    state = _make_initial_state(
        subject="Jobs for you: Senior Backend Engineer",
        sender="jobalerts-noreply@linkedin.com",
        raw_email_text="Subham, based on your profile, this job is a match! Apply now.",
    )
    result = graph.invoke(state)

    assert result["is_relevant"] is False
    assert result["committed"] is False
    assert result["execution_path"] == ["relevance_gate", "dead_letter_log"]


def test_node0_zyntrix_confirmation_traverses_to_commit(graph):
    """
    Real Zyntrix application confirmation email must pass Node 0 and
    traverse through the complete graph to commit_and_log.
    """
    state = _make_initial_state(
        subject="Application Received - Software Developer | Zyntrix Software Solution Pvt Ltd",
        sender="hr@zyntrixsoftware.com",
        raw_email_text=(
            "Dear Candidate,\n\n"
            "We have received your application for the Software Developer position at Zyntrix Software Solution. "
            "Our team is currently reviewing your resume."
        ),
    )
    result = graph.invoke(state)

    assert result["is_relevant"] is True
    assert result["committed"] is True
    assert result["dead_letter_reason"] is None
    expected_transition = [
        "relevance_gate",
        "extract_event",
        "validate_schema",
        "entity_resolution",
        "state_transition",
        "commit_and_log",
    ]
    expected_create = [
        "relevance_gate",
        "extract_event",
        "validate_schema",
        "entity_resolution",
        "create_new_record",
        "commit_and_log",
    ]
    assert result["execution_path"] in [expected_transition, expected_create]


def test_node0_application_viewed_traverses_to_commit(graph):
    """
    LinkedIn 'your application was viewed' email must be classified as relevant
    and traverse through the full state graph.
    """
    state = _make_initial_state(
        subject="Your application was viewed by Quon Labs",
        sender="jobs-noreply@linkedin.com",
        raw_email_text="Your application for Full Stack Engineer at Quon Labs was viewed by the recruiter.",
    )
    result = graph.invoke(state)

    assert result["is_relevant"] is True
    assert result["committed"] is True
    assert "relevance_gate" in result["execution_path"]
    assert "commit_and_log" in result["execution_path"]


# ==============================================================================
# 2. Conditional Routing Unit Tests
# ==============================================================================

def test_route_after_relevance():
    """Unit test for route_after_relevance conditional logic."""
    assert route_after_relevance({"is_relevant": True}) == "extract_event"
    assert route_after_relevance({"is_relevant": False}) == "dead_letter_log"
    assert route_after_relevance({}) == "dead_letter_log"


def test_route_after_validation():
    """Unit test for route_after_validation conditional logic."""
    assert route_after_validation({"validation_errors": []}) == "entity_resolution"
    assert route_after_validation({"validation_errors": ["Missing company"]}) == "self_repair"


def test_route_after_repair():
    """Unit test for route_after_repair retry loop and circuit breaker."""
    # Under retry limit -> retries validation
    assert route_after_repair({"retry_count": 1}) == "validate_schema"
    assert route_after_repair({"retry_count": 3}) == "validate_schema"
    # Exceeded retry limit -> circuit breaker trips to dead letter log
    assert route_after_repair({"retry_count": 4}) == "dead_letter_log"
    assert route_after_repair({"retry_count": 5}) == "dead_letter_log"


def test_route_after_resolution():
    """Unit test for route_after_resolution branching."""
    assert route_after_resolution({"is_new_application": True}) == "create_new_record"
    assert route_after_resolution({"resolution_confidence": "AMBIGUOUS"}) == "flag_for_manual"
    assert route_after_resolution({"resolution_confidence": "HIGH", "is_new_application": False}) == "state_transition"


# ==============================================================================
# 3. Graph Traversal Branching Integration Tests
# ==============================================================================

def test_graph_self_repair_circuit_breaker(graph):
    """
    When schema validation repeatedly fails beyond 3 retries, the circuit breaker
    must route the email to dead_letter_log.
    """
    # Force pre-injected bad event with retry_count initialized at 3
    state = _make_initial_state(
        subject="Application Received: Backend Engineer",
        sender="careers@phonepe.com",
        raw_email_text="We received your application.",
        parsed_event={"invalid_key": 123},  # Will fail schema validation
        retry_count=3,                      # Next repair attempt will be 4 (>3)
    )
    result = graph.invoke(state)

    assert result["committed"] is False
    assert "dead_letter_log" in result["execution_path"]
    assert "Self-repair circuit breaker tripped" in (result["dead_letter_reason"] or "")


def test_graph_new_application_creation_branch(graph):
    """
    When entity resolution determines this is a new application, the graph
    must route through create_new_record before commit_and_log.
    """
    state = _make_initial_state(
        subject="Application Received: Swiggy SDE-2",
        sender="recruiting@swiggy.in",
        raw_email_text="Thank you for applying to Swiggy.",
        is_new_application=True,
    )
    result = graph.invoke(state)

    assert result["is_relevant"] is True
    assert result["committed"] is True
    assert "create_new_record" in result["execution_path"]
    assert result["matched_application_id"] is not None


def test_graph_ambiguous_resolution_branch(graph):
    """
    When entity resolution confidence is AMBIGUOUS, the graph must route
    through flag_for_manual before commit_and_log.
    """
    state = _make_initial_state(
        subject="Your application status update",
        sender="careers@uber.com",
        raw_email_text="Your application is under review.",
        resolution_confidence="AMBIGUOUS",
    )
    result = graph.invoke(state)

    assert result["is_relevant"] is True
    assert result["committed"] is True
    assert "flag_for_manual" in result["execution_path"]
    assert "Flagged for user disambiguation" in result["resolution_note"]


def test_agent_state_schema_completeness():
    """Verify that ParsedEmailEvent and ApplicationEventType schemas are valid."""
    event = ParsedEmailEvent(
        company_raw="Zyntrix Technologies Pvt Ltd",
        role_title="Software Developer",
        event_type=ApplicationEventType.APPLICATION_RECEIVED,
        deadline=None,
    )
    assert event.company_raw == "Zyntrix Technologies Pvt Ltd"
    assert event.role_title == "Software Developer"
    assert event.event_type == ApplicationEventType.APPLICATION_RECEIVED
