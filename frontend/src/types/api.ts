// GreenShift Enterprise API Type Definitions
// Derived strictly from backend SQLAlchemy models and Pydantic schemas

export type JobStatus = 
  | 'SUBMITTED'
  | 'VALIDATED'
  | 'SCHEDULED'
  | 'PENDING_APPROVAL'
  | 'APPROVED'
  | 'READY'
  | 'CLAIMING'
  | 'DECLINED'
  | 'REJECTED'
  | 'QUEUED'
  | 'DISPATCHING'
  | 'RUNNING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED';

export type UserRole =
  | 'PLATFORM_ADMIN'
  | 'COMPANY_ADMIN'
  | 'COMPANY_USER';

export interface User {
  id: number | string;
  user_id?: string;
  username: string;
  email: string;
  role: UserRole;
  team_id: string;
  tenant_id?: string | null;
  company_name?: string | null;
  company?: { id: string; name: string } | null;
  approval_status?: string;
  is_active: boolean;
  created_at?: string;
}

export interface AuthTokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface Job {
  job_id: string;
  name?: string;
  team_id: string;
  tenant_id?: string | null;
  job_type?: string;
  priority?: string | number;
  status: JobStatus;
  region: string;
  runtime_minutes: number;
  power_kw: number;
  energy_kwh?: number;
  cpu_request?: string;
  memory_request?: string;
  container_image: string;
  carbon_budget_kg?: number;
  submitted_at: string;
  earliest_start_time?: string | null;
  deadline: string;
  selected_start?: string | null;
  selected_end?: string | null;
  carbon_intensity?: number | null;
  carbon_emission?: number | null;
  electricity_cost?: number | null;
  native_cost?: number | null;
  currency?: string;
  kubernetes_job_name?: string | null;
  kubernetes_namespace?: string | null;
  k8s_status?: string | null;
  pod_name?: string | null;
  actual_start?: string | null;
  actual_end?: string | null;
  schedule_decision?: any;
  kubernetes_execution?: any;
  created_at?: string;
  updated_at?: string;
}

export interface ScheduleDecision {
  id?: number | string;
  schedule_id?: number | string;
  decision_id?: string;
  job_id: string;
  selected_start: string;
  selected_end: string;
  // The requested window as stored on the job — GET/POST /schedule/{job_id}
  // include these alongside selected_start/selected_end so a client never
  // needs a second request to compare "requested" vs "recommended".
  requested_earliest_start?: string | null;
  requested_deadline?: string | null;
  carbon_intensity: number;
  // Always USD (energy_kwh * price_per_kwh_usd) — used for cross-region
  // comparison via the backend's existing FX mechanism. `currency` below
  // does NOT describe this field; it describes native_cost. Prefer
  // native_cost + currency for user-facing display — see
  // utils/workloadDisplay.formatCost, the single shared helper for this.
  electricity_cost: number;
  carbon_emission: number;
  region_id: string;
  tariff_plan?: string | null;
  // Denominates native_cost / baseline_native_cost ONLY (see above).
  currency: string;
  native_cost?: number | null;
  baseline_native_cost?: number | null;
  reason?: string;
  budget_remaining?: number | null;
  objective?: string;
  scheduler_objective?: string;
  // Only meaningful when scheduler_objective === 'CARBON_CONSTRAINED'.
  carbon_tolerance_pct?: number | null;
  candidates_evaluated: number;
  feasible_candidates_count: number;
  rejection_summary?: Record<string, number>;
  rejection_reasons?: string[];
  deterministic_ranking?: number;
  deterministic_rank?: number;
  baseline_start?: string | null;
  baseline_end?: string | null;
  baseline_carbon_emission?: number | null;
  // Always USD — paired with baseline_native_cost above for the native figure.
  baseline_cost?: number | null;
  carbon_avoided?: number | null;
  cost_difference?: number | null;
  carbon_reduction_pct?: number | null;
  cost_reduction_pct?: number | null;
  scheduling_delay_hours?: number | null;
  sla_met?: boolean;
  time_details?: {
    selected_start: any;
    selected_end: any;
  };
}

