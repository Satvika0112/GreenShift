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
from app.api.tenant_scope import is_team_restricted
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
    tenant_id: Optional[str] = Query(None, description="Filter by tenant ID (Platform Admin only)"),
    start_date: Optional[datetime] = Query(None, description="Filter from date (ISO8601)"),
    end_date: Optional[datetime] = Query(None, description="Filter to date (ISO8601)"),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """
    Generate a BRSR-style JSON sustainability report with tenant scoping.
    Includes per-job carbon, cost, SLA metrics and aggregate summary.
    """
    from app.shared.auth import is_company_admin, is_platform_admin
    if not is_platform_admin(current_user) and tenant_id and current_user.tenant_id and tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Cannot access reports for other tenants")
    effective_tenant = tenant_id if is_platform_admin(current_user) else current_user.tenant_id
    # A plain Company User's team_id is never client-overridable — clamped to
    # their own team regardless of what was requested, same fix as
    # /impact/fleet. Company Admin/Platform Admin may still filter by any
    # team_id, since tenant_id already bounds their real visibility.
    effective_team = team_id
    if not is_company_admin(current_user):
        effective_team = current_user.team_id
    try:
        return generate_report(
            db, team_id=effective_team, start_date=start_date, end_date=end_date, tenant_id=effective_tenant,
            team_restricted=is_team_restricted(current_user),
        )
    except Exception as exc:
        logger.error(f"Error generating report summary: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while generating the sustainability report.")


@router.get("/report/csv", response_class=PlainTextResponse)
def get_report_csv(
    team_id: Optional[str] = Query(None),
    tenant_id: Optional[str] = Query(None, description="Filter by tenant ID (Platform Admin only)"),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """
    Download BRSR report as CSV with tenant scoping.
    Suitable for BRSR annual report data submission.
    """
    from app.shared.auth import is_company_admin, is_platform_admin
    if not is_platform_admin(current_user) and tenant_id and current_user.tenant_id and tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Cannot access reports for other tenants")
    effective_tenant = tenant_id if is_platform_admin(current_user) else current_user.tenant_id
    effective_team = team_id
    if not is_company_admin(current_user):
        effective_team = current_user.team_id
    try:
        csv_content = generate_csv(
            db, team_id=effective_team, tenant_id=effective_tenant,
            team_restricted=is_team_restricted(current_user),
        )
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
    tenant_id: Optional[str] = Query(None, description="Filter by tenant ID (Platform Admin only)"),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Generate BRSR summary as Markdown text with tenant scoping."""
    from app.shared.auth import is_platform_admin
    if not is_platform_admin(current_user) and tenant_id and current_user.tenant_id and tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Cannot access reports for other tenants")
    effective_tenant = tenant_id if is_platform_admin(current_user) else current_user.tenant_id
    try:
        return PlainTextResponse(
            content=generate_markdown_summary(db, tenant_id=effective_tenant),
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

