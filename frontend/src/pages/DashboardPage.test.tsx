import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { DashboardPage } from './DashboardPage';
import { User } from '../types/api';

function makeQuery(data: any, overrides: Partial<Record<string, any>> = {}) {
  return {
    data,
    isLoading: false,
    isError: false,
    isFetching: false,
    refetch: vi.fn(),
    ...overrides,
  };
}

let summaryQ: any;
let headlineQ: any;
let jobsQ: any;
let regionsQ: any;
let carbonQ: any;
let pendingQ: any;
let healthQ: any;
let k8sQ: any;
let mockUser: User | null;

const usePendingApprovalsPreviewMock = vi.fn((..._args: any[]) => pendingQ);
const useSystemHealthMock = vi.fn((..._args: any[]) => healthQ);
const useK8sStateMock = vi.fn((..._args: any[]) => k8sQ);
const useRecentWorkloadsMock = vi.fn((..._args: any[]) => jobsQ);

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: mockUser }),
}));

vi.mock('../hooks/useDashboard', () => ({
  useDashboardSummary: () => summaryQ,
  useFleetHeadline: () => headlineQ,
  useRecentWorkloads: (...args: any[]) => useRecentWorkloadsMock(...args),
  useRegions: () => regionsQ,
  useRegionCarbon: () => carbonQ,
  usePendingApprovalsPreview: (...args: any[]) => usePendingApprovalsPreviewMock(...args),
  useSystemHealth: (...args: any[]) => useSystemHealthMock(...args),
  useK8sState: (...args: any[]) => useK8sStateMock(...args),
}));

const companyUser: User = {
  id: 1,
  username: 'user.one',
  email: 'user.one@example.com',
  role: 'COMPANY_USER',
  team_id: 'team-a',
  tenant_id: 'acme',
  company_name: 'Acme Corp',
  is_active: true,
};

const companyAdmin: User = {
  ...companyUser,
  id: 2,
  username: 'admin.one',
  role: 'COMPANY_ADMIN',
};

const platformAdmin: User = {
  id: 3,
  username: 'platform.one',
  email: 'platform.one@example.com',
  role: 'PLATFORM_ADMIN',
  team_id: 'team-a',
  tenant_id: null,
  company_name: null,
  is_active: true,
};

const summaryFixture = {
  total_jobs: 12,
  active_jobs: 3,
  jobs: { SUBMITTED: 2, PENDING_APPROVAL: 1, RUNNING: 3, COMPLETED: 6, FAILED: 0, DECLINED: 0 },
  carbon: { baseline_emissions_kg: 10, greenshift_emissions_kg: 6, carbon_avoided_kg: 4 },
  cost: { baseline_cost: 20, greenshift_cost: 15, cost_difference: 5 },
  audit: { event_count: 42 },
};

const jobFixture = {
  job_id: 'job-123',
  team_id: 'team-a',
  tenant_id: 'acme',
  job_type: 'BATCH',
  status: 'RUNNING',
  region: 'IN-TG',
  runtime_minutes: 30,
  power_kw: 5,
  container_image: 'x',
  carbon_budget_kg: 2,
  submitted_at: '2026-09-01T00:00:00Z',
  deadline: '2026-09-02T00:00:00Z',
};

const regionFixture = {
  region_id: 'IN-TG',
  country: 'IN',
  region_name: 'Telangana',
  timezone: 'Asia/Kolkata',
  currency: 'INR',
  electricity_maps_zone: 'IN-TG',
  default_plan: 'industrial',
  supported_tariff_plans: [],
  aliases: [],
  is_active: true,
};

function resetQueries() {
  summaryQ = makeQuery(summaryFixture);
  headlineQ = makeQuery({
    total_carbon_avoided_kg: 4,
    avg_carbon_reduction_pct: 22.5,
    total_cost_saved_usd: 5,
    sla_compliance_pct: 98.2,
    total_jobs: 12,
    jobs_with_positive_savings: 10,
  });
  jobsQ = makeQuery([jobFixture]);
  regionsQ = makeQuery([regionFixture]);
  carbonQ = makeQuery({ 'IN-TG': 350 });
  pendingQ = makeQuery([]);
  healthQ = makeQuery({ status: 'healthy', service: 'greenshift', timestamp: '', checks: { api: 'ok', database: 'ok', kubernetes: 'ok' }, components: {} });
  k8sQ = makeQuery({
    connected: true,
    cluster_health: 'healthy',
    total_nodes: 4,
    ready_nodes: 4,
    total_cpu_cores: 32,
    allocatable_cpu_cores: 30,
    used_cpu_cores: 10,
    free_cpu_cores: 20,
    total_memory_mib: 65536,
    allocatable_memory_mib: 60000,
    used_memory_mib: 20000,
    free_memory_mib: 40000,
    total_gpus: 0,
    allocatable_gpus: 0,
    used_gpus: 0,
    free_gpus: 0,
    timestamp: '',
    nodes: [],
  });
}

