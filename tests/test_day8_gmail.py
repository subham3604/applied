"""
tests/test_day8_gmail.py
========================
Test suite for Phase 2 Day 8: Gmail OAuth2 & Two-Layer Filter Construction.

Validates:
- Layer 1: Query generation syntax, positive matches, negative term overrides, blocked senders.
- Layer 2: LLM Relevance Gate intent classification (confirmations, interviews, assessments,
  rejections, offers vs mid-form OTPs, promo digests, AmbitionBox nudges).
- Headless OAuth credentials building and error handling.
- Base64url MIME payload extraction & HTML stripping.
- Database operational state persistence in worker_config.
- End-to-end simulated Gmail polling pipeline.
"""

import base64
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from db.session import SessionLocal
from worker.gmail_credentials import build_credentials_from_env
from worker.gmail_filter import (
    BLOCKED_SENDERS,
    NEGATIVE_SUBJECT_TERMS,
    POSITIVE_SUBJECT_TERMS,
    RelevanceDecision,
    build_gmail_query,
    check_email_relevance,
    is_layer1_candidate,
)
from worker.gmail_poller import (
    EmailMessage,
    _decode_base64_data,
    _strip_html,
    fetch_new_emails,
    get_worker_last_checked_at,
    parse_gmail_message,
    poll_and_filter_emails,
    update_worker_last_checked_at,
)


@pytest.fixture(scope="module")
def db_session():
    session = SessionLocal()
    yield session
    session.close()


# ==============================================================================
# 1. Layer 1 Query Construction & Syntax Tests
# ==============================================================================

def test_build_gmail_query_syntax():
    """Verify build_gmail_query generates valid Gmail search query syntax."""
    ts = datetime(2026, 9, 16, 8, 0, 0, tzinfo=timezone.utc)
    query = build_gmail_query(ts)

    expected_ts = int(ts.timestamp())
    assert f"after:{expected_ts}" in query

    # Verify key positive terms are grouped with OR
    assert 'subject:"application received"' in query
    assert 'subject:"your application"' in query
    assert "subject:interview" in query
    assert "subject:assessment" in query
    assert " OR " in query

    # Verify key negative terms are prefixed with -subject:
    assert '-subject:"security code"' in query
    assert '-subject:"apply now"' in query
    assert '-subject:"verification code"' in query
    assert '-subject:"one-time passcode"' in query

    # Verify blocked senders are prefixed with -from:
    assert "-from:ambitionbox.com" in query


# ==============================================================================
# 2. Layer 1 In-Memory Pre-Filter Tests
# ==============================================================================

def test_layer1_positive_matches():
    """Verify legitimate application subjects across all lifecycle stages pass Layer 1."""
    valid_subjects = [
        # Stage 1: Applications, Confirmations & Rejections
        "Application Received: Senior Backend Engineer at Zyntrix",
        "Thank you for applying to Google",
        "Your application for AI Systems Engineer at PhonePe",
        "Thank you for your interest in A.P Moller Maersk Group",
        "Visa - Application Update",
        "Your recent job application for Software Development Engineer - 25017217",
        "Update on your UiPath application: Software Engineer 1",
        "You applied for 1 job on Naukri.com",
        "Your candidacy for Senior Developer at Shopify",
        
        # Stage 2: Assessments (OA_PENDING)
        "Online Assessment: HackerRank test for Swiggy",
        "Your Codility Coding Challenge is ready",
        "CodeSignal General Coding Assessment Invitation",
        "Technical take-home challenge for Acme Corp",
        
        # Stage 3: Interviews (INTERVIEW_ROUND)
        "Interview Invitation: Technical Screen with Uber",
        "Recruiter phone screen scheduling - Netflix",
        "Next steps regarding your application at Microsoft",
        
        # Stage 4: Offers (OFFER)
        "Offer Letter - Staff Software Engineer at Datadog",
        "Job Offer: Senior AI Engineer at Anthropic",
    ]
    for sub in valid_subjects:
        assert is_layer1_candidate(sub, sender="jobs@company.com") is True, f"Failed for: {sub}"


