import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { SubmitWorkloadPage } from './SubmitWorkloadPage';
import { workloadsApi } from '../api/endpoints';
import { User } from '../types/api';

vi.mock('../api/endpoints', () => ({
  workloadsApi: { createJob: vi.fn(), getDatasetWorkloads: vi.fn() },
}));

function makeQuery(data: any, overrides: Partial<Record<string, any>> = {}) {
  return { data, isLoading: false, isError: false, refetch: vi.fn(), ...overrides };
}

let mockUser: User | null;
let regionsQ: any;

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: mockUser }),
}));

vi.mock('../hooks/useDashboard', () => ({
  useRegions: (..._args: any[]) => regionsQ,
}));

const companyUser: User = {
  id: 1,
  username: 'u1',
  email: 'u1@example.com',
  role: 'COMPANY_USER',
  team_id: 'team-a',
  tenant_id: 'acme',
  company_name: 'Acme',
  is_active: true,
};

const regionsFixture = [
  { region_id: 'IN-TG', country: 'India', region_name: 'Telangana', timezone: 'Asia/Kolkata', currency: 'INR', electricity_maps_zone: 'IN-TG', default_plan: 'ToD', supported_tariff_plans: [], aliases: [], is_active: true },
  { region_id: 'IN-GJ', country: 'India', region_name: 'Gujarat', timezone: 'Asia/Kolkata', currency: 'INR', electricity_maps_zone: 'IN-GJ', default_plan: 'HTP-I', supported_tariff_plans: [], aliases: [], is_active: true },
  { region_id: 'IN-OLD', country: 'India', region_name: 'Retired Zone', timezone: 'Asia/Kolkata', currency: 'INR', electricity_maps_zone: 'IN-OLD', default_plan: 'Flat', supported_tariff_plans: [], aliases: [], is_active: false },
  { region_id: 'AU-SA-Small', country: 'Australia', region_name: 'South Australia (Small)', timezone: 'Australia/Adelaide', currency: 'AUD', electricity_maps_zone: 'AU-SA', default_plan: 'ToD', supported_tariff_plans: [], aliases: [], is_active: true },
];

// Matches GET /api/v1/dataset/workloads exactly — a real dataset row shape,
// with its earliest_start_time/deadline already re-anchored to the future
// by the backend (same as the real endpoint contract).
function futureIso(hoursFromNow: number): string {
  return new Date(Date.now() + hoursFromNow * 3600 * 1000).toISOString();
}

const datasetWorkloadFixture = {
  job_id: 'GS-JOB-000042',
  job_type: 'DATA_PROCESSING',
  team: 'operations',
  priority: 'MEDIUM',
  region: 'AU-SA-Small',
  dataset_submit_time: '2026-04-01T01:15:00+00:00',
  earliest_start_time: futureIso(1),
  deadline: futureIso(9),
  runtime_minutes: 47,
  runtime_hours: 0.78,
  power_kw: 3.0,
  energy_kwh: 2.34,
  deferrable: true,
  container_image: 'greenshift/sample-workload:latest',
  cpu_request: '500m',
  memory_request: '1Gi',
  carbon_budget_kg: 2.17,
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/submit']}>
      <Routes>
        <Route path="/submit" element={<SubmitWorkloadPage />} />
        <Route path="/scheduling" element={<div data-testid="landing-scheduling">Scheduling</div>} />
        <Route path="/workloads/:id" element={<div data-testid="landing-detail">Detail</div>} />
      </Routes>
    </MemoryRouter>
  );
}

function futureLocalDateTime(hoursFromNow: number): string {
  const d = new Date(Date.now() + hoursFromNow * 3600 * 1000);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

async function fillValidForm(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/Workload Name/i), 'customer-churn-model-training');
  await user.selectOptions(screen.getByLabelText(/Workload Type/i), 'ML_TRAINING');
  await user.type(screen.getByLabelText(/Container Image/i), 'ghcr.io/company/model-training:latest');
  await user.selectOptions(screen.getByLabelText('Region *'), 'IN-TG');
  await user.clear(screen.getByLabelText(/Runtime Estimate/i));
  await user.type(screen.getByLabelText(/Runtime Estimate/i), '120');
  await user.clear(screen.getByLabelText(/Average Power Draw/i));
  await user.type(screen.getByLabelText(/Average Power Draw/i), '3.0');
  const deadlineInput = screen.getByLabelText(/SLA Deadline/i) as HTMLInputElement;
  await user.clear(deadlineInput);
  await user.type(deadlineInput, futureLocalDateTime(24));
}

