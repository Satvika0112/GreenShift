import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SettingsPage } from './SettingsPage';
import { sustainabilityApi, monitoringApi, notificationsApi } from '../api/endpoints';
import { User, NotificationPreferences } from '../types/api';
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
}));

let mockUser: User;
let mockIsCompanyAdmin: boolean;

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: mockUser, isCompanyAdmin: mockIsCompanyAdmin, isAuthenticated: true }),
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
    (sustainabilityApi.getDataSourcesStatus as any).mockResolvedValue({});
    (monitoringApi.getSystemHealth as any).mockResolvedValue({});
    (notificationsApi.getPreferences as any).mockResolvedValue({ ...defaultPreferences });
    (notificationsApi.updatePreferences as any).mockResolvedValue({ ...defaultPreferences });
  });

  it('renders the real authenticated identity fields, not placeholder text', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText(companyUser.username)).toBeInTheDocument());
    expect(screen.getByText(companyUser.email)).toBeInTheDocument();
    expect(screen.getByText(companyUser.role)).toBeInTheDocument();
    expect(screen.getByText(companyUser.company_name!)).toBeInTheDocument();
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
});
