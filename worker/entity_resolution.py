"""
worker/entity_resolution.py
===========================
Multi-Level Entity Resolution Engine for the JobTracker autonomous worker.

Maps inbound emails (which may contain legal corporate entities, holding companies,
subsidiaries, or missing roles) to the correct Application record in the database.

Fallback Chain (from Section 6 of SYSTEM_DESIGN.md):
- Level 1: Normalized company name + Levenshtein fuzzy string match (ratio >= 0.85).
- Level 2: LLM Arbitration for holding companies, subsidiaries, or multiple candidate roles.
- Level 3: Date Proximity Fallback (<24h -> LOW confidence; >=24h -> AMBIGUOUS).
"""

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, List, Optional, Tuple

import Levenshtein
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

logger = logging.getLogger("entity_resolution")

# Threshold for fuzzy string matching
FUZZY_RATIO_THRESHOLD = 0.85
ROLE_FUZZY_THRESHOLD = 0.70


# ==============================================================================
# Enums and Schemas
# ==============================================================================

class ResolutionConfidence(str, Enum):
    HIGH = "HIGH"
    LOW = "LOW"
    AMBIGUOUS = "AMBIGUOUS"
    NONE = "NONE"


class ResolutionAction(str, Enum):
    UPDATE = "UPDATE"
    CREATE_NEW = "CREATE_NEW"
    FLAG_FOR_MANUAL = "FLAG_FOR_MANUAL"


class ApplicationCandidate(BaseModel):
    """Encapsulates application details needed for entity matching."""
    id: str = Field(..., description="Unique application UUID string.")
    company_name: str
    canonical_company_name: Optional[str] = None
    role_title: str
    applied_at: datetime
    current_status: str = "APPLIED"


class ResolutionResult(BaseModel):
    """Complete outcome of the entity resolution process."""
    action: ResolutionAction
    matched_application_id: Optional[str] = None
    confidence: ResolutionConfidence
    note: str = ""
    candidate: Optional[ApplicationCandidate] = None


