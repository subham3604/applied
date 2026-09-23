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

import os
import re
import uuid
from datetime import datetime, timezone
from typing import List, Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from db.models import Application, ApplicationStatus, EventSource, InboundTriageItem, MasterExperienceVault, PipelineEvent, ResumeSnapshot, WorkerConfig
from db.session import SessionLocal, Base, engine
from web.queries import get_pipeline_metrics
from web.services.pipeline import PipelineResult, process_raw_jd
from web.services.rag_engine import embed_text
from web.services.state_controller import apply_manual_override, apply_manual_update

import logging
import threading
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("web.main")

_worker_scheduler: Optional[BackgroundScheduler] = None
_is_syncing: bool = False


def _run_worker_sync_safe():
    global _is_syncing
    if _is_syncing:
        logger.info("Worker sync already in progress, skipping concurrent run.")
        return {"status": "already_running"}
    _is_syncing = True
    try:
        from worker.worker import run_poll_cycle
        summary = run_poll_cycle()
        logger.info("Worker sync completed: %s", summary)
        return summary
    except Exception as exc:
        logger.error("Error during worker sync execution: %s", exc, exc_info=True)
        return {"error": str(exc)}
    finally:
        _is_syncing = False


# ==============================================================================
# App & CORS
# ==============================================================================

app = FastAPI(
    title="Relay API",
    description="Backend API for the Relay autonomous job application tracker.",
    version="1.0.0",
)

@app.on_event("startup")
def on_startup():
    global _worker_scheduler
    try:
        Base.metadata.create_all(bind=engine)
    except Exception:
        pass

    # Start embedded APScheduler for automated daily Gmail polling
    try:
        scheduler = BackgroundScheduler()
        cron_hour = int(os.getenv("WORKER_CRON_HOUR", "8"))
        cron_minute = int(os.getenv("WORKER_CRON_MINUTE", "0"))
        scheduler.add_job(
            func=_run_worker_sync_safe,
            trigger=CronTrigger(hour=cron_hour, minute=cron_minute, timezone="UTC"),
            id="daily_gmail_sync",
            name="Daily Autonomous Gmail Poller",
            replace_existing=True,
        )
        scheduler.start()
        _worker_scheduler = scheduler
        logger.info("Started embedded APScheduler for Gmail sync (Daily at %02d:%02d UTC)", cron_hour, cron_minute)
    except Exception as exc:
        logger.warning("Could not start background scheduler: %s", exc)

    # If run-on-startup is enabled, run an initial sync in a daemon thread
    run_on_startup = os.getenv("WORKER_RUN_ON_STARTUP", "true").lower() in ("1", "true", "yes")
    if run_on_startup:
        logger.info("Triggering initial background Gmail sync on startup...")
        threading.Thread(target=_run_worker_sync_safe, daemon=True).start()


@app.on_event("shutdown")
def on_shutdown():
    global _worker_scheduler
    if _worker_scheduler and _worker_scheduler.running:
        _worker_scheduler.shutdown(wait=False)



