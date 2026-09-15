import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SettingsPage } from './SettingsPage';
import { sustainabilityApi, monitoringApi, notificationsApi, companiesApi, optimizationPolicyApi } from '../api/endpoints';
import { User, NotificationPreferences, CompanyProfile, OptimizationPolicyResponse } from '../types/api';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('../api/endpoints', () => ({
  sustainabilityApi: {
    getDataSourcesStatus: vi.fn(),
  },
  monitoringApi: {
    getSystemHealth: vi.fn(),
  },
  notificationsApi: {
    getPreferences: vi.fn(),
    updatePreferences: vi.fn(),
  },
  companiesApi: {
    getMyCompany: vi.fn(),
    updateMyCompany: vi.fn(),
  },
  optimizationPolicyApi: {
    getPolicy: vi.fn(),
    updatePolicy: vi.fn(),
  },
}));

let mockUser: User;
let mockIsCompanyAdmin: boolean;

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: mockUser, isCompanyAdmin: mockIsCompanyAdmin, isAuthenticated: true }),
}));

let mockConnectionStatus: string;
let mockSoundEnabled: boolean;
const setSoundEnabledMock = vi.fn((v: boolean) => {
  mockSoundEnabled = v;
});

vi.mock('../context/RealtimeNotificationContext', () => ({
  useRealtimeNotifications: () => ({
    connectionStatus: mockConnectionStatus,
    toasts: [],
    dismissToast: vi.fn(),
    soundEnabled: mockSoundEnabled,
    setSoundEnabled: setSoundEnabledMock,
  }),
}));

const defaultPreferences: NotificationPreferences = {
  email_workload: true,
  email_scheduling: true,
  email_approval: true,
  email_execution: true,
  email_system: true,
};

const companyUser: User = {
  id: 3,
  username: 'company_user',
  email: 'user@acme.example',
  role: 'COMPANY_USER' as any,
  team_id: 'team-acme',
  tenant_id: 'acme',
  company_name: 'Acme Corp',
  is_active: true,
};

const companyAdminUser: User = {
  ...companyUser,
  id: 2,
  username: 'company_admin',
  role: 'COMPANY_ADMIN' as any,
};

const companyProfile: CompanyProfile = {
  id: 'acme',
  name: 'Acme Corp',
  legal_name: 'Acme Corporation Pvt Ltd',
  company_email: 'hq@acme.example',
  website: 'https://acme.example',
  industry: 'Technology',
  sector: 'B2B SaaS',
  country: 'India',
  address: '1 Acme Street',
  status: 'ACTIVE',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  user_count: 5,
  workload_count: 12,
};

const carbonFirstPolicy: OptimizationPolicyResponse = {
  policy: 'CARBON_FIRST',
  carbon_tolerance_pct: null,
  updated_by: null,
  updated_at: null,
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <SettingsPage />
    </QueryClientProvider>
  );
}

