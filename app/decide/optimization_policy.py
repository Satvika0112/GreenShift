"""
Agent 2 — DECIDE
GreenShift Policy-Aware Optimization.

Canonical OptimizationPolicy enum, validation, and policy-specific candidate
ranking — the single source of truth for "how should GreenShift prioritize
carbon vs electricity cost", shared by the single-job scheduler
(app.decide.scheduler) and the contention-aware batch scheduler
(app.decide.batch_scheduler). Neither module defines its own copy of the
policy enum or ranking logic.

HARD CONSTRAINTS ARE NOT DECIDED HERE. This module only reorders candidates
that a caller has already filtered down to hard-constraint-feasible (deadline,
SLA, region, CPU/RAM/GPU, workload carbon budget, carbon/cost data
availability — see app.decide.scheduler._execute_schedule_job). A company's
optimization policy can never make an infeasible candidate feasible, and it
can never override a workload's own carbon budget or any other hard
constraint — it only decides which of the already-feasible candidates wins.

Supported policies (lexicographic ranking; no arbitrary weights):

  CARBON_FIRST (default — existing scheduler behavior, unchanged by this
  module's introduction):
    1. Minimum carbon emissions
    2. Minimum electricity cost
    3. Earliest start time (deterministic final tie-breaker)

  COST_FIRST:
    1. Minimum electricity cost
    2. Minimum carbon emissions
    3. Earliest start time (deterministic final tie-breaker)

  CARBON_CONSTRAINED:
    1. Find the minimum achievable carbon among the candidates passed in.
    2. carbon_limit = min_carbon * (1 + carbon_tolerance_pct / 100)
    3. Keep only candidates whose carbon <= carbon_limit.
    4. Among those: minimum electricity cost, then earliest start time.
    The tolerance is never silently relaxed and the policy never silently
    falls back to another policy — see rank_feasible_candidates() below.

Pareto optimization is NOT implemented as an operational policy here — it
remains a possible future/analytics feature only.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Callable, List, Optional, Sequence, TypeVar

# Precision thresholds for float comparison — the same values the scheduler
# has always used for its carbon/cost ranking (moved here as the canonical
# source; app.decide.scheduler and app.decide.batch_scheduler both import
# them from this module rather than redefining them).
CARBON_EPSILON = 1e-6
COST_EPSILON = 1e-6


class OptimizationPolicy(str, enum.Enum):
    CARBON_FIRST = "CARBON_FIRST"
    COST_FIRST = "COST_FIRST"
    CARBON_CONSTRAINED = "CARBON_CONSTRAINED"


# CARBON_FIRST is the existing scheduler's only behavior prior to this
# feature — it remains the default whenever no company policy has been
# configured yet, so introducing this module never changes a company's
# scheduling outcomes until they explicitly choose otherwise.
DEFAULT_POLICY = OptimizationPolicy.CARBON_FIRST

MIN_CARBON_TOLERANCE_PCT = 0.0
MAX_CARBON_TOLERANCE_PCT = 100.0
DEFAULT_CARBON_TOLERANCE_PCT = 5.0


class InvalidOptimizationPolicyError(ValueError):
    """Raised for an invalid policy or carbon_tolerance_pct value. Callers
    must surface this as a validation error (e.g. HTTP 422) — never catch
    it and silently substitute a different policy or a clamped tolerance."""


def validate_policy(value) -> OptimizationPolicy:
    """Validate and normalize a policy value. Raises InvalidOptimizationPolicyError
    for anything that isn't exactly one of the three supported policies —
    never silently substitutes a default."""
    if isinstance(value, OptimizationPolicy):
        return value
    try:
        return OptimizationPolicy(str(value).strip().upper())
    except (ValueError, AttributeError):
        valid = ", ".join(p.value for p in OptimizationPolicy)
        raise InvalidOptimizationPolicyError(
            f"Invalid optimization policy {value!r} — must be one of: {valid}"
        )


def validate_carbon_tolerance_pct(value) -> float:
    """Validate a carbon tolerance percentage. Must be a finite number within
    [MIN_CARBON_TOLERANCE_PCT, MAX_CARBON_TOLERANCE_PCT]. Raises
    InvalidOptimizationPolicyError otherwise — never clamps or rounds a
    caller-supplied value into range."""
    try:
        pct = float(value)
    except (TypeError, ValueError):
        raise InvalidOptimizationPolicyError(f"carbon_tolerance_pct must be numeric, got {value!r}")
    if pct != pct or pct in (float("inf"), float("-inf")):  # NaN / +-inf guard
        raise InvalidOptimizationPolicyError("carbon_tolerance_pct must be a finite number")
    if pct < MIN_CARBON_TOLERANCE_PCT or pct > MAX_CARBON_TOLERANCE_PCT:
        raise InvalidOptimizationPolicyError(
            f"carbon_tolerance_pct must be between {MIN_CARBON_TOLERANCE_PCT} and "
            f"{MAX_CARBON_TOLERANCE_PCT}, got {pct}"
        )
    return pct


T = TypeVar("T")


def _default_carbon_of(c) -> Optional[float]:
    return getattr(c, "carbon_emission_kg", None)


def _default_cost_of(c) -> Optional[float]:
    return getattr(c, "electricity_cost", None)


def _default_start_of(c) -> datetime:
    return getattr(c, "start_time")


def min_carbon_kg(
    candidates: Sequence[T],
    carbon_of: Callable[[T], Optional[float]] = _default_carbon_of,
) -> float:
    """Minimum carbon emissions (kg CO2) among `candidates`. Callers use this
    to report "minimum achievable carbon" in explanations/benchmarks —
    kept as a small standalone helper so it can be computed once and reused
    without re-deriving it from rank_feasible_candidates' output."""
    return min((carbon_of(c) or 0.0) for c in candidates)