cors_origins_env = os.getenv("CORS_ORIGINS", "")
allowed_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "https://relay.vercel.app",
]
if cors_origins_env:
    allowed_origins.extend([o.strip() for o in cors_origins_env.split(",") if o.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"^https:\/\/.*\.vercel\.app$",
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


class AssignTriageRequest(BaseModel):
    application_id: str
    new_status: str
    note: Optional[str] = ""


class CreateFromTriageRequest(BaseModel):
    company_name: str
    role_title: str
    status: Optional[str] = "APPLIED"
    note: Optional[str] = ""


class UpdateApplicationRequest(BaseModel):
    company_name: Optional[str] = None
    role_title: Optional[str] = None
    location: Optional[str] = None
    primary_tech_stack: Optional[List[str]] = None
    source_platform: Optional[str] = None
    job_description_raw: Optional[str] = None



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
    Returns (deadline_text, tone) for a detected deadline.
    tone: "danger" if overdue or < 2 days, "warning" if < 7 days.
    """
    if not deadline_dt:
        return None, None
    now = datetime.now(timezone.utc)
    if deadline_dt.tzinfo is None:
        deadline_dt = deadline_dt.replace(tzinfo=timezone.utc)
    delta = deadline_dt - now
    time_str = deadline_dt.strftime("%b %d, %I:%M %p").replace(" 0", " ")
    if delta.total_seconds() < 0:
        abs_days = abs(delta.days)
        if abs_days == 0:
            return f"Overdue: {time_str}", "danger"
        return f"Overdue ({abs_days}d ago)", "danger"
    days = delta.days
    tone = "danger" if days < 2 else "warning"
    return f"Due: {time_str}", tone


def _format_applied(dt: Optional[datetime]) -> str:
    """Return friendly applied string e.g. 'Applied 3h ago', 'Applied yesterday', 'Applied Sep 15'."""
    if not dt:
        return "Applied recently"
    now = datetime.now(timezone.utc)
    ts = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    delta = now - ts
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 3600:
        mins = max(1, seconds // 60)
        return f"Applied {mins}m ago" if mins > 1 else "Applied just now"
    elif seconds < 86400:
        hours = seconds // 3600
        return f"Applied {hours}h ago"
    elif delta.days == 1 or (now.date() - ts.date()).days == 1:
        return "Applied yesterday"
    elif delta.days < 7:
        return f"Applied {delta.days}d ago"
    return f"Applied {ts.strftime('%b %d')}"


def _format_event_time(dt: Optional[datetime]) -> str:
    """Format timeline event timestamp e.g. 'Today, 3:02 AM' or 'Sep 17, 9:32 PM'."""
    if not dt:
        return ""
    now = datetime.now(timezone.utc)
    ts = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    delta = now - ts
    time_str = ts.strftime("%I:%M %p").lstrip("0")
    if delta.days == 0 and ts.date() == now.date():
        return f"Today, {time_str}"
    elif delta.days == 1 or (now.date() - ts.date()).days == 1:
        return f"Yesterday, {time_str}"
    elif delta.days < 7:
        return f"{ts.strftime('%b %d')}, {time_str}"
    return f"{ts.strftime('%b %d, %Y')}, {time_str}"


def _relative_date(dt: Optional[datetime]) -> str:
    """Return human-readable relative date string e.g. '3d ago', 'Today', 'Sep 5'."""
    return _format_event_time(dt)


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
        "id":        str(event.id),
        "title":     title,
        "detail":    detail,
        "date":      _format_event_time(event.created_at),
        "timestamp": event.created_at.isoformat() if event.created_at else None,
        "origin":    _SOURCE_TO_ORIGIN.get(event.source, "manual"),
        "payload":   raw,
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
    # ── Deadline: latest pipeline_event with a detected_deadline within the CURRENT stage
    deadline_text = None
    deadline_tone = None
    if app.current_status not in (ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN):
        sorted_events = sorted(
            app.pipeline_events or [], key=lambda e: e.created_at, reverse=True
        )
        for ev in sorted_events:
            # If we cross an event boundary into a prior status/stage,
            # deadlines belonging to that earlier stage are obsolete and resolved.
            if ev.to_status != app.current_status:
                break
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
        "applied":      _format_applied(app.applied_at),
        "applied_at":   app.applied_at.isoformat() if app.applied_at else "",
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


@app.patch("/api/applications/{app_id}")
def update_application(app_id: str, payload: UpdateApplicationRequest, db: Session = Depends(get_db)):
    """
    Update application fields (company, role, location, tech stack, source, JD).
    When company_name is modified:
    - Automatically updates canonical_company_name
    - Persists mapping into dynamic EntityAliasCache so subsequent inbound emails match seamlessly
    """
    try:
        uid = uuid.UUID(app_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid application ID format")

    app_row = db.query(Application).filter(Application.id == uid).first()
    if not app_row:
        raise HTTPException(status_code=404, detail="Application not found")

    if payload.company_name is not None and payload.company_name.strip():
        old_company = app_row.company_name
        new_company = payload.company_name.strip()
        app_row.company_name = new_company
        from web.services.schemas import normalize_company_name
        app_row.canonical_company_name = normalize_company_name(new_company)

        # Register user confirmation into dynamic alias cache
        try:
            from worker.entity_resolution import EntityAliasCache
            EntityAliasCache.set(new_company, new_company, db_session=db)
            if old_company and old_company.lower().strip() != new_company.lower().strip():
                EntityAliasCache.set(old_company, new_company, db_session=db)
        except Exception as e:
            logger.warning("Could not register updated company into EntityAliasCache: %s", e)

    if payload.role_title is not None and payload.role_title.strip():
        app_row.role_title = payload.role_title.strip()

    if payload.location is not None:
        app_row.location = payload.location.strip() or None

    if payload.primary_tech_stack is not None:
        app_row.primary_tech_stack = payload.primary_tech_stack

    if payload.source_platform is not None and payload.source_platform.strip():
        app_row.source_platform = payload.source_platform.strip()

    if payload.job_description_raw is not None:
        app_row.job_description_raw = payload.job_description_raw

    app_row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(app_row)

    return _serialize_application(app_row)


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

    app_row = db.query(Application).filter(Application.id == uid).first()
    if not app_row:
        raise HTTPException(status_code=404, detail="Application not found")

    snapshot = (
        db.query(ResumeSnapshot)
        .filter(
            ResumeSnapshot.application_id == uid,
            ResumeSnapshot.is_active == True,
        )
        .first()
    )
    if not snapshot:
        snapshot = ResumeSnapshot(
            id=uuid.uuid4(),
            application_id=uid,
            markdown_content=payload.markdown,
            is_user_edited=True,
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(snapshot)
    else:
        snapshot.markdown_content = payload.markdown
        snapshot.is_user_edited = True
        snapshot.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(snapshot)

    return {"success": True, "resume_snapshot_id": str(snapshot.id), "markdown": snapshot.markdown_content}


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
# Worker status — live background Gmail poller sync and health state
# ==============================================================================

@app.get("/api/worker/status")
def get_worker_status(db: Session = Depends(get_db)):
    """
    Returns live background Gmail worker status and sync information from worker_config.
    """
    row = db.query(WorkerConfig).filter(WorkerConfig.key == "last_checked_at").first()
    
    latest_event = (
        db.query(PipelineEvent)
        .filter(PipelineEvent.source == EventSource.GMAIL_WORKER)
        .order_by(PipelineEvent.created_at.desc())
        .first()
    )
    
    last_synced_dt = row.updated_at if row else (latest_event.created_at if latest_event else None)
    scheduler_running = _worker_scheduler.running if _worker_scheduler else False
    
    return {
        "active": scheduler_running or True,
        "is_syncing": _is_syncing,
        "schedule": "Daily at 08:00 AM UTC",
        "last_synced_at": last_synced_dt.isoformat() if last_synced_dt else None,
        "last_checked_boundary": row.value if row else None,
        "total_worker_events": (
            db.query(func.count(PipelineEvent.id))
            .filter(PipelineEvent.source == EventSource.GMAIL_WORKER)
            .scalar()
            or 0
        ),
    }


@app.post("/api/worker/sync")
def trigger_worker_sync():
    """
    Manually triggers an immediate autonomous Gmail polling and state machine cycle.
    """
    if _is_syncing:
        return {"success": False, "message": "A Gmail sync cycle is already in progress."}

    summary = _run_worker_sync_safe()
    if isinstance(summary, dict) and "error" in summary:
        raise HTTPException(status_code=500, detail=f"Gmail sync failed: {summary['error']}")
    return {"success": True, "summary": summary}



# ==============================================================================
# Master Experience Vault — CRUD & Dynamic Vector Embedding
# ==============================================================================

VAULT_CATEGORIES = ("WORK_EXPERIENCE", "PROJECT", "SKILL", "EDUCATION")


class VaultBulletCreateRequest(BaseModel):
    category: Literal["WORK_EXPERIENCE", "PROJECT", "SKILL", "EDUCATION"]
    title: str
    bullet_point: str
    tech_tags: List[str] = []


class VaultBulletUpdateRequest(BaseModel):
    category: Optional[Literal["WORK_EXPERIENCE", "PROJECT", "SKILL", "EDUCATION"]] = None
    title: Optional[str] = None
    bullet_point: Optional[str] = None
    tech_tags: Optional[List[str]] = None


@app.get("/api/vault")
def list_vault_bullets(
    category: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Lists all master experience vault bullets with optional category and keyword search filtering.
    """
    query = db.query(MasterExperienceVault)
    if category and category.upper() in VAULT_CATEGORIES:
        query = query.filter(MasterExperienceVault.category == category.upper())

    bullets = (
        query.order_by(
            MasterExperienceVault.category,
            MasterExperienceVault.title,
            MasterExperienceVault.created_at.desc(),
        ).all()
    )

    if search and search.strip():
        term = search.strip().lower()
        bullets = [
            b
            for b in bullets
            if term in b.title.lower()
            or term in b.bullet_point.lower()
            or any(term in tag.lower() for tag in (b.tech_tags or []))
        ]

    return [
        {
            "id": str(b.id),
            "category": b.category,
            "title": b.title,
            "bullet_point": b.bullet_point,
            "tech_tags": b.tech_tags or [],
            "created_at": b.created_at.isoformat() if b.created_at else "",
        }
        for b in bullets
    ]


@app.post("/api/vault")
def create_vault_bullet(
    body: VaultBulletCreateRequest,
    db: Session = Depends(get_db),
):
    """
    Creates a new experience bullet in the vault, generating a 1536-dim vector embedding.
    """
    if not body.title.strip():
        raise HTTPException(status_code=422, detail="Title cannot be empty.")
    if not body.bullet_point.strip():
        raise HTTPException(status_code=422, detail="Bullet point text cannot be empty.")

    try:
        embedding = embed_text(body.bullet_point.strip())
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to generate embedding: {str(exc)}"
        )

    bullet = MasterExperienceVault(
        id=uuid.uuid4(),
        category=body.category,
        title=body.title.strip(),
        bullet_point=body.bullet_point.strip(),
        tech_tags=body.tech_tags,
        embedding=embedding,
        created_at=datetime.now(timezone.utc),
    )
    db.add(bullet)
    db.commit()
    db.refresh(bullet)

    return {
        "id": str(bullet.id),
        "category": bullet.category,
        "title": bullet.title,
        "bullet_point": bullet.bullet_point,
        "tech_tags": bullet.tech_tags or [],
        "created_at": bullet.created_at.isoformat() if bullet.created_at else "",
    }


@app.patch("/api/vault/{id}")
def update_vault_bullet(
    id: str,
    body: VaultBulletUpdateRequest,
    db: Session = Depends(get_db),
):
    """
    Updates an existing vault bullet. Recomputes embedding if bullet_point text changes.
    """
    try:
        bullet_uuid = uuid.UUID(id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid bullet ID format.")

    bullet = (
        db.query(MasterExperienceVault)
        .filter(MasterExperienceVault.id == bullet_uuid)
        .first()
    )
    if not bullet:
        raise HTTPException(status_code=404, detail="Vault bullet not found.")

    if body.title is not None:
        if not body.title.strip():
            raise HTTPException(status_code=422, detail="Title cannot be empty.")
        bullet.title = body.title.strip()

    if body.category is not None:
        bullet.category = body.category

    if body.tech_tags is not None:
        bullet.tech_tags = body.tech_tags

    if body.bullet_point is not None:
        new_text = body.bullet_point.strip()
        if not new_text:
            raise HTTPException(
                status_code=422, detail="Bullet point text cannot be empty."
            )
        if new_text != bullet.bullet_point:
            bullet.bullet_point = new_text
            try:
                bullet.embedding = embed_text(new_text)
            except Exception as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to recompute embedding: {str(exc)}",
                )

    db.commit()
    db.refresh(bullet)

    return {
        "id": str(bullet.id),
        "category": bullet.category,
        "title": bullet.title,
        "bullet_point": bullet.bullet_point,
        "tech_tags": bullet.tech_tags or [],
        "created_at": bullet.created_at.isoformat() if bullet.created_at else "",
    }


@app.delete("/api/vault/{id}")
def delete_vault_bullet(
    id: str,
    db: Session = Depends(get_db),
):
    """
    Deletes a bullet from the master experience vault.
    """
    try:
        bullet_uuid = uuid.UUID(id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid bullet ID format.")

    bullet = (
        db.query(MasterExperienceVault)
        .filter(MasterExperienceVault.id == bullet_uuid)
        .first()
    )
    if not bullet:
        raise HTTPException(status_code=404, detail="Vault bullet not found.")

    db.delete(bullet)
    db.commit()
    return {"success": True, "deleted_id": str(bullet_uuid)}


# ==============================================================================
# Inbound Triage / Attention Required Endpoints
# ==============================================================================

def _serialize_triage_item(item: InboundTriageItem, db: Session) -> dict:
    candidate_apps = []
    if item.candidate_application_ids:
        app_uuids = []
        for cid in item.candidate_application_ids:
            try:
                app_uuids.append(uuid.UUID(str(cid)))
            except Exception:
                pass
        if app_uuids:
            apps = db.query(Application).filter(Application.id.in_(app_uuids)).all()
            candidate_apps = [
                {
                    "id": str(a.id),
                    "company": a.company_name,
                    "role": a.role_title,
                    "currentStatus": a.current_status.value,
                }
                for a in apps
            ]

    # Fallback to company name search if candidate_apps is empty
    if not candidate_apps and item.detected_company:
        term = f"%{item.detected_company.lower()}%"
        apps = db.query(Application).filter(func.lower(Application.company_name).like(term)).all()
        candidate_apps = [
            {
                "id": str(a.id),
                "company": a.company_name,
                "role": a.role_title,
                "currentStatus": a.current_status.value,
            }
            for a in apps
        ]

    # If still none, suggest recent applications
    if not candidate_apps:
        apps = db.query(Application).order_by(Application.applied_at.desc()).limit(3).all()
        candidate_apps = [
            {
                "id": str(a.id),
                "company": a.company_name,
                "role": a.role_title,
                "currentStatus": a.current_status.value,
            }
            for a in apps
        ]

    return {
        "id": str(item.id),
        "source": item.source,
        "sender": item.sender,
        "recipient": item.recipient,
        "subject": item.subject,
        "raw_body": item.raw_body,
        "detected_company": item.detected_company,
        "detected_role": item.detected_role,
        "suggested_stage": item.suggested_stage or "INTERVIEW_ROUND",
        "resolution_confidence": item.resolution_confidence,
        "resolution_note": item.resolution_note,
        "candidate_applications": candidate_apps,
        "status": item.status,
        "created_at": item.created_at.isoformat() if item.created_at else "",
    }


@app.get("/api/attention")
def get_attention_items(
    include_demo: bool = True,
    db: Session = Depends(get_db),
):
    """
    Returns all unresolved (PENDING) inbound items requiring user triage.
    """
    query = db.query(InboundTriageItem).filter(InboundTriageItem.status == "PENDING")
    if not include_demo:
        query = query.filter(
            InboundTriageItem.source != "DEMO",
            ~InboundTriageItem.sender.in_(["recruiting@bundltechnologies.com", "talent-team@stripe.com"])
        )
    items = query.order_by(InboundTriageItem.created_at.desc()).all()
    return [_serialize_triage_item(item, db) for item in items]


@app.post("/api/attention/{id}/assign")
def assign_attention_item(
    id: str,
    req: AssignTriageRequest,
    db: Session = Depends(get_db),
):
    """
    Assigns an ambiguous inbound item to an existing application, updates application
    status, and appends a verified PipelineEvent audit row.
    """
    try:
        item_uuid = uuid.UUID(id)
        app_uuid = uuid.UUID(req.application_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format.")

    item = db.query(InboundTriageItem).filter(InboundTriageItem.id == item_uuid).first()
    if not item:
        raise HTTPException(status_code=404, detail="Triage item not found.")

    target_app = db.query(Application).filter(Application.id == app_uuid).first()
    if not target_app:
        raise HTTPException(status_code=404, detail="Target application not found.")

    try:
        new_status_enum = ApplicationStatus(req.new_status)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{req.new_status}'. Allowed: {[s.value for s in ApplicationStatus]}",
        )

    # 1. Insert immutable PipelineEvent
    event_note = req.note or (
        f"User disambiguated inbound email from '{item.sender}' ({item.subject}) "
        f"and assigned to {target_app.company_name} ({target_app.role_title}) -> {new_status_enum.value}."
    )
    event = PipelineEvent(
        id=uuid.uuid4(),
        application_id=target_app.id,
        from_status=target_app.current_status,
        to_status=new_status_enum,
        source=EventSource.GMAIL_WORKER,
        raw_payload=item.raw_body,
        resolution_note=event_note,
        llm_confidence="HIGH",
        created_at=datetime.now(timezone.utc),
    )
    db.add(event)

    # 2. Advance target application status
    target_app.current_status = new_status_enum
    target_app.updated_at = datetime.now(timezone.utc)
    db.add(target_app)

    # 3. Mark triage item as RESOLVED
    item.status = "RESOLVED"
    item.resolved_application_id = target_app.id
    item.resolved_stage = new_status_enum.value
    item.resolved_at = datetime.now(timezone.utc)
    db.add(item)

    db.commit()
    return {"success": True, "application_id": str(target_app.id), "status": new_status_enum.value}


@app.post("/api/attention/{id}/create-application")
def create_application_from_attention(
    id: str,
    req: CreateFromTriageRequest,
    db: Session = Depends(get_db),
):
    """
    Creates a new Application from the triage item, appends initial PipelineEvent,
    and marks the triage item as RESOLVED.
    """
    try:
        item_uuid = uuid.UUID(id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format.")

    item = db.query(InboundTriageItem).filter(InboundTriageItem.id == item_uuid).first()
    if not item:
        raise HTTPException(status_code=404, detail="Triage item not found.")

    status_val = req.status or "APPLIED"
    try:
        status_enum = ApplicationStatus(status_val)
    except ValueError:
        status_enum = ApplicationStatus.APPLIED

    canonical_company = re.sub(r"[^\w\s]", "", req.company_name).strip().lower()
    new_app = Application(
        id=uuid.uuid4(),
        company_name=req.company_name.strip(),
        canonical_company_name=canonical_company,
        role_title=req.role_title.strip(),
        source_platform="Inbound Email",
        job_description_raw=item.raw_body,
        primary_tech_stack=[],
        current_status=status_enum,
        applied_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(new_app)
    db.flush()

    event = PipelineEvent(
        id=uuid.uuid4(),
        application_id=new_app.id,
        from_status=None,
        to_status=status_enum,
        source=EventSource.GMAIL_WORKER,
        raw_payload=item.raw_body,
        resolution_note=req.note or f"Created new application from inbound email '{item.subject}' ({item.sender}).",
        llm_confidence="HIGH",
        created_at=datetime.now(timezone.utc),
    )
    db.add(event)

    item.status = "RESOLVED"
    item.resolved_application_id = new_app.id
    item.resolved_stage = status_enum.value
    item.resolved_at = datetime.now(timezone.utc)
    db.add(item)

    db.commit()
    db.refresh(new_app)
    return {"success": True, "application_id": str(new_app.id)}


@app.post("/api/attention/{id}/dismiss")
def dismiss_attention_item(
    id: str,
    db: Session = Depends(get_db),
):
    """
    Dismisses an ambiguous triage item without modifying any applications.
    """
    try:
        item_uuid = uuid.UUID(id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format.")

    item = db.query(InboundTriageItem).filter(InboundTriageItem.id == item_uuid).first()
    if not item:
        raise HTTPException(status_code=404, detail="Triage item not found.")

    item.status = "DISMISSED"
    item.resolved_at = datetime.now(timezone.utc)
    db.add(item)
    db.commit()
    return {"success": True, "dismissed_id": str(item.id)}


@app.post("/api/attention/seed-demo")
def seed_demo_attention_items(
    db: Session = Depends(get_db),
):
    """
    Seeds initial realistic ambiguous triage items (Bundl/Swiggy, Stripe)
    via web.services.demo_seeder.
    """
    from web.services.demo_seeder import seed_demo_attention_data
    return seed_demo_attention_data(db)


@app.post("/api/attention/clear-demo")
def clear_demo_attention_items(
    db: Session = Depends(get_db),
):
    """
    Purges all demo/sample triage items from the database via web.services.demo_seeder.
    """
    from web.services.demo_seeder import clear_demo_attention_data
    return clear_demo_attention_data(db)



# ==============================================================================
# Health check — used by Docker healthcheck and Caddy upstream probes
# ==============================================================================

@app.get("/health")
def health():
    return {"status": "ok"}

