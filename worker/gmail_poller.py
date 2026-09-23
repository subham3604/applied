"""
worker/gmail_poller.py
======================
Autonomous Gmail Polling Service for JobTracker.

Handles:
- Execution of Layer 1 Gmail API search queries
- Robust base64url MIME payload extraction & decoding (multipart/alternative, text/plain, text/html)
- Layer 1 & Layer 2 candidate filtering pipeline
- Worker state management (reading & updating `last_checked_at` in the PostgreSQL `worker_config` table)
"""

import base64
import logging
import re
from datetime import datetime, timedelta, timezone
import html
from html.parser import HTMLParser
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from db.models import WorkerConfig
from worker.gmail_credentials import get_gmail_service
from worker.gmail_filter import (
    RelevanceDecision,
    build_gmail_query,
    check_email_relevance,
    is_layer1_candidate,
)

logger = logging.getLogger("gmail_poller")


# ==============================================================================
# HTML Stripper Utility
# ==============================================================================

class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.result = []
        self._ignore_tags = {"style", "script", "head", "noscript", "svg", "meta", "title"}
        self._ignore_depth = 0

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        if tag_lower in self._ignore_tags:
            self._ignore_depth += 1
        elif tag_lower in ("p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
            self.result.append("\n")

    def handle_endtag(self, tag):
        tag_lower = tag.lower()
        if tag_lower in self._ignore_tags:
            if self._ignore_depth > 0:
                self._ignore_depth -= 1
        elif tag_lower in ("p", "div", "tr", "li"):
            self.result.append("\n")

    def handle_data(self, d):
        if self._ignore_depth == 0:
            self.result.append(d)

    def get_text(self) -> str:
        raw = "".join(self.result)
        lines = [line.strip() for line in raw.splitlines()]
        cleaned = "\n".join(line for line in lines if line)
        return html.unescape(cleaned)


def _strip_html(html_str: str) -> str:
    """Strips HTML tags, styles, scripts, and normalizes whitespace."""
    if not html_str:
        return ""
    # Pre-strip script, style, head blocks for safety
    cleaned_html = re.sub(
        r"<(script|style|head|noscript)[\s\S]*?</\1>",
        " ",
        html_str,
        flags=re.IGNORECASE,
    )
    try:
        parser = _HTMLTextExtractor()
        parser.feed(cleaned_html)
        return parser.get_text()
    except Exception:
        # Fallback to regex tag stripping
        clean = re.sub(r"<[^>]+>", " ", cleaned_html)
        return html.unescape(" ".join(clean.split()))


# ==============================================================================
# Email Data Model
# ==============================================================================

class EmailMessage(BaseModel):
    """Structured representation of a parsed Gmail message."""
    message_id: str = Field(..., description="Unique Gmail message ID.")
    thread_id: str = Field(..., description="Gmail thread ID.")
    sender: str = Field(..., description="Sender header (From).")
    recipient: str = Field(..., description="Recipient header (To).")
    subject: str = Field(..., description="Subject line.")
    received_at: datetime = Field(..., description="Timestamp when the email was received.")
    snippet: str = Field(default="", description="Gmail snippet preview.")
    body_text: str = Field(..., description="Decoded plaintext content.")
    body_html: Optional[str] = Field(default=None, description="Decoded HTML content if present.")


# ==============================================================================
# MIME Decoding Helpers
# ==============================================================================

def _decode_base64_data(raw_data: str) -> str:
    """Decodes URL-safe base64 data with padding correction and UTF-8 fallback."""
    if not raw_data:
        return ""
    # Correct base64 URL-safe padding
    padding = len(raw_data) % 4
    if padding:
        raw_data += "=" * (4 - padding)
    try:
        decoded_bytes = base64.urlsafe_b64decode(raw_data)
        return decoded_bytes.decode("utf-8", errors="replace")
    except Exception as exc:
        logger.debug("Failed to decode base64 data: %s", exc)
        return ""


def _extract_body_parts(payload: dict) -> Tuple[str, Optional[str]]:
    """
    Recursively navigates MIME message parts to extract text/plain and text/html bodies.
    
    Returns:
        tuple (plain_text, html_text)
    """
    plain_parts = []
    html_parts = []

    def _walk_parts(part: dict):
        mime_type = part.get("mimeType", "").lower()
        body = part.get("body", {})
        data = body.get("data", "")

        if mime_type == "text/plain" and data:
            plain_parts.append(_decode_base64_data(data))
        elif mime_type == "text/html" and data:
            html_parts.append(_decode_base64_data(data))

        # Recurse into nested parts
        sub_parts = part.get("parts", [])
        for sub_part in sub_parts:
            _walk_parts(sub_part)

    _walk_parts(payload)

    plain_text = "\n".join(plain_parts).strip()
    html_text = "\n".join(html_parts).strip() if html_parts else None

    # If plaintext is empty or looks like raw HTML, derive plaintext from HTML or strip it
    if not plain_text and html_text:
        plain_text = _strip_html(html_text)
    elif plain_text and ("<html" in plain_text.lower() or "<div" in plain_text.lower() or "<style" in plain_text.lower() or "<table" in plain_text.lower()):
        plain_text = _strip_html(plain_text)

    return plain_text, html_text


def parse_gmail_message(raw_msg: dict) -> EmailMessage:
    """
    Parses a full Gmail API message dictionary into an EmailMessage object.
    
    Args:
        raw_msg: Full message payload dictionary from users.messages.get.
        
    Returns:
        Structured EmailMessage.
    """
    message_id = raw_msg.get("id", "")
    thread_id = raw_msg.get("threadId", "")
    snippet = raw_msg.get("snippet", "")
    payload = raw_msg.get("payload", {})

    # Extract headers
    headers = {h.get("name", "").lower(): h.get("value", "") for h in payload.get("headers", [])}
    subject = headers.get("subject", "(No Subject)")
    sender = headers.get("from", "")
    recipient = headers.get("to", "")

    # Parse timestamp from internalDate (ms since epoch) or Date header
    received_at = datetime.now(timezone.utc)
    internal_val = raw_msg.get("internalDate") or raw_msg.get("internaldate")
    if internal_val:
        try:
            ms = int(internal_val)
            received_at = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
        except Exception:
            pass
    elif "date" in headers:
        try:
            import email.utils
            parsed_tuple = email.utils.parsedate_to_datetime(headers["date"])
            if parsed_tuple:
                received_at = parsed_tuple.astimezone(timezone.utc)
        except Exception:
            pass

    # Extract body content
    plain_text, html_text = _extract_body_parts(payload)
    if not plain_text:
        plain_text = snippet

    return EmailMessage(
        message_id=message_id,
        thread_id=thread_id,
        sender=sender,
        recipient=recipient,
        subject=subject,
        received_at=received_at,
        snippet=snippet,
        body_text=plain_text,
        body_html=html_text,
    )


# ==============================================================================
# Gmail Polling Operations
# ==============================================================================

def fetch_new_emails(
    last_checked_at: datetime,
    service=None,
    max_results: int = 50,
) -> List[EmailMessage]:
    """
    Executes Layer 1 Gmail API search query and retrieves full parsed messages.
    
    Args:
        last_checked_at: Query timestamp boundary.
        service: Optional pre-built Gmail API resource.
        max_results: Maximum messages to retrieve per poll.
        
    Returns:
        List of parsed EmailMessage objects.
    """
    gmail = service or get_gmail_service()
    if not gmail:
        logger.warning("Gmail service is unavailable. Skipping fetch.")
        return []

    query = build_gmail_query(last_checked_at)
    logger.info("Executing Gmail API query: %s", query)

    try:
        response = gmail.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results,
        ).execute()

        messages_meta = response.get("messages", [])
        if not messages_meta:
            logger.info("No new emails found matching query.")
            return []

        logger.info("Found %d candidate messages in Gmail.", len(messages_meta))
        results = []
        for meta in messages_meta:
            msg_id = meta["id"]
            try:
                raw_msg = gmail.users().messages().get(
                    userId="me",
                    id=msg_id,
                    format="full",
                ).execute()
                email_obj = parse_gmail_message(raw_msg)
                results.append(email_obj)
            except Exception as get_err:
                logger.error("Failed to retrieve message %s: %s", msg_id, get_err)

        return results
    except Exception as exc:
        logger.error("Error listing Gmail messages: %s", exc)
        return []


