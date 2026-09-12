import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { RegisterCompanyPage } from './RegisterCompanyPage';
import { companiesApi } from '../api/endpoints';

vi.mock('../api/endpoints', () => ({
  companiesApi: {
    register: vi.fn(),
  },
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/register-company']}>
      <Routes>
        <Route path="/register-company" element={<RegisterCompanyPage />} />
        <Route path="/login" element={<div data-testid="login-landing">Login</div>} />
      </Routes>
    </MemoryRouter>
  );
}

async function fillStep1(user: ReturnType<typeof userEvent.setup>, overrides: Partial<Record<string, string>> = {}) {
  await user.type(screen.getByLabelText(/Company Name \*/i), overrides.company_name ?? 'Acme Corp');
  await user.type(screen.getByLabelText(/Company Email \*/i), overrides.company_email ?? 'hq@acme.com');
  await user.type(screen.getByLabelText(/Industry \*/i), overrides.industry ?? 'Technology');
  await user.type(screen.getByLabelText(/Country \*/i), overrides.country ?? 'India');
  await user.click(screen.getByText('Next: Administrator'));
}

async function fillStep2(user: ReturnType<typeof userEvent.setup>, overrides: Partial<Record<string, string>> = {}) {
  await user.type(screen.getByLabelText(/Admin Name \*/i), overrides.admin_name ?? 'Jane Doe');
  await user.type(screen.getByLabelText(/Admin Email \*/i), overrides.admin_email ?? 'jane@acme.com');
  await user.type(screen.getByLabelText(/^Password \*/i), overrides.password ?? 'StrongPass1');
  await user.type(screen.getByLabelText(/Confirm Password \*/i), overrides.confirm_password ?? 'StrongPass1');
  await user.click(screen.getByText('Next: Review'));
}

describe('RegisterCompanyPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders Step 1 — Company Details by default', () => {
    renderPage();
    expect(screen.getByText('Company Details')).toBeInTheDocument();
    expect(screen.getByLabelText(/Company Name \*/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Industry \*/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Country \*/i)).toBeInTheDocument();
  });

  it('requires company name, email, industry, and country before advancing', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByText('Next: Administrator'));
    expect(screen.getByText(/Company name is required/i)).toBeInTheDocument();
    expect(screen.getByText('Company Details')).toBeInTheDocument();
  });

  it('advances to Step 2 — Administrator once company details are valid', async () => {
    const user = userEvent.setup();
    renderPage();
    await fillStep1(user);
    expect(screen.getByText('Administrator')).toBeInTheDocument();
    expect(screen.getByLabelText(/Admin Name \*/i)).toBeInTheDocument();
  });

  it('rejects a weak password', async () => {
    const user = userEvent.setup();
    renderPage();
    await fillStep1(user);
    await user.type(screen.getByLabelText(/Admin Name \*/i), 'Jane Doe');
    await user.type(screen.getByLabelText(/Admin Email \*/i), 'jane@acme.com');
    await user.type(screen.getByLabelText(/^Password \*/i), 'weak');
    await user.type(screen.getByLabelText(/Confirm Password \*/i), 'weak');
    await user.click(screen.getByText('Next: Review'));
    expect(screen.getByText('Password must be at least 8 characters long.')).toBeInTheDocument();
  });

  it('rejects mismatched password confirmation', async () => {
    const user = userEvent.setup();
    renderPage();
    await fillStep1(user);
    await user.type(screen.getByLabelText(/Admin Name \*/i), 'Jane Doe');
    await user.type(screen.getByLabelText(/Admin Email \*/i), 'jane@acme.com');
    await user.type(screen.getByLabelText(/^Password \*/i), 'StrongPass1');
    await user.type(screen.getByLabelText(/Confirm Password \*/i), 'Different1');
    await user.click(screen.getByText('Next: Review'));
    expect(screen.getByText(/do not match/i)).toBeInTheDocument();
  });

  it('shows a Review step with the entered company and administrator information', async () => {
    const user = userEvent.setup();
    renderPage();
    await fillStep1(user, { company_name: 'Acme Corp' });
    await fillStep2(user, { admin_email: 'jane@acme.com' });
    expect(screen.getByText('Review')).toBeInTheDocument();
    expect(screen.getByText('Acme Corp')).toBeInTheDocument();
    expect(screen.getByText('jane@acme.com')).toBeInTheDocument();
    // Password is masked on review, never shown in plaintext.
    expect(screen.getByText('••••••••')).toBeInTheDocument();
  });

  it('never renders a role/tenant/team/company-id field anywhere in the flow', async () => {
    const user = userEvent.setup();
    renderPage();
    await fillStep1(user);
    await fillStep2(user);
    expect(screen.queryByLabelText(/role/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/tenant/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/team/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/company id/i)).not.toBeInTheDocument();
  });

  it('submits successfully and shows the success screen with Go to Login', async () => {
    const user = userEvent.setup();
    (companiesApi.register as any).mockResolvedValue({
      company_id: 'tenant-acme-corp',
      company_name: 'Acme Corp',
      team_id: 'team-tenant-acme-corp-default',
      team_name: 'General / Administration',
      admin: { id: 1, username: 'jane', email: 'jane@acme.com', role: 'COMPANY_ADMIN' },
      message: 'Company registered successfully',
    });

    renderPage();
    await fillStep1(user, { company_name: 'Acme Corp' });
    await fillStep2(user, { admin_email: 'jane@acme.com' });
    await user.click(screen.getByText('Create Company Account'));

    await waitFor(() => expect(screen.getByText('Company registered successfully')).toBeInTheDocument());
    expect(screen.getByText('Acme Corp')).toBeInTheDocument();
    expect(screen.getByText('jane')).toBeInTheDocument();
    expect(screen.getByText('Company Admin')).toBeInTheDocument();

    await user.click(screen.getByText('Go to Login'));
    expect(screen.getByTestId('login-landing')).toBeInTheDocument();
  });

  it('shows a duplicate-company API error without losing entered data', async () => {
    const user = userEvent.setup();
    (companiesApi.register as any).mockRejectedValue({
      response: { status: 409, data: { detail: "A company named 'Acme Corp' is already registered" } },
    });

    renderPage();
    await fillStep1(user, { company_name: 'Acme Corp' });
    await fillStep2(user);
    await user.click(screen.getByText('Create Company Account'));

    await waitFor(() => expect(screen.getByText(/already registered/i)).toBeInTheDocument());
    // Still on the review step with data intact — not reset.
    expect(screen.getByText('Review')).toBeInTheDocument();
  });

  it('shows a generic error message for an unexpected API failure', async () => {
    const user = userEvent.setup();
    (companiesApi.register as any).mockRejectedValue(new Error('network down'));

    renderPage();
    await fillStep1(user);
    await fillStep2(user);
    await user.click(screen.getByText('Create Company Account'));

    await waitFor(() => expect(screen.getByText(/Registration failed/i)).toBeInTheDocument());
  });

  it('allows navigating back from Administrator to Company Details', async () => {
    const user = userEvent.setup();
    renderPage();
    await fillStep1(user);
    await user.click(screen.getByText('Back'));
    expect(screen.getByText('Company Details')).toBeInTheDocument();
  });
});