def test_layer1_negative_exclusions_take_precedence():
    """
    CRITICAL REQUIREMENT:
    Negative exclusion terms MUST override positive terms.
    E.g. 'Security code for your application' hits 'your application',
    but 'security code' must veto it immediately.
    """
    excluded_cases = [
        # Greenhouse OTP email containing "your application"
        "Security code for your application at Stripe",
        # Amex verification code
        "Please verify your identity for your application",
        # Verification code
        "Verification code for your job application",
        # One-time passcode
        "Your one-time passcode for application login",
        # Promotional invitation containing "apply"
        "Apply now: Senior Backend Engineer roles recommended for you",
        # Job alert matching
        "Your saved job alert: 5 jobs is a match for your profile",
        # AmbitionBox review nudge
        "See what employees have to say about your application company",
        # Naukri multi-job batch digests (>1 job)
        "You applied for 12 jobs on 24 Sep",
        "You applied for 5 jobs on 23 Sep",
        # Naukri promotional alert
        "Subham, check out jobs applied by other Software Engineer",
        # Third-party OAuth notifications containing the word "application"
        "[GitHub] A third-party OAuth application has been added to your account",
    ]
    for sub in excluded_cases:
        assert is_layer1_candidate(sub, sender="noreply@service.com") is False, f"Should be excluded: {sub}"


def test_layer1_blocked_senders():
    """Verify blocked sender domains are excluded even with job-like subject lines."""
    subject = "Your application review and company feedback"
    # Blocked domain
    assert is_layer1_candidate(subject, sender="alerts@ambitionbox.com") is False
    assert is_layer1_candidate(subject, sender="AmbitionBox Team <noreply@ambitionbox.com>") is False
    # Normal domain with valid subject
    assert is_layer1_candidate("Your application at Zyntrix", sender="recruiting@zyntrix.com") is True


# ==============================================================================
# 3. Layer 2 LLM Relevance Gate Intent Tests (Precision)
# ==============================================================================

def test_layer2_application_confirmation_is_relevant():
    """Receipt confirmation emails must be classified as RELEVANT."""
    body = (
        "Hi Subham,\n\n"
        "Thank you for your application to the Senior Backend Engineer position at Zyntrix Technologies. "
        "We have received your resume and application materials. Our talent acquisition team will review "
        "your profile and reach out if there is a match.\n\nBest regards,\nZyntrix Recruiting Team"
    )
    decision = check_email_relevance(
        subject="Application Received: Senior Backend Engineer",
        sender="careers@zyntrixsoftware.com",
        body_text=body,
        force_fallback=True,
    )
    assert decision.is_relevant is True
    assert decision.confidence >= 0.8
    assert decision.category in ["APPLICATION_CONFIRMATION", "STATUS_UPDATE"]


def test_layer2_application_viewed_is_relevant():
    """
    Candidate application viewed notifications (e.g. LinkedIn Easy Apply, Naukri)
    must be classified as RELEVANT since they confirm an existing application.
    """
    body_linkedin = (
        "Your application for Full Stack Engineer at Quon Labs was viewed by the recruiter. "
        "You can track the progress of your application on LinkedIn."
    )
    decision = check_email_relevance(
        subject="Your application was viewed by Quon Labs",
        sender="jobs-noreply@linkedin.com",
        body_text=body_linkedin,
        force_fallback=True,
    )
    assert decision.is_relevant is True
    assert decision.confidence >= 0.8
    assert decision.category in ["APPLICATION_CONFIRMATION", "STATUS_UPDATE"]


def test_layer2_assessment_and_interview_is_relevant():
    """Online assessments and interview invites must be classified as RELEVANT."""
    # Assessment
    body_assessment = (
        "Hello Subham,\n\n"
        "You have been invited to complete a 90-minute online coding test on HackerRank for the "
        "Software Engineer II role at Swiggy. Please complete the assessment within 4 days."
    )
    decision_oa = check_email_relevance(
        subject="Coding Assessment Invitation from Swiggy",
        sender="no-reply@hackerrank.net",
        body_text=body_assessment,
        force_fallback=True,
    )
    assert decision_oa.is_relevant is True
    assert decision_oa.category == "ASSESSMENT_INVITATION"

    # Interview
    body_interview = (
        "Hi Subham,\n\n"
        "We would like to schedule a 45-minute technical screen round with one of our staff engineers "
        "for the Cloud Systems Architect position. Please share your availability for this week."
    )
    decision_interview = check_email_relevance(
        subject="Interview Invitation - Technical Screen",
        sender="talent@uber.com",
        body_text=body_interview,
        force_fallback=True,
    )
    assert decision_interview.is_relevant is True
    assert decision_interview.category == "INTERVIEW_INVITATION"