def poll_and_filter_emails(
    last_checked_at: datetime,
    service=None,
    apply_relevance_gate: bool = True,
    force_fallback_gate: bool = False,
    only_relevant: bool = False,
    max_results: int = 50,
) -> List[Tuple[EmailMessage, RelevanceDecision]]:
    """
    Complete Day 8 Pipeline:
    1. Fetches candidate emails via Layer 1 Gmail query.
    2. Runs Layer 1 in-memory verification (pre-filter).
    3. Runs Layer 2 LLM Relevance Gate intent classification.
    
    Args:
        last_checked_at: Query timestamp boundary.
        service: Optional pre-built Gmail API resource.
        apply_relevance_gate: Whether to execute Layer 2 Relevance Gate.
        force_fallback_gate: If True, forces heuristic evaluation.
        only_relevant: If True, filters output to only emails where is_relevant is True.
        max_results: Maximum messages to retrieve per poll.
        
    Returns:
        List of tuples: (EmailMessage, RelevanceDecision) for all processed emails.
    """
    raw_emails = fetch_new_emails(last_checked_at=last_checked_at, service=service, max_results=max_results)
    filtered_results: List[Tuple[EmailMessage, RelevanceDecision]] = []

    for email in raw_emails:
        # Layer 1 In-Memory Safety Pre-Filter
        if not is_layer1_candidate(email.subject, email.sender):
            logger.debug(
                "Email '%s' rejected by Layer 1 in-memory filter.",
                email.subject
            )
            continue

        # Layer 2 LLM Relevance Gate
        if apply_relevance_gate:
            decision = check_email_relevance(
                subject=email.subject,
                sender=email.sender,
                body_text=email.body_text,
                force_fallback=force_fallback_gate,
            )
        else:
            decision = RelevanceDecision(
                is_relevant=True,
                confidence=1.0,
                category="BYPASS_GATE",
                reason="Relevance gate explicitly bypassed."
            )

        if only_relevant and not decision.is_relevant:
            continue

        filtered_results.append((email, decision))

    return filtered_results


