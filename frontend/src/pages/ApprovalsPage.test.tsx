import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { ApprovalsPage } from './ApprovalsPage';
import { approvalsApi } from '../api/endpoints';
import { pendingApprovalItem, approvedHistoryItem, declinedHistoryItem } from '../test/fixtures/approvals';
import { User } from '../types/api';

vi.mock('../api/endpoints', () => ({
  approvalsApi: {
    approveJob: vi.fn(),
    declineJob: vi.fn(),
  },
}));

function makeQuery(data: any, overrides: Partial<Record<string, any>> = {}) {
  return { data, isLoading: false, isError: false, isFetching: false, refetch: vi.fn(), ...overrides };
}

let pendingQ: any;
let historyQ: any;
let mockUser: User;
let mockIsAdmin: boolean;

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: mockUser, isAdmin: mockIsAdmin }),
}));

const usePendingApprovalsMock = vi.fn((..._args: any[]) => pendingQ);
const useApprovalHistoryMock = vi.fn((..._args: any[]) => historyQ);
vi.mock('../hooks/useApprovals', () => ({
  usePendingApprovals: (...args: any[]) => usePendingApprovalsMock(...args),
  useApprovalHistory: (...args: any[]) => useApprovalHistoryMock(...args),
}));

const regionsFixture = [
  { region_id: 'IN-TG', country: 'India', region_name: 'Telangana', timezone: 'Asia/Kolkata', currency: 'INR', electricity_maps_zone: 'IN-SO', default_plan: 'ToD', supported_tariff_plans: [], aliases: [], is_active: true },
  { region_id: 'IN-GJ', country: 'India', region_name: 'Gujarat', timezone: 'Asia/Kolkata', currency: 'INR', electricity_maps_zone: 'IN-WE', default_plan: 'ToD', supported_tariff_plans: [], aliases: [], is_active: true },
];
vi.mock('../hooks/useDashboard', () => ({
  useRegions: () => makeQuery(regionsFixture),
}));

const adminUser: User = {
  id: 1,
  username: 'company_admin',
  email: 'admin@acme.example',
  role: 'COMPANY_ADMIN' as any,
  team_id: 'team-acme',
  is_active: true,
};

