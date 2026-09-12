import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrsrReportDetailPage } from './BrsrReportDetailPage';
import { brsrApi } from '../../api/endpoints';
import { BrsrOverview } from '../../types/api';

vi.mock('../../api/endpoints', () => ({
  brsrApi: {
    getOverview: vi.fn(),
    getMetrics: vi.fn(),
    getLatestValidation: vi.fn(),
    runValidation: vi.fn(),
    getAssessment: vi.fn(),
    updateAssessment: vi.fn(),
    getAuditTrail: vi.fn(),
    transitionStatus: vi.fn(),
    updateMetric: vi.fn(),
    exportReport: vi.fn(),
  },
}));

let mockRole: 'COMPANY_ADMIN' | 'COMPANY_USER' | 'PLATFORM_ADMIN';
vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({ user: { role: mockRole } }),
}));

function overview(overrides: Partial<BrsrOverview> = {}): BrsrOverview {
  return {
    report: {
      id: 1, tenant_id: 'tenant-acme', financial_year: '2025-26',
      reporting_period_start: '2025-04-01T00:00:00Z', reporting_period_end: '2026-03-31T00:00:00Z',
      framework_version: 'BRSR-2023', status: 'DRAFT', created_by: 1, approved_by: null,
      created_at: '2025-04-01T00:00:00Z', updated_at: null, validated_at: null, approved_at: null, generated_at: null,
    },
    completion_pct: 12.5,
    required_metrics_total: 8,
    required_metrics_filled: 1,
    data_quality: { high: 0, medium: 1, low: 0, missing: 39, total: 40 },
    missing_required_count: 7,
    brsr_core_completion_pct: 0,
    latest_validation: null,
    can_approve: false,
    can_generate: false,
    ...overrides,
  };
}

function renderPage(reportId = 1) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/brsr/reports/${reportId}`]}>
        <Routes>
          <Route path="/brsr/reports/:id" element={<BrsrReportDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('BrsrReportDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRole = 'COMPANY_ADMIN';
    (brsrApi.getMetrics as any).mockResolvedValue([]);
    (brsrApi.getLatestValidation as any).mockResolvedValue(null);
    (brsrApi.getAssessment as any).mockResolvedValue({
      report_id: 1, assessment_status: null, assessor_name: null, assessor_type: null,
      assessment_date: null, scope: null, notes: null, evidence_reference: null,
      source_type: 'COMPANY_PROVIDED', updated_at: null,
    });
    (brsrApi.getAuditTrail as any).mockResolvedValue([]);
  });

  it('shows real, backend-derived completion numbers — never a fake progress value', async () => {
    (brsrApi.getOverview as any).mockResolvedValue(overview({ completion_pct: 37.5 }));
    renderPage();
    await waitFor(() => expect(screen.getByText('37.5%')).toBeInTheDocument());
    expect(screen.getByText('1 / 8')).toBeInTheDocument();
  });

  it('shows an error state with retry on overview failure', async () => {
    (brsrApi.getOverview as any).mockRejectedValue(new Error('network error'));
    renderPage();
    await waitFor(() => expect(screen.getByText("Couldn't load this BRSR report.")).toBeInTheDocument());
  });

  it('switching to the Validation tab fetches and displays validation results', async () => {
    const user = userEvent.setup();
    (brsrApi.getOverview as any).mockResolvedValue(overview());
    (brsrApi.getLatestValidation as any).mockResolvedValue({
      id: 1, report_id: 1, run_at: '2025-05-01T00:00:00Z', run_by: 1, status: 'FAILED',
      error_count: 2, warning_count: 1, info_count: 0,
      issues: [{ metric_code: 'SEC_A_CSR_APPLICABLE', severity: 'ERROR', code: 'REQUIRED_FIELD_MISSING', message: 'Missing required field', suggested_resolution: null }],
    });
    renderPage();

    await waitFor(() => expect(screen.getByText('37.5%'.replace('37.5', '12.5'))).toBeInTheDocument());
    await user.click(screen.getByText('Validation'));

    await waitFor(() => expect(screen.getByText('2 Errors')).toBeInTheDocument());
    expect(screen.getByText('Missing required field')).toBeInTheDocument();
  });

  it('does not allow generation/approval when the backend says can_approve/can_generate are false', async () => {
    (brsrApi.getOverview as any).mockResolvedValue(overview({ report: { ...overview().report, status: 'VALIDATED' }, can_approve: false }));
    renderPage();

    await waitFor(() => expect(screen.getByText('Move to APPROVED')).toBeInTheDocument());
    expect(screen.getByText('Move to APPROVED').closest('button')).toBeDisabled();
  });

  it('company user does not see the workflow transition action', async () => {
    mockRole = 'COMPANY_USER';
    (brsrApi.getOverview as any).mockResolvedValue(overview());
    renderPage();

    await waitFor(() => expect(screen.getByText('12.5%')).toBeInTheDocument());
    expect(screen.queryByText(/Move to /)).not.toBeInTheDocument();
  });

  it('platform admin does not see the workflow transition action either — the backend unconditionally forbids Platform Admin from mutating a company\'s BRSR report', async () => {
    mockRole = 'PLATFORM_ADMIN';
    (brsrApi.getOverview as any).mockResolvedValue(overview());
    renderPage();

    await waitFor(() => expect(screen.getByText('12.5%')).toBeInTheDocument());
    expect(screen.queryByText(/Move to /)).not.toBeInTheDocument();
  });

  it('export tab blocks download before the report is GENERATED', async () => {
    const user = userEvent.setup();
    (brsrApi.getOverview as any).mockResolvedValue(overview());
    renderPage();

    await waitFor(() => expect(screen.getByText('12.5%')).toBeInTheDocument());
    await user.click(screen.getByText('Generate & Export'));

    await waitFor(() => expect(screen.getByText(/must reach GENERATED status/)).toBeInTheDocument());
    expect(screen.queryByText('PDF')).not.toBeInTheDocument();
  });
});
