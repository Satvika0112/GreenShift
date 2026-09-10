import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { ImpactReportsPage } from './ImpactReportsPage';
import { monitoringApi, reportsApi } from '../api/endpoints';
import { fleetImpactReport, fleetHeadline } from '../test/fixtures/impact';
import { User } from '../types/api';

vi.mock('../api/endpoints', () => ({
  monitoringApi: {
    getFleetImpact: vi.fn(),
    getFleetHeadline: vi.fn(),
  },
  reportsApi: {
    downloadReportCsv: vi.fn(),
    getReportMarkdown: vi.fn(),
  },
}));

let mockUser: User;
let mockIsAdmin: boolean;

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: mockUser, isAdmin: mockIsAdmin }),
}));

const adminUser: User = {
  id: 1,
  username: 'admin',
  email: 'admin@acme.example',
  role: 'PLATFORM_ADMIN' as any,
  team_id: 'platform',
  is_active: true,
};

function renderPage() {
  return render(<ImpactReportsPage />);
}

describe('ImpactReportsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUser = adminUser;
    mockIsAdmin = true;
  });

  it('renders real fleet impact KPI values from the backend, not fabricated numbers', async () => {
    (monitoringApi.getFleetImpact as any).mockResolvedValue(fleetImpactReport);
    (monitoringApi.getFleetHeadline as any).mockResolvedValue(fleetHeadline);
    renderPage();

    await waitFor(() => {
      expect(screen.getByText('482.6 kg')).toBeInTheDocument();
    });
    expect(screen.getByText('27.3%')).toBeInTheDocument();
    expect(screen.getByText('$118.42')).toBeInTheDocument();
    expect(screen.getByText('36')).toBeInTheDocument();
  });

  it('renders team breakdown using the real job_count field, never a fabricated count', async () => {
    (monitoringApi.getFleetImpact as any).mockResolvedValue(fleetImpactReport);
    (monitoringApi.getFleetHeadline as any).mockResolvedValue(fleetHeadline);
    renderPage();

    await waitFor(() => expect(screen.getByText('team-acme')).toBeInTheDocument());
    // job_count = 21 for team-acme, appears in both team and region rows.
    expect(screen.getAllByText('21').length).toBe(2);
  });

  it('never renders a fabricated environmental-equivalence section (trees/car-miles)', async () => {
    (monitoringApi.getFleetImpact as any).mockResolvedValue(fleetImpactReport);
    (monitoringApi.getFleetHeadline as any).mockResolvedValue(fleetHeadline);
    renderPage();

    await waitFor(() => expect(screen.getByText('482.6 kg')).toBeInTheDocument());
    expect(screen.queryByText(/trees planted/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/car miles/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/EPA/i)).not.toBeInTheDocument();
  });

  it('scopes the fleet impact request to the caller team for a non-admin user', async () => {
    mockIsAdmin = false;
    mockUser = { ...adminUser, role: 'COMPANY_USER' as any, team_id: 'team-acme' };
    (monitoringApi.getFleetImpact as any).mockResolvedValue(fleetImpactReport);
    (monitoringApi.getFleetHeadline as any).mockResolvedValue(fleetHeadline);
    renderPage();

    await waitFor(() => expect(monitoringApi.getFleetImpact).toHaveBeenCalled());
    expect(monitoringApi.getFleetImpact).toHaveBeenCalledWith({ team_id: 'team-acme' });
  });

  it('surfaces a backend error rather than silently showing zeros', async () => {
    (monitoringApi.getFleetImpact as any).mockRejectedValue(new Error('network down'));
    (monitoringApi.getFleetHeadline as any).mockRejectedValue(new Error('network down'));
    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/Failed to fetch fleet impact metrics/i)).toBeInTheDocument();
    });
  });

  it('triggers a real CSV export download through the reports API', async () => {
    (monitoringApi.getFleetImpact as any).mockResolvedValue(fleetImpactReport);
    (monitoringApi.getFleetHeadline as any).mockResolvedValue(fleetHeadline);
    (reportsApi.downloadReportCsv as any).mockResolvedValue('job_id,carbon\njob-1,4.1\n');
    renderPage();

    await waitFor(() => expect(screen.getByText('Export BRSR CSV')).toBeInTheDocument());
    screen.getByText('Export BRSR CSV').closest('button')!.click();

    await waitFor(() => {
      expect(reportsApi.downloadReportCsv).toHaveBeenCalledWith(undefined);
    });
  });
});
