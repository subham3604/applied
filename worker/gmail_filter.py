"""
worker/gmail_filter.py
======================
Two-Layer Email Ingestion Filter for the JobTracker autonomous worker.

Layer 1: Gmail Query Construction & In-Memory Subject/Header Pre-Filtering (Recall).
Layer 2: LLM Relevance Gate Intent Classification (Precision).
"""

import logging
import os
import re
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

logger = logging.getLogger("gmail_filter")

# ==============================================================================
# Filter Constants (from SYSTEM_DESIGN.md Section 4)
# ==============================================================================

POSITIVE_SUBJECT_TERMS = [
    '"application received"',
    '"thank you for applying"',
    '"thank you for your application"',
    '"your application"',
    '"we have received your application"',
    '"keep track of your application"',
    '"you applied for 1 job"',  # Naukri single-application summary
    "interview",
    "assessment",
    '"offer letter"',
    '"next steps"',
]

NEGATIVE_SUBJECT_TERMS = [
    '"apply now"',
    '"invited to apply"',
    '"is a match"',
    '"job alert"',
    '"jobs for you"',
    '"saved job"',
    '"recommended for you"',
    '"perfect match"',
    '"see what employees have to say"',  # AmbitionBox review nudges
    '"security code"',                  # Greenhouse OTP emails
    '"verify your identity"',           # Amex and similar identity checks
    '"verification code"',
    '"one-time passcode"',
    '"confirm your identity"',
    '"passcode"',
]

BLOCKED_SENDERS = [
    "ambitionbox.com",  # review nudges triggered by Naukri applications
]

RELEVANCE_GATE_PROMPT = """You are a precision filter for an autonomous job application tracking system.

Your task is to analyze the email metadata and the initial content (up to 1,000 characters) and classify whether this email is definitive evidence that the candidate has ALREADY submitted a job application.

DECISION CRITERIA:

MARK AS RELEVANT (is_relevant: true):
- Application receipt confirmations ("We have received your application", "Application Received", "Thank you for applying")
- Application activity & recruiter engagement updates on submitted applications:
  - "Your application was viewed by [Company]" (e.g. LinkedIn Easy Apply notification)
  - "Recruiter viewed your application" or "Your application was downloaded" (e.g. Naukri, Indeed, ATS)
  These are definitive signals that the candidate submitted an application and the employer is actively reviewing it.
- Interview invitations for a role the candidate applied to (Screening, Technical, Behavioral, System Design)
- Online assessment / coding test invitations (HackerRank, HackerEarth, Mercer Mettl, Codility, etc.)
- Rejection emails ("we've decided to move forward with other candidates", "we will keep your profile on file", "regret to inform")
- Offer letters or compensation discussions
- "Next steps" emails following a submitted application
- Naukri "You applied for 1 job" emails IF the body contains a specific job title and company name

MARK AS NOT RELEVANT (is_relevant: false):
- Emails inviting the candidate TO apply (candidate has not applied yet)
- Job recommendation / matching digests ("this job is a match", "based on your profile", "jobs you might like")
- Saved job reminders or alerts
- Recruiter cold outreach / marketing
- Naukri "You applied for N jobs" summary emails where the body is empty or contains only a count of multiple jobs
- AmbitionBox review nudges or survey requests
- OTP / security code / identity verification emails — these are sent WHILE filling out an application form before submission is confirmed. The presence of a short verification code (e.g., 'vQuSydKU', '595125') with instructions like "resubmit" or "expires in 10 minutes" is a definitive negative signal.

THE CORE PRINCIPLE:
RELEVANT emails confirm something the candidate ALREADY DID.
NOT RELEVANT emails ask the candidate to DO something (apply), or are sent mid-form prior to submission.
"""


# ==============================================================================
# Layer 2 Pydantic Schemas
# ==============================================================================

class RelevanceDecision(BaseModel):
    """Structured decision returned by the Layer 2 Relevance Gate."""
    is_relevant: bool = Field(
        ...,
        description="True if email confirms an already submitted application event; False if promotional, OTP, or alert."
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score in the relevance classification (0.0 to 1.0)."
    )
    category: str = Field(
        ...,
        description="Categorization tag: APPLICATION_CONFIRMATION, INTERVIEW_INVITATION, ASSESSMENT_INVITATION, REJECTION, OFFER_LETTER, STATUS_UPDATE, PROMOTIONAL_INVITE, OTP_SECURITY_CODE, JOB_ALERT, or OTHER."
    )
    reason: str = Field(
        ...,
        description="Concise rationale explaining the relevance determination."
    )


# ==============================================================================
# Layer 1: Query Builder & In-Memory Pre-Filter
# ==============================================================================