# ==============================================================================
# Worker State Persistence (worker_config table)
# ==============================================================================

WORKER_CONFIG_LAST_CHECKED_KEY = "last_checked_at"


def get_worker_last_checked_at(session: Session, default_lookback_hours: int = 24) -> datetime:
    """
    Reads the last_checked_at timestamp from worker_config table.
    Defaults to 24 hours ago if unset.
    """
    record = session.query(WorkerConfig).filter(WorkerConfig.key == WORKER_CONFIG_LAST_CHECKED_KEY).first()
    if record and record.value:
        try:
            dt = datetime.fromisoformat(record.value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception as exc:
            logger.warning("Invalid ISO timestamp in worker_config (%s): %s", record.value, exc)

    # Fallback to default lookback
    return datetime.now(timezone.utc) - timedelta(hours=default_lookback_hours)


def update_worker_last_checked_at(session: Session, dt: datetime) -> None:
    """
    Persists the updated last_checked_at timestamp atomically in worker_config.
    """
    iso_val = dt.astimezone(timezone.utc).isoformat()
    stmt = pg_insert(WorkerConfig).values(
        key=WORKER_CONFIG_LAST_CHECKED_KEY,
        value=iso_val,
        updated_at=datetime.now(timezone.utc),
    ).on_conflict_do_update(
        index_elements=[WorkerConfig.key],
        set_={
            "value": iso_val,
            "updated_at": datetime.now(timezone.utc),
        }
    )
    session.execute(stmt)
    session.commit()
    logger.info("Updated worker_config %s -> %s", WORKER_CONFIG_LAST_CHECKED_KEY, iso_val)
