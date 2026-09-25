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
from pydantic import BaseModel, Field, model_validator

load_dotenv()

logger = logging.getLogger("gmail_filter")

# ==============================================================================
# Filter Constants (Comprehensive Lifecycle Coverage for All Pipeline Stages)
# ==============================================================================

POSITIVE_SUBJECT_TERMS = [
    # --- Stage 1: Applications, Confirmations & Status Updates (APPLIED / REJECTED) ---
    '"application received"',
    '"thank you for applying"',
    '"thanks for applying"',
    '"thank you for your application"',
    '"your application"',
    '"we have received your application"',
    '"keep track of your application"',
    '"you applied for 1 job"',          # Naukri single-application summary (multi-job digests excluded)
    '"thank you for your interest"',    # Workday / enterprise career portals (e.g. Maersk)
    '"thanks for your interest"',
    '"application update"',            # e.g. Visa, Workday
    '"job application"',               # e.g. Texas Instruments, Pearson ("Your recent job application for...")
    "application",                      # Core domain anchor for ATS confirmation/update subjects
    '"your candidacy"',                # e.g. "Update regarding your candidacy"

    # --- Stage 2: Online Assessments & Coding Challenges (OA_PENDING) ---
    "assessment",                       # e.g. "Online Assessment Invitation", "Coding Assessment"
    "challenge",
    '"coding challenge"',
    '"coding test"',
    "hackerrank",
    "codility",
    "codesignal",
    "hackerearth",
    "testgorilla",
    "hirevue",
    "mettl",
    '"take-home"',

    # --- Stage 3: Interviews & Recruiter Engagement (INTERVIEW_ROUND) ---
    "interview",                        # e.g. "Technical Interview Invitation", "Interview Schedule"
    '"phone screen"',
    '"recruiter screen"',
    '"next steps"',
    '"next round"',
    "scheduling",

    # --- Stage 4: Offers (OFFER) ---
    '"offer letter"',
    '"job offer"',
    '"offer of employment"',
    '"formal offer"',
]

POSITIVE_ATS_DOMAINS = [
    "myworkday.com",
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "smartrecruiters.com",
    "jobvite.com",
    "icims.com",
]

NEGATIVE_SUBJECT_TERMS = [
    # Pre-application marketing, alerts, and promotions
    '"apply now"',
    '"invited to apply"',
    '"is a match"',
    '"job alert"',
    '"jobs for you"',
    '"saved job"',
    '"recommended for you"',
    '"perfect match"',
    '"jobs applied by other"',          # Naukri promotional alert
    '"jobs on "',                       # Naukri multi-job batch digests (e.g. "You applied for 12 jobs on 24 Sep")
    '"loan offer"',                     # Bank loan promotions
    '"credit card"',
    '"personal loan"',
    '"see what employees have to say"', # AmbitionBox review nudges

    # Security, OTP, and 2FA emails
    '"security code"',                  # Greenhouse OTP emails
    '"verify your identity"',           # Amex and similar identity checks
    '"verification code"',
    '"one-time passcode"',
    '"confirm your identity"',
    '"passcode"',
    '"third-party oauth application"',  # Developer OAuth notifications (e.g. GitHub/Google)
]

BLOCKED_SENDERS = [
    "jobalerts-noreply@linkedin.com",   # Daily automated LinkedIn job alert digest
    "ambitionbox.com",                  # Review nudges triggered by job applications
    "noreply@github.com",               # Developer notifications containing word "application"
    "hdfcbank.com",                     # Promotional bank notifications containing "offer"
    "hdfcbank.bank",
    "communications.sbi.co.in",
]