// Matches GET /api/v1/approvals/pending exactly (app/shared/models.py
// PendingApprovalItem). All decision-support fields are optional because
// they're only populated when the underlying ScheduleDecisionORM/JobORM
// columns have a value — never fabricated when absent.
export interface PendingApprovalItem {
  job_id: string;
  workload_name?: string;
  job_type?: string;
  priority?: string | null;
  team_id: string;
  region: string;
  timezone?: string;
  schedule_id: number;
  selected_start_utc: string;
  selected_start_local: string;
  selected_end_utc: string;
  selected_end_local: string;
  runtime_minutes: number;
  power_kw: number;
  carbon_intensity: number;
  carbon_emission_kg: number;
  electricity_cost_usd: number;
  deadline_utc: string;
  deadline_local: string;
  status: JobStatus;
  tariff_plan?: string | null;
  scheduler_objective?: string;
  objective?: string;
  carbon_tolerance_pct?: number | null;
  reason?: string | null;
  candidates_evaluated?: number;
  feasible_candidates_count?: number;
  rejection_summary?: Record<string, number>;
  carbon_budget_kg?: number | null;
  currency?: string | null;
  native_cost?: number | null;
  baseline_carbon_emission_kg?: number | null;
  baseline_cost_usd?: number | null;
  baseline_native_cost?: number | null;
  baseline_start_utc?: string | null;
  baseline_start_local?: string | null;
  carbon_avoided_kg?: number | null;
  cost_difference_usd?: number | null;
  carbon_reduction_pct?: number | null;
  sla_met?: boolean | null;
}

// Matches GET /api/v1/approvals/history exactly (app/shared/models.py
// ApprovalHistoryItem).
export interface ApprovalHistoryItem {
  job_id: string;
  workload_name?: string | null;
  decision: 'APPROVED' | 'DECLINED';
  team_id?: string | null;
  tenant_id?: string | null;
  region?: string | null;
  scheduled_start_utc?: string | null;
  decided_by?: string | null;
  decided_at: string;
  reason?: string | null;
}

export interface Approval {
  id: number | string;
  job_id: string;
  schedule_decision_id: number;
  decision: 'APPROVED' | 'DECLINED' | 'PENDING';
  job_status?: JobStatus;
  reason?: string | null;
  approved_by?: string | null;
  created_at: string;
  updated_at?: string;
  job?: Job;
}

