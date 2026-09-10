import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { ApprovalsPage } from './ApprovalsPage';
import { approvalsApi } from '../api/endpoints';
import { pendingApprovalItem, declinedApprovalItem } from '../test/fixtures/approvals';
import { User } from '../types/api';

vi.mock('../api/endpoints', () => ({
  approvalsApi: {
    getPendingApprovals: vi.fn(),
    getDeclinedApprovals: vi.fn(),
    approveJob: vi.fn(),
    declineJob: vi.fn(),
  },
}));

let mockUser: User;
let mockIsAdmin: boolean;

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: mockUser, isAdmin: mockIsAdmin }),
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
    <MemoryRouter>
      <ApprovalsPage />
    </MemoryRouter>
  );
}

describe('ApprovalsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUser = adminUser;
    mockIsAdmin = true;
    (approvalsApi.getPendingApprovals as any).mockResolvedValue([]);
    (approvalsApi.getDeclinedApprovals as any).mockResolvedValue([]);
  });

  it('renders real pending approval data from the backend', async () => {
    (approvalsApi.getPendingApprovals as any).mockResolvedValue([pendingApprovalItem]);
    renderPage();

    await waitFor(() => {
      expect(screen.getByText(pendingApprovalItem.workload_name!)).toBeInTheDocument();
    });
    expect(screen.getByText(pendingApprovalItem.region)).toBeInTheDocument();
    expect(screen.getByText(`Policy Trigger: ${pendingApprovalItem.reason}`)).toBeInTheDocument();
  });

  it('renders an empty state when the backend returns zero pending approvals', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('No Pending Workload Approvals')).toBeInTheDocument();
    });
  });

  it('scopes the request to the caller team for a non-admin user, not all teams', async () => {
    mockUser = viewerUser;
    mockIsAdmin = false;
    renderPage();

    await waitFor(() => expect(approvalsApi.getPendingApprovals).toHaveBeenCalled());
    expect(approvalsApi.getPendingApprovals).toHaveBeenCalledWith(viewerUser.team_id);
    expect(approvalsApi.getDeclinedApprovals).toHaveBeenCalledWith(viewerUser.team_id);
  });

  it('requests all teams (no team filter) for an admin user', async () => {
    renderPage();
    await waitFor(() => expect(approvalsApi.getPendingApprovals).toHaveBeenCalled());
    expect(approvalsApi.getPendingApprovals).toHaveBeenCalledWith(undefined);
  });

  it('hides approve/decline actions and shows a read-only notice for a non-admin user', async () => {
    mockUser = viewerUser;
    mockIsAdmin = false;
    (approvalsApi.getPendingApprovals as any).mockResolvedValue([pendingApprovalItem]);
    renderPage();

    await waitFor(() => expect(screen.getByText(pendingApprovalItem.workload_name!)).toBeInTheDocument());
    expect(screen.queryByText('Approve Dispatch')).not.toBeInTheDocument();
    expect(screen.getByText(/read-only observation permissions/)).toBeInTheDocument();
    expect(screen.getByText(/Only a Company Admin or Platform Admin/)).toBeInTheDocument();
  });

  it('calls approveJob through the real API layer with no client-supplied approver identity', async () => {
    const user = userEvent.setup();
    (approvalsApi.getPendingApprovals as any).mockResolvedValue([pendingApprovalItem]);
    (approvalsApi.approveJob as any).mockResolvedValue({});
    renderPage();

    await waitFor(() => expect(screen.getByText('Approve Dispatch')).toBeInTheDocument());
    await user.click(screen.getByText('Approve Dispatch'));

    await waitFor(() => {
      expect(approvalsApi.approveJob).toHaveBeenCalledWith(
        pendingApprovalItem.job_id,
        pendingApprovalItem.schedule_id,
        'Approved via GreenShift Control Plane'
      );
    });
    // approved_by is derived server-side from the JWT — never passed by the client.
    const call = (approvalsApi.approveJob as any).mock.calls[0];
    expect(call).toHaveLength(3);
  });

  it('requires a non-empty reason before declining and calls declineJob with it', async () => {
    const user = userEvent.setup();
    (approvalsApi.getPendingApprovals as any).mockResolvedValue([pendingApprovalItem]);
    (approvalsApi.declineJob as any).mockResolvedValue({});
    renderPage();

    await waitFor(() => expect(screen.getByText('Review / Decline')).toBeInTheDocument());
    await user.click(screen.getByText('Review / Decline'));

    const declineButton = await screen.findByText('Decline Workload');
    expect(declineButton).toBeDisabled();

    const textarea = screen.getByPlaceholderText(/Carbon budget exceeded/);
    await user.type(textarea, 'Budget exceeded, re-batch off-peak');
    expect(declineButton).toBeEnabled();

    await user.click(declineButton);
    await waitFor(() => {
      expect(approvalsApi.declineJob).toHaveBeenCalledWith(
        pendingApprovalItem.job_id,
        pendingApprovalItem.schedule_id,
        'Budget exceeded, re-batch off-peak'
      );
    });
  });

  it('renders real declined workload history on the History tab', async () => {
    const user = userEvent.setup();
    (approvalsApi.getDeclinedApprovals as any).mockResolvedValue([declinedApprovalItem]);
    renderPage();

    await waitFor(() => expect(screen.getByText(/Declined Workloads/)).toBeInTheDocument());
    await user.click(screen.getByText(/Declined Workloads/));

    expect(screen.getByText(declinedApprovalItem.job_id)).toBeInTheDocument();
    expect(screen.getByText(declinedApprovalItem.declined_by)).toBeInTheDocument();
    expect(screen.getByText(declinedApprovalItem.reason)).toBeInTheDocument();
  });

  it('shows a backend error message rather than a silent failure on approval submission failure', async () => {
    const user = userEvent.setup();
    (approvalsApi.getPendingApprovals as any).mockResolvedValue([pendingApprovalItem]);
    (approvalsApi.approveJob as any).mockRejectedValue({
      response: { data: { detail: 'Schedule already dispatched.' } },
    });
    renderPage();

    await waitFor(() => expect(screen.getByText('Approve Dispatch')).toBeInTheDocument());
    await user.click(screen.getByText('Approve Dispatch'));

    await waitFor(() => {
      expect(screen.getByText('Schedule already dispatched.')).toBeInTheDocument();
    });
  });
});
