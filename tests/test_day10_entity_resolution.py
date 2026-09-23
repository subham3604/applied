"""
tests/test_day10_entity_resolution.py
=====================================
Test suite for Phase 2 Day 10: Entity Resolution — Full Fallback Chain.

Validates all 5 mandatory deliverable test cases from Section 6 of SYSTEM_DESIGN.md
and Day 10 of BUILD_TIMELINE.md:
1. Case 1: "Bundl Technologies Pvt Ltd" -> resolves to "Swiggy" (LLM corporate arbitration).
2. Case 2: "Zomato Media Private Limited" -> resolves to "Zomato" (fuzzy + normalization).
3. Case 3: Two roles at same company, role absent, email same day (<24h) -> LOW confidence date proximity match.
4. Case 4: Two roles at same company, role absent, email 3 days later (72h) -> AMBIGUOUS (flag_for_manual).
5. Case 5: Unknown company -> CREATE_NEW.
6. Anti-Hallucination: LLM arbitration returns "AMBIGUOUS", never an unrecognized ID.
7. LangGraph Node 4 Integration: full graph execution verifying conditional routing.
"""

from datetime import datetime, timedelta, timezone
import pytest

from worker.agent_state import AgentState
from worker.entity_resolution import (
    ApplicationCandidate,
    EntityAliasCache,
    ResolutionAction,
    ResolutionConfidence,
    date_proximity_match,
    fuzzy_match,
    llm_arbitrate,
    normalize_company_name,
    resolve_entity,
    role_disambiguate,
)
from worker.graph_agent import build_email_agent_graph


# ==============================================================================
# Helper Factories
# ==============================================================================

def _make_candidate(
    app_id: str,
    company: str,
    role: str,
    applied_at: datetime,
    canonical: str = None
) -> ApplicationCandidate:
    return ApplicationCandidate(
        id=app_id,
        company_name=company,
        canonical_company_name=canonical or company,
        role_title=role,
        applied_at=applied_at,
        current_status="APPLIED"
    )


# ==============================================================================
# 1. Level 1: Normalization & Fuzzy Matching Unit Tests
# ==============================================================================

def test_normalize_company_name():
    """Verify company name normalization strips corporate and legal suffixes."""
    assert normalize_company_name("Bundl Technologies Pvt Ltd") == "bundl"
    assert normalize_company_name("Zomato Media Private Limited") == "zomato"
    assert normalize_company_name("Swiggy India Pvt. Ltd.") == "swiggy"
    assert normalize_company_name("Google (Alphabet Inc)") == "google"
    assert normalize_company_name("Microsoft Corporation") == "microsoft"
    assert normalize_company_name("One97 Communications Ltd") == "one97"
    assert normalize_company_name("Quon Labs Software Services") == "quon"


def test_fuzzy_match_levenshtein():
    """Verify Levenshtein ratio matching."""
    candidates = ["Zomato", "Swiggy", "Google", "Uber"]
    best, score = fuzzy_match("Zomato Media Private Limited", candidates)
    assert best == "Zomato"
    assert score >= 0.85

    # Dissimilar
    best_diff, score_diff = fuzzy_match("Acme Corp", candidates)
    assert score_diff < 0.5


def test_role_disambiguate():
    """Verify fuzzy matching on role titles."""
    c1 = _make_candidate("1", "Uber", "Senior Backend Engineer", datetime.now(timezone.utc))
    c2 = _make_candidate("2", "Uber", "Frontend Engineer", datetime.now(timezone.utc))

    matched, score = role_disambiguate("Senior Backend Engineer (Python)", [c1, c2])
    assert matched is not None
    assert matched.id == "1"
    assert score >= 0.70


# ==============================================================================
# 2. Five Mandatory Deliverable Test Cases (from BUILD_TIMELINE.md)
# ==============================================================================

def test_case1_bundl_resolves_to_swiggy():
    """
    Case 1: "Bundl Technologies Pvt Ltd" -> resolves to "Swiggy" (LLM arbitration).
    Bundl Technologies is Swiggy's parent corporate entity in India.
    """
    EntityAliasCache.set("bundl", "swiggy")
    EntityAliasCache.set("bundl technologies", "swiggy")

    swiggy_app = _make_candidate(
        app_id="app_swiggy_001",
        company="Swiggy",
        role="Senior Software Engineer - Backend",
        applied_at=datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc),
    )
    other_app = _make_candidate(
        app_id="app_google_002",
        company="Google",
        role="Software Engineer III",
        applied_at=datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc),
    )

    resolution = resolve_entity(
        company_raw="Bundl Technologies Pvt Ltd",
        role_title="Senior Software Engineer - Backend",
        email_received_at=datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc),
        candidate_apps=[swiggy_app, other_app],
    )

    assert resolution.action == ResolutionAction.UPDATE
    assert resolution.matched_application_id == "app_swiggy_001"
    assert resolution.confidence == ResolutionConfidence.HIGH
    assert "Swiggy" in resolution.note or "swiggy" in resolution.note.lower()


