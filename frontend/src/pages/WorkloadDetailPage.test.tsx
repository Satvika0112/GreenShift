import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { WorkloadDetailPage } from './WorkloadDetailPage';
import { schedulingApi, dispatchApi, workloadsApi, monitoringApi } from '../api/endpoints';
import { WorkloadDetail } from '../types/api';

vi.mock('../api/endpoints', () => ({
  schedulingApi: { scheduleJob: vi.fn() },
  dispatchApi: { dispatchJob: vi.fn() },
  workloadsApi: { cancelJob: vi.fn() },
  monitoringApi: { getActualImpact: vi.fn().mockRejectedValue({ response: { status: 404 } }) },
}));

function makeQuery(data: any, overrides: Partial<Record<string, any>> = {}) {
  return { data, isLoading: false, isError: false, error: null, refetch: vi.fn(), ...overrides };
}

let workloadQ: any;
const useWorkloadMock = vi.fn((..._args: any[]) => workloadQ);

vi.mock('../hooks/useWorkloads', () => ({
  useWorkload: (...args: any[]) => useWorkloadMock(...args),
}));

const regionsFixture = [
  { region_id: 'IN-TG', country: 'India', region_name: 'Telangana', timezone: 'Asia/Kolkata', currency: 'INR', electricity_maps_zone: 'IN-SO', default_plan: 'ToD', supported_tariff_plans: [], aliases: [], is_active: true },
];
vi.mock('../hooks/useDashboard', () => ({
  useRegions: () => makeQuery(regionsFixture),
}));

function detail(overrides: Partial<WorkloadDetail> = {}): WorkloadDetail {
  return {
    job_id: 'job-1',
    team_id: 'team-a',
    tenant_id: 'acme',
    job_type: 'BATCH',
    priority: 'HIGH',
    status: 'SUBMITTED',
    submitted_at: '2026-09-01T00:00:00Z',
    deadline: '2026-09-02T00:00:00Z',
    runtime_minutes: 30,
    power_kw: 5,
    deferrable: true,
    region: 'IN-TG',
    container_image: 'img:latest',
    cpu_request: '500m',
    memory_request: '512Mi',
    audit_events: [],
    ...overrides,
  };
}

const scheduleDecisionFixture = {
  job_id: 'job-1',
  selected_start: '2026-09-01T06:00:00Z',
  selected_end: '2026-09-01T06:30:00Z',
  carbon_intensity: 250,
  electricity_cost: 0.4,
  carbon_emission: 2.4,
  region_id: 'IN-TG',
  currency: 'USD',
  candidates_evaluated: 10,
  feasible_candidates_count: 4,
  baseline_carbon_emission: 5,
  baseline_cost: 1,
  carbon_avoided: 2.6,
  cost_difference: 0.6,
  scheduling_delay_hours: 2,
  sla_met: true,
};

