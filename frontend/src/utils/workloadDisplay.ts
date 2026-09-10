import { Job, JobStatus, WorkloadDetail } from '../types/api';

export function formatDateTime(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function formatDate(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
}

export function formatPriority(priority?: string | number | null): string {
  if (priority === undefined || priority === null || priority === '') return '—';
  const s = String(priority);
  return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
}

interface CostFields {
  native_cost?: number | null;
  currency?: string | null;
  electricity_cost?: number | null;
}

// electricity_cost is always USD-normalized by the backend; native_cost +
// currency (when present) reflects the region's actual billing currency —
// prefer the native figure so we never mislabel USD as a native amount.
export function formatCost(fields: CostFields): string {
  if (fields.native_cost !== undefined && fields.native_cost !== null && fields.currency) {
    return `${fields.native_cost.toFixed(2)} ${fields.currency}`;
  }
  if (fields.electricity_cost !== undefined && fields.electricity_cost !== null) {
    return `$${fields.electricity_cost.toFixed(2)}`;
  }
  return '—';
}

// The list/table-level `carbon_emission` is always the scheduler's
// pre-dispatch estimate, never a measured value — always label it as such.
export function formatCarbonKg(kg?: number | null, options?: { estimated?: boolean }): string {
  if (kg === undefined || kg === null) return '—';
  return `${kg.toFixed(2)} kg CO₂${options?.estimated ? ' (est.)' : ''}`;
}

export function recommendedStartDisplay(job: Pick<Job, 'status' | 'selected_start' | 'actual_start'>): string {
  if (job.actual_start) return `Executed · ${formatDateTime(job.actual_start)}`;
  if (job.selected_start) return formatDateTime(job.selected_start);
  return 'Not scheduled';
}

export type ApprovalDisplayStatus = 'NOT_REQUIRED' | 'PENDING' | 'APPROVED' | 'DECLINED';

export const APPROVAL_LABELS: Record<ApprovalDisplayStatus, string> = {
  NOT_REQUIRED: 'Not Required',
  PENDING: 'Pending',
  APPROVED: 'Approved',
  DECLINED: 'Declined',
};

// Approval is not a separate field on Job — it's derived from the real
// lifecycle status plus whether a schedule decision exists, using only
// values the backend actually returns (never fabricated).
export function deriveApprovalStatus(job: Pick<Job, 'status' | 'selected_start'>): ApprovalDisplayStatus {
  if (job.status === 'PENDING_APPROVAL') return 'PENDING';
  if (job.status === 'DECLINED' || job.status === 'REJECTED') return 'DECLINED';
  if (job.selected_start) return 'APPROVED';
  return 'NOT_REQUIRED';
}

export type WorkloadActionKind =
  | 'find-schedule'
  | 'review-schedule'
  | 'view-execution'
  | 'monitor'
  | 'view-impact'
  | 'view-failure'
  | 'view-reason';

export interface WorkloadContextualAction {
  kind: WorkloadActionKind;
  label: string;
}

// One contextual action per lifecycle status — never more than one, and
// never a dispatch action that would bypass human approval from a list view.
export function contextualActionForStatus(status: JobStatus): WorkloadContextualAction | null {
  switch (status) {
    case 'SUBMITTED':
    case 'VALIDATED':
      return { kind: 'find-schedule', label: 'Find Schedule' };
    case 'SCHEDULED':
    case 'PENDING_APPROVAL':
      return { kind: 'review-schedule', label: 'Review Schedule' };
    case 'APPROVED':
    case 'READY':
    case 'QUEUED':
    case 'CLAIMING':
      return { kind: 'view-execution', label: 'View Execution' };
    case 'DISPATCHING':
    case 'RUNNING':
      return { kind: 'monitor', label: 'Monitor' };
    case 'COMPLETED':
      return { kind: 'view-impact', label: 'View Impact' };
    case 'FAILED':
      return { kind: 'view-failure', label: 'View Failure' };
    case 'DECLINED':
    case 'REJECTED':
      return { kind: 'view-reason', label: 'View Reason' };
    default:
      return null;
  }
}

// Backend-real audit event types (app.shared.models.EventType) mapped to
// plain-language labels; anything not in this map falls back to its raw
// event_type string rather than being hidden or invented.
export const AUDIT_EVENT_LABELS: Record<string, string> = {
  JOB_SUBMITTED: 'Workload submitted',
  JOB_VALIDATED: 'Validation completed',
  JOB_SCHEDULED: 'Schedule generated',
  SCHEDULE_PROPOSED: 'Schedule generated',
  APPROVAL_GRANTED: 'Schedule approved',
  APPROVAL_DECLINED: 'Schedule declined',
  DISPATCH_REQUESTED: 'Dispatch requested',
  DISPATCH_AUTHORIZED: 'Dispatch authorized',
  DISPATCH_BLOCKED: 'Dispatch blocked',
  DISPATCH_STARTED: 'Execution started',
  K8S_JOB_CREATED: 'Kubernetes job created',
  K8S_JOB_STARTED: 'Execution running',
  K8S_JOB_COMPLETED: 'Workload completed',
  K8S_JOB_FAILED: 'Execution failed',
  JOB_CANCELLED: 'Workload cancelled',
};

export function auditEventLabel(eventType: string): string {
  return AUDIT_EVENT_LABELS[eventType] || eventType;
}

export function workloadDisplayName(job: Pick<Job | WorkloadDetail, 'job_id' | 'name'>): string {
  return job.name && job.name.trim().length > 0 ? job.name : job.job_id;
}