RELEVANCE_GATE_PROMPT = """You are a precision filter for an autonomous job application tracking system.

Your task is to analyze the email metadata and the initial content (up to 1,000 characters) and classify whether this email is definitive evidence that the EMAIL RECIPIENT has an active, submitted job application event with an employer.

DECISION CRITERIA:

MARK AS RELEVANT (is_relevant: true):
- Application receipt confirmations ("We have received your application", "Application Received", "Thank you for applying")
- Inbound employee referrals where an employer or recruiter reaches out to the recipient to interview based on an internal referral
- Application activity & recruiter engagement updates on submitted applications ("Your application was viewed by [Company]", "Recruiter viewed your application")
- Interview invitations for a job the recipient applied to or was referred for (Screening, Technical, Behavioral, System Design)
- Online assessment / coding test invitations (HackerRank, HackerEarth, Mercer Mettl, Codility, etc.)
- Rejection emails ("we've decided to move forward with other candidates", "we will keep your profile on file", "regret to inform")
- Offer letters or compensation discussions for employment (where the employer pays a salary to the recipient)
- Offer rescinded or hiring freeze cancellation notices (these reflect an active application transition to rejected)
- Assessment completion receipts (e.g. "You have completed your Codility test")
- "Next steps" emails following a submitted application
- Actual job hiring emails FROM platforms like LeetCode or Scaler hiring for their own engineering teams (e.g. "Software Engineer at LeetCode")

MARK AS NOT RELEVANT (is_relevant: false):
- Commercial Course / Bootcamp / EdTech Sales: Offers or invitations from training programs, bootcamps, or course platforms (Scaler Academy, Simplilearn, UpGrad, LeetCode premium, Coursera) offering "scholarships", "fellowships", or course admission discounts where the candidate must pay tuition or fees. An employment offer MUST be from an employer paying a salary, NOT asking the candidate to pay a fee or enroll in a batch.
- Outbound Referral Status Updates: Emails acknowledging a referral submitted BY the recipient FOR a colleague or friend ("Thank you for referring [Name]", "Your referral [Name] has applied", referral bonus tracking). The candidate being considered is a third party, NOT the recipient.
- Candidate Experience / Post-Interview Surveys: Emails asking the recipient for feedback or satisfaction ratings about past interviews ("How was your interview experience?", "Candidate feedback survey", Qualtrics/SurveyMonkey forms). These do NOT schedule a new interview and do NOT change job application status.
- Third-Party Interview Prep / Mock Tests: Newsletters or study guides offering mock interview simulations or practice questions (e.g. LeetCode prep newsletter).
- Pre-Application Invitations: Emails inviting the candidate TO apply or complete an unfinished portal draft.
- Recruiter Cold Outreach / Agency Pitch: Headhunters pitching unapplied roles with Calendly links.
- Open Hackathons / Public Coding Contests: Open competitions not tied to a specific job requisition.
- Event Cancellations / Webinars: Postponed tech sessions or webinars that use "regret" or "unfortunately".
- OTP / Security Codes / Identity Verification emails.
- Job alerts and recommendation digests.

THE CORE PRINCIPLE:
RELEVANT emails confirm a job application lifecycle event (confirmation, online test, interview invitation, rejection, offer, or status update) where the RECIPIENT is the job applicant.
- Rejection emails ARE ALWAYS RELEVANT (is_relevant: true, category: REJECTION) because the system must track that this application was rejected.
- Inbound employee referrals (where a colleague referred the recipient, and the company reaches out to schedule an interview) ARE ALWAYS RELEVANT (is_relevant: true, category: INTERVIEW_INVITATION).
NOT RELEVANT emails are commercial course sales, outbound referrals tracking someone else, post-interview surveys, or unsubmitted applications.
"""


# ==============================================================================
# Layer 2 Pydantic Schemas
# ==============================================================================

