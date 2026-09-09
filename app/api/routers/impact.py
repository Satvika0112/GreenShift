"""
FastAPI Router for Fleet Impact & Actual Execution Analytics.
Provides endpoints for fleet-level savings aggregations, headline figures,
and real-world estimated vs. actual execution tracking.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.analytics.fleet_impact import compute_fleet_impact
from app.analytics.actual_impact import compute_actual_impact, compute_fleet_actual_impact
from app.shared.auth import AuthenticatedIdentity, get_current_identity, is_platform_admin
from app.shared.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/impact/fleet", summary="Full Fleet Impact Analysis")
def get_fleet_impact(
    team_id: Optional[str] = Query(None, description="Filter by team identifier"),
    tenant_id: Optional[str] = Query(None, description="Filter by tenant (Platform Admin only)"),
    region_id: Optional[str] = Query(None, description="Filter by grid region (e.g. IN-TG, IN-GJ)"),
    job_type: Optional[str] = Query(None, description="Filter by job type"),
    experiment_id: Optional[str] = Query(None, description="Optional experiment run identifier"),
    db: Session = Depends(get_db),
    identity: Optional[AuthenticatedIdentity] = Depends(get_current_identity),
) -> Dict[str, Any]:
    """
    Returns full fleet impact analysis including totals, mean/median/p90 reductions,
    regional breakdowns, team breakdowns, job type breakdowns, and distribution arrays.
    Enforces company/tenant isolation.
    """
    if identity and not is_platform_admin(identity) and tenant_id and tenant_id != identity.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot view fleet impact for other tenants")
    effective_tenant_id = tenant_id if (identity and is_platform_admin(identity)) else (identity.tenant_id if identity else tenant_id)

    report = compute_fleet_impact(
        db=db,
        team_id=team_id,
        tenant_id=effective_tenant_id,
        region_id=region_id,
        job_type=job_type,
        experiment_id=experiment_id,
    )
    return report.to_dict()


@router.get("/impact/fleet/headline", summary="Headline Fleet Savings")
def get_headline_impact(
    tenant_id: Optional[str] = Query(None, description="Filter by tenant (Platform Admin only)"),
    db: Session = Depends(get_db),
    identity: Optional[AuthenticatedIdentity] = Depends(get_current_identity),
) -> Dict[str, Any]:
    """
    Single-call headline numbers for presentations, executive summaries, and pitch decks.
    """
    if identity and not is_platform_admin(identity) and tenant_id and tenant_id != identity.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot view fleet impact for other tenants")
    effective_tenant_id = tenant_id if (identity and is_platform_admin(identity)) else (identity.tenant_id if identity else tenant_id)
    report = compute_fleet_impact(db=db, tenant_id=effective_tenant_id)
    return {
        "total_carbon_avoided_kg": report.total_carbon_avoided_kg,
        "avg_carbon_reduction_pct": report.avg_carbon_reduction_pct,
        "total_cost_saved_usd": report.total_cost_saved_usd,
        "total_cost_saved_inr": report.total_cost_saved_inr,
        "sla_compliance_pct": report.sla_compliance_pct,
        "total_jobs": report.total_jobs_with_decisions,
        "jobs_with_positive_savings": report.jobs_with_positive_carbon_savings,
    }


@router.get("/impact/job/{job_id}/actual", summary="Estimated vs Actual Impact for Job")
def get_actual_impact(
    job_id: str,
    db: Session = Depends(get_db),
    identity: Optional[AuthenticatedIdentity] = Depends(get_current_identity),
) -> Dict[str, Any]:
    """
    Estimated vs. actual execution impact and variance for a completed Kubernetes job.
    """
    from app.api.tenant_scope import get_tenant_jobs
    get_tenant_jobs(db, identity=identity, job_id=job_id)

    result = compute_actual_impact(db, job_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No execution history or actual start timestamp found for job '{job_id}'",
        )
    return result.to_dict()


@router.get("/impact/fleet/actual", summary="Fleet-Wide Actual vs Estimated Variance")
def get_fleet_actual_impact(
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Fleet-wide estimation accuracy analysis across all executed jobs.
    """
    summary = compute_fleet_actual_impact(db)
    return summary.to_dict()