def build_gmail_query(last_checked_at: datetime) -> str:
    """
    Constructs an optimized Gmail search query executing server-side keyword filtering.
    
    Combines timestamp threshold, grouped positive subject keywords, negative subject
    exclusions, and blocked sender domains according to Section 4 of SYSTEM_DESIGN.md.
    
    Args:
        last_checked_at: Timestamp threshold (only search emails received after this time).
        
    Returns:
        Formatted Gmail query string.
    """
    ts = int(last_checked_at.timestamp())
    positive = " OR ".join(f"subject:{t}" for t in POSITIVE_SUBJECT_TERMS)
    negative = " ".join(f"-subject:{t}" for t in NEGATIVE_SUBJECT_TERMS)
    blocked = " ".join(f"-from:{d}" for d in BLOCKED_SENDERS)

    return f"after:{ts} ({positive}) {negative} {blocked}"


def is_layer1_candidate(subject: str, sender: str = "") -> bool:
    """
    In-memory evaluation of email subject and sender against Layer 1 rules.
    
    Negative exclusions take strict precedence over positive keyword matches.
    
    Args:
        subject: Email subject line.
        sender: Sender address or display header.
        
    Returns:
        True if email satisfies Layer 1 filters, False otherwise.
    """
    subject_clean = subject.strip().lower()
    sender_clean = sender.strip().lower()

    # 1. Blocked sender check
    for blocked in BLOCKED_SENDERS:
        if blocked.lower() in sender_clean:
            return False

    # 2. Negative terms check (Negative rules take absolute precedence)
    for raw_term in NEGATIVE_SUBJECT_TERMS:
        term = raw_term.strip('"').lower()
        if term in subject_clean:
            return False

    # 3. Positive terms check
    for raw_term in POSITIVE_SUBJECT_TERMS:
        term = raw_term.strip('"').lower()
        if term in subject_clean:
            return True

    return False


# ==============================================================================
# Layer 2: LLM Relevance Gate Intent Classifier
# ==============================================================================

def _get_instructor_client(api_key: Optional[str] = None):
    """Creates an Instructor-patched OpenAI client if credentials are valid."""
    raw_key = api_key or os.getenv("OPENAI_API_KEY")
    key = raw_key.strip().strip('"\'') if raw_key else None
    if not key or key.startswith("sk-proj-placeholder"):
        return None

    try:
        import instructor
        from openai import OpenAI
        raw_client = OpenAI(api_key=key)
        return instructor.from_openai(raw_client)
    except Exception as e:
        logger.warning("Could not initialize Instructor OpenAI client: %s", e)
        return None