def test_layer2_rejection_and_offer_is_relevant():
    """Rejections and offer letters must be classified as RELEVANT."""
    # Rejection
    body_rejection = (
        "Dear Subham,\n\n"
        "Thank you for taking the time to speak with our team regarding the Senior Backend position. "
        "Although we were impressed by your background, we have decided to move forward with other candidates "
        "whose experience more closely aligns with our current needs. We will keep your profile on file."
    )
    decision_rej = check_email_relevance(
        subject="Update on your application",
        sender="careers@google.com",
        body_text=body_rejection,
        force_fallback=True,
    )
    assert decision_rej.is_relevant is True
    assert decision_rej.category == "REJECTION"

    # Offer
    body_offer = (
        "Dear Subham,\n\n"
        "On behalf of Datadog, we are pleased to offer you the position of Senior Software Engineer. "
        "Please find your formal offer letter and compensation structure attached."
    )
    decision_offer = check_email_relevance(
        subject="Offer Letter - Senior Software Engineer",
        sender="hr@datadoghq.com",
        body_text=body_offer,
        force_fallback=True,
    )
    assert decision_offer.is_relevant is True
    assert decision_offer.category == "OFFER_LETTER"


def test_layer2_otp_and_security_code_is_not_relevant():
    """
    CRITICAL DELIVERABLE:
    Mid-submission OTP and security codes must be classified as NOT RELEVANT.
    """
    body_otp = (
        "Your verification code is 849201. "
        "This security code expires in 10 minutes. "
        "Please enter this code into your application form to verify your identity and submit."
    )
    decision = check_email_relevance(
        subject="Security code for your application",
        sender="no-reply@greenhouse.io",
        body_text=body_otp,
        force_fallback=True,
    )
    assert decision.is_relevant is False
    assert decision.category == "OTP_SECURITY_CODE"


def test_layer2_promotional_and_job_alerts_is_not_relevant():
    """Promotional job matching digests and invitations to apply must be NOT RELEVANT."""
    body_promo = (
        "Subham, based on your profile, this job is a match! "
        "Senior Backend Engineer at Stripe. "
        "Apply now with your saved profile before applications close."
    )
    decision = check_email_relevance(
        subject="Jobs for you: Senior Backend Engineer at Stripe",
        sender="jobalerts-noreply@linkedin.com",
        body_text=body_promo,
        force_fallback=True,
    )
    assert decision.is_relevant is False
    assert decision.category in ["JOB_ALERT", "PROMOTIONAL_INVITE", "OTHER"]


def test_layer2_naukri_single_vs_multi_summary():
    """Naukri single applied job with role details is relevant; multi-job count is not."""
    # Single job confirmation with company and role
    body_single = (
        "You applied for 1 job today.\n"
        "Company: Zyntrix Technologies\n"
        "Role: Senior Python Developer\n"
        "Status: Sent to recruiter"
    )
    decision_single = check_email_relevance(
        subject="You applied for 1 job",
        sender="messages@naukri.com",
        body_text=body_single,
        force_fallback=True,
    )
    assert decision_single.is_relevant is True

    # Multi-job summary count without specific role
    body_multi = (
        "You applied for 8 jobs today on Naukri.\n"
        "Keep up the momentum! Recommended jobs matching your searches:"
    )
    decision_multi = check_email_relevance(
        subject="You applied for 8 jobs",
        sender="messages@naukri.com",
        body_text=body_multi,
        force_fallback=True,
    )
    assert decision_multi.is_relevant is False


# ==============================================================================
# 4. Headless OAuth Credentials Tests
# ==============================================================================

def test_headless_credentials_missing_returns_none():
    """When credentials are absent or placeholder, builder returns None safely."""
    with patch.dict("os.environ", {
        "GMAIL_CLIENT_ID": "placeholder-client-id",
        "GMAIL_CLIENT_SECRET": "placeholder-secret",
        "GMAIL_REFRESH_TOKEN": "placeholder-token",
    }, clear=True):
        creds = build_credentials_from_env(token_json_path="/non/existent/path.json")
        assert creds is None


