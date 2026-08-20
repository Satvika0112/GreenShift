"""
Agent 1 — INGEST
Ingest-specific models (deprecated — use app.shared.models).
This file exists for compatibility with the project spec. All canonical
models live in app.shared.models. Import from there.
"""

from app.shared.models import (  # noqa: F401 — re-export
    JobSubmitRequest,
    JobSubmitResponse,
    CarbonDataPoint,
    TariffDataPoint,
    JobORM,
    JobStatus,
)
