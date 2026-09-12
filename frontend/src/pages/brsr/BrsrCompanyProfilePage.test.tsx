import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrsrCompanyProfilePage } from './BrsrCompanyProfilePage';
import { brsrApi } from '../../api/endpoints';
import { BrsrCompanyProfile } from '../../types/api';

vi.mock('../../api/endpoints', () => ({
  brsrApi: {
    getCompanyProfile: vi.fn(),
    updateCompanyProfile: vi.fn(),
  },
}));

let mockRole: 'COMPANY_ADMIN' | 'COMPANY_USER' | 'PLATFORM_ADMIN';
vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({ user: { role: mockRole } }),
}));

function profile(overrides: Partial<BrsrCompanyProfile> = {}): BrsrCompanyProfile {
  return {
    tenant_id: 'tenant-acme', company_name: null, cin: null, sector: null, industry: null,
    listed_status: null, stock_exchange: null, isin: null, locations: null, products_services: null,
    employees_count: null, workers_count: null, revenue: null, revenue_currency: null,
    net_worth: null, net_worth_currency: null, capital: null, capital_currency: null,
    reporting_boundary: null, currency_conversions: null, source_type: 'COMPANY_PROVIDED', updated_at: null,
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <BrsrCompanyProfilePage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('BrsrCompanyProfilePage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRole = 'COMPANY_ADMIN';
  });

  it('renders real (not fabricated) profile values once loaded', async () => {
    (brsrApi.getCompanyProfile as any).mockResolvedValue(profile({ company_name: 'Real Acme Corp' }));
    renderPage();
    await waitFor(() => expect(screen.getByDisplayValue('Real Acme Corp')).toBeInTheDocument());
  });

  it('shows an error state with retry on failure', async () => {
    (brsrApi.getCompanyProfile as any).mockRejectedValue(new Error('network error'));
    renderPage();
    await waitFor(() => expect(screen.getByText("Couldn't load the company profile.")).toBeInTheDocument());
  });

  it('company admin can edit and save the profile', async () => {
    const user = userEvent.setup();
    (brsrApi.getCompanyProfile as any).mockResolvedValue(profile());
    (brsrApi.updateCompanyProfile as any).mockResolvedValue(profile({ company_name: 'New Name' }));
    renderPage();

    const nameInput = (await screen.findByLabelText(/Company Name/i)) as HTMLInputElement;
    await user.clear(nameInput);
    await user.type(nameInput, 'New Name');
    await user.click(screen.getByText('Save Profile'));

    await waitFor(() => expect(brsrApi.updateCompanyProfile).toHaveBeenCalled());
    const payload = (brsrApi.updateCompanyProfile as any).mock.calls[0][0];
    expect(payload.company_name).toBe('New Name');
  });

  it('company user sees a read-only form with no save button', async () => {
    mockRole = 'COMPANY_USER';
    (brsrApi.getCompanyProfile as any).mockResolvedValue(profile({ company_name: 'Acme' }));
    renderPage();

    await waitFor(() => expect(screen.getByDisplayValue('Acme')).toBeInTheDocument());
    expect(screen.queryByText('Save Profile')).not.toBeInTheDocument();
    expect(screen.getByDisplayValue('Acme')).toBeDisabled();
  });

  it('platform admin also sees a read-only form — the backend unconditionally forbids Platform Admin from editing a company profile', async () => {
    mockRole = 'PLATFORM_ADMIN';
    (brsrApi.getCompanyProfile as any).mockResolvedValue(profile({ company_name: 'Acme' }));
    renderPage();

    await waitFor(() => expect(screen.getByDisplayValue('Acme')).toBeInTheDocument());
    expect(screen.queryByText('Save Profile')).not.toBeInTheDocument();
    expect(screen.getByDisplayValue('Acme')).toBeDisabled();
  });
});
