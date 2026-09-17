"""
web/queries.py
==============
Database query helpers and aggregations for the FastAPI application.
"""

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from db.models import Application, ApplicationStatus


def get_pipeline_metrics(db: Session) -> dict:
    """
    Aggregate pipeline counts for the frontend stats bar.
    
    Returns:
        dict: {
            "total": int,
            "applied": int,
            "pending_oa": int,
            "active_interviews": int,
            "offers": int,
            "rejected": int,
        }
    """
    row = (
        db.query(
            func.count(Application.id).label("total"),
            func.count(
                case((Application.current_status == ApplicationStatus.APPLIED, 1))
            ).label("applied"),
            func.count(
                case((Application.current_status == ApplicationStatus.OA_PENDING, 1))
            ).label("pending_oa"),
            func.count(
                case((Application.current_status == ApplicationStatus.INTERVIEW_ROUND, 1))
            ).label("active_interviews"),
            func.count(
                case((Application.current_status == ApplicationStatus.OFFER, 1))
            ).label("offers"),
            func.count(
                case(
                    (
                        Application.current_status.in_(
                            [ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN]
                        ),
                        1,
                    )
                )
            ).label("rejected"),
        ).first()
    )

    if not row or row.total is None:
        return {
            "total": 0,
            "applied": 0,
            "pending_oa": 0,
            "active_interviews": 0,
            "offers": 0,
            "rejected": 0,
        }

    return {
        "total": row.total or 0,
        "applied": row.applied or 0,
        "pending_oa": row.pending_oa or 0,
        "active_interviews": row.active_interviews or 0,
        "offers": row.offers or 0,
        "rejected": row.rejected or 0,
    }