def _heuristic_relevance_check(
    subject: str,
    sender: str,
    body_text: str,
) -> RelevanceDecision:
    """
    Deterministic rule-based intent classifier used for offline testing or
    when the OpenAI API is unconfigured/unavailable.
    """
    subject_lower = subject.lower()
    sender_lower = sender.lower()
    body_snippet = body_text[:1000].lower()
    full_sample = f"{subject_lower}\n{sender_lower}\n{body_snippet}"

    # 1. Check for OTP / security codes / verification mid-form
    otp_signals = [
        "security code", "verification code", "one-time passcode", "verify your identity",
        "confirm your identity", "passcode", "expires in 10 minutes", "expires in 15 minutes",
        "enter this code", "your one-time code"
    ]
    if any(sig in full_sample for sig in otp_signals):
        # Double check if there is an alphanumeric/numeric code pattern
        if re.search(r"\b([a-zA-Z0-9]{6,8}|\d{4,8})\b", body_snippet):
            return RelevanceDecision(
                is_relevant=False,
                confidence=0.95,
                category="OTP_SECURITY_CODE",
                reason="Detected mid-submission OTP or security verification code."
            )

    # 2. Blocked senders or AmbitionBox review nudges
    if "ambitionbox" in sender_lower or "see what employees have to say" in full_sample:
        return RelevanceDecision(
            is_relevant=False,
            confidence=0.98,
            category="PROMOTIONAL_INVITE",
            reason="AmbitionBox review nudge detected."
        )

    # 3. Promotional job digests / invitations to apply
    promo_signals = [
        "apply now", "invited to apply", "is a match", "job alert", "jobs for you",
        "recommended for you", "perfect match", "saved job", "jobs you might like",
        "explore similar jobs", "based on your profile"
    ]
    if any(sig in full_sample for sig in promo_signals):
        # Unless it specifically confirms application receipt
        if not any(c in full_sample for c in ["we have received your application", "application received", "thank you for applying"]):
            return RelevanceDecision(
                is_relevant=False,
                confidence=0.90,
                category="JOB_ALERT",
                reason="Email contains promotional job recommendation or invitation to apply."
            )

    # 4. Naukri multiple job summary vs single job confirmation
    if "you applied for" in full_sample:
        multi_match = re.search(r"you applied for (\d+) jobs?", full_sample)
        if multi_match:
            count = int(multi_match.group(1))
            if count > 1 and ("company" not in body_snippet and "role" not in body_snippet):
                return RelevanceDecision(
                    is_relevant=False,
                    confidence=0.90,
                    category="JOB_ALERT",
                    reason=f"Naukri multi-job summary ({count} jobs) without specific single role details."
                )

    # 5. Positive signals: Assessment invitations
    assessment_signals = [
        "assessment", "coding test", "hackerrank", "hackerearth",
        "codility", "mettl", "online test", "technical assessment"
    ]
    if any(sig in full_sample for sig in assessment_signals):
        return RelevanceDecision(
            is_relevant=True,
            confidence=0.95,
            category="ASSESSMENT_INVITATION",
            reason="Online assessment or technical coding test invitation detected."
        )

    # 6. Positive signals: Interview invitations
    interview_signals = [
        "interview", "discussion", "technical screen", "round 1", "round 2",
        "schedule a call", "hiring manager discussion"
    ]
    if any(sig in full_sample for sig in interview_signals):
        return RelevanceDecision(
            is_relevant=True,
            confidence=0.95,
            category="INTERVIEW_INVITATION",
            reason="Interview invitation or scheduling communication detected."
        )

    # 7. Positive signals: Offer letters
    offer_signals = ["offer letter", "pleased to offer", "congratulations on your offer"]
    if any(sig in full_sample for sig in offer_signals):
        return RelevanceDecision(
            is_relevant=True,
            confidence=0.98,
            category="OFFER_LETTER",
            reason="Job offer or compensation package communication detected."
        )

    # 8. Positive signals: Rejection notices
    rejection_signals = [
        "regret to inform", "move forward with other candidates",
        "will keep your profile on file", "not moving forward",
        "decided to pursue other applicants", "unfortunately"
    ]
    if any(sig in full_sample for sig in rejection_signals) and any(kw in full_sample for kw in ["application", "candidacy", "role"]):
        return RelevanceDecision(
            is_relevant=True,
            confidence=0.95,
            category="REJECTION",
            reason="Application rejection notification detected."
        )

    # 9. Positive signals: Application viewed / recruiter interaction updates
    viewed_signals = [
        "application was viewed",
        "application viewed",
        "recruiter viewed your application",
        "viewed your application",
        "application was downloaded",
        "recruiter downloaded your resume",
        "application has been shortlisted",
    ]
    if any(sig in full_sample for sig in viewed_signals):
        return RelevanceDecision(
            is_relevant=True,
            confidence=0.95,
            category="APPLICATION_CONFIRMATION",
            reason="Application viewed or recruiter activity update on submitted application detected."
        )

    # 10. Positive signals: Application confirmations
    confirmation_signals = [
        "application received", "thank you for applying", "thank you for your application",
        "we have received your application", "your application has been submitted",
        "keep track of your application", "next steps regarding your application"
    ]
    if any(sig in full_sample for sig in confirmation_signals):
        return RelevanceDecision(
            is_relevant=True,
            confidence=0.95,
            category="APPLICATION_CONFIRMATION",
            reason="Definitive application submission confirmation detected."
        )

    # Default fallback: If Layer 1 passed, evaluate general keywords
    if is_layer1_candidate(subject, sender):
        return RelevanceDecision(
            is_relevant=True,
            confidence=0.75,
            category="STATUS_UPDATE",
            reason="Subject matches Layer 1 application keywords and no negative patterns found."
        )

    return RelevanceDecision(
        is_relevant=False,
        confidence=0.70,
        category="OTHER",
        reason="Does not confirm a submitted job application event."
    )


def check_email_relevance(
    subject: str,
    sender: str,
    body_text: str,
    client: Optional[object] = None,
    model: str = "gpt-4o-mini",
    force_fallback: bool = False,
) -> RelevanceDecision:
    """
    Layer 2 Filter: Precision Intent Classification via Instructor LLM or deterministic fallback.
    
    Evaluates up to the first 1,000 characters of the email body alongside the subject and sender.
    
    Args:
        subject: Email subject line.
        sender: Sender address or header.
        body_text: Email plaintext body.
        client: Optional pre-configured Instructor client.
        model: Model identifier (default: 'gpt-4o-mini').
        force_fallback: If True, forces heuristic evaluation (for offline unit testing).
        
    Returns:
        RelevanceDecision with is_relevant, confidence, category, and reason.
    """
    # Clean inputs and slice first 1000 characters
    clean_body = body_text.strip()[:1000]
    
    if force_fallback:
        return _heuristic_relevance_check(subject, sender, clean_body)

    instructor_client = client or _get_instructor_client()
    if instructor_client is None:
        logger.debug("Instructor client unavailable; using heuristic relevance check.")
        return _heuristic_relevance_check(subject, sender, clean_body)

    user_content = f"""Sender: {sender}
Subject: {subject}

Email Content (First 1,000 chars):
{clean_body}
"""
    try:
        decision = instructor_client.chat.completions.create(
            model=model,
            response_model=RelevanceDecision,
            messages=[
                {"role": "system", "content": RELEVANCE_GATE_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
        )
        return decision
    except Exception as exc:
        logger.warning("LLM relevance check failed (%s); falling back to heuristic evaluation.", exc)
        return _heuristic_relevance_check(subject, sender, clean_body)
