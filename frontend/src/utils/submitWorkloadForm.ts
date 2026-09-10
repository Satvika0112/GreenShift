// Canonical job types per product specification. The backend's `job_type`
// field itself is a free-form string (no server-side enum) — these are the
// UI's restricted set, not a fabricated backend contract.
export const JOB_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: 'ML_TRAINING', label: 'ML Training' },
  { value: 'DATA_PROCESSING', label: 'Data Processing' },
  { value: 'ETL', label: 'ETL' },
  { value: 'IMAGE_PROCESSING', label: 'Image Processing' },
  { value: 'ANALYTICS', label: 'Analytics' },
  { value: 'BACKUP', label: 'Backup' },
  { value: 'REPORT_GENERATION', label: 'Report Generation' },
];

// Backend-validated values (app/shared/models.py JobSubmitRequest.validate_priority).
export const PRIORITY_OPTIONS: { value: string; label: string }[] = [
  { value: 'CRITICAL', label: 'Critical' },
  { value: 'HIGH', label: 'High' },
  { value: 'MEDIUM', label: 'Medium' },
  { value: 'LOW', label: 'Low' },
];

export interface SubmitWorkloadFormState {
  workloadName: string;
  jobType: string;
  priority: string;
  containerImage: string;
  region: string;
  runtimeMinutes: string;
  powerKw: string;
  cpuRequest: string;
  memoryRequest: string;
  earliestStart: string;
  deadline: string;
  deferrable: boolean;
  carbonBudgetKg: string;
}

export type SubmitWorkloadFieldErrors = Partial<Record<keyof SubmitWorkloadFormState, string>>;

// Kubernetes-style quantity formats (a practical subset, not the full OCI/K8s
// grammar — good enough for plausibility checking, never used to compute
// anything, and the backend remains the real validator).
const CPU_PATTERN = /^\d+m$|^\d+(\.\d+)?$/;
const MEMORY_PATTERN = /^\d+(\.\d+)?(Ki|Mi|Gi|Ti|Pi|Ei|K|M|G|T|P|E)?$/;
const IMAGE_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9._\-/:]*[a-zA-Z0-9]$/;

export function computeEstimatedEnergyKwh(powerKw: string, runtimeMinutes: string): number | null {
  const power = Number(powerKw);
  const runtime = Number(runtimeMinutes);
  if (!Number.isFinite(power) || !Number.isFinite(runtime) || power <= 0 || runtime <= 0) return null;
  return power * (runtime / 60);
}

export function validateSubmitWorkloadForm(form: SubmitWorkloadFormState, activeRegionIds: string[]): SubmitWorkloadFieldErrors {
  const errors: SubmitWorkloadFieldErrors = {};

  const name = form.workloadName.trim();
  if (!name) errors.workloadName = 'Workload name is required.';
  else if (name.length > 200) errors.workloadName = 'Workload name must be 200 characters or fewer.';

  if (!form.jobType) errors.jobType = 'Workload type is required.';
  if (!form.priority) errors.priority = 'Priority is required.';

  const image = form.containerImage.trim();
  if (!image) errors.containerImage = 'Container image is required.';
  else if (image.length > 255 || image.includes(' ') || !IMAGE_PATTERN.test(image)) {
    errors.containerImage = 'Enter a plausible container image reference, e.g. ghcr.io/company/model-training:latest.';
  }

  if (!form.region) errors.region = 'Region is required.';
  else if (activeRegionIds.length > 0 && !activeRegionIds.includes(form.region)) {
    errors.region = 'Select a currently supported region.';
  }

  const runtime = Number(form.runtimeMinutes);
  if (!form.runtimeMinutes || !Number.isFinite(runtime) || runtime <= 0) {
    errors.runtimeMinutes = 'Runtime must be greater than 0.';
  } else if (runtime > 10080) {
    errors.runtimeMinutes = 'Runtime cannot exceed 10,080 minutes (7 days).';
  }

  const power = Number(form.powerKw);
  if (!form.powerKw || !Number.isFinite(power) || power <= 0) {
    errors.powerKw = 'Average power draw must be greater than 0.';
  } else if (power > 100000) {
    errors.powerKw = 'Average power draw exceeds the supported maximum (100,000 kW).';
  }

  if (!form.cpuRequest.trim() || !CPU_PATTERN.test(form.cpuRequest.trim())) {
    errors.cpuRequest = 'Enter a valid CPU request, e.g. 500m or 2.';
  }

  if (!form.memoryRequest.trim() || !MEMORY_PATTERN.test(form.memoryRequest.trim())) {
    errors.memoryRequest = 'Enter a valid memory request, e.g. 512Mi or 4Gi.';
  }

  if (!form.deadline) {
    errors.deadline = 'SLA deadline is required.';
  } else {
    const deadlineDate = new Date(form.deadline);
    if (Number.isNaN(deadlineDate.getTime())) errors.deadline = 'Enter a valid SLA deadline.';
    else if (deadlineDate.getTime() <= Date.now()) errors.deadline = 'SLA deadline must be in the future.';
  }

  if (form.earliestStart) {
    const earliestDate = new Date(form.earliestStart);
    if (Number.isNaN(earliestDate.getTime())) {
      errors.earliestStart = 'Enter a valid earliest-start time.';
    } else if (form.deadline) {
      const deadlineDate = new Date(form.deadline);
      if (!Number.isNaN(deadlineDate.getTime()) && earliestDate.getTime() >= deadlineDate.getTime()) {
        errors.earliestStart = 'Earliest start must be before the SLA deadline.';
      }
    }
  }

  if (form.carbonBudgetKg.trim()) {
    const budget = Number(form.carbonBudgetKg);
    if (!Number.isFinite(budget) || budget < 0) {
      errors.carbonBudgetKg = 'Carbon budget must be zero or greater.';
    }
  }

  return errors;
}

const FIELD_LABELS: Record<string, string> = {
  workload_name: 'Workload name',
  team_id: 'Team',
  deadline: 'SLA deadline',
  earliest_start_time: 'Earliest start',
  runtime_minutes: 'Runtime',
  power_kw: 'Average power draw',
  region: 'Region',
  container_image: 'Container image',
  cpu_request: 'CPU request',
  memory_request: 'Memory request',
  carbon_budget_kg: 'Carbon budget',
  priority: 'Priority',
  job_type: 'Workload type',
};

export interface SubmitWorkloadErrorSummary {
  title: string;
  messages: string[];
}

// Never surfaces raw backend exceptions — only Pydantic's field-level
// validation messages (already safe, user-facing text) or a short, honest
// fallback. 401 is handled globally by the API client's interceptor.
export function mapSubmitWorkloadError(err: unknown): SubmitWorkloadErrorSummary {
  const anyErr = err as any;
  const status = anyErr?.response?.status;
  const detail = anyErr?.response?.data?.detail;

  if (status === 403) {
    return { title: "Couldn't submit workload", messages: ["You don't have permission to submit workloads for this team."] };
  }

  if (Array.isArray(detail)) {
    const messages = detail.map((d: any) => {
      const field = d?.loc?.[d.loc.length - 1];
      const label = field ? FIELD_LABELS[field] || field : null;
      return label ? `${label}: ${d.msg}` : String(d?.msg || 'Invalid value.');
    });
    return { title: 'Please fix the following', messages: messages.length ? messages : ['Please check the values you entered.'] };
  }

  if (typeof detail === 'string' && detail.trim()) {
    return { title: "Couldn't submit workload", messages: [detail] };
  }

  return { title: "Couldn't submit workload", messages: ['Failed to submit workload. Please check your connection and try again.'] };
}
