import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DatasetWorkloadPicker } from './DatasetWorkloadPicker';
import { workloadsApi } from '../../api/endpoints';
import { DatasetWorkloadItem } from '../../types/api';

vi.mock('../../api/endpoints', () => ({
  workloadsApi: { getDatasetWorkloads: vi.fn() },
}));

function row(overrides: Partial<DatasetWorkloadItem> = {}): DatasetWorkloadItem {
  return {
    job_id: 'GS-JOB-000001',
    job_type: 'DATA_PROCESSING',
    team: 'operations',
    priority: 'MEDIUM',
    region: 'IN-TG',
    dataset_submit_time: '2026-04-01T01:15:00+00:00',
    earliest_start_time: '2026-09-11T20:31:07+00:00',
    deadline: '2026-09-12T03:57:07+00:00',
    runtime_minutes: 47,
    runtime_hours: 0.78,
    power_kw: 3.0,
    energy_kwh: 2.34,
    deferrable: true,
    container_image: 'greenshift/sample-workload:latest',
    cpu_request: '500m',
    memory_request: '1Gi',
    carbon_budget_kg: 2.17,
    ...overrides,
  };
}

const rows = [
  row({ job_id: 'GS-JOB-000001', job_type: 'DATA_PROCESSING', team: 'operations', region: 'IN-TG' }),
  row({ job_id: 'GS-JOB-000002', job_type: 'ML_TRAINING', team: 'ml-platform', region: 'AU-SA-Small' }),
];

describe('DatasetWorkloadPicker', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches real dataset rows on mount and renders them (no hardcoded options)', async () => {
    (workloadsApi.getDatasetWorkloads as any).mockResolvedValue({ count: 2, source: 'data/greenshift_workloads_final.csv', workloads: rows });
    render(<DatasetWorkloadPicker selected={null} onSelect={vi.fn()} />);

    await waitFor(() => expect(workloadsApi.getDatasetWorkloads).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/GS-JOB-000001/)).toBeInTheDocument();
    expect(screen.getByText(/GS-JOB-000002/)).toBeInTheDocument();
  });

  it('calls onSelect with the real selected row when a workload is chosen', async () => {
    (workloadsApi.getDatasetWorkloads as any).mockResolvedValue({ count: 2, source: 'x', workloads: rows });
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<DatasetWorkloadPicker selected={null} onSelect={onSelect} />);

    const select = await screen.findByLabelText('Select workload');
    await user.selectOptions(select, 'GS-JOB-000002');

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect.mock.calls[0][0]).toEqual(rows[1]);
  });

  it('filters the list by search text (job id, type, team, region)', async () => {
    (workloadsApi.getDatasetWorkloads as any).mockResolvedValue({ count: 2, source: 'x', workloads: rows });
    const user = userEvent.setup();
    render(<DatasetWorkloadPicker selected={null} onSelect={vi.fn()} />);

    await screen.findByText(/GS-JOB-000001/);
    await user.type(screen.getByPlaceholderText(/search by job id/i), 'ml-platform');

    expect(screen.queryByText(/GS-JOB-000001/)).not.toBeInTheDocument();
    expect(screen.getByText(/GS-JOB-000002/)).toBeInTheDocument();
  });

  it('shows a loading state, then an empty state for an empty dataset', async () => {
    (workloadsApi.getDatasetWorkloads as any).mockResolvedValue({ count: 0, source: 'x', workloads: [] });
    render(<DatasetWorkloadPicker selected={null} onSelect={vi.fn()} />);

    expect(await screen.findByText(/no workloads found in the dataset/i)).toBeInTheDocument();
  });

  it('shows an honest error state with Retry on fetch failure, never a fake fallback list', async () => {
    (workloadsApi.getDatasetWorkloads as any).mockRejectedValueOnce(new Error('network down'));
    const user = userEvent.setup();
    render(<DatasetWorkloadPicker selected={null} onSelect={vi.fn()} />);

    expect(await screen.findByText(/unable to load the workload dataset/i)).toBeInTheDocument();

    (workloadsApi.getDatasetWorkloads as any).mockResolvedValueOnce({ count: 2, source: 'x', workloads: rows });
    await user.click(screen.getByRole('button', { name: /retry/i }));
    expect(await screen.findByText(/GS-JOB-000001/)).toBeInTheDocument();
  });
});