def rank_feasible_candidates(
    candidates: Sequence[T],
    policy: OptimizationPolicy,
    carbon_tolerance_pct: Optional[float] = None,
    *,
    carbon_of: Callable[[T], Optional[float]] = _default_carbon_of,
    cost_of: Callable[[T], Optional[float]] = _default_cost_of,
    start_of: Callable[[T], datetime] = _default_start_of,
) -> List[T]:
    """
    Return `candidates` reordered best-first per `policy`. Non-mutating and
    total on the input: the result is always a permutation of `candidates`
    (nothing is dropped), so callers needing a complete deterministic
    ordering — e.g. explainability rank metadata, or a capacity-fallback
    site that must still pick *something* from candidates outside the
    tolerance — can always index into it safely.

    `candidates` must already be hard-constraint-feasible; this function
    only ever reorders, it never evaluates or applies feasibility.

    For CARBON_CONSTRAINED, the minimum carbon (and therefore the tolerance
    limit) is computed from exactly the candidate set passed to this call.
    This means the minimum-carbon candidate is always a member of its own
    "within tolerance" set by construction — the tolerance can never end up
    with zero eligible candidates, so there is never a silent-relaxation or
    silent-fallback decision to make. Callers must pass the correctly-scoped
    feasible set for whatever they are ranking (see app.decide.scheduler and
    app.decide.batch_scheduler for the two call sites and how each scopes
    its candidate set).
    """
    if not candidates:
        return []

    if policy == OptimizationPolicy.CARBON_FIRST:
        return sorted(
            candidates,
            key=lambda c: (
                round((carbon_of(c) or 0.0) / CARBON_EPSILON) * CARBON_EPSILON,
                round((cost_of(c) or 0.0) / COST_EPSILON) * COST_EPSILON,
                start_of(c),
            ),
        )

    if policy == OptimizationPolicy.COST_FIRST:
        return sorted(
            candidates,
            key=lambda c: (
                round((cost_of(c) or 0.0) / COST_EPSILON) * COST_EPSILON,
                round((carbon_of(c) or 0.0) / CARBON_EPSILON) * CARBON_EPSILON,
                start_of(c),
            ),
        )

    if policy == OptimizationPolicy.CARBON_CONSTRAINED:
        tol = validate_carbon_tolerance_pct(
            carbon_tolerance_pct if carbon_tolerance_pct is not None else DEFAULT_CARBON_TOLERANCE_PCT
        )
        min_carbon = min_carbon_kg(candidates, carbon_of=carbon_of)
        carbon_limit = min_carbon * (1.0 + tol / 100.0)

        within_ids = set()
        within: List[T] = []
        outside: List[T] = []
        for c in candidates:
            # + CARBON_EPSILON guards the boundary against float rounding —
            # never excludes a candidate genuinely inside the tolerance, and
            # never widens the tolerance beyond what the percentage allows.
            if (carbon_of(c) or 0.0) <= carbon_limit + CARBON_EPSILON:
                within.append(c)
                within_ids.add(id(c))
            else:
                outside.append(c)

        within_sorted = sorted(
            within,
            key=lambda c: (
                round((cost_of(c) or 0.0) / COST_EPSILON) * COST_EPSILON,
                start_of(c),
            ),
        )
        outside_sorted = sorted(
            outside,
            key=lambda c: (
                round((carbon_of(c) or 0.0) / CARBON_EPSILON) * CARBON_EPSILON,
                round((cost_of(c) or 0.0) / COST_EPSILON) * COST_EPSILON,
                start_of(c),
            ),
        )
        return within_sorted + outside_sorted

    raise InvalidOptimizationPolicyError(f"Unsupported optimization policy: {policy!r}")


