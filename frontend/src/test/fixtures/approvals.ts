import { PendingApprovalItem } from '../../types/api';

// Matches the real shape returned by GET /api/v1/approvals/pending
// (app/api/routers/approval.py).
export const pendingApprovalItem: PendingApprovalItem = {
  job_id: 'job-9001',
  workload_name: 'nightly-batch-etl',
  job_type: 'batch',
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
};

// Matches GET /api/v1/approvals/declined (untyped dict on the frontend,
// mirroring the backend's declined-approval response fields).
export const declinedApprovalItem = {
  job_id: 'job-8899',
  team_id: 'team-acme',
  declined_by: 'company_admin',
  declined_at: '2026-09-09T14:22:00Z',
  reason: 'Exceeds quarterly carbon cap',
};
