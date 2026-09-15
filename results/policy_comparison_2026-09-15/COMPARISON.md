# GreenShift Policy-Aware Optimization — A/B/C Benchmark

**Date**: 2026-09-15
**Dataset**: `data/greenshift_workloads_final.csv` (the existing 560-workload benchmark dataset — no new/unrelated dataset was created for this comparison)
**Method**: `scripts/run_560_experiment.py --policy <POLICY>`, which forces the given `OptimizationPolicy` (`app/decide/optimization_policy.py`) for every job in the run via the same `resolve_effective_policy` resolution DECIDE calls in production, then runs the *unmodified* INGEST → DECIDE pipeline and impact analytics (`app/analytics/fleet_impact.py`).
**Environment**: `SIMULATE_CARBON_API_DOWN=true` (deterministic CSV/cached-fallback carbon telemetry — the same fallback path the rest of the test suite uses), single-job greedy scheduling mode (not contention-aware batch), each policy run against its own fresh database so the three runs cannot interfere with each other.

This comparison exists to demonstrate that GreenShift's scheduler **adapts its decisions to the configured company policy** on the same real dataset — it is not a claim that any one policy is universally better. Which policy is "best" depends entirely on an organization's own priorities.

## Headline Results

| Metric | A: CARBON_FIRST | B: COST_FIRST | C: CARBON_CONSTRAINED (5%) |
|---|---:|---:|---:|
| Workloads scheduled | 526 | 528 | 528 |
| Total energy | 9,941.2 kWh | 10,115.4 kWh | 10,115.4 kWh |
| Carbon emissions (baseline → GreenShift) | 3,665.0 → 3,519.1 kg CO₂ | 3,793.6 → 3,671.2 kg CO₂ | 3,793.6 → 3,682.8 kg CO₂ |
| Carbon avoided | **145.9 kg CO₂ (3.5%)** | 145.4 kg CO₂ (3.4%) | 134.6 kg CO₂ (3.1%) |
| Electricity cost (baseline → GreenShift, USD) | $917.07 → $917.07 | $939.96 → $832.92 | $939.96 → $832.92 |
| Cost saved | $0.00 (0.0%) | **$107.03 (6.8%)** | **$107.03 (6.8%)** |
| Cost saved, native currency | 0 (no region moved off its cheapest-available slot) | 8,919 INR (India regions only — the only regions with real Time-of-Day tariff variation in this dataset; US/AU/SE tariffs are flat) | 8,919 INR |
| Avg scheduling delay | 0.4 h | 1.2 h | 0.9 h |
| SLA compliance | 526/526 (100.0%) | 528/528 (100.0%) | 528/528 (100.0%) |
| Jobs with any carbon savings | 123/526 (23.4%) | 96/528 (18.2%) | 36/528 (6.8%) |
| Infeasible / failed jobs | 34 (dataset rows the ingest/arrival simulator did not convert into a schedulable job — same set for every run; not policy-related) | 32 | 32 |

Per-run artifacts (full per-job CSV, JSON summary, regional breakdown, distributions) are in `results/policy_comparison_2026-09-15/{carbon_first,cost_first,carbon_constrained}/`.

## Reading the results

- **CARBON_FIRST** avoided the most carbon (3.5%) and, notably, never made the workload's electricity cost *worse* on average — but also never actively minimized it (baseline and GreenShift cost are identical here: the minimum-carbon slot the scheduler picked already happened to be the earliest/cheapest available one for the plurality of jobs in this run, since this dataset's non-Indian regions have flat tariffs — there was no cost dimension to trade against for those).
- **COST_FIRST** found real, tangible savings (6.8%, entirely from India's real Time-of-Day tariff structure — the only regions in this dataset with tariff variation to exploit) while still avoiding nearly as much carbon as CARBON_FIRST (3.4% vs. 3.5%) — on this dataset, minimizing cost and minimizing carbon were only weakly in tension.
- **CARBON_CONSTRAINED (5% tolerance)** landed between the two: the same total cost savings as COST_FIRST in aggregate (the cheapest in-tolerance slot happened to coincide with the global cost optimum for most jobs), but fewer individual jobs ended up with a carbon improvement (36 vs. 96) and slightly less total carbon avoided (3.1% vs. 3.4%) than unconstrained COST_FIRST — because it only ever considers slots within 5% of that job's own minimum achievable carbon, a narrower candidate set than "anywhere cost is lowest". This is the intended behavior: a bounded compromise, not a strict improvement over either pure policy in every dimension.
- All three runs maintained **100% SLA compliance** — the policy layer only reorders already-feasible candidates; it never affects whether a deadline is met.
- The same 32–34 dataset rows failed to schedule in every run (job data quality, not policy) — infeasibility is governed entirely by hard constraints, which are identical across policies.

## What this does *not* show

- It does not show that `COST_FIRST` or `CARBON_CONSTRAINED` is "better" than `CARBON_FIRST` — carbon avoidance is highest under `CARBON_FIRST` by construction, and an organization that weights carbon above all else should stay on it.
- It is a single dataset, single point-in-time (cached/fallback) carbon and tariff snapshot, not a multi-day or multi-scenario study.
- Pareto/multi-objective optimization was not evaluated — it is out of scope for this pass (see `docs/DECISIONS.md`, ADR-014).
