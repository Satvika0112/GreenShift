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
          <Route path="/" element={<div data-testid="dashboard-landing">Dashboard</div>} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>
  );
}

const platformAdminUser = {
  id: 1,
  username: 'real.user',
  email: 'real.user@example.com',
  role: 'COMPANY_USER',
  team_id: 'team-a',
  tenant_id: 'tenant-a',
  is_active: true,
};

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
  });

  it('renders exactly the three real roles and no persona/seed shortcuts', () => {
    renderLoginFlow();
    expect(screen.getByText('Platform Admin')).toBeInTheDocument();
    expect(screen.getByText('Company Admin')).toBeInTheDocument();
    expect(screen.getByText('Company User')).toBeInTheDocument();

    // No demo/seed persona affordances of any kind.
    expect(screen.queryByText(/Quick Seed/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Switch Persona/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/admin123/i)).not.toBeInTheDocument();
  });

  it('does not prefill visible default credentials', () => {
    renderLoginFlow();
    const usernameInput = screen.getByLabelText(/Identity \/ Username/i) as HTMLInputElement;
    const passwordInput = screen.getByLabelText(/Credential \/ Password/i) as HTMLInputElement;
    expect(usernameInput.value).toBe('');
    expect(passwordInput.value).toBe('');
  });

  it('selecting a role is UI-only: it does not authenticate or navigate', async () => {
    const user = userEvent.setup();
    renderLoginFlow();

    await user.click(screen.getByText('Platform Admin'));

    expect(authApi.login).not.toHaveBeenCalled();
    expect(screen.queryByTestId('dashboard-landing')).not.toBeInTheDocument();
    // Still on the login form.
    expect(screen.getByRole('button', { name: /Sign In to Control Plane/i })).toBeInTheDocument();
  });

  it('invalid credentials show an error and keep the user on the login page', async () => {
    const user = userEvent.setup();
    (authApi.login as any).mockRejectedValue({
      response: { data: { detail: 'Invalid username or password' } },
    });
    renderLoginFlow();

    await user.type(screen.getByLabelText(/Identity \/ Username/i), 'someone');
    await user.type(screen.getByLabelText(/Credential \/ Password/i), 'wrongpass');
    await user.click(screen.getByRole('button', { name: /Sign In to Control Plane/i }));

    await waitFor(() => expect(screen.getByText('Invalid username or password')).toBeInTheDocument());
    expect(screen.queryByTestId('dashboard-landing')).not.toBeInTheDocument();
  });

  it('successful backend authentication redirects to the app', async () => {
    const user = userEvent.setup();
    (authApi.login as any).mockResolvedValue({
      access_token: 'real-jwt-token',
      token_type: 'bearer',
      expires_in: 3600,
      user: platformAdminUser,
    });
    renderLoginFlow();

    await user.type(screen.getByLabelText(/Identity \/ Username/i), 'real.user');
    await user.type(screen.getByLabelText(/Credential \/ Password/i), 'correct-password');
    await user.click(screen.getByRole('button', { name: /Sign In to Control Plane/i }));

    await waitFor(() => expect(screen.getByTestId('dashboard-landing')).toBeInTheDocument());
    expect(authApi.login).toHaveBeenCalledWith({ username: 'real.user', password: 'correct-password' });
  });

  it('the authenticated role always comes from the backend response, never the UI selection', async () => {
    const user = userEvent.setup();
    // User selects Platform Admin in the UI, but the backend authenticates them as COMPANY_USER.
    (authApi.login as any).mockResolvedValue({
      access_token: 'real-jwt-token',
      token_type: 'bearer',
      expires_in: 3600,
      user: platformAdminUser, // role: COMPANY_USER
    });
    renderLoginFlow();

    await user.click(screen.getByText('Platform Admin'));
    await user.type(screen.getByLabelText(/Identity \/ Username/i), 'real.user');
    await user.type(screen.getByLabelText(/Credential \/ Password/i), 'correct-password');
    await user.click(screen.getByRole('button', { name: /Sign In to Control Plane/i }));

    // No privilege elevation: the mismatch is surfaced, not silently granted.
    await waitFor(() => expect(screen.getByText(/actual role is COMPANY_USER/i)).toBeInTheDocument());
    // Still eventually lands in the app with the real (non-elevated) identity.
    await waitFor(() => expect(screen.getByTestId('dashboard-landing')).toBeInTheDocument(), { timeout: 3000 });
  });

  it('disables the submit button and shows a loading label while authenticating', async () => {
    const user = userEvent.setup();
    let resolveLogin: (v: any) => void;
    (authApi.login as any).mockReturnValue(new Promise((resolve) => { resolveLogin = resolve; }));
    renderLoginFlow();

    await user.type(screen.getByLabelText(/Identity \/ Username/i), 'real.user');
    await user.type(screen.getByLabelText(/Credential \/ Password/i), 'correct-password');
    await user.click(screen.getByRole('button', { name: /Sign In to Control Plane/i }));

    const pendingButton = await screen.findByRole('button', { name: /Authenticating/i });
    expect(pendingButton).toBeDisabled();

    resolveLogin!({
      access_token: 'tok',
      token_type: 'bearer',
      expires_in: 3600,
      user: platformAdminUser,
    });
    await waitFor(() => expect(screen.getByTestId('dashboard-landing')).toBeInTheDocument());
  });
});
