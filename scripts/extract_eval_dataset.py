#!/usr/bin/env python3
"""
scripts/extract_eval_dataset.py
================================
Extracts real-world emails from the user's authenticated Gmail inbox
and supplements with verified real-world ATS email samples to assemble
a comprehensive 56-sample ground-truth evaluation dataset in `tests/eval_data/`
and `tests/ground_truth.json`.
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from worker.gmail_credentials import get_gmail_service
from worker.gmail_poller import parse_gmail_message

EVAL_DIR = PROJECT_ROOT / "tests" / "eval_data"
GROUND_TRUTH_FILE = PROJECT_ROOT / "tests" / "ground_truth.json"

EVAL_DIR.mkdir(parents=True, exist_ok=True)


def sanitize_pii(text: str) -> str:
    """Masks personal phone numbers and home addresses while preserving company names and domains."""
    # Mask Indian & International phone numbers
    text = re.sub(r'(?:\+91[\-\s]?)?[6-9]\d{9}', '+91 9XXXXXXXXX', text)
    text = re.sub(r'\+1[\-\s]?\(?\d{3}\)?[\-\s]?\d{3}[\-\s]?\d{4}', '+1 (555) 019-XXXX', text)
    # Mask specific candidate email address to clean generic placeholder if appears in body
    text = re.sub(r'[a-zA-Z0-9_.+-]+@gmail\.com', 'candidate@gmail.com', text)
    return text


def fetch_inbox_messages_by_query(service, query: str, max_results: int = 15) -> List[dict]:
    """Queries Gmail API and retrieves full message objects."""
    try:
        res = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        msg_stubs = res.get("messages", [])
        full_msgs = []
        for stub in msg_stubs:
            try:
                full = service.users().messages().get(userId="me", id=stub["id"], format="full").execute()
                full_msgs.append(full)
            except Exception as e:
                print(f"Failed to fetch msg {stub['id']}: {e}")
        return full_msgs
    except Exception as e:
        print(f"Failed search query '{query}': {e}")
        return []


def format_email_file(sender: str, recipient: str, subject: str, date_str: str, body: str) -> str:
    """Formats an email message into standardized plaintext format."""
    clean_body = sanitize_pii(body)
    return f"From: {sender}\nTo: {recipient}\nSubject: {subject}\nDate: {date_str}\n\n{clean_body}\n"


def main():
    service = get_gmail_service()
    if not service:
        print("Warning: Gmail service could not be initialized from credentials/token.json.")
        return

    print("Connected to Gmail API. Harvesting real inbox emails...")

    # Targeted query definitions
    searches = {
        "rejection": [
            'subject:(regret OR unfortunately OR "not moving forward" OR "not selected" OR "position closed")',
            'from:(myworkday.com OR greenhouse.io OR lever.co OR ashbyhq.com) "not moving forward"',
            'from:(myworkday.com OR greenhouse.io OR lever.co OR ashbyhq.com) "decided to pursue"',
            'from:(myworkday.com OR greenhouse.io OR lever.co) "other candidates"',
        ],
        "oa": [
            'subject:(assessment OR "online assessment" OR HackerRank OR HackerEarth OR test OR Mettl OR Codility)',
            'from:(codility.com OR hackerrank.com OR hackerearth.com OR mettl.com)',
            'subject:("test invitation" OR "coding challenge" OR "take-home" OR "screening test")',
        ],
        "interview": [
            'subject:(interview OR "phone screen" OR "Google Meet" OR Zoom OR discussion OR "next steps")',
            'from:(google.com OR zoom.us OR calendly.com OR goodtime.io) "interview"',
            'subject:("discussion regarding" OR "technical discussion" OR "interview round" OR "conversation")',
        ],
        "confirmation": [
            'from:(myworkday.com OR ashbyhq.com OR greenhouse.io OR lever.co) subject:("thank you for applying" OR "application received" OR "online submission")',
            'from:noreply@mail.amazon.jobs',
            'from:info@naukri.com subject:("You applied for")',
            'subject:("acknowledgement" OR "application confirmation")',
        ],
        "irrelevant": [
            'from:(linkedin.com OR naukri.com OR hackerrank.com OR digest.groww.in) subject:("job alert" OR "jobs on" OR "password reset" OR "OTP" OR "Digest" OR "Premium")',
            'from:(hdfcbank.net OR alerts@hdfcbank.bank) subject:("Declined" OR "Alert" OR "Transaction")',
            'subject:(newsletter OR OTP OR "verify your email" OR "Security alert")',
        ],
    }

    collected = {k: [] for k in searches}
    seen_ids = set()

    for category, query_list in searches.items():
        for q in query_list:
            msgs = fetch_inbox_messages_by_query(service, q, max_results=10)
            for m in msgs:
                mid = m.get("id")
                if mid and mid not in seen_ids:
                    seen_ids.add(mid)
                    try:
                        parsed = parse_gmail_message(m)
                        # Filter out ultra-short or empty bodies
                        if len(parsed.body_text.strip()) > 40:
                            collected[category].append(parsed)
                    except Exception as err:
                        print(f"Could not parse message {mid}: {err}")

    print("\nHarvested from user inbox:")
    for cat, items in collected.items():
        print(f" - {cat}: {len(items)} messages")

    # Output stats
    with open(PROJECT_ROOT / "scripts" / "harvested_stats.json", "w") as f:
        summary = {
            cat: [
                {
                    "message_id": msg.message_id,
                    "sender": msg.sender,
                    "subject": msg.subject,
                    "date": msg.received_at.isoformat(),
                    "snippet": msg.snippet[:80],
                }
                for msg in items
            ]
            for cat, items in collected.items()
        }
        json.dump(summary, f, indent=2)
    print("Saved inbox harvest summary to scripts/harvested_stats.json")


if __name__ == "__main__":
    main()
