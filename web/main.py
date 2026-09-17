"""
web/main.py
============
FastAPI application — the HTTP bridge between the React frontend and all
backend services built in Phase 1 & 2.

Endpoints:
  GET  /api/metrics                        → stats bar counts
  GET  /api/applications                   → all applications (Kanban board)
  GET  /api/applications/{id}              → single application detail
  POST /api/applications/parse             → JD text → extract + tailor + save
  PATCH /api/applications/{id}/resume      → save edited resume snapshot
  PATCH /api/applications/{id}/status      → direct status override (zero LLM)
  POST  /api/applications/{id}/text-update → AI-parsed portal text drop

All response shapes match the TypeScript types in src/lib/relay-data.ts exactly.
"""

import uuid
from datetime import datetime, timezone
from typing import List, Literal, Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from db.models import Application, ApplicationStatus, EventSource, ResumeSnapshot
from db.session import SessionLocal
from web.queries import get_pipeline_metrics
from web.services.pipeline import PipelineResult, process_raw_jd
from web.services.state_controller import apply_manual_override, apply_manual_update

# ==============================================================================
# App & CORS
# ==============================================================================

app = FastAPI(
    title="Relay API",
    description="Backend API for the Relay autonomous job application tracker.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "https://relay.vercel.app",
        # Add your custom Vercel production domain here once configured
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================================================================
# DB Dependency
# ==============================================================================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==============================================================================
# Request Models
# ==============================================================================

class ParseJDRequest(BaseModel):
    jd_text: str
    source_platform: Optional[str] = "Direct"


class UpdateResumeRequest(BaseModel):
    markdown: str


class OverrideStatusRequest(BaseModel):
    # One of: APPLIED, OA_PENDING, INTERVIEW_ROUND, OFFER, REJECTED, WITHDRAWN
    new_status: str
    note: Optional[str] = ""


class TextUpdateRequest(BaseModel):
    raw_text: str


# ==============================================================================
# Serializers — map backend models → frontend TypeScript shapes
# ==============================================================================

# Backend ApplicationStatus → frontend Stage (relay-data.ts)
_STATUS_TO_STAGE: dict = {
    ApplicationStatus.APPLIED:         "applied",
    ApplicationStatus.OA_PENDING:      "oa",
    ApplicationStatus.INTERVIEW_ROUND: "interview",
    ApplicationStatus.OFFER:           "offer",
    ApplicationStatus.REJECTED:        "rejected",
    ApplicationStatus.WITHDRAWN:       "rejected",  # frontend lumps both into "rejected"
}

# Backend EventSource → frontend TimelineEvent.origin (relay-data.ts)
_SOURCE_TO_ORIGIN: dict = {
    EventSource.GMAIL_WORKER:    "worker",
    EventSource.MANUAL_DROP:     "manual",
    EventSource.MANUAL_OVERRIDE: "override",
}


def _deadline_display(deadline_dt: Optional[datetime]):
    """
    Returns (deadline_text, tone) for a future deadline, or (None, None) if past/absent.
    tone: "danger" if < 2 days, "warning" if < 7 days.
    """
    if not deadline_dt:
        return None, None
    now = datetime.now(timezone.utc)
    if deadline_dt.tzinfo is None:
        deadline_dt = deadline_dt.replace(tzinfo=timezone.utc)
    delta = deadline_dt - now
    if delta.total_seconds() < 0:
        return None, None
    days = delta.days
    time_str = deadline_dt.strftime("%b %d, %I:%M %p")
    tone = "danger" if days < 2 else "warning"
    return f"Due: {time_str}", tone


def _relative_date(dt: Optional[datetime]) -> str:
    """Return human-readable relative date string e.g. '3d ago', 'Today', 'Sep 5'."""
    if not dt:
        return ""
    now = datetime.now(timezone.utc)
    ts = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    delta = now - ts
    if delta.days == 0:
        hours = delta.seconds // 3600
        return f"{hours}h ago" if hours > 0 else "Today"
    elif delta.days == 1:
        return "Yesterday"
    elif delta.days < 7:
        return f"{delta.days}d ago"
    return ts.strftime("%b %d")


def _serialize_timeline_event(event) -> dict:
    """Serialize a PipelineEvent DB row → frontend TimelineEvent shape."""
    to_label = event.to_status.value.replace("_", " ").title()
    source_label = event.source.value.replace("_", " ").title()
    title = f"{to_label} ({source_label})"

    raw = event.raw_payload or ""
    detail = (
        event.resolution_note
        or (raw[:120] + "…" if len(raw) > 120 else raw)
    )

    return {
        "id":      str(event.id),
        "title":   title,
        "detail":  detail,
        "date":    _relative_date(event.created_at),
        "origin":  _SOURCE_TO_ORIGIN.get(event.source, "manual"),
        "payload": raw,
    }


def _serialize_application(
    app: Application,
    include_timeline: bool = True,
    include_resume: bool = True,
) -> dict:
    """
    Serialize a SQLAlchemy Application (with eager-loaded relationships) into
    the exact shape defined by the frontend Application type in relay-data.ts.

    Every field name and value maps 1:1 to what the TypeScript type expects.
    """
    # ── Deadline: latest pipeline_event with a future detected_deadline
    deadline_text = None
    deadline_tone = None
    sorted_events = sorted(
        app.pipeline_events or [], key=lambda e: e.created_at, reverse=True
    )
    for ev in sorted_events:
        if ev.detected_deadline:
            deadline_text, deadline_tone = _deadline_display(ev.detected_deadline)
            if deadline_text:
                break

    # ── Priority: interview stage or danger-level deadline
    is_priority = (
        app.current_status == ApplicationStatus.INTERVIEW_ROUND
        or deadline_tone == "danger"
    )

    # ── Active resume snapshot markdown
    resume_md = ""
    if include_resume:
        active = [s for s in (app.resume_snapshots or []) if s.is_active]
        if active:
            resume_md = active[0].markdown_content

    # ── Timeline events ordered oldest → newest
    timeline: list = []
    if include_timeline:
        ordered = sorted(app.pipeline_events or [], key=lambda e: e.created_at)
        timeline = [_serialize_timeline_event(ev) for ev in ordered]

    return {
        "id":           str(app.id),
        "company":      app.company_name,
        "role":         app.role_title,
        "stage":        _STATUS_TO_STAGE.get(app.current_status, "applied"),
        "source":       app.source_platform or "Direct",
        "applied":      app.applied_at.isoformat() if app.applied_at else "",
        "deadline":     deadline_text,
        "deadlineTone": deadline_tone,
        "stack":        app.primary_tech_stack or [],
        "priority":     is_priority,
        "location":     app.location or "",
        "timeline":     timeline,
        "resume":       resume_md,
    }


# ==============================================================================
# Routes
# ==============================================================================

@app.get("/api/metrics")
def get_metrics(db: Session = Depends(get_db)):
    """Stats bar counts. Matches frontend hardcoded stats shape."""
    return get_pipeline_metrics(db)


@app.get("/api/applications")
def list_applications(db: Session = Depends(get_db)):
    """
    All applications with eager-loaded pipeline_events and resume_snapshots.
    Used by index.tsx Kanban board — renders all stage columns.
    """
    apps = (
        db.query(Application)
        .options(
            joinedload(Application.pipeline_events),
            joinedload(Application.resume_snapshots),
        )
        .order_by(Application.updated_at.desc())
        .all()
    )
    return [_serialize_application(a) for a in apps]


@app.get("/api/applications/{app_id}")
def get_application(app_id: str, db: Session = Depends(get_db)):
    """Single application detail for DetailDrawer."""
    try:
        uid = uuid.UUID(app_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid application ID format")

    app_row = (
        db.query(Application)
        .options(
            joinedload(Application.pipeline_events),
            joinedload(Application.resume_snapshots),
        )
        .filter(Application.id == uid)
        .first()
    )
    if not app_row:
        raise HTTPException(status_code=404, detail="Application not found")
    return _serialize_application(app_row)


@app.post("/api/applications/parse")
def parse_and_tailor(payload: ParseJDRequest, db: Session = Depends(get_db)):
    """
    New Drop (CUJ-1): JD text → LLM extraction → RAG resume tailoring → DB save.
    Frontend calls this on "Parse & Tailor Resume" click.
    Application is saved immediately. application_id is returned so the
    frontend can call PATCH /resume if the user edits before confirming.
    """
    if not payload.jd_text or not payload.jd_text.strip():
        raise HTTPException(status_code=422, detail="jd_text cannot be empty")

    result: PipelineResult = process_raw_jd(
        raw_text=payload.jd_text,
        source_platform=payload.source_platform or "Direct",
        db=db,
    )

    if not result.success:
        return {
            "success":        False,
            "error":          result.error,
            "circuit_broken": result.circuit_broken,
        }

    return {
        "success":            True,
        "application_id":     str(result.application_id),
        # Metadata card fields — match frontend Application shape
        "company":            result.company_name,
        "role":               result.role_title,
        "stack":              result.primary_tech_stack,
        "location":           result.location or "",
        "source":             result.source_platform or "Direct",
        # Resume panel
        "resume":             result.markdown_resume,
        "guard_passed":       result.guard_passed,
        "extraction_retries": result.extraction_retries,
    }


@app.patch("/api/applications/{app_id}/resume")
def update_resume(app_id: str, payload: UpdateResumeRequest, db: Session = Depends(get_db)):
    """
    Save edited resume snapshot.
    Called when user modifies the Markdown textarea and clicks "Confirm & Save".
    Sets is_user_edited = True on the active snapshot.
    """
    try:
        uid = uuid.UUID(app_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid application ID format")

    snapshot = (
        db.query(ResumeSnapshot)
        .filter(
            ResumeSnapshot.application_id == uid,
            ResumeSnapshot.is_active == True,
        )
        .first()
    )
    if not snapshot:
        raise HTTPException(
            status_code=404,
            detail="No active resume snapshot found for this application",
        )

    snapshot.markdown_content = payload.markdown
    snapshot.is_user_edited = True
    snapshot.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {"success": True, "resume_snapshot_id": str(snapshot.id)}


@app.patch("/api/applications/{app_id}/status")
def override_status(app_id: str, payload: OverrideStatusRequest, db: Session = Depends(get_db)):
    """
    Direct Status Override (CUJ-4) — zero LLM cost.
    "Direct Override" tab in DetailDrawer.
    Accepts any new_status, including backward corrections (correcting a wrong
    auto-classification). Logs a MANUAL_OVERRIDE pipeline_event.
    """
    try:
        event = apply_manual_override(
            application_id=app_id,
            new_status=payload.new_status.upper(),
            note=payload.note or "",
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "success":    True,
        "event_id":   str(event.id),
        "new_status": event.to_status.value,
        # Return frontend stage immediately so UI can update without a refetch
        "stage":      _STATUS_TO_STAGE.get(event.to_status, "applied"),
    }


@app.post("/api/applications/{app_id}/text-update")
def text_update(app_id: str, payload: TextUpdateRequest, db: Session = Depends(get_db)):
    """
    AI-parsed portal text drop (CUJ-3) — "Paste Portal Snippet" tab in DetailDrawer.
    Classifies the pasted text, validates transition against the state DAG,
    updates application status, and logs a MANUAL_DROP pipeline_event.
    """
    if not payload.raw_text or not payload.raw_text.strip():
        raise HTTPException(status_code=422, detail="raw_text cannot be empty")

    try:
        event = apply_manual_update(
            application_id=app_id,
            raw_text=payload.raw_text,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "success":    True,
        "event_id":   str(event.id),
        "new_status": event.to_status.value,
        "stage":      _STATUS_TO_STAGE.get(event.to_status, "applied"),
    }


# ==============================================================================
# Health check — used by Docker healthcheck and Caddy upstream probes
# ==============================================================================

@app.get("/health")
def health():
    return {"status": "ok"}