class LLMArbitrationDecision(BaseModel):
    """Structured decision returned by LLM arbitration."""
    decision: str = Field(
        ...,
        description="Either the matching application_id UUID string, 'NEW', or 'AMBIGUOUS'."
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason: str = Field(..., description="Concise justification for the decision.")


# ==============================================================================
# Level 1: Company Normalization & Fuzzy String Matching
# ==============================================================================

def normalize_company_name(name: str) -> str:
    """
    Normalizes corporate and brand names by stripping legal entity qualifiers,
    punctuation, parentheticals, and generic corporate tokens.
    
    Examples:
        'Bundl Technologies Pvt Ltd' -> 'bundl'
        'Zomato Media Private Limited' -> 'zomato'
        'Swiggy India Pvt. Ltd.' -> 'swiggy'
    """
    if not name:
        return ""

    normalized = name.lower().strip()

    # Remove content in parentheses e.g. "Google (Alphabet)" -> "Google"
    normalized = re.sub(r"\(.*?\)", "", normalized).strip()

    # Normalize punctuation and symbols to whitespace
    normalized = re.sub(r"[,\.\-_/\\|]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    # Suffixes and legal entities to strip (sorted descending by length)
    suffixes = [
        "private limited", "pvt ltd", "pvt", "ltd",
        "technologies", "technology", "tech", "solutions", "services",
        "corporation", "corp", "incorporated", "inc", "enterprises",
        "communications", "communication",
        "holdings", "holding", "group", "media", "software", "systems",
        "india", "global", "international", "labs", "lab"
    ]
    suffixes.sort(key=len, reverse=True)

    for suffix in suffixes:
        pattern = rf"\b{re.escape(suffix)}\b"
        normalized = re.sub(pattern, "", normalized).strip()

    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized or name.lower().strip()


def fuzzy_match(query: str, candidates: List[str]) -> Tuple[Optional[str], float]:
    """
    Calculates Levenshtein similarity ratio between query and candidate strings.
    
    Returns:
        tuple of (best_candidate, best_score)
    """
    if not query or not candidates:
        return None, 0.0

    q_norm = normalize_company_name(query)
    best_cand = None
    best_score = 0.0

    for cand in candidates:
        cand_norm = normalize_company_name(cand)
        # 1. Exact normalized match has score 1.0
        if q_norm and q_norm == cand_norm:
            return cand, 1.0

        # 2. Levenshtein ratio
        score = Levenshtein.ratio(q_norm, cand_norm)
        if score > best_score:
            best_score = score
            best_cand = cand

    return best_cand, best_score


def role_disambiguate(
    role_raw: Optional[str],
    candidates: List[ApplicationCandidate],
    threshold: float = ROLE_FUZZY_THRESHOLD,
) -> Tuple[Optional[ApplicationCandidate], float]:
    """
    Fuzzy matches raw role against candidates' role titles.
    Requires clear separation: if multiple candidates have identical or near-identical
    top scores, returns (None, score) to indicate ambiguity.
    """
    if not role_raw or not candidates:
        return None, 0.0

    role_clean = role_raw.lower().strip()
    scored_candidates = []

    for cand in candidates:
        cand_role = cand.role_title.lower().strip()
        if role_clean == cand_role:
            score = 1.0
        elif role_clean in cand_role or cand_role in role_clean:
            score = 0.95
        else:
            score = Levenshtein.ratio(role_clean, cand_role)
        scored_candidates.append((score, cand))

    scored_candidates.sort(key=lambda x: x[0], reverse=True)
    best_score, best_cand = scored_candidates[0]

    if best_score < threshold:
        return None, best_score

    # Check for ambiguity: if second candidate has virtually the same score
    if len(scored_candidates) > 1:
        second_score = scored_candidates[1][0]
        if (best_score - second_score) < 0.10 and second_score >= threshold:
            # Ambiguous! Both candidates match role equally
            return None, best_score

    return best_cand, best_score


# ==============================================================================
# Level 2: LLM Corporate Entity & Multi-Role Arbitration
# ==============================================================================

DISAMBIGUATION_PROMPT = """Multiple active job applications exist in the tracker database.
Determine which existing application this incoming email corresponds to, or whether it is a new application.

Email Data:
  Company mentioned: "{company_raw}"
  Role mentioned: "{role_raw}"

Active Applications List:
{applications_list}

RULES:
1. Indian Tech Corporate Entities: Recognize legal corporate identities (e.g. 'Bundl Technologies Pvt Ltd' is the legal operating company of 'Swiggy', 'Zomato Media Private Limited' is 'Zomato', 'One97 Communications' is 'Paytm').
2. Matching:
   - If the email belongs to one of the active applications, return that exact application_id.
   - If the email is clearly for a new application not in the list, return "NEW".
   - If multiple roles exist at the company and the email lacks sufficient detail to determine which one with certainty, return "AMBIGUOUS".
3. Anti-Hallucination: Do NOT guess or fabricate application IDs. If uncertain, you MUST return "AMBIGUOUS".
"""

# Common Indian tech legal entity alias registry (for fast deterministic & offline matching)
CORPORATE_ENTITY_ALIASES = {
    "bundl": "swiggy",
    "bundl technologies": "swiggy",
    "zomato media": "zomato",
    "one97": "paytm",
    "one97 communications": "paytm",
    "alphabet": "google",
    "meta": "facebook",
    "walmart global tech": "walmart",
    "quon": "quon labs",
}


def _get_instructor_client():
    """Initializes Instructor client if OpenAI API key is configured."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip().strip('"\'')
    if not api_key or api_key.startswith("sk-proj-placeholder"):
        return None
    try:
        import instructor
        from openai import OpenAI
        return instructor.from_openai(OpenAI(api_key=api_key))
    except Exception as exc:
        logger.warning("Instructor client could not be loaded: %s", exc)
        return None


def _heuristic_arbitrate(
    company_raw: str,
    role_raw: Optional[str],
    candidates: List[ApplicationCandidate],
) -> Tuple[str, str]:
    """
    Deterministic rule-based arbitration used for offline testing or when OpenAI is unavailable.
    """
    comp_norm = normalize_company_name(company_raw)

    # 1. Check corporate alias dictionary
    target_brand = CORPORATE_ENTITY_ALIASES.get(comp_norm) or CORPORATE_ENTITY_ALIASES.get(company_raw.lower().strip())
    if target_brand:
        matching_by_alias = [
            c for c in candidates
            if normalize_company_name(c.company_name) == target_brand
            or (c.canonical_company_name and normalize_company_name(c.canonical_company_name) == target_brand)
        ]
        if len(matching_by_alias) == 1:
            return matching_by_alias[0].id, f"Resolved via corporate entity alias: '{company_raw}' -> '{matching_by_alias[0].company_name}'"
        elif len(matching_by_alias) > 1 and role_raw:
            best_cand, score = role_disambiguate(role_raw, matching_by_alias)
            if best_cand:
                return best_cand.id, f"Resolved via alias and role match ({score:.2f})"
            return "AMBIGUOUS", "Multiple roles at aliased company; role could not be disambiguated"

    # 2. Check if candidate companies match normalized
    matching_cands = [
        c for c in candidates
        if normalize_company_name(c.company_name) == comp_norm
        or (c.canonical_company_name and normalize_company_name(c.canonical_company_name) == comp_norm)
    ]
    if len(matching_cands) == 1:
        return matching_cands[0].id, "Matched single candidate"
    elif len(matching_cands) > 1:
        if role_raw:
            best_cand, score = role_disambiguate(role_raw, matching_cands)
            if best_cand:
                return best_cand.id, f"Disambiguated by role ({score:.2f})"
        return "AMBIGUOUS", "Multiple applications found for company without distinctive role details"

    return "NEW", "No existing applications match company"


def llm_arbitrate(
    company_raw: str,
    role_raw: Optional[str],
    candidates: List[ApplicationCandidate],
    client=None,
    model: str = "gpt-4o-mini",
    force_fallback: bool = False,
) -> Tuple[str, str]:
    """
    Level 2 LLM Disambiguation Call.
    
    Returns:
        tuple (decision, reason) where decision is an application_id, 'NEW', or 'AMBIGUOUS'.
    """
    if not candidates:
        return "NEW", "No active candidates to arbitrate against."

    if force_fallback:
        return _heuristic_arbitrate(company_raw, role_raw, candidates)

    instructor_client = client or _get_instructor_client()
    if instructor_client is None:
        return _heuristic_arbitrate(company_raw, role_raw, candidates)

    apps_formatted = "\n".join([
        f"- ID: {c.id} | Company: {c.company_name} | Role: {c.role_title} | Applied: {c.applied_at.strftime('%Y-%m-%d %H:%M')}"
        for c in candidates
    ])

    user_prompt = DISAMBIGUATION_PROMPT.format(
        company_raw=company_raw,
        role_raw=role_raw or "None explicitly stated",
        applications_list=apps_formatted,
    )

    try:
        decision_obj = instructor_client.chat.completions.create(
            model=model,
            response_model=LLMArbitrationDecision,
            messages=[
                {"role": "system", "content": "You are a precise ATS database disambiguation engine. Return only structured decisions."},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
        )

        dec = decision_obj.decision.strip()
        # Verify valid application ID was returned or recognized keyword
        valid_ids = {c.id for c in candidates}
        if dec in valid_ids or dec in ["NEW", "AMBIGUOUS"]:
            return dec, decision_obj.reason

        # Anti-hallucination guard: if model returned an unrecognized ID, force AMBIGUOUS
        logger.warning("LLM returned non-existent application_id '%s'; forcing AMBIGUOUS.", dec)
        return "AMBIGUOUS", "Model returned unrecognized ID; defaulted to AMBIGUOUS for safety."
    except Exception as exc:
        logger.warning("LLM arbitration failed (%s); falling back to heuristic.", exc)
        return _heuristic_arbitrate(company_raw, role_raw, candidates)


# ==============================================================================
# Level 3: Date Proximity Fallback (Role Title Absent)
# ==============================================================================

def date_proximity_match(
    email_received_at: datetime,
    candidates: List[ApplicationCandidate],
    threshold_hours: float = 24.0,
) -> Tuple[Optional[ApplicationCandidate], ResolutionConfidence, str]:
    """
    Matches role-less emails to the closest active application within threshold_hours.
    """
    if not candidates:
        return None, ResolutionConfidence.NONE, "No candidates available for date proximity"

    # Ensure timezone awareness
    if email_received_at.tzinfo is None:
        email_received_at = email_received_at.replace(tzinfo=timezone.utc)

    def _get_gap(app: ApplicationCandidate) -> float:
        app_dt = app.applied_at
        if app_dt.tzinfo is None:
            app_dt = app_dt.replace(tzinfo=timezone.utc)
        return abs((email_received_at - app_dt).total_seconds())

    closest = min(candidates, key=_get_gap)
    gap_seconds = _get_gap(closest)
    threshold_seconds = threshold_hours * 3600.0

    if gap_seconds < threshold_seconds:
        hours = gap_seconds / 3600.0
        return (
            closest,
            ResolutionConfidence.LOW,
            f"Role absent from email; matched by date proximity ({hours:.1f}h gap < {threshold_hours}h)"
        )

    days = gap_seconds / 86400.0
    return (
        None,
        ResolutionConfidence.AMBIGUOUS,
        f"Role absent from email; closest match gap ({days:.1f} days) exceeds {threshold_hours}h threshold"
    )


# ==============================================================================
# Master Entity Resolution Pipeline
# ==============================================================================

def resolve_entity(
    company_raw: str,
    role_title: Optional[str],
    email_received_at: datetime,
    candidate_apps: List[ApplicationCandidate],
    client=None,
    force_fallback: bool = False,
) -> ResolutionResult:
    """
    Executes the complete entity resolution fallback chain (Section 6 of SYSTEM_DESIGN.md).
    
    Returns:
        ResolutionResult with action (UPDATE, CREATE_NEW, or FLAG_FOR_MANUAL),
        matched_application_id, confidence, note, and matched candidate.
    """
    if not company_raw or not company_raw.strip():
        return ResolutionResult(
            action=ResolutionAction.CREATE_NEW,
            confidence=ResolutionConfidence.NONE,
            note="No company provided; creating new record.",
        )

    comp_norm = normalize_company_name(company_raw)
    target_alias = CORPORATE_ENTITY_ALIASES.get(comp_norm) or CORPORATE_ENTITY_ALIASES.get(company_raw.lower().strip())

    # --------------------------------------------------------------------------
    # Step 1: Filter candidates by company (Normalized exact, alias, or Levenshtein >= 0.85)
    # --------------------------------------------------------------------------
    company_matches: List[ApplicationCandidate] = []
    for cand in candidate_apps:
        cand_norm = normalize_company_name(cand.company_name)
        canon_norm = normalize_company_name(cand.canonical_company_name or "")

        if comp_norm in [cand_norm, canon_norm]:
            company_matches.append(cand)
        elif target_alias and target_alias in [cand_norm, canon_norm]:
            company_matches.append(cand)
        elif Levenshtein.ratio(comp_norm, cand_norm) >= FUZZY_RATIO_THRESHOLD:
            company_matches.append(cand)
        elif canon_norm and Levenshtein.ratio(comp_norm, canon_norm) >= FUZZY_RATIO_THRESHOLD:
            company_matches.append(cand)

    # --------------------------------------------------------------------------
    # Case A: 0 Company Matches (Check LLM arbitration for holding companies)
    # --------------------------------------------------------------------------
    if len(company_matches) == 0:
        if not candidate_apps:
            return ResolutionResult(
                action=ResolutionAction.CREATE_NEW,
                confidence=ResolutionConfidence.HIGH,
                note="No existing applications; create new record.",
            )

        # Trigger LLM arbitration across all active applications (e.g. Bundl -> Swiggy)
        decision, reason = llm_arbitrate(
            company_raw=company_raw,
            role_raw=role_title,
            candidates=candidate_apps,
            client=client,
            force_fallback=force_fallback,
        )

        if decision == "NEW":
            return ResolutionResult(
                action=ResolutionAction.CREATE_NEW,
                confidence=ResolutionConfidence.HIGH,
                note=reason,
            )
        elif decision == "AMBIGUOUS":
            return ResolutionResult(
                action=ResolutionAction.FLAG_FOR_MANUAL,
                confidence=ResolutionConfidence.AMBIGUOUS,
                note=reason,
            )
        else:
            # Matched specific application_id
            matched_cand = next((c for c in candidate_apps if c.id == decision), None)
            return ResolutionResult(
                action=ResolutionAction.UPDATE,
                matched_application_id=decision,
                confidence=ResolutionConfidence.HIGH,
                note=f"Resolved via LLM arbitration: {reason}",
                candidate=matched_cand,
            )

    # --------------------------------------------------------------------------
    # Case B: Exactly 1 Company Match
    # --------------------------------------------------------------------------
    if len(company_matches) == 1:
        cand = company_matches[0]
        # If role is provided, verify it doesn't clearly conflict with a different role
        if role_title:
            _, score = role_disambiguate(role_title, [cand])
            # If role is completely different, check with LLM if this is a new application at same company
            if score < 0.35 and len(role_title.split()) > 1:
                decision, reason = llm_arbitrate(
                    company_raw=company_raw,
                    role_raw=role_title,
                    candidates=[cand],
                    client=client,
                    force_fallback=force_fallback,
                )
                if decision == "NEW":
                    return ResolutionResult(
                        action=ResolutionAction.CREATE_NEW,
                        confidence=ResolutionConfidence.HIGH,
                        note="Different role detected at same company; create new record.",
                    )

        return ResolutionResult(
            action=ResolutionAction.UPDATE,
            matched_application_id=cand.id,
            confidence=ResolutionConfidence.HIGH,
            note=f"Single active application matched for company '{cand.company_name}'",
            candidate=cand,
        )

    # --------------------------------------------------------------------------
    # Case C: N Company Matches (Multiple roles at same company)
    # --------------------------------------------------------------------------
    # Sub-case C1: Role Title is known
    if role_title:
        matched_cand, score = role_disambiguate(role_title, company_matches)
        if matched_cand and score >= 0.75:
            return ResolutionResult(
                action=ResolutionAction.UPDATE,
                matched_application_id=matched_cand.id,
                confidence=ResolutionConfidence.HIGH,
                note=f"Role fuzzy matched '{matched_cand.role_title}' (similarity={score:.2f})",
                candidate=matched_cand,
            )

        # Role fuzzy match was below threshold or ambiguous; invoke LLM arbitration
        decision, reason = llm_arbitrate(
            company_raw=company_raw,
            role_raw=role_title,
            candidates=company_matches,
            client=client,
            force_fallback=force_fallback,
        )
        if decision == "NEW":
            return ResolutionResult(
                action=ResolutionAction.CREATE_NEW,
                confidence=ResolutionConfidence.HIGH,
                note=f"New role at existing company: {reason}",
            )
        elif decision == "AMBIGUOUS":
            return ResolutionResult(
                action=ResolutionAction.FLAG_FOR_MANUAL,
                confidence=ResolutionConfidence.AMBIGUOUS,
                note=f"Ambiguous role resolution: {reason}",
            )
        else:
            matched = next((c for c in company_matches if c.id == decision), None)
            return ResolutionResult(
                action=ResolutionAction.UPDATE,
                matched_application_id=decision,
                confidence=ResolutionConfidence.HIGH,
                note=f"Disambiguated via LLM: {reason}",
                candidate=matched,
            )

    # Sub-case C2: Role Title is None (Email omitted the role)
    closest_cand, conf, reason = date_proximity_match(
        email_received_at=email_received_at,
        candidates=company_matches,
        threshold_hours=24.0,
    )

    if conf == ResolutionConfidence.LOW and closest_cand:
        return ResolutionResult(
            action=ResolutionAction.UPDATE,
            matched_application_id=closest_cand.id,
            confidence=ResolutionConfidence.LOW,
            note=reason,
            candidate=closest_cand,
        )

    return ResolutionResult(
        action=ResolutionAction.FLAG_FOR_MANUAL,
        confidence=ResolutionConfidence.AMBIGUOUS,
        note=reason,
    )
