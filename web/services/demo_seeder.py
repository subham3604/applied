"""
web/services/demo_seeder.py
===========================
Utility service to seed and clear realistic demo/mock triage attention items
and test records without bloating web/main.py.
"""

from datetime import datetime, timezone
import uuid
from typing import Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func

from db.models import Application, InboundTriageItem


def seed_demo_attention_data(db: Session) -> Dict[str, Any]:
    """
    Seeds initial realistic ambiguous triage items (Bundl/Swiggy, Stripe)
    if no pending items exist, marked with source="DEMO".
    """
    existing = (
        db.query(InboundTriageItem)
        .filter(
            (InboundTriageItem.source == "DEMO")
            | (InboundTriageItem.sender.in_(["recruiting@bundltechnologies.com", "talent-team@stripe.com"]))
        )
        .count()
    )
    if existing > 0:
        return {"success": True, "message": f"{existing} demo triage items already exist."}

    swiggy_apps = db.query(Application).filter(func.lower(Application.company_name).like("%swiggy%")).all()
    swiggy_ids = [str(a.id) for a in swiggy_apps]

    item1 = InboundTriageItem(
        id=uuid.uuid4(),
        source="DEMO",
        sender="recruiting@bundltechnologies.com",
        subject="Next steps regarding your application at Bundl Technologies (Swiggy)",
        raw_body=(
            "Hi candidate, thank you for your application to Bundl Technologies (Swiggy). "
            "We were impressed with your engineering background and would like to schedule a "
            "technical discussion regarding your candidacy. Please confirm which application and stage to update."
        ),
        detected_company="Bundl Technologies",
        detected_role="Full Stack Engineer",
        suggested_stage="INTERVIEW_ROUND",
        resolution_confidence="AMBIGUOUS",
        resolution_note="Multiple active applications found under alias 'Bundl Technologies / Swiggy'. Needs user disambiguation.",
        candidate_application_ids=swiggy_ids,
        status="PENDING",
        created_at=datetime.now(timezone.utc),
    )
    db.add(item1)

    item2 = InboundTriageItem(
        id=uuid.uuid4(),
        source="DEMO",
        sender="talent-team@stripe.com",
        subject="Update on your interview loop at Stripe",
        raw_body=(
            "Hello, our hiring committee has reviewed your profile and wanted to coordinate the "
            "upcoming technical interview rounds with our payments infrastructure engineering group."
        ),
        detected_company="Stripe",
        detected_role="Software Engineer - Infrastructure",
        suggested_stage="INTERVIEW_ROUND",
        resolution_confidence="AMBIGUOUS",
        resolution_note="Sender domain matches Stripe, but application role title differs between Backend Engineer and Infrastructure Engineer.",
        candidate_application_ids=[],
        status="PENDING",
        created_at=datetime.now(timezone.utc),
    )
    db.add(item2)

    db.commit()
    return {"success": True, "seeded": 2}


def clear_demo_attention_data(db: Session) -> Dict[str, Any]:
    """
    Purges all demo/sample triage items from the database.
    """
    items = (
        db.query(InboundTriageItem)
        .filter(
            (InboundTriageItem.source == "DEMO")
            | (InboundTriageItem.sender.in_(["recruiting@bundltechnologies.com", "talent-team@stripe.com"]))
        )
        .all()
    )
    count = len(items)
    for it in items:
        db.delete(it)
    db.commit()
    return {"success": True, "deleted": count}
