import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider, useAuth } from './AuthContext';
import { authApi } from '../api/endpoints';

vi.mock('../api/endpoints', () => ({
  authApi: {
    login: vi.fn(),
    getCurrentUser: vi.fn(),
  },
}));

const companyUser = {
  id: 1,
  username: 'real.user',
  email: 'real.user@example.com',
  role: 'COMPANY_USER',
  team_id: 'team-a',
  tenant_id: 'tenant-a',
  is_active: true,
};

function Probe() {
  const { user, isAuthenticated, isLoading, login, logout } = useAuth();
  return (
    <div>
      <span data-testid="loading">{String(isLoading)}</span>
      <span data-testid="authed">{String(isAuthenticated)}</span>
      <span data-testid="username">{user?.username || ''}</span>
      <button onClick={() => login('real.user', 'pw').catch(() => {})}>do-login</button>
      <button onClick={() => logout()}>do-logout</button>
    </div>
  );
}

function renderProbe() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <Probe />
      </AuthProvider>
    </QueryClientProvider>
  );
  return { ...view, queryClient };
}

describe('AuthContext', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
  });

  it('starts unauthenticated with no stored token and resolves loading immediately', async () => {
    renderProbe();
    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('authed').textContent).toBe('false');
    expect(authApi.getCurrentUser).not.toHaveBeenCalled();
  });

  it('restores a valid session from a stored token via GET /auth/me on mount', async () => {
    sessionStorage.setItem('greenshift_token', 'stored-jwt');
    (authApi.getCurrentUser as any).mockResolvedValue(companyUser);

    renderProbe();

    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('authed').textContent).toBe('true');
    expect(screen.getByTestId('username').textContent).toBe('real.user');
    expect(authApi.getCurrentUser).toHaveBeenCalledTimes(1);
  });

  it('clears the session when the stored token is rejected by the backend (expired/invalid)', async () => {
    sessionStorage.setItem('greenshift_token', 'stale-jwt');
    (authApi.getCurrentUser as any).mockRejectedValue({ response: { status: 401 } });

    renderProbe();

    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('authed').textContent).toBe('false');
    expect(sessionStorage.getItem('greenshift_token')).toBeNull();
  });

  it('clears the session on a non-401/403 refreshUser failure too (fail closed, never trust an unconfirmed stored identity)', async () => {
    // A hand-edited sessionStorage identity claiming PLATFORM_ADMIN must
    // never render role-gated UI off an unconfirmed value just because the
    // confirming /auth/me call happened to fail with a network/5xx error
    // rather than 401/403.
    sessionStorage.setItem('greenshift_token', 'stored-jwt');
    sessionStorage.setItem('greenshift_user', JSON.stringify({ ...companyUser, role: 'PLATFORM_ADMIN' }));
    (authApi.getCurrentUser as any).mockRejectedValue(new Error('Network Error'));

    renderProbe();

    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('authed').textContent).toBe('false');
    expect(sessionStorage.getItem('greenshift_token')).toBeNull();
    expect(sessionStorage.getItem('greenshift_user')).toBeNull();
  });

  it('login stores the token and the backend-authenticated user', async () => {
    const user = userEvent.setup();
    (authApi.login as any).mockResolvedValue({
      access_token: 'fresh-jwt',
      token_type: 'bearer',
      expires_in: 3600,
      user: companyUser,
    });
    renderProbe();
    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));

    await user.click(screen.getByText('do-login'));

    await waitFor(() => expect(screen.getByTestId('authed').textContent).toBe('true'));
    expect(sessionStorage.getItem('greenshift_token')).toBe('fresh-jwt');
    expect(JSON.parse(sessionStorage.getItem('greenshift_user') || 'null').role).toBe('COMPANY_USER');
  });

  it('logout clears authentication state and stored session', async () => {
    const user = userEvent.setup();
    sessionStorage.setItem('greenshift_token', 'stored-jwt');
    (authApi.getCurrentUser as any).mockResolvedValue(companyUser);
    renderProbe();
    await waitFor(() => expect(screen.getByTestId('authed').textContent).toBe('true'));

    await user.click(screen.getByText('do-logout'));

    expect(screen.getByTestId('authed').textContent).toBe('false');
    expect(sessionStorage.getItem('greenshift_token')).toBeNull();
    expect(sessionStorage.getItem('greenshift_user')).toBeNull();
  });

  it('logout clears the React Query cache, so the next signed-in user never sees stale tenant data from cache', async () => {
    const user = userEvent.setup();
    sessionStorage.setItem('greenshift_token', 'stored-jwt');
    (authApi.getCurrentUser as any).mockResolvedValue(companyUser);
    const { queryClient } = renderProbe();
    await waitFor(() => expect(screen.getByTestId('authed').textContent).toBe('true'));

    // Simulate data some other page fetched during the session (e.g. workloads).
    queryClient.setQueryData(['workloads', 'tenant-a'], [{ job_id: 'JOB-1' }]);
    expect(queryClient.getQueryCache().getAll().length).toBeGreaterThan(0);

    await user.click(screen.getByText('do-logout'));

    expect(queryClient.getQueryCache().getAll().length).toBe(0);
  });

  it('reacts to a global auth-expired event by logging out', async () => {
    sessionStorage.setItem('greenshift_token', 'stored-jwt');
    (authApi.getCurrentUser as any).mockResolvedValue(companyUser);
    renderProbe();
    await waitFor(() => expect(screen.getByTestId('authed').textContent).toBe('true'));

    window.dispatchEvent(new CustomEvent('greenshift:auth-expired'));

    await waitFor(() => expect(screen.getByTestId('authed').textContent).toBe('false'));
  });
});