class RelevanceDecision(BaseModel):
    """Structured decision returned by the Layer 2 Relevance Gate."""
    is_commercial_course: bool = Field(
        default=False,
        description="True if this is a training course, bootcamp, or fee-paying fellowship/scholarship offer."
    )
    is_third_party_referral: bool = Field(
        default=False,
        description="True if the user is the referrer for someone else, rather than the job applicant."
    )
    is_survey_or_feedback: bool = Field(
        default=False,
        description="True if this is a candidate experience or post-interview feedback survey."
    )
    is_relevant: bool = Field(
        ...,
        description="True if email confirms a job application lifecycle event (confirmation, OA, interview, rejection, offer) for the recipient; False if promotional, survey, third-party referral, OTP, or alert."
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

    @model_validator(mode="after")
    def reconcile_relevance_and_category(self) -> "RelevanceDecision":
        """Ensures that confirmed lifecycle events are marked relevant unless explicitly flagged by an adversarial check."""
        if self.is_commercial_course or self.is_third_party_referral or self.is_survey_or_feedback:
            self.is_relevant = False
            return self
        if self.category in (
            "APPLICATION_CONFIRMATION", "INTERVIEW_INVITATION",
            "ASSESSMENT_INVITATION", "REJECTION", "OFFER_LETTER"
        ):
            self.is_relevant = True
        return self


# ==============================================================================
# Layer 1: Query Builder & In-Memory Pre-Filter
# ==============================================================================

def build_gmail_query(last_checked_at: datetime) -> str:
    """
    Constructs an optimized Gmail search query executing server-side keyword filtering.
    
    Combines timestamp threshold, grouped positive subject keywords, direct ATS sender
    domains, negative subject exclusions, and blocked sender domains according to SYSTEM_DESIGN.md.
    
    Args:
        last_checked_at: Timestamp threshold (only search emails received after this time).
        
    Returns:
        Formatted Gmail query string.
    """
    ts = int(last_checked_at.timestamp())
    subject_queries = [f"subject:{t}" for t in POSITIVE_SUBJECT_TERMS]
    ats_queries = [f"from:{d}" for d in POSITIVE_ATS_DOMAINS]
    positive = " OR ".join(subject_queries + ats_queries)
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

    # 3. Direct ATS domain check (always candidate unless vetoed by negative rule)
    for domain in POSITIVE_ATS_DOMAINS:
        if domain.lower() in sender_clean:
            return True

    # 4. Positive terms check
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

    # 4b. Commercial course / fellowship sales
    if any(sig in full_sample for sig in ["scholarship value", "program fee", "fellowship program", "tuition concession"]):
        return RelevanceDecision(
            is_commercial_course=True,
            is_relevant=False,
            confidence=0.95,
            category="PROMOTIONAL_INVITE",
            reason="Commercial training course, bootcamp, or fee-paying fellowship detected."
        )

    # 4c. Outbound referral tracking (user referred someone else)
    if ("thank you for referring" in full_sample or "your referral," in full_sample or "referral bonus" in full_sample) and "referred you" not in full_sample:
        return RelevanceDecision(
            is_third_party_referral=True,
            is_relevant=False,
            confidence=0.95,
            category="OTHER",
            reason="Outbound referral receipt or tracking update for a third party candidate."
        )

    # 4d. Candidate experience / post-interview surveys
    if any(sig in full_sample for sig in ["take the survey", "feedback about our interview", "tell us about your interview", "interview experience survey"]):
        return RelevanceDecision(
            is_survey_or_feedback=True,
            is_relevant=False,
            confidence=0.95,
            category="OTHER",
            reason="Candidate experience or post-interview feedback survey detected."
        )

    # 4e. Draft reminders (incomplete application)
    if "haven't finished submitting" in full_sample or "haven't submitted it yet" in full_sample:
        return RelevanceDecision(
            is_relevant=False,
            confidence=0.95,
            category="PROMOTIONAL_INVITE",
            reason="Unsubmitted application draft reminder detected."
        )

    # 4f. Event / webinar postponements
    if ("postponed" in full_sample or "rescheduled" in full_sample) and ("session" in full_sample or "webinar" in full_sample):
        return RelevanceDecision(
            is_relevant=False,
            confidence=0.90,
            category="OTHER",
            reason="Event or webinar rescheduling notice detected."
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
