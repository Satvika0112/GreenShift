import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { RequestAccessPage } from './RequestAccessPage';
import { authApi } from '../api/endpoints';

vi.mock('../api/endpoints', () => ({
  authApi: {
    register: vi.fn(),
  },
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/register']}>
      <Routes>
        <Route path="/register" element={<RequestAccessPage />} />
        <Route path="/login" element={<div data-testid="login-landing">Login</div>} />
      </Routes>
    </MemoryRouter>
  );
}

async function fillForm(user: ReturnType<typeof userEvent.setup>, overrides: Partial<Record<'username' | 'email' | 'password' | 'confirm', string>> = {}) {
  await user.type(screen.getByLabelText(/^Username$/i), overrides.username ?? 'new.hire');
  await user.type(screen.getByLabelText(/^Email$/i), overrides.email ?? 'new.hire@example.com');
  await user.type(screen.getByLabelText(/^Password$/i), overrides.password ?? 'secret6+');
  await user.type(screen.getByLabelText(/Confirm Password/i), overrides.confirm ?? 'secret6+');
}

describe('RequestAccessPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the registration form', () => {
    renderPage();
    expect(screen.getByLabelText(/^Username$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Email$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Password$/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Request Access/i })).toBeInTheDocument();
  });

  it('blocks submission when passwords do not match, without calling the backend', async () => {
    const user = userEvent.setup();
    renderPage();
    await fillForm(user, { confirm: 'different-pw' });
    await user.click(screen.getByRole('button', { name: /Request Access/i }));

    expect(await screen.findByText(/Passwords do not match/i)).toBeInTheDocument();
    expect(authApi.register).not.toHaveBeenCalled();
  });

  it('submits a real registration and shows the pending-approval confirmation', async () => {
    const user = userEvent.setup();
    (authApi.register as any).mockResolvedValue({
      id: 5,
      username: 'new.hire',
      email: 'new.hire@example.com',
      role: 'COMPANY_USER',
      approval_status: 'PENDING',
      is_active: false,
    });
    renderPage();
    await fillForm(user);
    await user.click(screen.getByRole('button', { name: /Request Access/i }));

    await waitFor(() => expect(screen.getByText('Request Submitted')).toBeInTheDocument());
    expect(authApi.register).toHaveBeenCalledWith({
      username: 'new.hire',
      email: 'new.hire@example.com',
      password: 'secret6+',
    });
  });

  it('surfaces a safe conflict message when the username/email is already taken', async () => {
    const user = userEvent.setup();
    (authApi.register as any).mockRejectedValue({
      response: { status: 409, data: { detail: "Username 'new.hire' is already taken" } },
    });
    renderPage();
    await fillForm(user);
    await user.click(screen.getByRole('button', { name: /Request Access/i }));

    await waitFor(() => expect(screen.getByText("Username 'new.hire' is already taken")).toBeInTheDocument());
  });

  it('links back to Sign In', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('link', { name: /Sign in/i }));
    expect(screen.getByTestId('login-landing')).toBeInTheDocument();
  });
});
