import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SettingsPage } from './SettingsPage';
import { sustainabilityApi, monitoringApi } from '../api/endpoints';
import { User } from '../types/api';

vi.mock('../api/endpoints', () => ({
  sustainabilityApi: {
    getDataSourcesStatus: vi.fn(),
  },
  monitoringApi: {
    getSystemHealth: vi.fn(),
  },
}));

let mockUser: User;
let mockIsCompanyAdmin: boolean;

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: mockUser, isCompanyAdmin: mockIsCompanyAdmin }),
}));

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
  return render(<SettingsPage />);
}

describe('SettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockUser = companyUser;
    mockIsCompanyAdmin = false;
    (sustainabilityApi.getDataSourcesStatus as any).mockResolvedValue({});
    (monitoringApi.getSystemHealth as any).mockResolvedValue({});
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
});
