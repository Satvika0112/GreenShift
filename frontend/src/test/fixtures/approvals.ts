import { PendingApprovalItem, ApprovalHistoryItem } from '../../types/api';

// Matches the real shape returned by GET /api/v1/approvals/pending
// (app/shared/models.py PendingApprovalItem, app/approval/service.py).
export const pendingApprovalItem: PendingApprovalItem = {
  job_id: 'job-9001',
  workload_name: 'nightly-batch-etl',
  job_type: 'batch',
  priority: 'HIGH',
  team_id: 'team-acme',
  region: 'US-CAL-CISO',
  timezone: 'America/Los_Angeles',
  schedule_id: 42,
  selected_start_utc: '2026-09-10T09:00:00Z',
  selected_start_local: '2026-09-10T02:00:00-07:00',
  selected_end_utc: '2026-09-10T10:30:00Z',
  selected_end_local: '2026-09-10T03:30:00-07:00',
  runtime_minutes: 90,
  power_kw: 12.5,
  carbon_intensity: 220,
  carbon_emission_kg: 4.1,
  electricity_cost_usd: 3.75,
  deadline_utc: '2026-09-10T18:00:00Z',
  deadline_local: '2026-09-10T11:00:00-07:00',
  status: 'PENDING_APPROVAL' as any,
  reason: 'Carbon budget exceeded for team-acme this billing cycle',
  carbon_budget_kg: 5,
  currency: 'USD',
  native_cost: 3.75,
  baseline_carbon_emission_kg: 6.0,
  baseline_cost_usd: 4.9,
  baseline_native_cost: 4.9,
  baseline_start_utc: '2026-09-10T00:30:00Z',
  baseline_start_local: '2026-09-09T17:30:00-07:00',
  carbon_avoided_kg: 1.9,
  cost_difference_usd: 1.15,
  carbon_reduction_pct: 31,
  sla_met: true,
};

// Matches GET /api/v1/approvals/history (app/shared/models.py
// ApprovalHistoryItem).
export const approvedHistoryItem: ApprovalHistoryItem = {
  job_id: 'job-7788',
  workload_name: 'customer-churn-training',
  decision: 'APPROVED',
  team_id: 'team-acme',
  tenant_id: 'acme',
  region: 'IN-TG',
  scheduled_start_utc: '2026-09-11T14:00:00Z',
  decided_by: 'company_admin',
  decided_at: '2026-09-10T15:20:00Z',
  reason: null,
};

export const declinedHistoryItem: ApprovalHistoryItem = {
  job_id: 'job-8899',
  workload_name: 'etl-pipeline-118',
  decision: 'DECLINED',
  team_id: 'team-acme',
  tenant_id: 'acme',
  region: 'IN-GJ',
  scheduled_start_utc: '2026-09-12T10:00:00Z',
  decided_by: 'company_admin',
  decided_at: '2026-09-09T14:22:00Z',
  reason: 'Exceeds quarterly carbon cap',
};
