import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { JobMonitoringPage } from './JobMonitoringPage';
import { dispatchApi, workloadsApi, sustainabilityApi } from '../api/endpoints';
import {
  runningExecution,
  failedExecution,
  clusterState,
  k8sHealthAvailable,
  k8sHealthSimulated,
} from '../test/fixtures/jobMonitoring';

vi.mock('../api/endpoints', () => ({
  dispatchApi: {
    getAllExecutions: vi.fn(),
    getK8sState: vi.fn(),
    getK8sHealth: vi.fn(),
  },
  workloadsApi: {
    getJobs: vi.fn().mockResolvedValue([]),
  },
  sustainabilityApi: {
    getRegions: vi.fn().mockResolvedValue([
      { region_id: 'IN-TG', country: 'India', region_name: 'Telangana', timezone: 'Asia/Kolkata', currency: 'INR', electricity_maps_zone: 'IN-SO', default_plan: 'ToD', supported_tariff_plans: [], aliases: [], is_active: true },
    ]),
  },
}));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <JobMonitoringPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('JobMonitoringPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders real dispatched executions and cluster telemetry from the backend', async () => {
    (dispatchApi.getAllExecutions as any).mockResolvedValue([runningExecution]);
    (dispatchApi.getK8sState as any).mockResolvedValue(clusterState);
    (dispatchApi.getK8sHealth as any).mockResolvedValue(k8sHealthAvailable);
    renderPage();

    await waitFor(() => {
      expect(screen.getAllByText(runningExecution.kubernetes_job_name)[0]).toBeInTheDocument();
    });
    expect(screen.getByText('CONNECTED / READY')).toBeInTheDocument();
    expect(screen.getByText('4 / 4 Nodes')).toBeInTheDocument();
    expect(screen.getByText('18 / 32 Cores')).toBeInTheDocument();
  });

  it('shows SIMULATION MODE when the backend reports Kubernetes is unavailable, never a fake connected status', async () => {
    (dispatchApi.getAllExecutions as any).mockResolvedValue([runningExecution]);
    (dispatchApi.getK8sState as any).mockResolvedValue(clusterState);
    (dispatchApi.getK8sHealth as any).mockResolvedValue(k8sHealthSimulated);
    renderPage();

    await waitFor(() => expect(screen.getByText('SIMULATION MODE')).toBeInTheDocument());
  });

  it('renders an empty state with a link to Workloads when there are no executions', async () => {
    (dispatchApi.getAllExecutions as any).mockResolvedValue([]);
    (dispatchApi.getK8sState as any).mockResolvedValue(clusterState);
    (dispatchApi.getK8sHealth as any).mockResolvedValue(k8sHealthAvailable);
    renderPage();

    await waitFor(() => {
      expect(screen.getByText('No Active or Past Executions')).toBeInTheDocument();
    });
    expect(screen.getByText('Go to Workloads Registry')).toBeInTheDocument();
  });

  it('shows real error details for a failed execution, never a fabricated log stream', async () => {
    const user = userEvent.setup();
    (dispatchApi.getAllExecutions as any).mockResolvedValue([runningExecution, failedExecution]);
    (dispatchApi.getK8sState as any).mockResolvedValue(clusterState);
    (dispatchApi.getK8sHealth as any).mockResolvedValue(k8sHealthAvailable);
    renderPage();

    await waitFor(() => expect(screen.getAllByText(runningExecution.kubernetes_job_name)[0]).toBeInTheDocument());
    await user.click(screen.getByText(failedExecution.kubernetes_job_name));

    await waitFor(() => {
      expect(screen.getByText(/OOMKilled/)).toBeInTheDocument();
    });
    // No synthesized terminal log lines from earlier fabricated-log behavior.
    expect(screen.queryByText(/greenshift-dispatcher/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Claim verified for job/)).not.toBeInTheDocument();
  });

  it('never claims a fixed 5-second polling cadence it does not honor', async () => {
    (dispatchApi.getAllExecutions as any).mockResolvedValue([runningExecution]);
    (dispatchApi.getK8sState as any).mockResolvedValue(clusterState);
    (dispatchApi.getK8sHealth as any).mockResolvedValue(k8sHealthAvailable);
    renderPage();

    await waitFor(() => expect(screen.getAllByText(runningExecution.kubernetes_job_name)[0]).toBeInTheDocument());
    expect(screen.queryByText(/5-second intervals/)).not.toBeInTheDocument();
  });

  it('auto-refreshes telemetry on the real 15s interval without user interaction', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    (dispatchApi.getAllExecutions as any).mockResolvedValue([runningExecution]);
    (dispatchApi.getK8sState as any).mockResolvedValue(clusterState);
    (dispatchApi.getK8sHealth as any).mockResolvedValue(k8sHealthAvailable);
    renderPage();

    await vi.waitFor(() => expect(dispatchApi.getAllExecutions).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(15000);
    await vi.waitFor(() => expect(dispatchApi.getAllExecutions).toHaveBeenCalledTimes(2));
  });

  it('shows an error banner on a manual poll failure', async () => {
    const user = userEvent.setup();
    (dispatchApi.getAllExecutions as any)
      .mockResolvedValueOnce([runningExecution])
      .mockRejectedValueOnce(new Error('cluster unreachable'));
    (dispatchApi.getK8sState as any).mockResolvedValue(clusterState);
    (dispatchApi.getK8sHealth as any).mockResolvedValue(k8sHealthAvailable);
    renderPage();

    await waitFor(() => expect(screen.getAllByText(runningExecution.kubernetes_job_name)[0]).toBeInTheDocument());
    await user.click(screen.getByText('Poll Clusters'));

    await waitFor(() => {
      expect(screen.getByText(/Failed to poll Kubernetes execution telemetry/i)).toBeInTheDocument();
    });
  });
});