def build_policy_reason(
    policy: OptimizationPolicy,
    *,
    carbon_kg: float,
    cost_usd: float,
    start_time,
    carbon_tolerance_pct: Optional[float] = None,
    min_carbon_kg: Optional[float] = None,
) -> str:
    """
    Build the human-readable explanation for a policy-ranked decision.

    CARBON_FIRST's wording is intentionally byte-identical to the
    scheduler's pre-policy-layer text (tests/test_scheduler_explainability.py
    asserts on the "Lowest-carbon feasible window" substring) — introducing
    this policy layer must not change the explanation a user already sees
    for the existing default policy.
    """
    start_iso = start_time.isoformat() if hasattr(start_time, "isoformat") else str(start_time)

    if policy == OptimizationPolicy.CARBON_FIRST:
        return (
            f"Lowest-carbon feasible window ({carbon_kg:.4f} kg CO2). "
            f"Electricity cost (${cost_usd:.4f}) was used as secondary tie-breaker, "
            f"and earliest start time ({start_iso}) as deterministic final tie-breaker."
        )

    if policy == OptimizationPolicy.COST_FIRST:
        return (
            f"Selected the feasible window with minimum electricity cost (${cost_usd:.4f}). "
            f"Carbon emissions ({carbon_kg:.4f} kg CO2) were used as a secondary criterion, "
            f"and earliest start time ({start_iso}) as deterministic final tie-breaker."
        )

    if policy == OptimizationPolicy.CARBON_CONSTRAINED:
        pct = carbon_tolerance_pct if carbon_tolerance_pct is not None else DEFAULT_CARBON_TOLERANCE_PCT
        min_part = f"{min_carbon_kg:.4f} kg CO2" if min_carbon_kg is not None else "the minimum achievable carbon"
        return (
            f"Selected the lowest-cost feasible window (${cost_usd:.4f}) within {pct:g}% "
            f"of the minimum achievable carbon emissions ({min_part}) — selected window carbon: "
            f"{carbon_kg:.4f} kg CO2. Earliest start time ({start_iso}) was the deterministic "
            f"final tie-breaker."
        )

    raise InvalidOptimizationPolicyError(f"Unsupported optimization policy: {policy!r}")