describe('SettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockUser = companyUser;
    mockIsCompanyAdmin = false;
    mockConnectionStatus = 'connected';
    mockSoundEnabled = true;
    (sustainabilityApi.getDataSourcesStatus as any).mockResolvedValue({});
    (monitoringApi.getSystemHealth as any).mockResolvedValue({});
    (notificationsApi.getPreferences as any).mockResolvedValue({ ...defaultPreferences });
    (notificationsApi.updatePreferences as any).mockResolvedValue({ ...defaultPreferences });
    (companiesApi.getMyCompany as any).mockResolvedValue({ ...companyProfile });
    (companiesApi.updateMyCompany as any).mockResolvedValue({ ...companyProfile });
    (optimizationPolicyApi.getPolicy as any).mockResolvedValue({ ...carbonFirstPolicy });
    (optimizationPolicyApi.updatePolicy as any).mockResolvedValue({ ...carbonFirstPolicy });
  });

  it('renders the real authenticated identity fields, not placeholder text', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText(companyUser.username)).toBeInTheDocument());
    expect(screen.getByText(companyUser.email)).toBeInTheDocument();
    expect(screen.getByText(companyUser.role)).toBeInTheDocument();
    // The company name now legitimately appears twice — once in the Profile
    // card (from the JWT-derived identity) and once in the Company Profile
    // card below it (from GET /companies/me) — both real, not duplicated by
    // accident.
    expect(screen.getAllByText(companyUser.company_name!).length).toBeGreaterThanOrEqual(1);
  });

  it('hides the admin-only backend runtime section for a non-admin user', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText(companyUser.username)).toBeInTheDocument());
    expect(screen.queryByText('Backend Runtime Architecture & Data Sources')).not.toBeInTheDocument();
  });

  it('shows real backend data-source values for a company admin when available', async () => {
    mockIsCompanyAdmin = true;
    (sustainabilityApi.getDataSourcesStatus as any).mockResolvedValue({
      carbon_source: 'WattTime API',
      tariff_source: 'Custom Regional Tariff Feed',
    });
    (monitoringApi.getSystemHealth as any).mockResolvedValue({ service: 'greenshift-api', status: 'healthy' });
    renderPage();

    await waitFor(() => expect(screen.getByText('Backend Runtime Architecture & Data Sources')).toBeInTheDocument());
    expect(screen.getByText('WattTime API')).toBeInTheDocument();
    expect(screen.getByText('Custom Regional Tariff Feed')).toBeInTheDocument();
    expect(screen.getByText('HEALTHY')).toBeInTheDocument();
  });

  it('shows the real email delivery configuration status for a company admin', async () => {
    mockIsCompanyAdmin = true;
    (sustainabilityApi.getDataSourcesStatus as any).mockResolvedValue({});
    (monitoringApi.getSystemHealth as any).mockResolvedValue({
      service: 'greenshift-api',
      status: 'healthy',
      components: { email_delivery: { status: 'configured' } },
    });
    renderPage();
    await waitFor(() => expect(screen.getByText('CONFIGURED')).toBeInTheDocument());
  });

  it('shows a disabled email delivery status without exposing any SMTP credentials', async () => {
    mockIsCompanyAdmin = true;
    (sustainabilityApi.getDataSourcesStatus as any).mockResolvedValue({});
    (monitoringApi.getSystemHealth as any).mockResolvedValue({
      service: 'greenshift-api',
      status: 'healthy',
      components: { email_delivery: { status: 'disabled', reason: 'SMTP_ENABLED is false' } },
    });
    renderPage();
    await waitFor(() => expect(screen.getByText(/DISABLED/)).toBeInTheDocument());
    expect(screen.getByText(/In-app notifications always work regardless/)).toBeInTheDocument();
    expect(document.body.innerHTML.toLowerCase()).not.toContain('smtp_password');
  });

  it('shows pending/failed email delivery counters and last-sent time without exposing credentials', async () => {
    mockIsCompanyAdmin = true;
    (sustainabilityApi.getDataSourcesStatus as any).mockResolvedValue({});
    (monitoringApi.getSystemHealth as any).mockResolvedValue({
      service: 'greenshift-api',
      status: 'healthy',
      components: {
        email_delivery: {
          status: 'configured',
          pending_count: 3,
          failed_count: 1,
          last_sent_at: '2026-09-13T09:00:00+00:00',
        },
      },
    });
    renderPage();
    await waitFor(() => expect(screen.getByText('CONFIGURED')).toBeInTheDocument());
    expect(screen.getByText(/Pending: 3/)).toBeInTheDocument();
    expect(screen.getByText(/Failed: 1/)).toBeInTheDocument();
    expect(screen.getByText(/Last sent:/)).toBeInTheDocument();
    expect(document.body.innerHTML.toLowerCase()).not.toContain('smtp_password');
    expect(document.body.innerHTML.toLowerCase()).not.toContain('smtp_username');
  });

  it('persists the poll interval preference to local storage on save', async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByText(companyUser.username)).toBeInTheDocument());

    // fireEvent.change (not userEvent.clear+type) — jsdom's <input
    // type="number"> doesn't support real text selection, so
    // userEvent's keystroke-simulated typing appends onto the existing
    // value instead of replacing it; a direct change event sets it cleanly.
    const pollInput = document.getElementById('telemetry-poll-interval') as HTMLInputElement;
    fireEvent.change(pollInput, { target: { value: '30' } });
    expect(pollInput.value).toBe('30');

    await user.click(screen.getByText('Save Preferences'));

    await waitFor(() => {
      expect(screen.getByText(/UI control preferences saved/)).toBeInTheDocument();
    });
    expect(localStorage.getItem('gs_pref_poll_interval')).toBe('30');
    // The old client-only "preferred objective" preference has been fully
    // replaced by the backend-owned optimization policy below — it must
    // never be written to localStorage again.
    expect(localStorage.getItem('gs_pref_objective')).toBeNull();
  });

  it('loads a previously saved poll interval from local storage on mount', async () => {
    localStorage.setItem('gs_pref_poll_interval', '30');
    renderPage();

    await waitFor(() => expect(screen.getByText(companyUser.username)).toBeInTheDocument());
    const pollInput = document.getElementById('telemetry-poll-interval') as HTMLInputElement;
    expect(pollInput.value).toBe('30');
  });

  describe('Notification email preferences', () => {
    it('loads and displays real preference values from the backend', async () => {
      (notificationsApi.getPreferences as any).mockResolvedValue({
        email_workload: true,
        email_scheduling: false,
        email_approval: true,
        email_execution: false,
        email_system: true,
      });
      renderPage();

      await waitFor(() => expect(notificationsApi.getPreferences).toHaveBeenCalled());
      const schedulingToggle = await screen.findByLabelText('Email me for Scheduling notifications');
      const workloadToggle = await screen.findByLabelText('Email me for Workload notifications');
      expect((schedulingToggle as HTMLInputElement).checked).toBe(false);
      expect((workloadToggle as HTMLInputElement).checked).toBe(true);
    });

    it('shows an error state with retry when preferences fail to load', async () => {
      (notificationsApi.getPreferences as any).mockRejectedValue(new Error('network error'));
      renderPage();

      await waitFor(() => expect(screen.getByText("Couldn't load notification preferences.")).toBeInTheDocument());
      expect(screen.getByText('Retry')).toBeInTheDocument();
    });

    it('toggling a category calls updatePreferences with only that field', async () => {
      const user = userEvent.setup();
      renderPage();

      const approvalToggle = await screen.findByLabelText('Email me for Approval notifications');
      await user.click(approvalToggle);

      await waitFor(() => {
        expect(notificationsApi.updatePreferences).toHaveBeenCalledWith({ email_approval: false });
      });
    });

    it('never renders a toggle for the non-disableable system/security category', async () => {
      renderPage();
      await waitFor(() => expect(notificationsApi.getPreferences).toHaveBeenCalled());
      expect(screen.queryByLabelText(/Email me for System notifications/i)).not.toBeInTheDocument();
      expect(screen.queryByLabelText(/Email me for Security notifications/i)).not.toBeInTheDocument();
    });
  });

  describe('Real-time notifications', () => {
    it('shows the live connection status', async () => {
      mockConnectionStatus = 'connected';
      renderPage();
      await waitFor(() => expect(screen.getByText('CONNECTED')).toBeInTheDocument());
      expect(screen.getByText(/Live — new notifications arrive instantly/)).toBeInTheDocument();
    });

    it('shows a fallback message when real-time delivery is unavailable', async () => {
      mockConnectionStatus = 'unavailable';
      renderPage();
      await waitFor(() => expect(screen.getByText('UNAVAILABLE')).toBeInTheDocument());
      expect(screen.getByText(/falling back to periodic refresh/)).toBeInTheDocument();
    });

    it('reflects the current sound preference and toggling calls setSoundEnabled', async () => {
      const user = userEvent.setup();
      mockSoundEnabled = true;
      renderPage();

      const soundToggle = await screen.findByLabelText('Notification sound');
      expect((soundToggle as HTMLInputElement).checked).toBe(true);

      await user.click(soundToggle);
      expect(setSoundEnabledMock).toHaveBeenCalledWith(false);
    });
  });

  describe('Company Profile', () => {
    it('renders the company profile read-only for a Company User', async () => {
      mockUser = companyUser;
      renderPage();
      await waitFor(() => expect(companiesApi.getMyCompany).toHaveBeenCalled());
      expect(await screen.findByText('Acme Corporation Pvt Ltd')).toBeInTheDocument();
      expect(screen.getByText('Technology')).toBeInTheDocument();
      expect(screen.getByText(/only a Company Admin can edit/i)).toBeInTheDocument();
      // No editable input for company fields when read-only.
      expect(screen.queryByDisplayValue('Acme Corp')).not.toBeInTheDocument();
    });

    it('renders editable fields and allows a Company Admin to save changes', async () => {
      mockUser = companyAdminUser;
      renderPage();
      await waitFor(() => expect(companiesApi.getMyCompany).toHaveBeenCalled());

      const websiteInput = await screen.findByDisplayValue('https://acme.example');
      const user = userEvent.setup();
      await user.clear(websiteInput);
      await user.type(websiteInput, 'https://new-acme.example');

      const saveButton = screen.getByText('Save Company Profile');
      await user.click(saveButton);

      await waitFor(() => {
        expect(companiesApi.updateMyCompany).toHaveBeenCalledWith(
          expect.objectContaining({ website: 'https://new-acme.example' }),
        );
      });
      await waitFor(() => expect(screen.getByText('Company profile saved.')).toBeInTheDocument());
    });

    it('does not render the company profile card for a user with no company (e.g. Platform Admin)', async () => {
      mockUser = { ...companyUser, tenant_id: null };
      renderPage();
      await waitFor(() => expect(screen.getByText(companyUser.username)).toBeInTheDocument());
      expect(screen.queryByText('Company Profile')).not.toBeInTheDocument();
      expect(companiesApi.getMyCompany).not.toHaveBeenCalled();
    });

    it('shows an error banner when the company profile fails to load', async () => {
      (companiesApi.getMyCompany as any).mockRejectedValue(new Error('network error'));
      mockUser = companyUser;
      renderPage();
      await waitFor(() => expect(screen.getByText("Couldn't load company profile.")).toBeInTheDocument());
    });
  });

  describe('Scheduling Optimization Policy', () => {
    it('loads the backend policy — never from local storage', async () => {
      mockUser = companyUser;
      mockIsCompanyAdmin = false;
      (optimizationPolicyApi.getPolicy as any).mockResolvedValue({
        policy: 'COST_FIRST', carbon_tolerance_pct: null, updated_by: 'company_admin', updated_at: '2026-09-01T00:00:00Z',
      });
      renderPage();

      await waitFor(() => expect(optimizationPolicyApi.getPolicy).toHaveBeenCalled());
      const costRadio = await screen.findByRole('radio', { name: /cost first/i });
      expect((costRadio as HTMLInputElement).checked).toBe(true);
    });

    it('is read-only for a Company User, with the change button hidden', async () => {
      mockUser = companyUser;
      mockIsCompanyAdmin = false;
      renderPage();

      const carbonRadio = await screen.findByRole('radio', { name: /^carbon first/i });
      expect((carbonRadio as HTMLInputElement).disabled).toBe(true);
      expect(screen.getByText(/only a Company Admin can change the scheduling optimization policy/i)).toBeInTheDocument();
      expect(screen.queryByText('Save Optimization Policy')).not.toBeInTheDocument();
    });

    it('allows a Company Admin to change and save the policy', async () => {
      mockUser = companyAdminUser;
      mockIsCompanyAdmin = true;
      (optimizationPolicyApi.updatePolicy as any).mockResolvedValue({
        policy: 'COST_FIRST', carbon_tolerance_pct: null, updated_by: 'company_admin', updated_at: '2026-09-15T00:00:00Z',
      });
      renderPage();

      const costRadio = await screen.findByRole('radio', { name: /cost first/i });
      const user = userEvent.setup();
      await user.click(costRadio);
      await user.click(screen.getByText('Save Optimization Policy'));

      await waitFor(() => {
        expect(optimizationPolicyApi.updatePolicy).toHaveBeenCalledWith({ policy: 'COST_FIRST' });
      });
      await waitFor(() => expect(screen.getByText('Scheduling optimization policy saved.')).toBeInTheDocument());
    });

    it('reveals the carbon tolerance input only for Carbon Constrained and includes it on save', async () => {
      mockUser = companyAdminUser;
      mockIsCompanyAdmin = true;
      (optimizationPolicyApi.updatePolicy as any).mockResolvedValue({
        policy: 'CARBON_CONSTRAINED', carbon_tolerance_pct: 10, updated_by: 'company_admin', updated_at: '2026-09-15T00:00:00Z',
      });
      renderPage();

      await screen.findByRole('radio', { name: /^carbon first/i });
      expect(screen.queryByLabelText('Carbon Tolerance (%)')).not.toBeInTheDocument();

      const user = userEvent.setup();
      await user.click(screen.getByRole('radio', { name: /balanced/i }));

      const toleranceInput = await screen.findByLabelText('Carbon Tolerance (%)');
      await user.clear(toleranceInput);
      await user.type(toleranceInput, '10');

      await user.click(screen.getByText('Save Optimization Policy'));
      await waitFor(() => {
        expect(optimizationPolicyApi.updatePolicy).toHaveBeenCalledWith({ policy: 'CARBON_CONSTRAINED', carbon_tolerance_pct: 10 });
      });
    });

    it('shows an error state with retry when the policy fails to load', async () => {
      (optimizationPolicyApi.getPolicy as any).mockRejectedValue(new Error('network error'));
      renderPage();
      await waitFor(() => expect(screen.getByText("Couldn't load the scheduling optimization policy.")).toBeInTheDocument());
      expect(screen.getByText('Retry')).toBeInTheDocument();
    });

    it('shows a friendly error and does not silently succeed when saving fails', async () => {
      mockUser = companyAdminUser;
      mockIsCompanyAdmin = true;
      (optimizationPolicyApi.updatePolicy as any).mockRejectedValue({
        response: { data: { detail: 'carbon_tolerance_pct is required when policy is CARBON_CONSTRAINED' } },
      });
      renderPage();

      const user = userEvent.setup();
      await user.click(await screen.findByRole('radio', { name: /balanced/i }));
      await user.click(screen.getByText('Save Optimization Policy'));

      await waitFor(() => {
        expect(screen.getByText('carbon_tolerance_pct is required when policy is CARBON_CONSTRAINED')).toBeInTheDocument();
      });
    });
  });
});
