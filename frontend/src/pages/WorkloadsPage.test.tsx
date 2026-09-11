import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { WorkloadsPage } from './WorkloadsPage';
import { workloadsApi, schedulingApi } from '../api/endpoints';
import { Job, User } from '../types/api';

vi.mock('../api/endpoints', () => ({
  workloadsApi: { cancelJob: vi.fn() },
  schedulingApi: { scheduleJob: vi.fn() },
}));

function makeQuery(data: any, overrides: Partial<Record<string, any>> = {}) {
  return { data, isLoading: false, isError: false, isFetching: false, refetch: vi.fn(), ...overrides };
}

let summaryQ: any;
let workloadsQ: any;
let mockUser: User;

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: mockUser, isPlatformAdmin: mockUser.role === 'PLATFORM_ADMIN' }),
}));

const regionsFixture = [
  { region_id: 'IN-TG', country: 'India', region_name: 'Telangana', timezone: 'Asia/Kolkata', currency: 'INR', electricity_maps_zone: 'IN-SO', default_plan: 'ToD', supported_tariff_plans: [], aliases: [], is_active: true },
];
let regionsQ: any;

vi.mock('../hooks/useDashboard', () => ({
  useDashboardSummary: () => summaryQ,
  useRegions: () => regionsQ,
}));

const useWorkloadsMock = vi.fn((..._args: any[]) => workloadsQ);
vi.mock('../hooks/useWorkloads', () => ({
  useWorkloads: (...args: any[]) => useWorkloadsMock(...args),
}));

const companyUser: User = {
  id: 1, username: 'u1', email: 'u1@example.com', role: 'COMPANY_USER',
  team_id: 'team-a', tenant_id: 'acme', company_name: 'Acme', is_active: true,
};

function job(overrides: Partial<Job>): Job {
  return {
    job_id: 'job-1',
    team_id: 'team-a',
    tenant_id: 'acme',
    job_type: 'BATCH',
    priority: 'HIGH',
    status: 'RUNNING',
    region: 'IN-TG',
    runtime_minutes: 30,
    power_kw: 5,
    container_image: 'img:latest',
    submitted_at: '2026-09-01T00:00:00Z',
    deadline: '2026-09-02T00:00:00Z',
    carbon_emission: 2.4,
    electricity_cost: 0.5,
    selected_start: '2026-09-01T06:00:00Z',
    ...overrides,
  };
}

const summaryFixture = {
  total_jobs: 10,
  active_jobs: 2,
  jobs: { RUNNING: 2, PENDING_APPROVAL: 1, COMPLETED: 5, FAILED: 1 },
  carbon: { baseline_emissions_kg: 1, greenshift_emissions_kg: 1, carbon_avoided_kg: 1 },
  cost: { baseline_cost: 1, greenshift_cost: 1, cost_difference: 1 },
  audit: { event_count: 1 },
};

