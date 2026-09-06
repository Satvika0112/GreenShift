"""
Agent 5 — PRESENT
FastAPI router — BRSR Report + Data Source endpoints.

Adds:
  GET /api/v1/report/summary      — JSON sustainability report
  GET /api/v1/report/csv          — CSV download
  GET /api/v1/report/markdown     — Markdown report
  GET /api/v1/data-sources/status — Which data sources (CSV/API/mock) are active
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.trust.report import generate_report, generate_csv, generate_markdown_summary
from app.ingest.data_sources import get_data_source_status
from app.shared.database import get_db
from app.shared.auth import get_current_user
from app.shared.models import UserORM
from app.shared.utils import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/report/summary")
def get_report_summary(
    team_id: Optional[str] = Query(None, description="Filter by team ID"),
    start_date: Optional[datetime] = Query(None, description="Filter from date (ISO8601)"),
    end_date: Optional[datetime] = Query(None, description="Filter to date (ISO8601)"),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """
    Generate a BRSR-style JSON sustainability report.
    Includes per-job carbon, cost, SLA metrics and aggregate summary.
    """
    try:
        return generate_report(db, team_id=team_id, start_date=start_date, end_date=end_date)
    except Exception as exc:
        logger.error(f"Error generating report summary: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while generating the sustainability report.")


@router.get("/report/csv", response_class=PlainTextResponse)
def get_report_csv(
    team_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """
    Download BRSR report as CSV.
    Suitable for BRSR annual report data submission.
    """
    try:
        csv_content = generate_csv(db, team_id=team_id)
        return PlainTextResponse(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": (
                    f"attachment; filename=greenshift_brsr_report_"
                    f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
                )
            },
        )
    except Exception as exc:
        logger.error(f"Error generating report CSV: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while generating the report CSV.")


@router.get("/report/markdown", response_class=PlainTextResponse)
def get_report_markdown(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Generate BRSR summary as Markdown text."""
    try:
        return PlainTextResponse(
            content=generate_markdown_summary(db),
            media_type="text/markdown",
        )
    except Exception as exc:
        logger.error(f"Error generating report markdown: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while generating the report markdown.")


@router.get("/data-sources/status")
def get_data_sources(
    current_user: UserORM = Depends(get_current_user),
):
    """
    Return the active data source for carbon and tariff data.
    Possible values: 'csv', 'api', 'mock'
    """
    try:
        return get_data_source_status()
    except Exception as exc:
        logger.error(f"Error getting data sources status: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while fetching data sources status.")

