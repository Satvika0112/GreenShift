"""
Agent 1 — INGEST
Job CSV Loader — loads real workloads from greenshift_workloads_final.csv.

Dataset columns (all required):
  job_id, job_type, team, priority, region, submit_time, earliest_start_time,
  deadline, runtime_hours, power_kw, energy_kwh, slack_hours, deferrable,
  container_image, cpu_request, memory_request, carbon_budget_kg

Key behaviours:
  - Validates all required columns are present.
  - Parses timestamps (submit_time, earliest_start_time, deadline) as UTC-aware.
  - Converts runtime_hours → runtime_minutes (× 60, rounded to int).
  - Preserves energy_kwh from dataset; recalculates only when value is zero or missing.
    Formula: energy_kwh = power_kw × runtime_hours
  - Validates deadline >= earliest_start_time per row.
  - Re-anchors historical deadlines to current time, preserving slack_hours window.
    (Most CSV records are from April 2026; raw deadlines would fail the API's
     "deadline must be in future" guard.)
  - Parses deferrable as bool (case-insensitive "TRUE"/"FALSE"/"1"/"0").
  - Handles invalid rows gracefully — collects errors, continues loading.
  - Returns (valid_jobs: list[dict], validation_errors: list[str]).

The returned dicts are compatible with JobSubmitRequest fields.
"""

import csv
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Required columns in the workloads CSV
# ─────────────────────────────────────────────────────────────────────────────

REQUIRED_COLUMNS = {
    "job_id", "job_type", "team", "priority", "region",
    "submit_time", "earliest_start_time", "deadline",
    "runtime_hours", "power_kw", "deferrable",
    "container_image", "cpu_request", "memory_request",
    "carbon_budget_kg",
}


from app.shared.timezone import normalize_to_utc


def _parse_timestamp(value: str, region: Optional[str] = None, timezone_name: Optional[str] = None) -> Optional[datetime]:
    """Parse an ISO-8601 / common datetime string to UTC-aware datetime using IANA timezone normalization."""
    if not value or value.strip() in ("", "None", "nan", "NaT"):
        return None
    try:
        return normalize_to_utc(value, region=region, timezone_name=timezone_name)
    except Exception:
        return None


def _parse_bool(value: str) -> bool:
    """Parse TRUE/FALSE/1/0/Yes/No strings to bool."""
    return value.strip().upper() in ("TRUE", "1", "YES", "T")


def _reanchor_to_future(
    earliest_start: datetime,
    deadline: datetime,
    slack_hours: float,
    now: datetime,
    runtime_hours: float = 1.0,
) -> Tuple[datetime, datetime]:
    """
    Re-anchor historical timestamps to the present while preserving the job's
    scheduling window characteristics (slack_hours + runtime_hours).
    """
    window = timedelta(hours=max(slack_hours + runtime_hours, 2.0))
    new_earliest = now
    new_deadline = now + window
    return new_earliest, new_deadline