def test_headless_credentials_valid_construction():
    """When valid credentials are provided, Credentials object is properly created."""
    with patch("google.oauth2.credentials.Credentials.refresh") as mock_refresh:
        creds = build_credentials_from_env(
            client_id="valid-id-123.apps.googleusercontent.com",
            client_secret="valid-secret-xyz",
            refresh_token="valid-refresh-token-456",
        )
        assert creds is not None
        assert creds.client_id == "valid-id-123.apps.googleusercontent.com"
        assert creds.refresh_token == "valid-refresh-token-456"


# ==============================================================================
# 5. MIME Decoding & Payload Extraction Tests
# ==============================================================================

def test_decode_base64_data():
    """Verify URL-safe base64 decoding with padding tolerance."""
    raw_str = "Hello JobTracker autonomous worker!"
    encoded = base64.urlsafe_b64encode(raw_str.encode("utf-8")).decode("ascii").rstrip("=")
    decoded = _decode_base64_data(encoded)
    assert decoded == raw_str


def test_strip_html():
    """Verify HTML stripping cleans markup cleanly."""
    html_sample = "<p>Thank you for applying to <b>Zyntrix</b>.</p><br><div>Next steps soon.</div>"
    clean = _strip_html(html_sample)
    assert "Thank you for applying to Zyntrix." in clean
    assert "Next steps soon." in clean
    assert "<p>" not in clean


def test_parse_gmail_message_multipart():
    """Verify parsing of full Gmail message dictionary with nested MIME parts."""
    plain_text = "We have received your application for Backend SDE-2 at PhonePe."
    encoded_plain = base64.urlsafe_b64encode(plain_text.encode("utf-8")).decode("ascii")

    html_text = "<p>We have received your application for <b>Backend SDE-2</b> at PhonePe.</p>"
    encoded_html = base64.urlsafe_b64encode(html_text.encode("utf-8")).decode("ascii")

    raw_api_response = {
        "id": "msg_test_12345",
        "threadId": "th_test_67890",
        "snippet": "We have received your application...",
        "internalDate": "1789540000000",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Application Received: Backend SDE-2"},
                {"name": "From", "value": "careers@phonepe.com"},
                {"name": "To", "value": "subham@example.com"},
                {"name": "Date", "value": "Wed, 16 Sep 2026 08:30:00 +0000"},
            ],
            "mimeType": "multipart/alternative",
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": encoded_plain},
                },
                {
                    "mimeType": "text/html",
                    "body": {"data": encoded_html},
                }
            ]
        }
    }

    parsed = parse_gmail_message(raw_api_response)
    assert isinstance(parsed, EmailMessage)
    assert parsed.message_id == "msg_test_12345"
    assert parsed.thread_id == "th_test_67890"
    assert parsed.subject == "Application Received: Backend SDE-2"
    assert parsed.sender == "careers@phonepe.com"
    assert plain_text in parsed.body_text
    assert parsed.body_html == html_text


# ==============================================================================
# 6. Database Operational State Tests (worker_config)
# ==============================================================================

def test_worker_config_last_checked_at_persistence(db_session: Session):
    """Verify get_worker_last_checked_at and update_worker_last_checked_at."""
    target_dt = datetime(2026, 9, 16, 12, 30, 45, tzinfo=timezone.utc)
    update_worker_last_checked_at(db_session, target_dt)

    retrieved_dt = get_worker_last_checked_at(db_session)
    assert retrieved_dt is not None
    # Compare down to seconds
    assert int(retrieved_dt.timestamp()) == int(target_dt.timestamp())


# ==============================================================================
# 7. End-to-End Mock Gmail Poller Pipeline Test
# ==============================================================================