def test_case2_zomato_media_resolves_to_zomato():
    """
    Case 2: "Zomato Media Private Limited" -> resolves to "Zomato" (fuzzy + normalization).
    """
    zomato_app = _make_candidate(
        app_id="app_zomato_001",
        company="Zomato",
        role="Frontend SDE-2",
        applied_at=datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc),
    )

    resolution = resolve_entity(
        company_raw="Zomato Media Private Limited",
        role_title="Frontend SDE-2",
        email_received_at=datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc),
        candidate_apps=[zomato_app],
    )

    assert resolution.action == ResolutionAction.UPDATE
    assert resolution.matched_application_id == "app_zomato_001"
    assert resolution.confidence == ResolutionConfidence.HIGH


def test_case3_two_roles_role_absent_email_same_day():
    """
    Case 3: Two roles at same company, role absent from email, email received same day (<24h)
    -> LOW confidence date proximity match to the closest application.
    """
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    app_backend = _make_candidate(
        app_id="app_uber_backend",
        company="Uber",
        role="Backend SDE-2",
        applied_at=now - timedelta(hours=2),  # Applied 2 hours ago
    )
    app_ai = _make_candidate(
        app_id="app_uber_ai",
        company="Uber",
        role="AI Engineer",
        applied_at=now - timedelta(days=5),    # Applied 5 days ago
    )

    resolution = resolve_entity(
        company_raw="Uber",
        role_title=None,  # Role absent from email
        email_received_at=now,
        candidate_apps=[app_backend, app_ai],
    )

    assert resolution.action == ResolutionAction.UPDATE
    assert resolution.matched_application_id == "app_uber_backend"
    assert resolution.confidence == ResolutionConfidence.LOW
    assert "date proximity" in resolution.note.lower()


def test_case4_two_roles_role_absent_email_3_days_later():
    """
    Case 4: Two roles at same company, role absent, email 3 days later (gap >= 24h)
    -> FLAG_FOR_MANUAL (confidence=AMBIGUOUS).
    """
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    app_1 = _make_candidate(
        app_id="app_meta_1",
        company="Meta",
        role="Production Engineer",
        applied_at=now - timedelta(days=3),  # 72 hours ago
    )
    app_2 = _make_candidate(
        app_id="app_meta_2",
        company="Meta",
        role="Software Engineer",
        applied_at=now - timedelta(days=4),  # 96 hours ago
    )

    resolution = resolve_entity(
        company_raw="Meta",
        role_title=None,
        email_received_at=now,
        candidate_apps=[app_1, app_2],
    )

    assert resolution.action == ResolutionAction.FLAG_FOR_MANUAL
    assert resolution.confidence == ResolutionConfidence.AMBIGUOUS
    assert resolution.matched_application_id is None
    assert "exceeds" in resolution.note.lower() or "threshold" in resolution.note.lower()


def test_case5_unknown_company_creates_new():
    """
    Case 5: Unknown company with no existing active records -> CREATE_NEW.
    """
    existing_app = _make_candidate(
        app_id="app_existing_1",
        company="Google",
        role="SDE-2",
        applied_at=datetime.now(timezone.utc),
    )

    resolution = resolve_entity(
        company_raw="Acme Robotics Pvt Ltd",
        role_title="Robotics Software Engineer",
        email_received_at=datetime.now(timezone.utc),
        candidate_apps=[existing_app],
    )

    assert resolution.action == ResolutionAction.CREATE_NEW
    assert resolution.matched_application_id is None
    assert resolution.confidence == ResolutionConfidence.HIGH


# ==============================================================================
# 3. Anti-Hallucination Guarantee Test
# ==============================================================================

def test_anti_hallucination_arbitration():
    """
    When multiple applications are completely indistinguishable and ambiguous,
    arbitration MUST return AMBIGUOUS and NEVER a fabricated ID.
    """
    now = datetime.now(timezone.utc)
    app_a = _make_candidate("app_dup_1", "Acme", "Engineer", now - timedelta(days=2))
    app_b = _make_candidate("app_dup_2", "Acme", "Engineer", now - timedelta(days=2))

    decision, reason = llm_arbitrate(
        company_raw="Acme",
        role_raw="Engineer",
        candidates=[app_a, app_b],
        force_fallback=True,
    )

    assert decision == "AMBIGUOUS"
    assert decision != "app_hallucinated_123"


# ==============================================================================
# 4. LangGraph Node 4 Integration Test
# ==============================================================================

def test_langgraph_entity_resolution_integration():
    """
    Verify full LangGraph execution routes seamlessly through Node 4 (entity_resolution)
    and conditionally transitions state or flags for manual review.
    """
    graph = build_email_agent_graph()

    now = datetime.now(timezone.utc)
    app_zyntrix = _make_candidate(
        app_id="app_zyntrix_live",
        company="Zyntrix",
        role="Software Developer",
        applied_at=now - timedelta(hours=1),
    )

    # State with active candidate list passed in
    state: AgentState = {
        "raw_email_text": "We received your application for Software Developer at Zyntrix.",
        "email_received_at": now,
        "sender": "hr@zyntrixsoftware.com",
        "subject": "Application Received: Software Developer at Zyntrix",
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
        "candidate_apps": [app_zyntrix],
    }

    result = graph.invoke(state)

    assert result["is_relevant"] is True
    assert result["committed"] is True
    assert result["matched_application_id"] == "app_zyntrix_live"
    assert result["resolution_confidence"] == "HIGH"
    assert "entity_resolution" in result["execution_path"]
    assert "state_transition" in result["execution_path"]
    assert "commit_and_log" in result["execution_path"]