def load_jobs_from_csv(
    csv_path: str,
    reanchor_historical: bool = True,
    validate_regions: bool = False,
) -> Tuple[List[Dict], List[str]]:
    """
    Load and validate workload jobs from a CSV file.

    Args:
        csv_path:            Path to greenshift_workloads_final.csv
        reanchor_historical: If True, re-anchor past deadlines to current time
                             preserving slack_hours. If False, keep original
                             timestamps (useful for testing/reporting).
        validate_regions:    If True, filter out jobs with unsupported regions.

    Returns:
        (valid_jobs, validation_errors)
        valid_jobs        — list of dicts compatible with JobSubmitRequest
        validation_errors — list of human-readable error strings for bad rows
    """
    path = Path(csv_path)
    if not path.exists():
        error = f"Job CSV not found: {csv_path}"
        logger.error(error)
        return [], [error]

    now = datetime.now(timezone.utc)
    valid_jobs: List[Dict] = []
    validation_errors: List[str] = []

    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = set(h.lower().strip() for h in (reader.fieldnames or []))

            # Validate required columns are present
            missing_cols = REQUIRED_COLUMNS - headers
            if missing_cols:
                error = (
                    f"Job CSV missing required columns: {sorted(missing_cols)}. "
                    f"Found: {sorted(headers)}"
                )
                logger.error(error)
                return [], [error]

            # Normalise header map: lowercase→original
            header_map = {h.lower().strip(): h for h in (reader.fieldnames or [])}

            def get(row: dict, col: str) -> str:
                return row.get(header_map.get(col, col), "").strip()

            for row_num, row in enumerate(reader, start=2):  # 2 because row 1 = header
                job_id = get(row, "job_id")
                if not job_id:
                    validation_errors.append(f"Row {row_num}: missing job_id — skipped")
                    continue

                # ── Parse region and validate if requested ────────────────
                region = get(row, "region") or "IN-SO"
                if validate_regions:
                    from app.ingest.regional_registry import is_supported_region
                    if not is_supported_region(region):
                        validation_errors.append(
                            f"Row {row_num} ({job_id}): region '{region}' is unsupported. "
                            f"(No tariff profile present in master_tod_tariff_all_regions.csv) — skipped"
                        )
                        continue

                # ── Parse timestamps with region-aware IANA normalization ─
                submit_time_raw    = get(row, "submit_time")
                earliest_start_raw = get(row, "earliest_start_time")
                deadline_raw       = get(row, "deadline")
                row_tz             = get(row, "timezone") or None

                submit_time    = _parse_timestamp(submit_time_raw, region=region, timezone_name=row_tz)
                earliest_start = _parse_timestamp(earliest_start_raw, region=region, timezone_name=row_tz)
                deadline       = _parse_timestamp(deadline_raw, region=region, timezone_name=row_tz)

                if submit_time is None:
                    validation_errors.append(
                        f"Row {row_num} ({job_id}): invalid submit_time '{submit_time_raw}' — skipped"
                    )
                    continue
                if earliest_start is None:
                    validation_errors.append(
                        f"Row {row_num} ({job_id}): invalid earliest_start_time '{earliest_start_raw}' — skipped"
                    )
                    continue
                if deadline is None:
                    validation_errors.append(
                        f"Row {row_num} ({job_id}): invalid deadline '{deadline_raw}' — skipped"
                    )
                    continue

                # ── Validate deadline >= earliest_start ───────────────────
                if deadline < earliest_start:
                    validation_errors.append(
                        f"Row {row_num} ({job_id}): deadline {deadline.isoformat()} "
                        f"< earliest_start {earliest_start.isoformat()} — skipped"
                    )
                    continue

                # ── Parse numeric fields ──────────────────────────────────
                try:
                    runtime_hours = float(get(row, "runtime_hours"))
                except ValueError:
                    validation_errors.append(
                        f"Row {row_num} ({job_id}): invalid runtime_hours '{get(row, 'runtime_hours')}' — skipped"
                    )
                    continue

                try:
                    power_kw = float(get(row, "power_kw"))
                    if power_kw <= 0:
                        raise ValueError("power_kw must be > 0")
                except ValueError as exc:
                    validation_errors.append(
                        f"Row {row_num} ({job_id}): invalid power_kw — {exc} — skipped"
                    )
                    continue

                try:
                    energy_kwh_raw = float(get(row, "energy_kwh"))
                except ValueError:
                    energy_kwh_raw = 0.0

                # Preserve dataset energy_kwh; recalculate only if zero/missing
                # Formula: energy_kwh = power_kw × runtime_hours
                if energy_kwh_raw > 0:
                    energy_kwh = energy_kwh_raw
                else:
                    energy_kwh = round(power_kw * runtime_hours, 6)
                    logger.debug(
                        "Row %d (%s): energy_kwh recalculated = %.4f kWh (%.2f kW × %.2f h)",
                        row_num, job_id, energy_kwh, power_kw, runtime_hours,
                    )

                try:
                    slack_hours_raw = float(get(row, "slack_hours"))
                    slack_hours = slack_hours_raw if slack_hours_raw > 0 else round(max(0.0, (deadline - earliest_start).total_seconds() / 3600.0 - runtime_hours), 4)
                except ValueError:
                    slack_hours = round(max(0.0, (deadline - earliest_start).total_seconds() / 3600.0 - runtime_hours), 4)

                try:
                    carbon_budget_kg_raw = get(row, "carbon_budget_kg")
                    carbon_budget_kg: Optional[float] = (
                        float(carbon_budget_kg_raw) if carbon_budget_kg_raw else None
                    )
                except ValueError:
                    carbon_budget_kg = None

                # ── Validate runtime fits in scheduling window ─────────────
                window_hours = (deadline - earliest_start).total_seconds() / 3600.0
                if runtime_hours > window_hours + 0.01:  # small tolerance
                    validation_errors.append(
                        f"Row {row_num} ({job_id}): runtime_hours {runtime_hours:.2f} "
                        f"exceeds scheduling window {window_hours:.2f}h — skipped"
                    )
                    continue

                # ── Re-anchor historical timestamps if needed ──────────────
                if reanchor_historical and deadline <= now:
                    earliest_start, deadline = _reanchor_to_future(
                        earliest_start, deadline, slack_hours, now, runtime_hours
                    )

                # Convert runtime_hours → runtime_minutes (internal representation)
                runtime_minutes = max(1, int(round(runtime_hours * 60)))

                # ── Parse other fields ────────────────────────────────────
                deferrable = _parse_bool(get(row, "deferrable"))
                team       = get(row, "team") or "unknown"
                priority   = get(row, "priority") or "MEDIUM"
                region     = get(row, "region") or "IN-SO"
                job_type   = get(row, "job_type") or ""
                container_image = get(row, "container_image") or "greenshift/sample-workload:latest"
                cpu_request     = get(row, "cpu_request") or "500m"
                memory_request  = get(row, "memory_request") or "512Mi"

                valid_jobs.append({
                    "job_id":              job_id,
                    "team_id":             team,
                    "job_type":            job_type,
                    "priority":            priority,
                    "region":              region,
                    "submit_time":         submit_time,
                    "deadline":            deadline,
                    "earliest_start_time": earliest_start,
                    "runtime_minutes":     runtime_minutes,
                    "power_kw":            power_kw,
                    "energy_kwh":          energy_kwh,
                    "slack_hours":         slack_hours,
                    "deferrable":          deferrable,
                    "container_image":     container_image,
                    "cpu_request":         cpu_request,
                    "memory_request":      memory_request,
                    "carbon_budget_kg":    carbon_budget_kg,
                })

    except Exception as exc:
        error = f"Failed to read job CSV {csv_path}: {exc}"
        logger.error(error)
        return valid_jobs, validation_errors + [error]

    logger.info(
        "Job CSV loaded: %d valid jobs, %d validation errors from %s",
        len(valid_jobs), len(validation_errors), csv_path,
    )
    return valid_jobs, validation_errors


def get_job_csv_count(csv_path: str) -> int:
    """Return the number of data rows in the job CSV (excluding header)."""
    path = Path(csv_path)
    if not path.exists():
        return 0
    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            return sum(1 for row in csv.reader(f)) - 1  # subtract header row
    except Exception:
        return 0