const viewerUser: User = {
  id: 2,
  username: 'company_user',
  email: 'user@acme.example',
  role: 'COMPANY_USER' as any,
  team_id: 'team-acme',
  is_active: true,
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/approvals']}>
      <Routes>
        <Route path="/approvals" element={<ApprovalsPage />} />
        <Route path="/scheduling" element={<div data-testid="landing-scheduling">Scheduling</div>} />
        <Route path="/workloads/:id" element={<div data-testid="landing-detail">Detail</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe('ApprovalsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUser = adminUser;
    mockIsAdmin = true;
    pendingQ = makeQuery([]);
    historyQ = makeQuery([]);
  });

  describe('page identity', () => {
    it('renders the title and subtitle, with the old governance wording removed', () => {
      renderPage();
      expect(screen.getByRole('heading', { name: 'Review' })).toBeInTheDocument();
      expect(screen.getByText('Review and authorize recommended workload schedules before execution.')).toBeInTheDocument();
      expect(screen.queryByText(/Human-in-the-Loop Governance/i)).not.toBeInTheDocument();
    });
  });

  describe('pending count', () => {
    it('shows the real backend-driven pending count', () => {
      pendingQ = makeQuery([pendingApprovalItem]);
      renderPage();
      expect(screen.getByText('1 Pending')).toBeInTheDocument();
    });

    it('shows a placeholder, not a fabricated zero, while loading', () => {
      pendingQ = makeQuery(undefined, { isLoading: true });
      renderPage();
      expect(screen.getByText('—')).toBeInTheDocument();
    });

    it('shows an honest unavailable state when the count cannot be loaded', () => {
      pendingQ = makeQuery(undefined, { isError: true });
      renderPage();
      expect(screen.getByText('Data unavailable')).toBeInTheDocument();
    });
  });

  describe('pending queue states', () => {
    it('shows a loading state', () => {
      pendingQ = makeQuery(undefined, { isLoading: true });
      renderPage();
      expect(screen.queryByText(/No pending approvals/i)).not.toBeInTheDocument();
    });

    it('shows an honest empty state', () => {
      renderPage();
      expect(screen.getByText('No pending approvals')).toBeInTheDocument();
      expect(screen.getByText('There are no workload schedules waiting for your decision.')).toBeInTheDocument();
    });

    it('shows an error state with Retry', async () => {
      const user = userEvent.setup();
      pendingQ = makeQuery(undefined, { isError: true });
      renderPage();
      expect(screen.getByText("Couldn't load approvals. Please try again.")).toBeInTheDocument();
      await user.click(screen.getAllByRole('button', { name: /retry/i })[0]);
      expect(pendingQ.refetch).toHaveBeenCalled();
    });
  });

  describe('pending card content', () => {
    beforeEach(() => {
      pendingQ = makeQuery([pendingApprovalItem]);
    });

    it('shows workload name, job ID, priority, team, and region', () => {
      renderPage();
      expect(screen.getByText('nightly-batch-etl')).toBeInTheDocument();
      expect(screen.getByText('job-9001')).toBeInTheDocument();
      expect(screen.getByText(/High/)).toBeInTheDocument();
      expect(screen.getByText(/Team team-acme/)).toBeInTheDocument();
      expect(screen.getByText(/US-CAL-CISO/)).toBeInTheDocument();
    });

    it('shows deadline, recommended start, estimated carbon, estimated cost, carbon budget, and SLA status', () => {
      renderPage();
      expect(screen.getByText('Deadline')).toBeInTheDocument();
      expect(screen.getByText('Recommended Start')).toBeInTheDocument();
      expect(screen.getByText('Estimated Carbon')).toBeInTheDocument();
      expect(screen.getByText('4.10 kg CO₂ (est.)')).toBeInTheDocument();
      expect(screen.getByText('Estimated Cost')).toBeInTheDocument();
      expect(screen.getByText('Carbon Budget')).toBeInTheDocument();
      expect(screen.getByText('5 kg CO₂ ✓')).toBeInTheDocument();
      expect(screen.getByText('SLA Status')).toBeInTheDocument();
      expect(screen.getByText('Within deadline')).toBeInTheDocument();
    });

    it('shows carbon reduction vs immediate execution using the real backend percentage', () => {
      renderPage();
      expect(screen.getByText('↓ 31% carbon')).toBeInTheDocument();
    });

    it('omits carbon reduction entirely when the backend has not provided it, never inventing a percentage', () => {
      pendingQ = makeQuery([{ ...pendingApprovalItem, carbon_reduction_pct: null }]);
      renderPage();
      expect(screen.queryByText(/vs Immediate Execution/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/%/)).not.toBeInTheDocument();
    });

    it('shows honest unavailable states for carbon budget and SLA status when the backend has not provided them', () => {
      pendingQ = makeQuery([{ ...pendingApprovalItem, carbon_budget_kg: null, sla_met: null }]);
      renderPage();
      expect(screen.getByText('No carbon budget')).toBeInTheDocument();
      expect(screen.getByText('Unavailable')).toBeInTheDocument();
    });

    it('shows the Approval Context', () => {
      renderPage();
      expect(screen.getByText(/Approval Context:/)).toBeInTheDocument();
      expect(screen.getByText(/Carbon budget exceeded for team-acme/)).toBeInTheDocument();
    });

    it('falls back to the honest default Approval Context when the backend gives no reason', () => {
      pendingQ = makeQuery([{ ...pendingApprovalItem, reason: null }]);
      renderPage();
      expect(screen.getByText(/Schedule requires human authorization before execution\./)).toBeInTheDocument();
    });

    it('has a Review Schedule action, not a one-click approve', () => {
      renderPage();
      expect(screen.getByRole('button', { name: /review schedule/i })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /^approve$/i })).not.toBeInTheDocument();
    });
  });

  describe('review modal', () => {
    beforeEach(() => {
      pendingQ = makeQuery([pendingApprovalItem]);
    });

    it('opens on Review Schedule and shows the real recommendation summary', async () => {
      const user = userEvent.setup();
      renderPage();
      await user.click(screen.getByRole('button', { name: /review schedule/i }));

      expect(screen.getByRole('dialog')).toBeInTheDocument();
      expect(screen.getByText('Summary')).toBeInTheDocument();
      expect(screen.getByText('Execution Region')).toBeInTheDocument();
    });

    it('shows the Immediate vs GreenShift comparison using real baseline data', async () => {
      const user = userEvent.setup();
      renderPage();
      await user.click(screen.getByRole('button', { name: /review schedule/i }));

      expect(screen.getByText('Comparison')).toBeInTheDocument();
      expect(screen.getByText('Immediate Execution')).toBeInTheDocument();
      expect(screen.getByText('GreenShift')).toBeInTheDocument();
      expect(screen.getByText('6.00 kg CO₂ (est.)')).toBeInTheDocument();
    });

    it('shows unavailable comparison cells rather than a fabricated figure when baseline data is missing', async () => {
      const user = userEvent.setup();
      pendingQ = makeQuery([{ ...pendingApprovalItem, baseline_carbon_emission_kg: null, baseline_cost_usd: null, baseline_start_utc: null, baseline_start_local: null }]);
      renderPage();
      await user.click(screen.getByRole('button', { name: /review schedule/i }));

      const dialog = screen.getByRole('dialog');
      const dashCells = within(dialog).getAllByText('—');
      expect(dashCells.length).toBeGreaterThan(0);
    });

    it('View Scheduling Analysis navigates to the real Scheduling page with the job id', async () => {
      const user = userEvent.setup();
      renderPage();
      await user.click(screen.getByRole('button', { name: /review schedule/i }));
      await user.click(screen.getByRole('button', { name: /view scheduling analysis/i }));
      expect(screen.getByTestId('landing-scheduling')).toBeInTheDocument();
    });

    it('View Workload navigates to the real Workload Detail page', async () => {
      const user = userEvent.setup();
      renderPage();
      await user.click(screen.getByRole('button', { name: /review schedule/i }));
      await user.click(screen.getByRole('button', { name: /^view workload$/i }));
      expect(screen.getByTestId('landing-detail')).toBeInTheDocument();
    });

    it('closes on Escape', async () => {
      const user = userEvent.setup();
      renderPage();
      await user.click(screen.getByRole('button', { name: /review schedule/i }));
      expect(screen.getByRole('dialog')).toBeInTheDocument();
      await user.keyboard('{Escape}');
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  describe('approve', () => {
    beforeEach(() => {
      pendingQ = makeQuery([pendingApprovalItem]);
    });

    it('allows approval with an empty note (optional)', async () => {
      const user = userEvent.setup();
      (approvalsApi.approveJob as any).mockResolvedValue({});
      renderPage();
      await user.click(screen.getByRole('button', { name: /review schedule/i }));
      await user.click(screen.getByRole('button', { name: /approve schedule/i }));

      expect(approvalsApi.approveJob).toHaveBeenCalledWith('job-9001', 42, undefined);
    });

    it('shows the correct success message and refreshes pending/history after approval', async () => {
      const user = userEvent.setup();
      (approvalsApi.approveJob as any).mockResolvedValue({});
      renderPage();
      await user.click(screen.getByRole('button', { name: /review schedule/i }));
      await user.click(screen.getByRole('button', { name: /approve schedule/i }));

      expect(await screen.findByText('Schedule approved — ready for execution')).toBeInTheDocument();
      expect(pendingQ.refetch).toHaveBeenCalled();
      expect(historyQ.refetch).toHaveBeenCalled();
    });

    it('shows a friendly error on approval failure, not a raw exception', async () => {
      const user = userEvent.setup();
      (approvalsApi.approveJob as any).mockRejectedValue({ response: { data: {} } });
      renderPage();
      await user.click(screen.getByRole('button', { name: /review schedule/i }));
      await user.click(screen.getByRole('button', { name: /approve schedule/i }));

      expect(await screen.findByText("Couldn't approve this schedule. Please try again.")).toBeInTheDocument();
    });
  });

  describe('decline', () => {
    beforeEach(() => {
      pendingQ = makeQuery([pendingApprovalItem]);
    });

    it('disables Decline Schedule until a reason is entered', async () => {
      const user = userEvent.setup();
      renderPage();
      await user.click(screen.getByRole('button', { name: /review schedule/i }));

      const declineButton = screen.getByRole('button', { name: /decline schedule/i });
      expect(declineButton).toBeDisabled();

      await user.type(screen.getByLabelText(/decision note/i), 'Deadline conflict');
      expect(declineButton).toBeEnabled();
    });

    it('calls declineJob with the required reason and refreshes after success', async () => {
      const user = userEvent.setup();
      (approvalsApi.declineJob as any).mockResolvedValue({});
      renderPage();
      await user.click(screen.getByRole('button', { name: /review schedule/i }));
      await user.type(screen.getByLabelText(/decision note/i), 'Deadline conflict');
      await user.click(screen.getByRole('button', { name: /decline schedule/i }));

      expect(approvalsApi.declineJob).toHaveBeenCalledWith('job-9001', 42, 'Deadline conflict');
      expect(await screen.findByText('Schedule declined')).toBeInTheDocument();
      expect(pendingQ.refetch).toHaveBeenCalled();
      expect(historyQ.refetch).toHaveBeenCalled();
    });

    it('shows a friendly error on decline failure', async () => {
      const user = userEvent.setup();
      (approvalsApi.declineJob as any).mockRejectedValue({ response: { data: {} } });
      renderPage();
      await user.click(screen.getByRole('button', { name: /review schedule/i }));
      await user.type(screen.getByLabelText(/decision note/i), 'Deadline conflict');
      await user.click(screen.getByRole('button', { name: /decline schedule/i }));

      expect(await screen.findByText("Couldn't decline this schedule. Please try again.")).toBeInTheDocument();
    });
  });

  describe('history tab', () => {
    it('switches to History and shows both approved and declined decisions', async () => {
      const user = userEvent.setup();
      historyQ = makeQuery([approvedHistoryItem, declinedHistoryItem]);
      renderPage();
      await user.click(screen.getByRole('tab', { name: /history/i }));

      expect(screen.getByText('customer-churn-training')).toBeInTheDocument();
      expect(screen.getByText('APPROVED')).toBeInTheDocument();
      expect(screen.getByText('etl-pipeline-118')).toBeInTheDocument();
      expect(screen.getByText('DECLINED')).toBeInTheDocument();
      expect(screen.getByText('Exceeds quarterly carbon cap')).toBeInTheDocument();
    });

    it('shows the decided-by and decided-at columns', async () => {
      const user = userEvent.setup();
      historyQ = makeQuery([approvedHistoryItem]);
      renderPage();
      await user.click(screen.getByRole('tab', { name: /history/i }));
      expect(screen.getByText('company_admin')).toBeInTheDocument();
    });

    it('shows an honest empty state', async () => {
      const user = userEvent.setup();
      renderPage();
      await user.click(screen.getByRole('tab', { name: /history/i }));
      expect(screen.getByText('No approval history')).toBeInTheDocument();
      expect(screen.getByText('There are no recorded approval decisions yet.')).toBeInTheDocument();
    });

    it('shows a loading state', async () => {
      const user = userEvent.setup();
      historyQ = makeQuery(undefined, { isLoading: true });
      renderPage();
      await user.click(screen.getByRole('tab', { name: /history/i }));
      expect(screen.queryByText('No approval history')).not.toBeInTheDocument();
    });

    it('shows an error state with Retry', async () => {
      const user = userEvent.setup();
      historyQ = makeQuery(undefined, { isError: true });
      renderPage();
      await user.click(screen.getByRole('tab', { name: /history/i }));
      expect(screen.getByText("Couldn't load approvals. Please try again.")).toBeInTheDocument();
      await user.click(screen.getByRole('button', { name: /retry/i }));
      expect(historyQ.refetch).toHaveBeenCalled();
    });
  });

  describe('RBAC', () => {
    beforeEach(() => {
      mockUser = viewerUser;
      mockIsAdmin = false;
      pendingQ = makeQuery([pendingApprovalItem]);
    });

    it('shows a read-only notice and no approve/decline actions for COMPANY_USER', async () => {
      renderPage();
      expect(screen.getByText(/read-only observation permissions/)).toBeInTheDocument();
      expect(screen.getByText(/Only a Company Admin or Platform Admin/)).toBeInTheDocument();
    });

    it('the review modal has no Approve/Decline actions for COMPANY_USER, only Close', async () => {
      const user = userEvent.setup();
      renderPage();
      await user.click(screen.getByRole('button', { name: /review schedule/i }));

      expect(screen.queryByRole('button', { name: /approve schedule/i })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /decline schedule/i })).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: /^close$/i })).toBeInTheDocument();
    });

    it('scopes the request to the caller team for a non-admin user', () => {
      renderPage();
      expect(usePendingApprovalsMock).toHaveBeenCalledWith(viewerUser.team_id);
      expect(useApprovalHistoryMock).toHaveBeenCalledWith(viewerUser.team_id);
    });
  });

  describe('admin scoping', () => {
    it('requests all teams (no team filter) for an admin user', () => {
      renderPage();
      expect(usePendingApprovalsMock).toHaveBeenCalledWith(undefined);
      expect(useApprovalHistoryMock).toHaveBeenCalledWith(undefined);
    });
  });

  describe('refresh', () => {
    it('re-fetches both pending and history data', async () => {
      const user = userEvent.setup();
      renderPage();
      await user.click(screen.getByRole('button', { name: /^refresh$/i }));
      expect(pendingQ.refetch).toHaveBeenCalledTimes(1);
      expect(historyQ.refetch).toHaveBeenCalledTimes(1);
    });
  });
});