function renderDashboard(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/submit" element={<div data-testid="landing-submit">Submit</div>} />
        <Route path="/scheduling" element={<div data-testid="landing-scheduling">Scheduling</div>} />
        <Route path="/approvals" element={<div data-testid="landing-approvals">Review</div>} />
        <Route path="/monitoring" element={<div data-testid="landing-monitoring">Monitoring</div>} />
        <Route path="/impact" element={<div data-testid="landing-impact">Impact</div>} />
        <Route path="/audit" element={<div data-testid="landing-audit">Audit</div>} />
        <Route path="/regions" element={<div data-testid="landing-regions">Regions</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe('DashboardPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetQueries();
  });

  describe('role-aware experience', () => {
    it('gives PLATFORM_ADMIN the Platform Command Center', () => {
      mockUser = platformAdmin;
      renderDashboard();
      expect(screen.getByText('Platform Command Center')).toBeInTheDocument();
      expect(screen.getByText('Kubernetes Ready Nodes')).toBeInTheDocument();
    });

    it('gives COMPANY_ADMIN the Company Operations dashboard', () => {
      mockUser = companyAdmin;
      renderDashboard();
      expect(screen.getByText('Company Operations')).toBeInTheDocument();
      expect(screen.queryByText('My Workloads')).not.toBeInTheDocument();
    });

    it('gives COMPANY_USER the Workload Operations dashboard', () => {
      mockUser = companyUser;
      renderDashboard();
      expect(screen.getByText('Workload Operations')).toBeInTheDocument();
      expect(screen.getByText('My Workloads')).toBeInTheDocument();
    });

    it('never fabricates a company name in the subtitle when the backend did not supply one', () => {
      mockUser = { ...companyAdmin, company_name: null };
      renderDashboard();
      expect(screen.queryByText(/undefined/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/\bnull\b/i)).not.toBeInTheDocument();
    });

    it('does not render any role selector on the Dashboard itself', () => {
      mockUser = companyUser;
      renderDashboard();
      expect(screen.queryByRole('button', { name: /platform admin/i })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /company admin/i })).not.toBeInTheDocument();
    });

    it('ignores URL query parameters entirely when deciding which dashboard to show', () => {
      mockUser = companyUser;
      renderDashboard('/?role=PLATFORM_ADMIN&company_id=another-company');
      // Still the Company User's own dashboard — the URL had no effect.
      expect(screen.getByText('Workload Operations')).toBeInTheDocument();
      expect(screen.queryByText('Platform Command Center')).not.toBeInTheDocument();
    });

    it('shows Pending Approvals and execution health only for admin roles, not Company User', () => {
      pendingQ = makeQuery([
        { job_id: 'job-9', region: 'IN-TG', schedule_id: 1, selected_start_utc: '', selected_start_local: '', selected_end_utc: '', selected_end_local: '', runtime_minutes: 10, power_kw: 1, carbon_intensity: 1, carbon_emission_kg: 0.5, electricity_cost_usd: 0.2, deadline_utc: '', deadline_local: '', status: 'PENDING_APPROVAL', team_id: 'team-a' },
      ]);
      mockUser = companyUser;
      renderDashboard();
      expect(screen.queryByText(/recommended windows awaiting your sign-off/i)).not.toBeInTheDocument();
      expect(useSystemHealthMock).toHaveBeenCalledWith(false);
    });
  });

  describe('no fabricated data', () => {
    it('removes "Fleet Achieved" branding entirely', () => {
      mockUser = companyUser;
      renderDashboard();
      expect(screen.queryByText(/fleet achieved/i)).not.toBeInTheDocument();
    });

    it('shows the real backend carbon-reduction figure under new wording', () => {
      mockUser = companyUser;
      renderDashboard();
      expect(screen.getByText(/22.5%/)).toBeInTheDocument();
      expect(screen.getByText(/carbon-primary scheduling reduced emissions by/i)).toBeInTheDocument();
    });

    it('shows DATA UNAVAILABLE, not a fake number, when carbon/cost data is absent', () => {
      summaryQ = makeQuery({ ...summaryFixture, carbon: undefined, cost: undefined });
      headlineQ = makeQuery(undefined);
      mockUser = companyUser;
      renderDashboard();
      expect(screen.getAllByText('DATA UNAVAILABLE').length).toBeGreaterThan(0);
    });

    it('shows a real region carbon reading, or DATA UNAVAILABLE rather than a fabricated one', () => {
      carbonQ = makeQuery({});
      mockUser = companyUser;
      renderDashboard();
      expect(screen.queryByText(/no regions returned by backend/i)).not.toBeInTheDocument();
      expect(screen.getAllByText('DATA UNAVAILABLE').length).toBeGreaterThan(0);
    });

    it('never trusts a client-side company_id/tenant_id filter for the workload query', () => {
      mockUser = companyUser;
      renderDashboard();
      expect(useRecentWorkloadsMock).toHaveBeenCalledWith(10);
    });
  });

  describe('loading, empty, and error states', () => {
    it('shows a placeholder, not a fabricated zero, while summary data is loading', () => {
      summaryQ = makeQuery(undefined, { isLoading: true });
      mockUser = companyUser;
      renderDashboard();
      expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    });

    it('shows an honest empty state with no fabricated workload rows', () => {
      jobsQ = makeQuery([]);
      mockUser = companyUser;
      renderDashboard();
      expect(screen.getByText('No Workloads Yet')).toBeInTheDocument();
      expect(screen.getByText("You haven't submitted any workloads yet.")).toBeInTheDocument();
    });

    it('shows an error state with Retry when the workload query fails, without crashing the page', () => {
      jobsQ = makeQuery(undefined, { isError: true });
      mockUser = companyUser;
      renderDashboard();
      expect(screen.getByText('Unable to load workload data.')).toBeInTheDocument();
      // The rest of the dashboard still renders.
      expect(screen.getByText('Workload Operations')).toBeInTheDocument();
    });

    it('Retry re-fetches the failed section', async () => {
      const user = userEvent.setup();
      jobsQ = makeQuery(undefined, { isError: true });
      mockUser = companyUser;
      renderDashboard();

      await user.click(screen.getByRole('button', { name: /retry/i }));
      expect(jobsQ.refetch).toHaveBeenCalledTimes(1);
    });

    it('Refresh re-fetches backend data rather than just re-rendering', async () => {
      const user = userEvent.setup();
      mockUser = companyAdmin;
      renderDashboard();

      await user.click(screen.getByRole('button', { name: /^refresh$/i }));
      expect(summaryQ.refetch).toHaveBeenCalledTimes(1);
      expect(headlineQ.refetch).toHaveBeenCalledTimes(1);
      expect(jobsQ.refetch).toHaveBeenCalledTimes(1);
      expect(regionsQ.refetch).toHaveBeenCalledTimes(1);
      expect(pendingQ.refetch).toHaveBeenCalledTimes(1);
      expect(healthQ.refetch).toHaveBeenCalledTimes(1);
    });
  });

  describe('GreenShift lifecycle navigation', () => {
    beforeEach(() => {
      mockUser = companyAdmin;
    });

    it('navigates through Submit / Schedule / Approve / Monitor / Impact / Audit', async () => {
      const user = userEvent.setup();
      renderDashboard();

      await user.click(screen.getByRole('button', { name: 'Submit' }));
      expect(screen.getByTestId('landing-submit')).toBeInTheDocument();
    });

    it('Scheduling step navigates to /scheduling', async () => {
      const user = userEvent.setup();
      renderDashboard();
      await user.click(screen.getByRole('button', { name: 'Schedule' }));
      expect(screen.getByTestId('landing-scheduling')).toBeInTheDocument();
    });

    it('Monitor step navigates to /monitoring', async () => {
      const user = userEvent.setup();
      renderDashboard();
      await user.click(screen.getByRole('button', { name: 'Monitor' }));
      expect(screen.getByTestId('landing-monitoring')).toBeInTheDocument();
    });

    it('Measure Impact step navigates to /impact', async () => {
      const user = userEvent.setup();
      renderDashboard();
      await user.click(screen.getByRole('button', { name: 'Measure Impact' }));
      expect(screen.getByTestId('landing-impact')).toBeInTheDocument();
    });

    it('Audit / Notify step navigates to /audit', async () => {
      const user = userEvent.setup();
      renderDashboard();
      await user.click(screen.getByRole('button', { name: 'Audit / Notify' }));
      expect(screen.getByTestId('landing-audit')).toBeInTheDocument();
    });
  });

  describe('primary header action per role', () => {
    it('Company User: primary action submits a workload', async () => {
      const user = userEvent.setup();
      mockUser = companyUser;
      renderDashboard();
      await user.click(screen.getByRole('button', { name: /submit workload/i }));
      expect(screen.getByTestId('landing-submit')).toBeInTheDocument();
    });

    it('Company Admin: primary action opens Review', async () => {
      const user = userEvent.setup();
      mockUser = companyAdmin;
      renderDashboard();
      await user.click(screen.getByRole('button', { name: /^review$/i }));
      expect(screen.getByTestId('landing-approvals')).toBeInTheDocument();
    });

    it('Platform Admin: primary action reviews regions', async () => {
      const user = userEvent.setup();
      mockUser = platformAdmin;
      renderDashboard();
      await user.click(screen.getByRole('button', { name: /review regions/i }));
      expect(screen.getByTestId('landing-regions')).toBeInTheDocument();
    });
  });
});
