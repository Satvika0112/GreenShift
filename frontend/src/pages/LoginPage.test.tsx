import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { LoginPage } from './LoginPage';
import { AuthProvider } from '../context/AuthContext';
import { authApi } from '../api/endpoints';

vi.mock('../api/endpoints', () => ({
  authApi: {
    login: vi.fn(),
    getCurrentUser: vi.fn(),
  },
}));

function renderLoginFlow() {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<div data-testid="register-landing">Register</div>} />
          <Route path="/register-company" element={<div data-testid="register-company-landing">Register Company</div>} />
          <Route path="/" element={<div data-testid="dashboard-landing">Dashboard</div>} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>
  );
}

const companyUser = {
  id: 1,
  username: 'real.user',
  email: 'real.user@example.com',
  role: 'COMPANY_USER',
  team_id: 'team-a',
  tenant_id: 'tenant-a',
  is_active: true,
};

const platformAdmin = {
  id: 2,
  username: 'platform.admin',
  email: 'platform.admin@example.com',
  role: 'PLATFORM_ADMIN',
  team_id: 'team-a',
  tenant_id: null,
  is_active: true,
};

function getUsername() {
  return screen.getByLabelText(/Username or Email/i) as HTMLInputElement;
}
function getPassword() {
  return screen.getByLabelText(/^Password$/i) as HTMLInputElement;
}
function getSubmit() {
  return screen.getByRole('button', { name: /Sign In/i });
}

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
  });

  it('renders the username/email field, password field, and Sign In button', () => {
    renderLoginFlow();
    expect(getUsername()).toBeInTheDocument();
    expect(getPassword()).toBeInTheDocument();
    expect(getSubmit()).toBeInTheDocument();
  });

  it('renders no role selector of any kind', () => {
    renderLoginFlow();
    expect(screen.queryByText('Platform Admin')).not.toBeInTheDocument();
    expect(screen.queryByText('Company Admin')).not.toBeInTheDocument();
    expect(screen.queryByText('Company User')).not.toBeInTheDocument();
    expect(screen.queryByText(/Login Role/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Platform Admin/i })).not.toBeInTheDocument();
  });

  it('has no Quick Seed Personas, "Login as", or hardcoded demo credentials', () => {
    renderLoginFlow();
    expect(screen.queryByText(/Quick Seed/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Login as/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/admin123/i)).not.toBeInTheDocument();
    expect(getUsername().value).toBe('');
    expect(getPassword().value).toBe('');
  });

  it('hides the password by default and shows the Eye toggle', () => {
    renderLoginFlow();
    expect(getPassword().type).toBe('password');
    expect(screen.getByRole('button', { name: /show password/i })).toBeInTheDocument();
  });

  it('reveals the password on Eye click and hides it again on EyeOff click, without changing the value', async () => {
    const user = userEvent.setup();
    renderLoginFlow();

    await user.type(getPassword(), 'my-secret-pw');
    expect(getPassword().value).toBe('my-secret-pw');

    await user.click(screen.getByRole('button', { name: /show password/i }));
    expect(getPassword().type).toBe('text');
    expect(getPassword().value).toBe('my-secret-pw');

    await user.click(screen.getByRole('button', { name: /hide password/i }));
    expect(getPassword().type).toBe('password');
    expect(getPassword().value).toBe('my-secret-pw');
  });

  it('shows a generic invalid-credentials message on 401 and stays on Login', async () => {
    const user = userEvent.setup();
    (authApi.login as any).mockRejectedValue({
      response: { status: 401, data: { detail: 'Invalid username or password' } },
    });
    renderLoginFlow();

    await user.type(getUsername(), 'someone');
    await user.type(getPassword(), 'wrongpass');
    await user.click(getSubmit());

    await waitFor(() => expect(screen.getByText('Invalid username or password.')).toBeInTheDocument());
    expect(screen.queryByTestId('dashboard-landing')).not.toBeInTheDocument();
  });

  it('does not expose raw backend/network errors', async () => {
    const user = userEvent.setup();
    (authApi.login as any).mockRejectedValue(new Error('connect ECONNREFUSED 127.0.0.1:8000'));
    renderLoginFlow();

    await user.type(getUsername(), 'someone');
    await user.type(getPassword(), 'pw');
    await user.click(getSubmit());

    await waitFor(() => expect(screen.getByText(/Unable to sign in right now/i)).toBeInTheDocument());
    expect(screen.queryByText(/ECONNREFUSED/i)).not.toBeInTheDocument();
  });

  it('performs real backend authentication and redirects on success, with role taken from the backend', async () => {
    const user = userEvent.setup();
    (authApi.login as any).mockResolvedValue({
      access_token: 'real-jwt-token',
      token_type: 'bearer',
      expires_in: 3600,
      user: platformAdmin,
    });
    renderLoginFlow();

    await user.type(getUsername(), 'platform.admin');
    await user.type(getPassword(), 'correct-password');
    await user.click(getSubmit());

    await waitFor(() => expect(screen.getByTestId('dashboard-landing')).toBeInTheDocument());
    expect(authApi.login).toHaveBeenCalledWith({ username: 'platform.admin', password: 'correct-password' });
    expect(JSON.parse(sessionStorage.getItem('greenshift_user') || 'null').role).toBe('PLATFORM_ADMIN');
  });

  it('disables Sign In and shows a loading label while authenticating, preventing duplicate submits', async () => {
    const user = userEvent.setup();
    let resolveLogin: (v: any) => void;
    (authApi.login as any).mockReturnValue(new Promise((resolve) => { resolveLogin = resolve; }));
    renderLoginFlow();

    await user.type(getUsername(), 'real.user');
    await user.type(getPassword(), 'correct-password');
    await user.click(getSubmit());

    const pendingButton = await screen.findByRole('button', { name: /Signing in/i });
    expect(pendingButton).toBeDisabled();
    expect(authApi.login).toHaveBeenCalledTimes(1);

    resolveLogin!({ access_token: 'tok', token_type: 'bearer', expires_in: 3600, user: companyUser });
    await waitFor(() => expect(screen.getByTestId('dashboard-landing')).toBeInTheDocument());
  });

  it('shows a Pending Access view for a 403 pending-approval account and does not authenticate', async () => {
    const user = userEvent.setup();
    (authApi.login as any).mockRejectedValue({
      response: { status: 403, data: { detail: 'Account pending approval' } },
    });
    renderLoginFlow();

    await user.type(getUsername(), 'new.hire');
    await user.type(getPassword(), 'pw');
    await user.click(getSubmit());

    await waitFor(() => expect(screen.getByText('Pending Access')).toBeInTheDocument());
    expect(screen.getByText(/pending approval/i)).toBeInTheDocument();
    expect(screen.queryByTestId('dashboard-landing')).not.toBeInTheDocument();
  });

  it('shows an Access Rejected view for a declined registration', async () => {
    const user = userEvent.setup();
    (authApi.login as any).mockRejectedValue({
      response: { status: 403, data: { detail: 'User account registration was declined' } },
    });
    renderLoginFlow();

    await user.type(getUsername(), 'rejected.user');
    await user.type(getPassword(), 'pw');
    await user.click(getSubmit());

    await waitFor(() => expect(screen.getByText('Access Rejected')).toBeInTheDocument());
  });

  it('shows an Account Inactive view for a deactivated user', async () => {
    const user = userEvent.setup();
    (authApi.login as any).mockRejectedValue({
      response: { status: 403, data: { detail: 'User account is deactivated' } },
    });
    renderLoginFlow();

    await user.type(getUsername(), 'inactive.user');
    await user.type(getPassword(), 'pw');
    await user.click(getSubmit());

    await waitFor(() => expect(screen.getByText('Account Inactive')).toBeInTheDocument());
  });

  it('shows a Company Inactive view when the backend reports the tenant is inactive', async () => {
    const user = userEvent.setup();
    (authApi.login as any).mockRejectedValue({
      response: { status: 403, data: { detail: 'Company account is inactive' } },
    });
    renderLoginFlow();

    await user.type(getUsername(), 'someone');
    await user.type(getPassword(), 'pw');
    await user.click(getSubmit());

    await waitFor(() => expect(screen.getByText('Company Inactive')).toBeInTheDocument());

    // "Back to Sign In" returns to the credentials form for another attempt.
    await user.click(screen.getByRole('button', { name: /Back to Sign In/i }));
    expect(getUsername()).toBeInTheDocument();
  });

  it('shows a session-expired notice when redirected here after an expired session', () => {
    sessionStorage.setItem('greenshift_session_expired', '1');
    renderLoginFlow();
    expect(screen.getByText(/session has expired/i)).toBeInTheDocument();
    expect(sessionStorage.getItem('greenshift_session_expired')).toBeNull();
  });

  it('has no Forgot Password link, since no backend reset flow exists', () => {
    renderLoginFlow();
    expect(screen.queryByText(/Forgot password/i)).not.toBeInTheDocument();
  });

  it('links Request Access to the real registration flow', async () => {
    const user = userEvent.setup();
    renderLoginFlow();
    await user.click(screen.getByRole('link', { name: /Request access/i }));
    expect(screen.getByTestId('register-landing')).toBeInTheDocument();
  });

  it('links "Register your organization" to the company onboarding flow', async () => {
    const user = userEvent.setup();
    renderLoginFlow();
    await user.click(screen.getByRole('link', { name: /Register your organization/i }));
    expect(screen.getByTestId('register-company-landing')).toBeInTheDocument();
  });
});