function renderDetail(id = 'job-1') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/workloads/${id}`]}>
        <Routes>
          <Route path="/workloads/:id" element={<WorkloadDetailPage />} />
          <Route path="/workloads" element={<div data-testid="landing-workloads">Workloads</div>} />
          <Route path="/scheduling" element={<div data-testid="landing-scheduling">Scheduling</div>} />
          <Route path="/monitoring" element={<div data-testid="landing-monitoring">Monitoring</div>} />
          <Route path="/impact" element={<div data-testid="landing-impact">Impact</div>} />
          <Route path="/audit" element={<div data-testid="landing-audit">Audit</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('WorkloadDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (monitoringApi.getActualImpact as any).mockRejectedValue({ response: { status: 404 } });
  });

  it('shows a loading skeleton while the workload is loading', () => {
    workloadQ = makeQuery(undefined, { isLoading: true });
    renderDetail();
    expect(screen.getByText('Back to Workloads')).toBeInTheDocument();
    expect(screen.queryByText('Overview')).not.toBeInTheDocument();
  });

  it('shows an honest not-found error state with Retry-equivalent navigation, without a stack trace', () => {
    workloadQ = makeQuery(undefined, {
      isError: true,
      error: { response: { data: { detail: "Job 'job-1' not found" } } },
    });
    renderDetail();
    expect(screen.getByText("Job 'job-1' not found")).toBeInTheDocument();
    expect(screen.queryByText(/traceback|Exception|SQLAlchemy/i)).not.toBeInTheDocument();
  });

  it('loads and renders the real workload once resolved', () => {
    workloadQ = makeQuery(detail());
    renderDetail();
    expect(screen.getByRole('heading', { name: 'job-1' })).toBeInTheDocument();
    expect(screen.getByText('Overview')).toBeInTheDocument();
  });

  describe('Overview', () => {
    it('uses real backend fields, with a "—" fallback rather than a fabricated default', () => {
      workloadQ = makeQuery(detail({ priority: null, team_id: '' }));
      renderDetail();
      // Priority row shows the em dash fallback rather than any invented value.
      expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    });
  });

  describe('Compute Requirements', () => {
    it('uses real backend fields and never fabricates a CPU/memory default', () => {
      workloadQ = makeQuery(detail({ cpu_request: undefined, memory_request: undefined }));
      renderDetail();
      expect(screen.getByText('Compute Requirements')).toBeInTheDocument();
      expect(screen.queryByText('500m')).not.toBeInTheDocument();
      expect(screen.queryByText('512Mi')).not.toBeInTheDocument();
    });
  });

  describe('Scheduling Summary', () => {
    it('shows a real, non-fabricated Not Scheduled state with a Find Schedule action', async () => {
      const user = userEvent.setup();
      (schedulingApi.scheduleJob as any).mockResolvedValue({});
      workloadQ = makeQuery(detail({ status: 'SUBMITTED' }));
      renderDetail();

      expect(screen.getByText('Not scheduled yet')).toBeInTheDocument();
      await user.click(screen.getByRole('button', { name: /find schedule/i }));
      expect(schedulingApi.scheduleJob).toHaveBeenCalledWith('job-1', true);
      await waitFor(() => expect(workloadQ.refetch).toHaveBeenCalled());
    });

    it('uses real backend scheduling values, never fabricated carbon/cost', () => {
      workloadQ = makeQuery(detail({ status: 'PENDING_APPROVAL', schedule_decision: scheduleDecisionFixture as any }));
      renderDetail();
      expect(screen.getByText('2.40 kg CO₂ (est.)')).toBeInTheDocument();
      expect(screen.getByText('$0.40')).toBeInTheDocument();
    });

    it('links to the full Scheduling Analysis page with the real job id', async () => {
      const user = userEvent.setup();
      workloadQ = makeQuery(detail({ status: 'PENDING_APPROVAL', schedule_decision: scheduleDecisionFixture as any }));
      renderDetail();
      await user.click(screen.getByRole('button', { name: /view full scheduling analysis/i }));
      expect(screen.getByTestId('landing-scheduling')).toBeInTheDocument();
    });
  });

  describe('Lifecycle', () => {
    it('renders the real current stage for a running workload', () => {
      workloadQ = makeQuery(detail({ status: 'RUNNING', schedule_decision: scheduleDecisionFixture as any }));
      renderDetail();
      expect(screen.getByText('Workload Lifecycle')).toBeInTheDocument();
      expect(screen.getAllByText('RUNNING').length).toBeGreaterThan(0);
    });

    it('shows a terminal notice for a declined workload without fabricating further progress', () => {
      workloadQ = makeQuery(detail({ status: 'DECLINED', schedule_decision: scheduleDecisionFixture as any }));
      renderDetail();
      expect(screen.getByText(/will not proceed further/i)).toBeInTheDocument();
    });
  });

  describe('Execution', () => {
    it('shows Not Yet Dispatched when there is no real Kubernetes telemetry', () => {
      workloadQ = makeQuery(detail({ status: 'APPROVED', schedule_decision: scheduleDecisionFixture as any }));
      renderDetail();
      expect(screen.getByText('Not Yet Dispatched')).toBeInTheDocument();
    });

    it('uses real Kubernetes fields and derives Actual Runtime only from two real timestamps', () => {
      workloadQ = makeQuery(
        detail({
          status: 'RUNNING',
          schedule_decision: scheduleDecisionFixture as any,
          kubernetes: {
            kubernetes_job_name: 'gs-job-1',
            pod_name: 'gs-job-1-pod',
            k8s_status: 'Running',
            gs_status: 'RUNNING',
            planned_start: '2026-09-01T06:00:00Z',
            actual_start: '2026-09-01T06:05:00Z',
            actual_end: '2026-09-01T06:35:00Z',
          },
        })
      );
      renderDetail();
      expect(screen.getByText('gs-job-1')).toBeInTheDocument();
      expect(screen.getAllByText('30 min').length).toBeGreaterThanOrEqual(2); // runtime + derived actual runtime
    });

    it('links to Monitoring once execution telemetry exists', async () => {
      const user = userEvent.setup();
      workloadQ = makeQuery(
        detail({ status: 'RUNNING', kubernetes: { kubernetes_job_name: 'gs-job-1', gs_status: 'RUNNING' } })
      );
      renderDetail();
      await user.click(screen.getByRole('button', { name: /monitor execution/i }));
      expect(screen.getByTestId('landing-monitoring')).toBeInTheDocument();
    });
  });

  describe('Impact', () => {
    it('shows "Impact data is not available yet" before a schedule decision exists', () => {
      workloadQ = makeQuery(detail({ status: 'SUBMITTED' }));
      renderDetail();
      expect(screen.getByText('Impact data is not available yet.')).toBeInTheDocument();
    });

    it('shows the real ESTIMATED figures once a schedule decision exists', () => {
      workloadQ = makeQuery(detail({ status: 'PENDING_APPROVAL', schedule_decision: scheduleDecisionFixture as any }));
      renderDetail();
      expect(screen.getByText('Estimated at scheduling time')).toBeInTheDocument();
      expect(screen.getByText('Met')).toBeInTheDocument(); // sla_met: true
    });

    it('shows OBSERVED/ACTUAL figures for a completed workload with real execution telemetry', async () => {
      (monitoringApi.getActualImpact as any).mockResolvedValue({
        job_id: 'job-1',
        estimated_carbon_emission_kg: 2.4,
        estimated_cost_usd: 0.4,
        estimated_carbon_intensity: 250,
        actual_carbon_emission_kg: 2.1,
        actual_cost_usd: 0.35,
        actual_carbon_intensity: 230,
        carbon_estimation_error_pct: -12.5,
        cost_estimation_error_pct: -12.5,
        actual_vs_baseline_carbon_saved_kg: 2.9,
        actual_vs_baseline_carbon_reduction_pct: 58,
        actual_vs_baseline_cost_saved_usd: 0.65,
        estimation_quality: 'ACCURATE',
      });
      workloadQ = makeQuery(detail({ status: 'COMPLETED', schedule_decision: scheduleDecisionFixture as any }));
      renderDetail();

      await waitFor(() => expect(screen.getByText('Observed / Actual')).toBeInTheDocument());
      expect(screen.getByText('ACCURATE')).toBeInTheDocument();
    });

    it('links to the Impact Reports page', async () => {
      const user = userEvent.setup();
      workloadQ = makeQuery(detail({ status: 'PENDING_APPROVAL', schedule_decision: scheduleDecisionFixture as any }));
      renderDetail();
      await user.click(screen.getByRole('button', { name: /view impact report/i }));
      expect(screen.getByTestId('landing-impact')).toBeInTheDocument();
    });
  });

  describe('Activity', () => {
    it('renders real audit events, not fabricated ones', () => {
      workloadQ = makeQuery(
        detail({
          audit_events: [
            { event_id: 'e1', sequence: 1, event_type: 'JOB_SUBMITTED', job_id: 'job-1', timestamp: '2026-09-01T00:00:00Z', payload_hash: 'h1', previous_hash: 'GENESIS', current_hash: 'h1' },
          ],
        })
      );
      renderDetail();
      expect(screen.getByText('Workload submitted')).toBeInTheDocument();
    });

    it('shows an honest empty state when there are no events yet', () => {
      workloadQ = makeQuery(detail({ audit_events: [] }));
      renderDetail();
      expect(screen.getByText('No lifecycle events recorded yet.')).toBeInTheDocument();
    });

    it('links to the Audit & Trust page', async () => {
      const user = userEvent.setup();
      workloadQ = makeQuery(detail());
      renderDetail();
      await user.click(screen.getByRole('button', { name: /view audit trail/i }));
      expect(screen.getByTestId('landing-audit')).toBeInTheDocument();
    });
  });

  describe('actions', () => {
    it('offers Dispatch only for a real dispatch-eligible status, never bypassing approval from PENDING_APPROVAL', () => {
      workloadQ = makeQuery(detail({ status: 'PENDING_APPROVAL', schedule_decision: scheduleDecisionFixture as any }));
      renderDetail();
      expect(screen.queryByRole('button', { name: /^dispatch$/i })).not.toBeInTheDocument();
    });

    it('offers Dispatch for an APPROVED workload and dispatches on click', async () => {
      const user = userEvent.setup();
      (dispatchApi.dispatchJob as any).mockResolvedValue({ kubernetes_job_name: 'gs-job-1' });
      workloadQ = makeQuery(detail({ status: 'APPROVED', schedule_decision: scheduleDecisionFixture as any }));
      renderDetail();

      await user.click(screen.getByRole('button', { name: /^dispatch$/i }));
      expect(dispatchApi.dispatchJob).toHaveBeenCalledWith('job-1');
      await waitFor(() => expect(screen.getByText(/dispatched to kubernetes/i)).toBeInTheDocument());
    });

    it('offers Cancel for a non-terminal workload and cancels on confirmation', async () => {
      const user = userEvent.setup();
      vi.spyOn(window, 'confirm').mockReturnValue(true);
      (workloadsApi.cancelJob as any).mockResolvedValue({ job_id: 'job-1', status: 'CANCELLED' });
      workloadQ = makeQuery(detail({ status: 'SUBMITTED' }));
      renderDetail();

      await user.click(screen.getByRole('button', { name: /cancel job/i }));
      expect(workloadsApi.cancelJob).toHaveBeenCalledWith('job-1');
    });

    it('does not offer Cancel for a terminal workload', () => {
      workloadQ = makeQuery(detail({ status: 'COMPLETED', schedule_decision: scheduleDecisionFixture as any }));
      renderDetail();
      expect(screen.queryByRole('button', { name: /cancel job/i })).not.toBeInTheDocument();
    });

    it('Refresh re-fetches the workload', async () => {
      const user = userEvent.setup();
      workloadQ = makeQuery(detail());
      renderDetail();
      await user.click(screen.getByRole('button', { name: /^refresh$/i }));
      expect(workloadQ.refetch).toHaveBeenCalledTimes(1);
    });
  });
});
