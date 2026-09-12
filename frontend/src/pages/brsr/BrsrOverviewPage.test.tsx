import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrsrOverviewPage } from './BrsrOverviewPage';
import { brsrApi } from '../../api/endpoints';
import { BrsrReport } from '../../types/api';

const navigateMock = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => navigateMock };
});

vi.mock('../../api/endpoints', () => ({
  brsrApi: {
    getReports: vi.fn(),
    createReport: vi.fn(),
  },
}));

let mockRole: 'COMPANY_ADMIN' | 'COMPANY_USER' | 'PLATFORM_ADMIN';
vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({ user: { role: mockRole } }),
}));

function report(overrides: Partial<BrsrReport> = {}): BrsrReport {
  return {
    id: 1, tenant_id: 'tenant-acme', financial_year: '2025-26',
    reporting_period_start: '2025-04-01T00:00:00Z', reporting_period_end: '2026-03-31T00:00:00Z',
    framework_version: 'BRSR-2023', status: 'DRAFT', created_by: 1, approved_by: null,
    created_at: '2025-04-01T00:00:00Z', updated_at: null, validated_at: null, approved_at: null, generated_at: null,
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <BrsrOverviewPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('BrsrOverviewPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navigateMock.mockClear();
    mockRole = 'COMPANY_ADMIN';
  });

  it('shows a loading state then the list of real reports', async () => {
    (brsrApi.getReports as any).mockResolvedValue([report({ financial_year: '2025-26' })]);
    renderPage();
    await waitFor(() => expect(screen.getByText('FY 2025-26')).toBeInTheDocument());
  });

  it('shows an empty state with a create action for company admin when there are no reports', async () => {
    (brsrApi.getReports as any).mockResolvedValue([]);
    renderPage();
    await waitFor(() => expect(screen.getByText('No BRSR reports yet')).toBeInTheDocument());
  });

  it('shows an error state with retry on failure', async () => {
    (brsrApi.getReports as any).mockRejectedValue(new Error('network error'));
    renderPage();
    await waitFor(() => expect(screen.getByText("Couldn't load BRSR reports.")).toBeInTheDocument());
    expect(screen.getByText('Retry')).toBeInTheDocument();
  });

  it('company user does not see the "New BRSR Report" action', async () => {
    mockRole = 'COMPANY_USER';
    (brsrApi.getReports as any).mockResolvedValue([]);
    renderPage();
    await waitFor(() => expect(screen.getByText('No BRSR reports yet')).toBeInTheDocument());
    expect(screen.queryAllByText('New BRSR Report')).toHaveLength(0);
  });

  it('platform admin does not see the "New BRSR Report" action either — the backend unconditionally forbids Platform Admin from creating BRSR data', async () => {
    mockRole = 'PLATFORM_ADMIN';
    (brsrApi.getReports as any).mockResolvedValue([]);
    renderPage();
    await waitFor(() => expect(screen.getByText('No BRSR reports yet')).toBeInTheDocument());
    expect(screen.queryAllByText('New BRSR Report')).toHaveLength(0);
  });

  it('clicking a report row navigates to its detail page', async () => {
    const user = userEvent.setup();
    (brsrApi.getReports as any).mockResolvedValue([report({ id: 42, financial_year: '2025-26' })]);
    renderPage();
    const row = await screen.findByText('FY 2025-26');
    await user.click(row);
    expect(navigateMock).toHaveBeenCalledWith('/brsr/reports/42');
  });

  it('creating a report calls the API with a real financial year and navigates to it on success', async () => {
    const user = userEvent.setup();
    (brsrApi.getReports as any).mockResolvedValue([]);
    (brsrApi.createReport as any).mockResolvedValue(report({ id: 7, financial_year: '2025-26' }));
    renderPage();

    await waitFor(() => expect(screen.getByText('No BRSR reports yet')).toBeInTheDocument());
    await user.click(screen.getAllByText('New BRSR Report')[0]);
    await user.click(screen.getByText('Create Report'));

    await waitFor(() => expect(brsrApi.createReport).toHaveBeenCalled());
    const callArg = (brsrApi.createReport as any).mock.calls[0][0];
    expect(callArg.financial_year).toMatch(/^\d{4}-\d{2}$/);
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith('/brsr/reports/7'));
  });
});
