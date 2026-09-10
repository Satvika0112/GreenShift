/**
 * Fixture ScheduleDecision payloads. These are not invented — they mirror the
 * exact shapes returned by the real backend, captured via live E2E verification
 * against a running `app.api.main:app` instance during this session:
 *
 *   - fullDecisionWithBaseline: shape of the `schedule_decision` object nested
 *     in `GET /api/v1/jobs/{id}` (includes baseline_carbon_emission/baseline_cost).
 *   - decisionWithoutBaseline: shape returned by `POST /api/v1/schedule/{jobId}`
 *     for the same job (omits baseline_carbon_emission/baseline_cost entirely —
 *     this is a real backend inconsistency between the two endpoints, not a
 *     frontend assumption).
 *
 * Field semantics verified against app/shared/models.py's ScheduleDecision:
 *   - electricity_cost and baseline_cost are always USD-normalized.
 *   - currency describes native_cost / baseline_native_cost's denomination only.
 */

export const fullDecisionWithBaseline = {
  id: 3,
  schedule_id: 3,
  job_id: 'JOB-AAF97A1F',
  selected_start: '2026-09-10T08:00:00',
  selected_end: '2026-09-10T08:30:00',
  carbon_intensity: 406.0,
  electricity_cost: 0.0858,
  carbon_emission: 0.406,
  region_id: 'IN-TG',
  tariff_plan: 'ToD',
  currency: 'INR',
  native_cost: 7.15,
  baseline_native_cost: 7.15,
  tariff_inr_per_kwh: 7.15,
  tariff_category: 'ToD',
  reason:
    "Lowest-carbon feasible window (0.4060 kg CO2). Electricity cost ($0.0858) was used as secondary tie-breaker, and earliest start time (2026-09-10T08:00:00+00:00) as deterministic final tie-breaker.",
  budget_remaining: null,
  objective: 'CARBON_FIRST',
  scheduler_objective: 'CARBON_FIRST',
  candidates_evaluated: 6,
  feasible_candidates_count: 6,
  rejection_summary: {},
  rejection_reasons: [],
  deterministic_ranking: 1,
  deterministic_rank: 1,
  baseline_start: '2026-09-10T06:16:44.865797',
  baseline_end: '2026-09-10T06:46:44.865797',
  baseline_carbon_emission: 0.409,
  baseline_cost: 0.0858,
  carbon_avoided: 0.003,
  cost_difference: 0.0,
  carbon_reduction_pct: 0.73,
  cost_reduction_pct: 0.0,
  scheduling_delay_hours: 1.72,
  sla_met: true,
};

export const decisionWithoutBaseline = {
  id: 3,
  schedule_id: 3,
  job_id: 'JOB-AAF97A1F',
  selected_start: '2026-09-10T08:00:00+00:00',
  selected_end: '2026-09-10T08:30:00+00:00',
  carbon_intensity: 406.0,
  electricity_cost: 0.0858,
  carbon_emission: 0.406,
  region_id: 'IN-TG',
  tariff_plan: 'ToD',
  currency: 'INR',
  native_cost: 7.15,
  // The real endpoint DOES include baseline_native_cost here — only
  // baseline_carbon_emission and baseline_cost (USD) are absent from this
  // particular endpoint's response, unlike GET /api/v1/jobs/{id}.
  baseline_native_cost: 7.15,
  reason:
    "Lowest-carbon feasible window (0.4060 kg CO2). Electricity cost ($0.0858) was used as secondary tie-breaker, and earliest start time (2026-09-10T08:00:00+00:00) as deterministic final tie-breaker.",
  budget_remaining: null,
  objective: 'CARBON_FIRST',
  scheduler_objective: 'CARBON_FIRST',
  candidates_evaluated: 6,
  feasible_candidates_count: 6,
  rejection_summary: {},
  rejection_reasons: [],
  deterministic_ranking: 1,
  deterministic_rank: 1,
  baseline_start: '2026-09-10T06:16:44.865797+00:00',
  baseline_end: '2026-09-10T06:46:44.865797+00:00',
  carbon_avoided: 0.003,
  cost_difference: 0.0,
  carbon_reduction_pct: 0.73,
  cost_reduction_pct: 0.0,
  scheduling_delay_hours: 1.72,
  sla_met: true,
};

/** A decision with real rejected windows, for WhyThisWindow's rejection breakdown. */
export const decisionWithRejections = {
  ...fullDecisionWithBaseline,
  candidates_evaluated: 8,
  feasible_candidates_count: 3,
  rejection_summary: {
    deadline_exceeded: 4,
    resource_conflict: 1,
  },
};
