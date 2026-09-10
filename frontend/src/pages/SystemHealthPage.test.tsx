import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { SystemHealthPage } from './SystemHealthPage';
import { monitoringApi } from '../api/endpoints';
import { healthyReport, degradedReport } from '../test/fixtures/health';

vi.mock('../api/endpoints', () => ({
  monitoringApi: {
    getSystemLive: vi.fn(),
    getSystemHealth: vi.fn(),
    getSystemReady: vi.fn(),
  },
}));

function renderPage() {
  return render(<SystemHealthPage />);
}

describe('SystemHealthPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders a healthy status derived entirely from real backend probe results', async () => {
    (monitoringApi.getSystemLive as any).mockResolvedValue({ status: 'ok' });
    (monitoringApi.getSystemHealth as any).mockResolvedValue(healthyReport);
    (monitoringApi.getSystemReady as any).mockResolvedValue({ status: 'ready' });
    renderPage();

    await waitFor(() => {
      expect(screen.getByText('SYSTEM STATUS: HEALTHY')).toBeInTheDocument();
    });
    expect(screen.getByText('PASS (HTTP 200)')).toBeInTheDocument();
    expect(screen.getByText('READY (HTTP 200)')).toBeInTheDocument();
  });

  it('renders degraded/unhealthy component statuses from real backend component data', async () => {
    (monitoringApi.getSystemLive as any).mockResolvedValue({ status: 'ok' });
    (monitoringApi.getSystemHealth as any).mockResolvedValue(degradedReport);
    (monitoringApi.getSystemReady as any).mockResolvedValue({ status: 'ready' });
    renderPage();

    await waitFor(() => {
      expect(screen.getByText('SYSTEM STATUS: DEGRADED')).toBeInTheDocument();
    });
    expect(screen.getByText('high latency')).toBeInTheDocument();
    expect(screen.getByText('cluster unreachable')).toBeInTheDocument();
    // carbon_data's `reason` takes precedence over `mode` when both are present.
    expect(screen.getByText('primary feed timeout')).toBeInTheDocument();
  });

  it('shows an unreachable-backend error banner when the health probe itself fails', async () => {
    (monitoringApi.getSystemLive as any).mockRejectedValue(new Error('down'));
    (monitoringApi.getSystemHealth as any).mockRejectedValue(new Error('down'));
    (monitoringApi.getSystemReady as any).mockRejectedValue(new Error('down'));
    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/Backend health probe failed/i)).toBeInTheDocument();
    });
    expect(screen.getByText('FAIL')).toBeInTheDocument();
    expect(screen.getByText('NOT READY')).toBeInTheDocument();
  });

  it('never renders a fabricated Tariff Engine probe', async () => {
    (monitoringApi.getSystemLive as any).mockResolvedValue({ status: 'ok' });
    (monitoringApi.getSystemHealth as any).mockResolvedValue(healthyReport);
    (monitoringApi.getSystemReady as any).mockResolvedValue({ status: 'ready' });
    renderPage();

    await waitFor(() => expect(screen.getByText('SYSTEM STATUS: HEALTHY')).toBeInTheDocument());
    expect(screen.queryByText(/Tariff Engine/i)).not.toBeInTheDocument();
  });

  it('never renders a latency figure for sub-components the backend does not time', async () => {
    (monitoringApi.getSystemLive as any).mockResolvedValue({ status: 'ok' });
    (monitoringApi.getSystemHealth as any).mockResolvedValue(healthyReport);
    (monitoringApi.getSystemReady as any).mockResolvedValue({ status: 'ready' });
    renderPage();

    await waitFor(() => expect(screen.getByText('PostgreSQL / SQLite State Store')).toBeInTheDocument());
    // Only the two real measured latencies (API gateway + full health check) render
    // "Roundtrip Latency"; database/redis/kubernetes/carbon_data must not.
    expect(screen.getAllByText('Roundtrip Latency:').length).toBe(2);
  });

  it('re-probes all services when "Probe All Services" is clicked', async () => {
    (monitoringApi.getSystemLive as any).mockResolvedValue({ status: 'ok' });
    (monitoringApi.getSystemHealth as any).mockResolvedValue(healthyReport);
    (monitoringApi.getSystemReady as any).mockResolvedValue({ status: 'ready' });
    renderPage();

    await waitFor(() => expect(screen.getByText('SYSTEM STATUS: HEALTHY')).toBeInTheDocument());
    screen.getByText('Probe All Services').closest('button')!.click();

    await waitFor(() => {
      expect(monitoringApi.getSystemHealth).toHaveBeenCalledTimes(2);
    });
  });
});
