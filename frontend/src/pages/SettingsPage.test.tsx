import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SettingsPage } from './SettingsPage';
import { sustainabilityApi, monitoringApi, notificationsApi, companiesApi } from '../api/endpoints';
import { User, NotificationPreferences, CompanyProfile } from '../types/api';
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

  it('persists client preferences to local storage on save', async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByText(companyUser.username)).toBeInTheDocument());

    const objectiveSelect = document.querySelector('select.select') as HTMLSelectElement;
    await user.selectOptions(objectiveSelect, 'cost');

    await user.click(screen.getByText('Save Preferences'));

    await waitFor(() => {
      expect(screen.getByText(/UI control preferences saved/)).toBeInTheDocument();
    });
    expect(localStorage.getItem('gs_pref_objective')).toBe('cost');
  });

  it('loads a previously saved preference from local storage on mount', async () => {
    localStorage.setItem('gs_pref_objective', 'balanced');
    localStorage.setItem('gs_pref_poll_interval', '30');
    renderPage();

    await waitFor(() => expect(screen.getByText(companyUser.username)).toBeInTheDocument());
    const objectiveSelect = document.querySelector('select.select') as HTMLSelectElement;
    expect(objectiveSelect.value).toBe('balanced');
    const pollInput = document.querySelector('input[type="number"]') as HTMLInputElement;
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
});
