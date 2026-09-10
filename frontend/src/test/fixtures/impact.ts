// Matches app.analytics.fleet_impact.FleetImpactReport.to_dict() exactly —
// dataclass fields, notably `job_count` (not `count`) on by_team/by_region entries.
export const fleetImpactReport = {
  total_carbon_avoided_kg: 482.6,
  avg_carbon_reduction_pct: 27.3,
  total_cost_saved_usd: 118.42,
  total_jobs_with_decisions: 36,
  by_team: {
    'team-acme': {
      job_count: 21,
      total_carbon_avoided_kg: 310.1,
      avg_carbon_reduction_pct: 29.0,
      total_cost_saved_usd: 74.5,
      total_cost_saved_inr: 6200.3,
      sla_compliance_pct: 98.1,
    },
  },
  by_region: {
    'US-CAL-CISO': {
      job_count: 21,
      total_carbon_avoided_kg: 310.1,
      total_cost_saved_usd: 74.5,
    },
  },
};

export const fleetHeadline = {
  total_carbon_avoided_kg: 482.6,
  avg_carbon_reduction_pct: 27.3,
  total_cost_saved_usd: 118.42,
  total_jobs: 36,
};
