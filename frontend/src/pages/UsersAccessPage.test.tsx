import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { UsersAccessPage } from './UsersAccessPage';
import { authApi, companyApi } from '../api/endpoints';
import { approvedAdminUser, pendingUser, apiKeyFixture, companyFixture } from '../test/fixtures/users';
import { User } from '../types/api';

vi.mock('../api/endpoints', () => ({
  authApi: {
    getUsers: vi.fn(),
    listApiKeys: vi.fn(),
    adminCreateUser: vi.fn(),
    updateUserStatus: vi.fn(),
    createApiKey: vi.fn(),
    deleteApiKey: vi.fn(),
  },
  companyApi: {
    getCompanies: vi.fn(),
  },
}));

let mockUser: User;
let mockIsAdmin: boolean;
let mockIsPlatformAdmin: boolean;
let mockIsCompanyAdmin: boolean;

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({
    user: mockUser,
    isAdmin: mockIsAdmin,
    isPlatformAdmin: mockIsPlatformAdmin,
    isCompanyAdmin: mockIsCompanyAdmin,
  }),
}));

function renderPage() {
  return render(<UsersAccessPage />);
}

describe('UsersAccessPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUser = approvedAdminUser;
    mockIsAdmin = true;
    mockIsPlatformAdmin = false;
    mockIsCompanyAdmin = true;
    (authApi.getUsers as any).mockResolvedValue([]);
    (authApi.listApiKeys as any).mockResolvedValue([]);
    (companyApi.getCompanies as any).mockResolvedValue([]);
  });

  it('renders real directory users from the backend', async () => {
    (authApi.getUsers as any).mockResolvedValue([approvedAdminUser, pendingUser]);
    renderPage();

    await waitFor(() => {
      expect(screen.getByText('company_admin')).toBeInTheDocument();
    });
    expect(screen.getByText('new_hire')).toBeInTheDocument();
    expect(screen.getByText('PENDING')).toBeInTheDocument();
  });

  it('scopes the directory to only the caller for a non-admin user (never fetches all tenants)', async () => {
    mockIsAdmin = false;
    mockIsPlatformAdmin = false;
    mockIsCompanyAdmin = false;
    mockUser = { ...approvedAdminUser, role: 'COMPANY_USER' as any };
    renderPage();

    await waitFor(() => expect(screen.getByText(mockUser.username)).toBeInTheDocument());
    expect(authApi.getUsers).not.toHaveBeenCalled();
  });

  it('provisions a new user through the real API layer with no hardcoded team default', async () => {
    const user = userEvent.setup();
    (authApi.adminCreateUser as any).mockResolvedValue(approvedAdminUser);
    renderPage();

    await waitFor(() => expect(screen.getByText('Provision User')).toBeInTheDocument());
    await user.click(screen.getByText('Provision User'));

    await user.type(screen.getByPlaceholderText('engineer@company.com'), 'new.engineer@acme.example');
    const passwordInput = document.querySelector('input[type="password"]') as HTMLInputElement;
    await user.type(passwordInput, 'S3curePass!');
    await user.click(screen.getByText('Confirm Provisioning'));

    await waitFor(() => {
      expect(authApi.adminCreateUser).toHaveBeenCalledWith({
        email: 'new.engineer@acme.example',
        username: undefined,
        password: 'S3curePass!',
        role: 'COMPANY_USER',
        team_id: undefined,
        tenant_id: undefined,
      });
    });
  });

  it('grants a PLATFORM_ADMIN role option only when the caller is a platform admin', async () => {
    const user = userEvent.setup();
    mockIsPlatformAdmin = true;
    renderPage();

    await waitFor(() => expect(screen.getByText('Provision User')).toBeInTheDocument());
    await user.click(screen.getByText('Provision User'));

    expect(screen.getByRole('option', { name: 'PLATFORM_ADMIN' })).toBeInTheDocument();
  });

  it('does not offer a PLATFORM_ADMIN role option for a company admin (no privilege escalation)', async () => {
    const user = userEvent.setup();
    mockIsPlatformAdmin = false;
    renderPage();

    await waitFor(() => expect(screen.getByText('Provision User')).toBeInTheDocument());
    await user.click(screen.getByText('Provision User'));

    expect(screen.queryByRole('option', { name: 'PLATFORM_ADMIN' })).not.toBeInTheDocument();
  });

  it('calls updateUserStatus through the real API to approve a pending user', async () => {
    const user = userEvent.setup();
    (authApi.getUsers as any).mockResolvedValue([pendingUser]);
    (authApi.updateUserStatus as any).mockResolvedValue({ ...pendingUser, approval_status: 'APPROVED' });
    renderPage();

    await waitFor(() => expect(screen.getByText('new_hire')).toBeInTheDocument());
    await user.click(screen.getByTitle('Approve User'));

    await waitFor(() => {
      expect(authApi.updateUserStatus).toHaveBeenCalledWith(pendingUser.id, {
        approval_status: 'APPROVED',
        is_active: true,
      });
    });
  });

  it('renders real API keys and revokes one through the real API layer', async () => {
    const user = userEvent.setup();
    (authApi.listApiKeys as any).mockResolvedValue([apiKeyFixture]);
    (authApi.deleteApiKey as any).mockResolvedValue({});
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderPage();

    await waitFor(() => expect(screen.getByText(apiKeyFixture.label)).toBeInTheDocument());
    await user.click(screen.getByTitle('Revoke Key'));

    await waitFor(() => {
      expect(authApi.deleteApiKey).toHaveBeenCalledWith(apiKeyFixture.id);
    });
  });

  it('shows a backend error message rather than a silent failure on directory fetch error', async () => {
    (authApi.getUsers as any).mockRejectedValue({ response: { data: { detail: 'Forbidden.' } } });
    (authApi.listApiKeys as any).mockResolvedValue([]);
    (companyApi.getCompanies as any).mockResolvedValue([]);
    renderPage();

    await waitFor(() => {
      expect(screen.getByText('Failed to fetch directory data from backend.')).toBeInTheDocument();
    });
    // No fabricated fallback rows appear when the real fetch failed.
    expect(screen.getByText('No Users Found')).toBeInTheDocument();
  });
});