export interface KubernetesExecution {
  job_id: string;
  execution_id: number | string;
  kubernetes_job_name: string;
  namespace: string;
  kubernetes_namespace?: string;
  pod_name?: string | null;
  planned_start?: string | null;
  actual_start?: string | null;
  actual_end?: string | null;
  k8s_status?: string | null;
  gs_status?: string | null;
  error_message?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

// Kubernetes telemetry nested inside GET /jobs/{id} and /jobs/{id}/history —
// a narrower shape than KubernetesExecution (no execution_id/error_message).
export interface WorkloadKubernetesInfo {
  kubernetes_job_name?: string | null;
  kubernetes_namespace?: string | null;
  pod_name?: string | null;
  planned_start?: string | null;
  actual_start?: string | null;
  actual_end?: string | null;
  k8s_status?: string | null;
  gs_status?: string | null;
}

// Matches GET /api/v1/jobs/{id} and /jobs/{id}/history exactly
// (app/api/routers/ingest.py get_job_detail / get_job_history). `status` here
// reflects the live Kubernetes gs_status once execution exists, which can be
// more current than the plain Job.status from the list endpoint.
export interface WorkloadDetail {
  job_id: string;
  name?: string;
  team_id: string;
  tenant_id?: string | null;
  company_name?: string | null;
  job_type?: string;
  priority?: string | number | null;
  status: JobStatus;
  submitted_at: string;
  earliest_start_time?: string | null;
  deadline: string;
  runtime_minutes: number;
  power_kw: number;
  energy_kwh?: number | null;
  deferrable?: boolean;
  region: string;
  container_image: string;
  cpu_request?: string | null;
  memory_request?: string | null;
  carbon_budget_kg?: number | null;
  schedule_decision?: ScheduleDecision;
  kubernetes?: WorkloadKubernetesInfo;
  kubernetes_job_name?: string | null;
  pod_name?: string | null;
  audit_events?: AuditEvent[];
}

// Matches GET /api/v1/impact/job/{id}/actual exactly
// (app/analytics/actual_impact.py ActualImpactResult.to_dict()).
export interface ActualImpactResult {
  job_id: string;
  estimated_carbon_emission_kg: number;
  estimated_cost_usd: number;
  estimated_carbon_intensity: number;
  actual_carbon_emission_kg: number;
  actual_cost_usd: number;
  actual_carbon_intensity: number;
  carbon_estimation_error_pct: number;
  cost_estimation_error_pct: number;
  actual_vs_baseline_carbon_saved_kg: number;
  actual_vs_baseline_carbon_reduction_pct: number;
  actual_vs_baseline_cost_saved_usd: number;
  estimation_quality: 'ACCURATE' | 'ACCEPTABLE' | 'POOR';
}

export interface K8sNode {
  name: string;
  status: string;
  cpu_capacity_cores: number;
  cpu_allocatable_cores: number;
  cpu_used_cores: number;
  cpu_free_cores: number;
  memory_capacity_mib: number;
  memory_allocatable_mib: number;
  memory_used_mib: number;
  memory_free_mib: number;
  gpu_capacity: number;
  gpu_allocatable: number;
  gpu_used: number;
  gpu_free: number;
  roles?: string[];
}

export interface KubernetesClusterState {
  connected: boolean;
  cluster_health: string;
  total_nodes: number;
  ready_nodes: number;
  total_cpu_cores: number;
  allocatable_cpu_cores: number;
  used_cpu_cores: number;
  free_cpu_cores: number;
  total_memory_mib: number;
  allocatable_memory_mib: number;
  used_memory_mib: number;
  free_memory_mib: number;
  total_gpus: number;
  allocatable_gpus: number;
  used_gpus: number;
  free_gpus: number;
  timestamp: string;
  nodes: K8sNode[];
}

// Matches app.shared.models.AuditEvent exactly (Pydantic response_model on
// GET /api/v1/trust/events, /trust/jobs/{job_id}).
export interface AuditEvent {
  event_id: string;
  sequence: number;
  event_type: string;
  job_id: string | null;
  timestamp: string;
  payload_hash: string;
  previous_hash: string;
  current_hash: string;
  tenant_id?: string | null;
  team_id?: string | null;
  actor_user_id?: string | null;
  actor_username?: string | null;
  actor_role?: string | null;
  actor_type?: string | null;
  request_id?: string | null;
  source_service?: string | null;
  reason?: string | null;
}

// Matches the anchor dict shape returned by GET /trust/anchors — the new
// DB-backed historical anchor list, distinct from the legacy file-based
// AnchorRecord (which has no id/created_by_user_id/label).
export interface AuditAnchor {
  id: number;
  sequence: number;
  root_hash: string;
  event_count: number;
  created_at: string;
  created_by_user_id: string | null;
  label: string | null;
}

export interface TrustEventFilters {
  job_id?: string;
  team_id?: string;
  actor?: string;
  event_type?: string;
  start_time?: string;
  end_time?: string;
  limit?: number;
}

export interface DashboardSummary {
  total_jobs: number;
  active_jobs: number;
  jobs: Record<string, number>;
  carbon: {
    baseline_emissions_kg: number;
    greenshift_emissions_kg: number;
    carbon_avoided_kg: number;
  };
  cost: {
    baseline_cost: number;
    greenshift_cost: number;
    cost_difference: number;
  };
  audit: {
    event_count: number;
  };
}

export interface FleetHeadline {
  total_carbon_avoided_kg: number;
  avg_carbon_reduction_pct: number;
  total_cost_saved_usd: number;
  // Currency-separated native savings — a fleet can span multiple execution
  // regions/currencies, so this is never a single combined figure (see
  // app.analytics.fleet_impact.FleetImpactReport.cost_saved_by_currency).
  cost_saved_by_currency?: Record<string, number>;
  sla_compliance_pct: number;
  total_jobs: number;
  jobs_with_positive_savings: number;
}

export interface RegionInfo {
  region_id: string;
  country: string;
  region_name: string;
  timezone: string;
  currency: string;
  electricity_maps_zone: string;
  default_plan: string;
  supported_tariff_plans: Array<{
    plan_id: string;
    display_name: string;
    description: string;
    is_industrial: boolean;
    is_commercial: boolean;
    is_flat: boolean;
    default_rate: number;
  }>;
  aliases: string[];
  is_active: boolean;
}

// Matches GET /api/v1/tariffs/{region}/current exactly
// (app/api/routers/ingest.py get_current_tariff / app/shared/tariff_service.py).
// `effective_price` + `currency` together are the region's real native
// tariff rate — `price_per_kwh_usd` is a separate, USD-normalized figure
// for cross-region comparison and must never be displayed as if it were
// the native rate.
export interface CurrentTariffInfo {
  utc_timestamp: string;
  local_timestamp: string;
  local_hour: number;
  timezone: string;
  time_interval: string;
  time_of_day: string;
  base_charge: number;
  adder_charge: number;
  effective_price: number;
  currency: string;
  tariff_type: string;
  season: string;
  price_per_kwh_usd: number;
}

export interface CurrentTariffResponse {
  region: string;
  region_id: string;
  currency: string;
  current_tariff: CurrentTariffInfo;
}

// Matches GET /api/v1/tariffs/{region} exactly.
export interface HourlyTariffRecord {
  hour: number;
  time_interval: string;
  time_of_day: string;
  base_charge: number;
  adder_charge: number;
  effective_price: number;
  currency: string;
  tariff_type: string;
  season: string;
  price_per_kwh_usd: number;
}

export interface RegionHourlyTariffsResponse {
  region: string;
  region_id: string;
  currency: string;
  season: string;
  tariffs: HourlyTariffRecord[];
}

export interface SystemHealthReport {
  status: 'healthy' | 'degraded' | 'unhealthy';
  service: string;
  timestamp: string;
  checks: {
    api: string;
    database: string;
    kubernetes: string;
  };
  components: {
    application?: { status: string; reason?: string };
    database?: { status: string; reason?: string };
    redis?: { status: string; reason?: string };
    kubernetes?: { status: string; reason?: string };
    carbon_data?: { status: string; mode?: string; reason?: string };
  };
}

export interface NotificationItem {
  id: number;
  job_id?: string | null;
  event_type: string;
  category: string;
  severity: 'INFO' | 'WARNING' | 'CRITICAL' | string;
  title: string;
  message: string;
  action_url?: string | null;
  created_at: string;
  read_at?: string | null;
  is_read: boolean;
}

export interface UnreadCountResponse {
  unread_count: number;
}

// Matches GET/PUT /api/v1/notifications/preferences (app/shared/models.py
// NotificationPreferenceResponse). `email_system` is read-only — the
// backend never accepts it in an update request (security/account/
// infrastructure notifications cannot be disabled by the recipient).
export interface NotificationPreferences {
  email_workload: boolean;
  email_scheduling: boolean;
  email_approval: boolean;
  email_execution: boolean;
  email_system: boolean;
}

export type NotificationPreferencesUpdate = Partial<
  Pick<NotificationPreferences, 'email_workload' | 'email_scheduling' | 'email_approval' | 'email_execution'>
>;

// Matches app.shared.models.AuditVerifyResponse exactly (response_model on
// GET /api/v1/trust/verify) — no other fields exist on this response.
export interface AuditVerifyResponse {
  valid: boolean;
  event_count: number;
  message: string;
  failed_check?: string | null;
  failed_sequence?: number | null;
  expected_sequence?: number | null;
  actual_sequence?: number | null;
  reason?: string | null;
}

// Matches the dict shapes returned by app.trust.anchor.verify_anchor()
// (GET /api/v1/trust/anchor/verify) — a plain dict, not a Pydantic model, so
// this mirrors the exact keys read from app/trust/anchor.py.
export interface AnchorRecord {
  timestamp: string;
  sequence: number;
  root_hash: string;
  event_count: number;
  latest_event_id: string;
  latest_event_type: string;
}

export interface AnchorStatus {
  status:
    | 'no_anchor_file' | 'empty_anchor_file' | 'corrupt_anchor_file' | 'event_not_found'
    | 'verified' | 'tampered'
    // app.trust.anchor.verify_anchor_by_id() statuses (GET /trust/anchors/{id}/verify):
    | 'anchor_not_found' | 'event_missing'
    // frontend-only fallback when the verify request itself fails:
    | 'error';
  verified: boolean;
  message: string;
  anchor?: AnchorRecord;
  total_anchors?: number;
}

// POST /api/v1/trust/anchor/create response (app/api/routers/trust.py).
export interface AnchorCreateResult {
  status: 'created' | 'empty_chain';
  anchor?: AnchorRecord;
  message?: string;
}

// Matches POST /api/v1/jobs's JobSubmitResponse exactly (app/shared/models.py).
export interface JobSubmitResult {
  job_id: string;
  status: JobStatus;
  submitted_at: string;
  name?: string | null;
}

// Matches POST /api/v1/jobs's JobSubmitRequest exactly (app/shared/models.py)
// for the fields the Submit Workload UI actually collects.
export interface CreateJobInput {
  workload_name?: string;
  team_id: string;
  deadline: string;
  earliest_start_time?: string;
  runtime_minutes: number;
  power_kw: number;
  region: string;
  container_image: string;
  cpu_request?: string;
  memory_request?: string;
  carbon_budget_kg?: number;
  priority?: string;
  job_type?: string;
  deferrable?: boolean;
  timezone?: string;
  job_id?: string;
}

// Matches GET /api/v1/dataset/workloads exactly (app/api/routers/ingest.py
// list_dataset_workloads). `team` and `dataset_submit_time` are deliberately
// named apart from `team_id`/`submit_time` on CreateJobInput — they are
// display-only provenance fields and must never be sent to POST /jobs as-is
// (team ownership always comes from the authenticated user; the real
// submission timestamp is always set at actual registration time).
export interface DatasetWorkloadItem {
  job_id: string;
  job_type: string;
  team: string;
  priority: string;
  region: string;
  dataset_submit_time: string;
  earliest_start_time: string;
  deadline: string;
  runtime_minutes: number;
  runtime_hours: number;
  power_kw: number;
  energy_kwh: number;
  deferrable: boolean;
  container_image: string;
  cpu_request: string;
  memory_request: string;
  carbon_budget_kg: number | null;
}

export interface DatasetWorkloadsResponse {
  count: number;
  source: string;
  workloads: DatasetWorkloadItem[];
}

// ==========================================
// COMPANY / ORGANIZATION ONBOARDING
// ==========================================

// Matches app.shared.models.CompanyRegisterRequest exactly — deliberately
// has no role/tenant_id/team_id/company_id field; the backend always
// determines those. Never add such a field here.
export interface CompanyRegisterRequest {
  company_name: string;
  legal_name?: string;
  company_email: string;
  website?: string;
  industry: string;
  sector?: string;
  country: string;
  address?: string;
  admin_name: string;
  admin_email: string;
  password: string;
  confirm_password: string;
}

export interface CompanyRegisteredAdmin {
  id: number;
  username: string;
  email: string;
  role: string;
}

export interface CompanyRegisterResponse {
  company_id: string;
  company_name: string;
  team_id: string;
  team_name: string;
  admin: CompanyRegisteredAdmin;
  message: string;
}

// Matches app.shared.models.CompanyProfileResponse (GET/PATCH /companies/me).
export interface CompanyProfile {
  id: string;
  name: string;
  legal_name?: string | null;
  company_email?: string | null;
  website?: string | null;
  industry?: string | null;
  sector?: string | null;
  country?: string | null;
  address?: string | null;
  status: string;
  cin?: string | null;
  gstin?: string | null;
  employee_count?: number | null;
  contact_phone?: string | null;
  is_active: boolean;
  created_at: string;
  updated_at?: string | null;
  user_count?: number;
  workload_count?: number;
}

// PATCH /companies/me — every field optional, no id/tenant_id/status field.
export type CompanyProfileUpdate = Partial<{
  name: string;
  legal_name: string;
  website: string;
  industry: string;
  sector: string;
  country: string;
  address: string;
  company_email: string;
  cin: string;
  gstin: string;
  employee_count: number;
  contact_phone: string;
}>;

export interface CompanyTeam {
  id: string;
  tenant_id: string;
  name: string;
  created_at: string;
  member_count?: number;
}

export interface CompanyTeamCreate {
  name: string;
}

// POST /companies/me/users — no tenant_id/company_id field.
export interface CompanyUserCreate {
  email: string;
  password: string;
  username?: string;
  role?: 'COMPANY_ADMIN' | 'COMPANY_USER';
  team_id?: string;
}

// ==========================================
// GREENSHIFT POLICY-AWARE OPTIMIZATION
// ==========================================

// The one canonical set of policy values — mirrors
// app.decide.optimization_policy.OptimizationPolicy exactly. Never
// redefine this union elsewhere in the frontend.
export type OptimizationPolicy = 'CARBON_FIRST' | 'COST_FIRST' | 'CARBON_CONSTRAINED';

// GET/PUT /api/v1/settings/optimization-policy response — the
// authenticated caller's own company's active scheduling policy. This is
// the backend source of truth; it is never read from or written to
// localStorage.
export interface OptimizationPolicyResponse {
  policy: OptimizationPolicy;
  carbon_tolerance_pct?: number | null;
  updated_by?: string | null;
  updated_at?: string | null;
}

// PUT /api/v1/settings/optimization-policy request body.
// `carbon_tolerance_pct` is required by the backend when
// policy === 'CARBON_CONSTRAINED' and rejected otherwise.
export interface OptimizationPolicyUpdate {
  policy: OptimizationPolicy;
  carbon_tolerance_pct?: number | null;
}