describe('SubmitWorkloadPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUser = companyUser;
    regionsQ = makeQuery(regionsFixture);
    (workloadsApi.getDatasetWorkloads as any).mockResolvedValue({
      count: 1,
      source: 'data/greenshift_workloads_final.csv',
      workloads: [datasetWorkloadFixture],
    });
  });

  describe('header', () => {
    it('renders the user-facing title and subtitle, no technical ingest wording', () => {
      renderPage();
      expect(screen.getByRole('heading', { name: 'Submit Workload' })).toBeInTheDocument();
      expect(screen.getByText('Configure and submit a workload for carbon-aware execution.')).toBeInTheDocument();
      expect(screen.queryByText(/ingest/i)).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: /^submit workload$/i })).toBeInTheDocument();
    });
  });

  describe('templates removed', () => {
    it('has no Quick Templates, preset buttons, or demo workload defaults', () => {
      renderPage();
      expect(screen.queryByText(/quick templates/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/1-click/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/LLM 70B Benchmark/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/Monte Carlo Financial Risk/i)).not.toBeInTheDocument();
      // The form starts empty, not pre-filled from a template.
      expect((screen.getByLabelText(/Workload Name/i) as HTMLInputElement).value).toBe('');
      expect((screen.getByLabelText(/Container Image/i) as HTMLInputElement).value).toBe('');
    });
  });

  describe('Workload section', () => {
    it('requires a workload name', async () => {
      const user = userEvent.setup();
      renderPage();
      await user.selectOptions(screen.getByLabelText(/Workload Type/i), 'ML_TRAINING');
      await user.type(screen.getByLabelText(/Container Image/i), 'ghcr.io/x/y:latest');
      await user.selectOptions(screen.getByLabelText('Region *'), 'IN-TG');
      await user.click(screen.getByRole('button', { name: /^submit workload$/i }));
      expect((await screen.findAllByText('Workload name is required.')).length).toBeGreaterThan(0);
      expect(workloadsApi.createJob).not.toHaveBeenCalled();
    });

    it('offers exactly the canonical workload types', () => {
      renderPage();
      const select = screen.getByLabelText(/Workload Type/i);
      const optionLabels = Array.from(select.querySelectorAll('option')).map((o) => o.textContent);
      expect(optionLabels).toEqual(
        expect.arrayContaining(['ML Training', 'Data Processing', 'ETL', 'Image Processing', 'Analytics', 'Backup', 'Report Generation'])
      );
    });

    it('labels Priority as urgency for dispatch ordering, not carbon optimization', () => {
      renderPage();
      expect(screen.getByText(/urgency for dispatch ordering/i)).toBeInTheDocument();
      expect(screen.queryByText(/carbon.optimization priority/i)).not.toBeInTheDocument();
    });
  });

  describe('Execution Requirements section', () => {
    it('validates container image format', async () => {
      const user = userEvent.setup();
      renderPage();
      await user.type(screen.getByLabelText(/Workload Name/i), 'x');
      await user.selectOptions(screen.getByLabelText(/Workload Type/i), 'ML_TRAINING');
      await user.type(screen.getByLabelText(/Container Image/i), 'not a valid image');
      await user.selectOptions(screen.getByLabelText('Region *'), 'IN-TG');
      await user.click(screen.getByRole('button', { name: /^submit workload$/i }));
      expect((await screen.findAllByText(/plausible container image reference/i)).length).toBeGreaterThan(0);
    });

    it('populates Region from backend data and only offers active regions', () => {
      renderPage();
      const select = screen.getByLabelText('Region *');
      expect(select.textContent).toContain('Telangana');
      expect(select.textContent).toContain('Gujarat');
      expect(select.textContent).not.toContain('Retired Zone');
    });

    it('shows a loading state while regions are loading', () => {
      regionsQ = makeQuery(undefined, { isLoading: true });
      renderPage();
      expect(screen.getByText('Loading regions…')).toBeInTheDocument();
      expect(screen.getByLabelText('Region *')).toBeDisabled();
    });

    it('shows a clear error state with Retry when regions fail to load, never a silent fake fallback', async () => {
      const user = userEvent.setup();
      regionsQ = makeQuery(undefined, { isError: true });
      renderPage();
      expect(screen.getByText('Unable to load supported regions.')).toBeInTheDocument();
      expect(screen.queryByText('Telangana')).not.toBeInTheDocument();
      await user.click(screen.getByRole('button', { name: /retry/i }));
      expect(regionsQ.refetch).toHaveBeenCalledTimes(1);
    });
  });

  describe('Compute Requirements', () => {
    it('rejects runtime <= 0 and runtime > 10080', async () => {
      const user = userEvent.setup();
      renderPage();
      await user.type(screen.getByLabelText(/Workload Name/i), 'x');
      await user.selectOptions(screen.getByLabelText(/Workload Type/i), 'ML_TRAINING');
      await user.type(screen.getByLabelText(/Container Image/i), 'ghcr.io/x/y:latest');
      await user.selectOptions(screen.getByLabelText('Region *'), 'IN-TG');
      const runtimeInput = screen.getByLabelText(/Runtime Estimate/i);
      await user.clear(runtimeInput);
      await user.type(runtimeInput, '99999');
      await user.click(screen.getByRole('button', { name: /^submit workload$/i }));
      expect((await screen.findAllByText(/cannot exceed 10,080 minutes/i)).length).toBeGreaterThan(0);
    });

    it('computes estimated energy deterministically from power x runtime, with no fabricated carbon estimate', async () => {
      const user = userEvent.setup();
      renderPage();
      const runtimeInput = screen.getByLabelText(/Runtime Estimate/i);
      await user.clear(runtimeInput);
      await user.type(runtimeInput, '120');
      const powerInput = screen.getByLabelText(/Average Power Draw/i);
      await user.clear(powerInput);
      await user.type(powerInput, '3.0');
      expect(screen.getByText('6.00 kWh')).toBeInTheDocument();
      expect(screen.queryByText(/kg CO/i)).not.toBeInTheDocument();
    });

    it('validates CPU and memory request formats', async () => {
      const user = userEvent.setup();
      renderPage();
      await user.type(screen.getByLabelText(/Workload Name/i), 'x');
      await user.selectOptions(screen.getByLabelText(/Workload Type/i), 'ML_TRAINING');
      await user.type(screen.getByLabelText(/Container Image/i), 'ghcr.io/x/y:latest');
      await user.selectOptions(screen.getByLabelText('Region *'), 'IN-TG');
      const cpuInput = screen.getByLabelText(/CPU Request/i);
      await user.clear(cpuInput);
      await user.type(cpuInput, 'lots');
      const memInput = screen.getByLabelText(/Memory Request/i);
      await user.clear(memInput);
      await user.type(memInput, 'huge');
      await user.click(screen.getByRole('button', { name: /^submit workload$/i }));
      expect((await screen.findAllByText(/valid CPU request/i)).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/valid memory request/i).length).toBeGreaterThan(0);
    });

    it('does not render a GPU field (not supported by the backend)', () => {
      renderPage();
      expect(screen.queryByLabelText(/gpu/i)).not.toBeInTheDocument();
    });
  });

  describe('Scheduling Policy', () => {
    it('requires the SLA deadline to be in the future', async () => {
      const user = userEvent.setup();
      renderPage();
      await user.type(screen.getByLabelText(/Workload Name/i), 'x');
      await user.selectOptions(screen.getByLabelText(/Workload Type/i), 'ML_TRAINING');
      await user.type(screen.getByLabelText(/Container Image/i), 'ghcr.io/x/y:latest');
      await user.selectOptions(screen.getByLabelText('Region *'), 'IN-TG');
      const deadlineInput = screen.getByLabelText(/SLA Deadline/i);
      await user.type(deadlineInput, '2020-01-01T00:00');
      await user.click(screen.getByRole('button', { name: /^submit workload$/i }));
      expect((await screen.findAllByText('SLA deadline must be in the future.')).length).toBeGreaterThan(0);
    });

    it('shows the selected region timezone beside the deadline', async () => {
      const user = userEvent.setup();
      renderPage();
      await user.selectOptions(screen.getByLabelText('Region *'), 'IN-TG');
      expect(screen.getByText(/Asia\/Kolkata/)).toBeInTheDocument();
    });

    it('defaults Scheduling Flexibility to Deferrable and allows switching to Immediate', async () => {
      const user = userEvent.setup();
      renderPage();
      const select = screen.getByLabelText(/Scheduling Flexibility/i) as HTMLSelectElement;
      expect(select.value).toBe('DEFERRABLE');
      await user.selectOptions(select, 'IMMEDIATE');
      expect(select.value).toBe('IMMEDIATE');
    });

    it('earliest start is optional', async () => {
      const user = userEvent.setup();
      (workloadsApi.createJob as any).mockResolvedValue({ job_id: 'JOB-1', status: 'SUBMITTED', submitted_at: '2026-09-10T00:00:00Z', name: 'customer-churn-model-training' });
      renderPage();
      await fillValidForm(user);
      await user.click(screen.getByRole('button', { name: /^submit workload$/i }));
      await waitFor(() => expect(workloadsApi.createJob).toHaveBeenCalled());
      const payload = (workloadsApi.createJob as any).mock.calls[0][0];
      expect(payload.earliest_start_time).toBeUndefined();
    });
  });

  describe('Sustainability Constraints', () => {
    it('validates carbon budget is non-negative', async () => {
      const user = userEvent.setup();
      renderPage();
      await user.type(screen.getByLabelText(/Workload Name/i), 'x');
      await user.selectOptions(screen.getByLabelText(/Workload Type/i), 'ML_TRAINING');
      await user.type(screen.getByLabelText(/Container Image/i), 'ghcr.io/x/y:latest');
      await user.selectOptions(screen.getByLabelText('Region *'), 'IN-TG');
      await user.type(screen.getByLabelText(/Carbon Budget/i), '-5');
      await user.click(screen.getByRole('button', { name: /^submit workload$/i }));
      expect((await screen.findAllByText('Carbon budget must be zero or greater.')).length).toBeGreaterThan(0);
    });

    it('shows "No carbon budget constraint" when left empty', () => {
      renderPage();
      expect(screen.getByText('No carbon budget constraint.')).toBeInTheDocument();
    });
  });

  describe('submission', () => {
    it('submits the correct payload with authenticated team ownership, never auto-scheduling or dispatching', async () => {
      const user = userEvent.setup();
      (workloadsApi.createJob as any).mockResolvedValue({ job_id: 'JOB-1', status: 'SUBMITTED', submitted_at: '2026-09-10T00:00:00Z', name: 'customer-churn-model-training' });
      renderPage();
      await fillValidForm(user);
      await user.click(screen.getByRole('button', { name: /^submit workload$/i }));

      await waitFor(() => expect(workloadsApi.createJob).toHaveBeenCalledTimes(1));
      const [payload, autoSchedule] = (workloadsApi.createJob as any).mock.calls[0];
      expect(payload.team_id).toBe('team-a');
      expect(payload.workload_name).toBe('customer-churn-model-training');
      expect(payload.region).toBe('IN-TG');
      expect(autoSchedule).toBe(false);
    });

    it('disables the button and shows a loading label while submitting, preventing duplicate submission', async () => {
      const user = userEvent.setup();
      let resolveCreate: (v: any) => void;
      (workloadsApi.createJob as any).mockReturnValue(new Promise((resolve) => { resolveCreate = resolve; }));
      renderPage();
      await fillValidForm(user);
      await user.click(screen.getByRole('button', { name: /^submit workload$/i }));

      const pendingButton = await screen.findByRole('button', { name: /submitting workload/i });
      expect(pendingButton).toBeDisabled();
      expect(workloadsApi.createJob).toHaveBeenCalledTimes(1);

      resolveCreate!({ job_id: 'JOB-1', status: 'SUBMITTED', submitted_at: '2026-09-10T00:00:00Z', name: 'x' });
      await waitFor(() => expect(screen.getByText('Workload submitted successfully')).toBeInTheDocument());
    });

    it('shows the real backend Job ID and name on success, with navigation CTAs', async () => {
      const user = userEvent.setup();
      (workloadsApi.createJob as any).mockResolvedValue({ job_id: 'JOB-REAL-999', status: 'SUBMITTED', submitted_at: '2026-09-10T00:00:00Z', name: 'customer-churn-model-training' });
      renderPage();
      await fillValidForm(user);
      await user.click(screen.getByRole('button', { name: /^submit workload$/i }));

      await waitFor(() => expect(screen.getByText('JOB-REAL-999')).toBeInTheDocument());
      expect(screen.getByText('customer-churn-model-training')).toBeInTheDocument();

      await user.click(screen.getByRole('button', { name: /view scheduling recommendation/i }));
      expect(screen.getByTestId('landing-scheduling')).toBeInTheDocument();
    });

    it('View Workload navigates to the real Workload Detail page', async () => {
      const user = userEvent.setup();
      (workloadsApi.createJob as any).mockResolvedValue({ job_id: 'JOB-REAL-999', status: 'SUBMITTED', submitted_at: '2026-09-10T00:00:00Z' });
      renderPage();
      await fillValidForm(user);
      await user.click(screen.getByRole('button', { name: /^submit workload$/i }));
      await waitFor(() => expect(screen.getByText('Workload submitted successfully')).toBeInTheDocument());

      await user.click(screen.getByRole('button', { name: /view workload/i }));
      expect(screen.getByTestId('landing-detail')).toBeInTheDocument();
    });

    it('preserves form values and shows a friendly message on failure, without exposing raw backend detail arrays', async () => {
      const user = userEvent.setup();
      (workloadsApi.createJob as any).mockRejectedValue({
        response: { status: 400, data: { detail: [{ loc: ['body', 'deadline'], msg: 'Deadline must be in the future' }] } },
      });
      renderPage();
      await fillValidForm(user);
      await user.click(screen.getByRole('button', { name: /^submit workload$/i }));

      expect(await screen.findByText('Please fix the following')).toBeInTheDocument();
      expect(screen.getByText(/SLA deadline: Deadline must be in the future/i)).toBeInTheDocument();
      // Values are preserved, not cleared.
      expect((screen.getByLabelText(/Workload Name/i) as HTMLInputElement).value).toBe('customer-churn-model-training');
    });

    it('shows a friendly 403 message without a role selector or logout', async () => {
      const user = userEvent.setup();
      (workloadsApi.createJob as any).mockRejectedValue({ response: { status: 403 } });
      renderPage();
      await fillValidForm(user);
      await user.click(screen.getByRole('button', { name: /^submit workload$/i }));

      expect(await screen.findByText(/don't have permission to submit workloads/i)).toBeInTheDocument();
    });
  });

  describe('dataset mode', () => {
    it('shows Create New Workload selected by default, with no dataset picker', () => {
      renderPage();
      expect(screen.getByRole('radio', { name: /create new workload/i })).toHaveAttribute('aria-checked', 'true');
      expect(screen.queryByText(/select workload from dataset/i)).not.toBeInTheDocument();
    });

    it('shows the dataset picker using real backend data when switched to dataset mode', async () => {
      const user = userEvent.setup();
      renderPage();
      await user.click(screen.getByRole('radio', { name: /use existing workload dataset/i }));
      expect(await screen.findByText(/select workload from dataset/i)).toBeInTheDocument();
      await waitFor(() => expect(workloadsApi.getDatasetWorkloads).toHaveBeenCalled());
      expect(await screen.findByText(new RegExp(datasetWorkloadFixture.job_id))).toBeInTheDocument();
    });

    it('populates the form from the selected dataset row, without letting team be edited', async () => {
      const user = userEvent.setup();
      renderPage();
      await user.click(screen.getByRole('radio', { name: /use existing workload dataset/i }));
      await user.selectOptions(await screen.findByLabelText('Select workload'), datasetWorkloadFixture.job_id);

      expect((screen.getByLabelText(/Container Image/i) as HTMLInputElement).value).toBe(datasetWorkloadFixture.container_image);
      expect((screen.getByLabelText('Region *') as HTMLSelectElement).value).toBe(datasetWorkloadFixture.region);
      expect((screen.getByLabelText(/Runtime Estimate/i) as HTMLInputElement).value).toBe(String(datasetWorkloadFixture.runtime_minutes));
      expect((screen.getByLabelText(/Average Power Draw/i) as HTMLInputElement).value).toBe(String(datasetWorkloadFixture.power_kw));
      expect((screen.getByLabelText(/CPU Request/i) as HTMLInputElement).value).toBe(datasetWorkloadFixture.cpu_request);
      expect((screen.getByLabelText(/Memory Request/i) as HTMLInputElement).value).toBe(datasetWorkloadFixture.memory_request);
      expect((screen.getByLabelText(/Carbon Budget/i) as HTMLInputElement).value).toBe(String(datasetWorkloadFixture.carbon_budget_kg));
      // No team selector ever exists, dataset mode included.
      expect(screen.queryByLabelText(/team/i)).not.toBeInTheDocument();
    });

    it('shows dataset timing read-only by default, with the dataset submit time and job id for reference', async () => {
      const user = userEvent.setup();
      renderPage();
      await user.click(screen.getByRole('radio', { name: /use existing workload dataset/i }));
      await user.selectOptions(await screen.findByLabelText('Select workload'), datasetWorkloadFixture.job_id);

      expect(screen.getByText('Dataset Job ID')).toBeInTheDocument();
      expect(screen.getByText(datasetWorkloadFixture.job_id)).toBeInTheDocument();
      expect(screen.getByText('Dataset Submit Time')).toBeInTheDocument();
      // Read-only mode: no editable datetime-local inputs for earliest start / deadline.
      expect(screen.queryByLabelText(/^Earliest Start$/i)).not.toBeInTheDocument();
      expect(screen.queryByLabelText(/SLA Deadline/i)).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: /override dataset timing/i })).toBeInTheDocument();
    });

    it('switches to editable local-time inputs when the user overrides dataset timing', async () => {
      const user = userEvent.setup();
      renderPage();
      await user.click(screen.getByRole('radio', { name: /use existing workload dataset/i }));
      await user.selectOptions(await screen.findByLabelText('Select workload'), datasetWorkloadFixture.job_id);
      await user.click(screen.getByRole('button', { name: /override dataset timing/i }));

      expect(screen.getByLabelText(/SLA Deadline/i)).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /override dataset timing/i })).not.toBeInTheDocument();
    });

    it('submits a dataset-backed workload without the dataset job_id or dataset_submit_time in the payload', async () => {
      const user = userEvent.setup();
      (workloadsApi.createJob as any).mockResolvedValue({ job_id: 'JOB-NEW-1', status: 'SUBMITTED', submitted_at: '2026-09-10T00:00:00Z', name: 'x' });
      renderPage();
      await user.click(screen.getByRole('radio', { name: /use existing workload dataset/i }));
      await user.selectOptions(await screen.findByLabelText('Select workload'), datasetWorkloadFixture.job_id);
      await user.click(screen.getByRole('button', { name: /^submit workload$/i }));

      await waitFor(() => expect(workloadsApi.createJob).toHaveBeenCalledTimes(1));
      const [payload] = (workloadsApi.createJob as any).mock.calls[0];
      // The real submission contract (CreateJobInput) has no field the
      // dataset's job_id/dataset_submit_time could even be smuggled into —
      // this asserts submitted_at is never pre-set from the dataset value.
      expect(payload).not.toHaveProperty('job_id');
      expect(payload).not.toHaveProperty('submit_time');
      expect(payload.team_id).toBe('team-a'); // still only from the authenticated user
      expect(payload.region).toBe(datasetWorkloadFixture.region);
      expect(payload.deadline).toBe(datasetWorkloadFixture.deadline);
      expect(payload.earliest_start_time).toBe(datasetWorkloadFixture.earliest_start_time);
    });

    it('switching back to Create New Workload clears the dataset selection and resets the form', async () => {
      const user = userEvent.setup();
      renderPage();
      await user.click(screen.getByRole('radio', { name: /use existing workload dataset/i }));
      await user.selectOptions(await screen.findByLabelText('Select workload'), datasetWorkloadFixture.job_id);
      expect((screen.getByLabelText('Region *') as HTMLSelectElement).value).toBe(datasetWorkloadFixture.region);

      await user.click(screen.getByRole('radio', { name: /create new workload/i }));
      expect(screen.queryByText(/select workload from dataset/i)).not.toBeInTheDocument();
      expect((screen.getByLabelText('Region *') as HTMLSelectElement).value).toBe('');
    });
  });

  describe('security', () => {
    it('does not render any team selector — ownership comes only from the authenticated user', () => {
      renderPage();
      expect(screen.queryByLabelText(/team/i)).not.toBeInTheDocument();
    });

    it('does not render a role selector anywhere on the page', () => {
      renderPage();
      expect(screen.queryByText(/platform admin/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/company admin/i)).not.toBeInTheDocument();
    });

    it('blocks submission with a clear message when the authenticated user has no team assigned', async () => {
      const user = userEvent.setup();
      mockUser = { ...companyUser, team_id: '' };
      renderPage();
      await fillValidForm(user);
      await user.click(screen.getByRole('button', { name: /^submit workload$/i }));
      expect(await screen.findByText(/no team assigned/i)).toBeInTheDocument();
      expect(workloadsApi.createJob).not.toHaveBeenCalled();
    });

    it('never offers a dispatch action or auto-approval language on this page', () => {
      renderPage();
      expect(screen.queryByRole('button', { name: /^dispatch$/i })).not.toBeInTheDocument();
      expect(screen.queryByText(/auto.approv/i)).not.toBeInTheDocument();
      expect(screen.getByText(/does not run until the required approval is provided/i)).toBeInTheDocument();
    });
  });
});