def test_end_to_end_mock_poller_pipeline():
    """
    Simulates a realistic Gmail inbox containing:
    1. Zyntrix "Application Received" (Should pass Layer 1 and Layer 2)
    2. Greenhouse "Security code for your application" (Should be rejected by Layer 1 negative filter)
    3. LinkedIn "Apply now: 10 new software jobs" (Should be rejected by Layer 1 negative filter)
    4. Uber "Assessment Invitation - HackerRank" (Should pass Layer 1 and Layer 2)
    5. AmbitionBox review nudge (Should be rejected by Layer 1 blocked sender)
    """
    # 1. Zyntrix Valid
    b64_zyntrix = base64.urlsafe_b64encode(b"We have received your application for SDE-2.").decode("ascii")
    msg_zyntrix = {
        "id": "msg_001",
        "threadId": "th_001",
        "internalDate": "1789541000000",
        "snippet": "We have received your application...",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Application Received: SDE-2 at Zyntrix"},
                {"name": "From", "value": "recruiting@zyntrixsoftware.com"},
            ],
            "mimeType": "text/plain",
            "body": {"data": b64_zyntrix},
        }
    }

    # 2. Greenhouse OTP (Layer 1 negative match)
    b64_gh = base64.urlsafe_b64encode(b"Security code is 482910. Expires in 10 minutes.").decode("ascii")
    msg_greenhouse = {
        "id": "msg_002",
        "threadId": "th_002",
        "internalDate": "1789542000000",
        "snippet": "Security code...",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Security code for your application at Datadog"},
                {"name": "From", "value": "no-reply@greenhouse.io"},
            ],
            "mimeType": "text/plain",
            "body": {"data": b64_gh},
        }
    }

    # 3. LinkedIn Promo (Layer 1 negative match)
    b64_li = base64.urlsafe_b64encode(b"Apply now to top jobs matching your profile.").decode("ascii")
    msg_linkedin = {
        "id": "msg_003",
        "threadId": "th_003",
        "internalDate": "1789543000000",
        "snippet": "Apply now...",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Apply now: 10 new backend software engineer jobs"},
                {"name": "From", "value": "jobalerts@linkedin.com"},
            ],
            "mimeType": "text/plain",
            "body": {"data": b64_li},
        }
    }

    # 4. Uber Assessment (Layer 1 + Layer 2 positive)
    b64_uber = base64.urlsafe_b64encode(b"Please complete this HackerRank assessment for Uber.").decode("ascii")
    msg_uber = {
        "id": "msg_004",
        "threadId": "th_004",
        "internalDate": "1789544000000",
        "snippet": "HackerRank assessment...",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Assessment Invitation: Uber Backend Engineer"},
                {"name": "From", "value": "talent@uber.com"},
            ],
            "mimeType": "text/plain",
            "body": {"data": b64_uber},
        }
    }

    # 5. AmbitionBox Blocked Sender
    b64_ab = base64.urlsafe_b64encode(b"See what employees have to say about companies.").decode("ascii")
    msg_ambitionbox = {
        "id": "msg_005",
        "threadId": "th_005",
        "internalDate": "1789545000000",
        "snippet": "Employee reviews...",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Your application company reviews"},
                {"name": "From", "value": "alerts@ambitionbox.com"},
            ],
            "mimeType": "text/plain",
            "body": {"data": b64_ab},
        }
    }

    raw_messages_map = {
        "msg_001": msg_zyntrix,
        "msg_002": msg_greenhouse,
        "msg_003": msg_linkedin,
        "msg_004": msg_uber,
        "msg_005": msg_ambitionbox,
    }

    mock_service = MagicMock()
    # Mock users().messages().list()
    mock_service.users().messages().list().execute.return_value = {
        "messages": [{"id": k} for k in raw_messages_map.keys()]
    }
    # Mock users().messages().get()
    def _mock_get(userId, id, format):
        mock_get_req = MagicMock()
        mock_get_req.execute.return_value = raw_messages_map[id]
        return mock_get_req

    mock_service.users().messages().get.side_effect = _mock_get

    # Run poller pipeline
    last_checked = datetime(2026, 9, 15, 0, 0, 0, tzinfo=timezone.utc)
    results = poll_and_filter_emails(
        last_checked_at=last_checked,
        service=mock_service,
        apply_relevance_gate=True,
        force_fallback_gate=True,
    )

    # Deliverable checks:
    # 1. Greenhouse "Security code" excluded
    # 2. LinkedIn "Apply now" excluded
    # 3. AmbitionBox review nudge excluded
    # 4. Zyntrix "Application Received" included
    # 5. Uber "Assessment Invitation" included
    passed_ids = [email.message_id for email, decision in results if decision.is_relevant]

    assert "msg_002" not in passed_ids, "Greenhouse security code must be excluded"
    assert "msg_003" not in passed_ids, "LinkedIn apply now must be excluded"
    assert "msg_005" not in passed_ids, "AmbitionBox must be excluded"

    assert "msg_001" in passed_ids, "Zyntrix application received must be included"
    assert "msg_004" in passed_ids, "Uber assessment invitation must be included"
    assert len(passed_ids) == 2