function resetQueries() {
  summaryQ = makeQuery(summaryFixture);
  regionsQ = makeQuery(regionsFixture);
  workloadsQ = makeQuery([
    job({ job_id: 'job-submitted', status: 'SUBMITTED', priority: 'LOW', selected_start: null }),
    job({ job_id: 'job-pending', status: 'PENDING_APPROVAL', priority: 'HIGH' }),
    job({ job_id: 'job-running', name: 'Nightly ETL', status: 'RUNNING', priority: 'CRITICAL' }),
    job({ job_id: 'job-completed', status: 'COMPLETED', priority: 'MEDIUM' }),
    job({ job_id: 'job-failed', status: 'FAILED', priority: 'LOW' }),
  ]);
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/workloads']}>
      <Routes>
        <Route path="/workloads" element={<WorkloadsPage />} />
        <Route path="/submit" element={<div data-testid="landing-submit">Submit</div>} />
        <Route path="/workloads/:id" element={<div data-testid="landing-detail">Detail</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe('WorkloadsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUser = companyUser;
    resetQueries();
  });

  it('renders the page title, subtitle, Refresh, and Submit Workload', () => {
    renderPage();
    expect(screen.getByText('Workloads')).toBeInTheDocument();
    expect(screen.getByText('Monitor, review, and manage workload execution across GreenShift.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^refresh$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /submit workload/i })).toBeInTheDocument();
  });

  it('renders the KPI strip driven by backend summary data', () => {
    renderPage();
    expect(screen.getByText('Total Workloads')).toBeInTheDocument();
    expect(screen.getByText('10')).toBeInTheDocument(); // total_jobs
    expect(screen.getByText('Running')).toBeInTheDocument();
    expect(screen.getByText('Pending Approval')).toBeInTheDocument();
    expect(screen.getByText('Completed')).toBeInTheDocument();
    expect(screen.getByText('Failed')).toBeInTheDocument();
  });

  it('shows a placeholder, never a fabricated zero, while the KPI summary is loading', () => {
    summaryQ = makeQuery(undefined, { isLoading: true });
    renderPage();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    expect(screen.queryByText('DATA UNAVAILABLE')).not.toBeInTheDocument();
  });

  it('shows an honest empty state when there are no workloads at all', () => {
    workloadsQ = makeQuery([]);
    renderPage();
    expect(screen.getByText('No workloads yet')).toBeInTheDocument();
  });

  it('shows a no-results state (with Clear Filters) when filters exclude everything', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByPlaceholderText(/search workloads/i), 'no-such-workload-xyz');
    expect(screen.getByText('No Workloads Found')).toBeInTheDocument();
    expect(screen.getByText('No workloads match your filters.')).toBeInTheDocument();
    await user.click(screen.getAllByRole('button', { name: /clear filters/i })[0]);
    expect(screen.getByTestId('workload-row-job-submitted')).toBeInTheDocument();
  });

  it('searches by workload name, job ID, and job type', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByPlaceholderText(/search workloads/i), 'Nightly ETL');
    expect(screen.getByText('Nightly ETL')).toBeInTheDocument();
    expect(screen.queryByText('job-submitted')).not.toBeInTheDocument();
  });

  it('filters by status', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText(/filter by status/i), 'FAILED');
    expect(screen.getByTestId('workload-row-job-failed')).toBeInTheDocument();
    expect(screen.queryByTestId('workload-row-job-running')).not.toBeInTheDocument();
  });

  it('filters by priority', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText(/filter by priority/i), 'CRITICAL');
    expect(screen.getByText('Nightly ETL')).toBeInTheDocument();
    expect(screen.queryByText('job-completed')).not.toBeInTheDocument();
  });

  it('filters by job type', async () => {
    const user = userEvent.setup();
    workloadsQ = makeQuery([
      job({ job_id: 'job-batch', job_type: 'BATCH' }),
      job({ job_id: 'job-stream', job_type: 'STREAMING' }),
    ]);
    renderPage();
    await user.selectOptions(screen.getByLabelText(/filter by job type/i), 'STREAMING');
    expect(screen.getByTestId('workload-row-job-stream')).toBeInTheDocument();
    expect(screen.queryByTestId('workload-row-job-batch')).not.toBeInTheDocument();
  });

  it('filters by execution region', async () => {
    const user = userEvent.setup();
    workloadsQ = makeQuery([
      job({ job_id: 'job-tg', region: 'IN-TG' }),
      job({ job_id: 'job-gj', region: 'IN-GJ' }),
    ]);
    renderPage();
    await user.selectOptions(screen.getByLabelText(/filter by region/i), 'IN-GJ');
    expect(screen.getByTestId('workload-row-job-gj')).toBeInTheDocument();
    expect(screen.queryByTestId('workload-row-job-tg')).not.toBeInTheDocument();
  });

  it('filters by approval status', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText(/filter by approval/i), 'Pending');
    expect(screen.getByTestId('workload-row-job-pending')).toBeInTheDocument();
    expect(screen.queryByTestId('workload-row-job-completed')).not.toBeInTheDocument();
  });

  it('only shows a Team filter for PLATFORM_ADMIN', () => {
    renderPage(); // COMPANY_USER
    expect(screen.queryByLabelText(/filter by team/i)).not.toBeInTheDocument();

    mockUser = { ...companyUser, id: 9, role: 'PLATFORM_ADMIN', tenant_id: null };
    renderPage();
    expect(screen.getByLabelText(/filter by team/i)).toBeInTheDocument();
  });

  it('has no fake fallback values and no "Fleet Achieved" branding', () => {
    renderPage();
    expect(screen.queryByText(/fleet achieved/i)).not.toBeInTheDocument();
    expect(screen.queryByText('team-acme')).not.toBeInTheDocument();
    expect(screen.queryByText('default-team')).not.toBeInTheDocument();
  });

  it('Refresh re-fetches backend data', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('button', { name: /^refresh$/i }));
    expect(summaryQ.refetch).toHaveBeenCalledTimes(1);
    expect(workloadsQ.refetch).toHaveBeenCalledTimes(1);
  });

  it('shows an error state with Retry on API failure, without crashing the rest of the page', async () => {
    const user = userEvent.setup();
    workloadsQ = makeQuery(undefined, { isError: true });
    renderPage();
    expect(screen.getByText("We couldn't retrieve the workload registry.")).toBeInTheDocument();
    expect(screen.getByText('Workloads')).toBeInTheDocument(); // page header still renders

    await user.click(screen.getByRole('button', { name: /retry/i }));
    expect(workloadsQ.refetch).toHaveBeenCalledTimes(1);
  });

  it('requests the authorized dataset without any client-supplied team_id for a non-platform-admin', () => {
    renderPage();
    expect(useWorkloadsMock).toHaveBeenCalledWith({ teamId: undefined });
  });

  describe('role-specific experience', () => {
    it('labels the table "My Workloads" for COMPANY_USER', () => {
      renderPage();
      expect(screen.getByText(/My Workloads/)).toBeInTheDocument();
    });

    it('labels the table "Recent Workloads" (honest, team-scoped) for COMPANY_ADMIN', () => {
      mockUser = { ...companyUser, id: 2, role: 'COMPANY_ADMIN' };
      renderPage();
      expect(screen.getByText(/Recent Workloads/)).toBeInTheDocument();
      expect(screen.queryByText(/My Workloads/)).not.toBeInTheDocument();
    });

    it('labels the table "Platform Workloads" for PLATFORM_ADMIN', () => {
      mockUser = { ...companyUser, id: 3, role: 'PLATFORM_ADMIN', tenant_id: null };
      renderPage();
      expect(screen.getByText(/Platform Workloads/)).toBeInTheDocument();
    });
  });

  describe('contextual actions', () => {
    it('SUBMITTED shows Find Schedule, which triggers real scheduling then refetches', async () => {
      const user = userEvent.setup();
      (schedulingApi.scheduleJob as any).mockResolvedValue({});
      workloadsQ = makeQuery([job({ job_id: 'job-submitted', status: 'SUBMITTED', selected_start: null })]);
      renderPage();

      const row = screen.getByTestId('workload-row-job-submitted');
      await user.click(within(row).getByRole('button', { name: /find schedule/i }));

      expect(schedulingApi.scheduleJob).toHaveBeenCalledWith('job-submitted', true);
      expect(workloadsQ.refetch).toHaveBeenCalled();
    });

    it('PENDING_APPROVAL shows Review Schedule, which opens the workload (never a bypass Dispatch button)', async () => {
      const user = userEvent.setup();
      workloadsQ = makeQuery([job({ job_id: 'job-pending', status: 'PENDING_APPROVAL' })]);
      renderPage();

      const row = screen.getByTestId('workload-row-job-pending');
      expect(within(row).queryByRole('button', { name: /dispatch/i })).not.toBeInTheDocument();
      await user.click(within(row).getByRole('button', { name: /review schedule/i }));
      expect(screen.getByTestId('landing-detail')).toBeInTheDocument();
    });

    it('RUNNING shows Monitor', () => {
      workloadsQ = makeQuery([job({ job_id: 'job-running', status: 'RUNNING' })]);
      renderPage();
      const row = screen.getByTestId('workload-row-job-running');
      expect(within(row).getByRole('button', { name: /^monitor$/i })).toBeInTheDocument();
    });

    it('COMPLETED shows View Impact', () => {
      workloadsQ = makeQuery([job({ job_id: 'job-completed', status: 'COMPLETED' })]);
      renderPage();
      const row = screen.getByTestId('workload-row-job-completed');
      expect(within(row).getByRole('button', { name: /view impact/i })).toBeInTheDocument();
    });

    it('FAILED shows View Failure information', () => {
      workloadsQ = makeQuery([job({ job_id: 'job-failed', status: 'FAILED' })]);
      renderPage();
      const row = screen.getByTestId('workload-row-job-failed');
      expect(within(row).getByRole('button', { name: /view failure/i })).toBeInTheDocument();
    });

    it('DECLINED shows View Reason', () => {
      workloadsQ = makeQuery([job({ job_id: 'job-declined', status: 'DECLINED' })]);
      renderPage();
      const row = screen.getByTestId('workload-row-job-declined');
      expect(within(row).getByRole('button', { name: /view reason/i })).toBeInTheDocument();
    });

    it('every row always has a View Details action', () => {
      renderPage();
      expect(screen.getAllByTitle('View Details').length).toBe(workloadsQ.data.length);
    });

    it('cancels a cancellable workload after confirmation', async () => {
      const user = userEvent.setup();
      vi.spyOn(window, 'confirm').mockReturnValue(true);
      (workloadsApi.cancelJob as any).mockResolvedValue({ job_id: 'job-running', status: 'CANCELLED' });
      workloadsQ = makeQuery([job({ job_id: 'job-running', status: 'RUNNING' })]);
      renderPage();

      const row = screen.getByTestId('workload-row-job-running');
      await user.click(within(row).getByTitle('Cancel Job'));
      expect(workloadsApi.cancelJob).toHaveBeenCalledWith('job-running');
    });

    it('does not offer Cancel for a terminal workload', () => {
      workloadsQ = makeQuery([job({ job_id: 'job-completed', status: 'COMPLETED' })]);
      renderPage();
      const row = screen.getByTestId('workload-row-job-completed');
      expect(within(row).queryByTitle('Cancel Job')).not.toBeInTheDocument();
    });
  });
});
