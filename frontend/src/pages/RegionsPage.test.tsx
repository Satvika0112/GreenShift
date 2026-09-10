import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RegionsPage } from './RegionsPage';
import { sustainabilityApi, dispatchApi, workloadsApi } from '../api/endpoints';

vi.mock('../api/endpoints', () => ({
  sustainabilityApi: {
    getRegions: vi.fn(),
    getCarbonCurrent: vi.fn(),
    getCurrentTariff: vi.fn(),
  },
  dispatchApi: {
    getK8sState: vi.fn(),
  },
  workloadsApi: {
    getJobs: vi.fn(),
  },
}));

const indiaRegion = {
  region_id: 'IN-TG',
  country: 'India',
  region_name: 'Telangana',
  timezone: 'Asia/Kolkata',
  currency: 'INR',
  electricity_maps_zone: 'IN-SO',
  default_plan: 'ToD',
  supported_tariff_plans: [],
  aliases: [],
  is_active: true,
};

const usaRegion = {
  region_id: 'US-CA',
  country: 'United States',
  region_name: 'California',
  timezone: 'America/Los_Angeles',
  currency: 'USD',
  electricity_maps_zone: 'US-CAL-CISO',
  default_plan: 'ToD',
  supported_tariff_plans: [],
  aliases: [],
  is_active: true,
};

const australiaRegion = {
  region_id: 'AU-SA-Small',
  country: 'Australia',
  region_name: 'South Australia (Small)',
  timezone: 'Australia/Adelaide',
  currency: 'AUD',
  electricity_maps_zone: 'AU-SA',
  default_plan: 'ToD',
  supported_tariff_plans: [],
  aliases: [],
  is_active: true,
};

function tariffResponseFor(regionId: string, currency: string, effectivePrice: number) {
  return {
    region: regionId,
    region_id: regionId,
    currency,
    current_tariff: {
      utc_timestamp: '2026-09-11T00:00:00Z',
      local_timestamp: '2026-09-11T05:30:00+05:30',
      local_hour: 5,
      timezone: 'Asia/Kolkata',
      time_interval: '05:00-06:00',
      time_of_day: 'Off-Peak',
      base_charge: effectivePrice,
      adder_charge: 0,
      effective_price: effectivePrice,
      currency,
      tariff_type: 'ToD',
      season: 'All-Year',
      price_per_kwh_usd: effectivePrice / 80, // deliberately different from effective_price
    },
  };
}

function carbonResponseFor(regionId: string, value: number) {
  return { region: regionId, carbon_gco2_kwh: value, timestamp: '2026-09-11T00:00:00Z', source: 'Electricity Maps', is_fallback: false };
}

function setupRegions(regions: any[]) {
  (sustainabilityApi.getRegions as any).mockResolvedValue(regions);
  (dispatchApi.getK8sState as any).mockResolvedValue({ connected: true, total_nodes: 3, ready_nodes: 3, free_cpu_cores: 10, total_cpu_cores: 20, free_memory_mib: 4096 });
  (workloadsApi.getJobs as any).mockResolvedValue([]);
}

describe('RegionsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows a loading state before data arrives', () => {
    setupRegions([indiaRegion]);
    (sustainabilityApi.getCarbonCurrent as any).mockReturnValue(new Promise(() => {}));
    (sustainabilityApi.getCurrentTariff as any).mockReturnValue(new Promise(() => {}));
    render(<RegionsPage />);
    expect(screen.queryByText('Telangana')).not.toBeInTheDocument();
  });

  it('India displays its real native INR tariff, never a $ sign', async () => {
    setupRegions([indiaRegion]);
    (sustainabilityApi.getCarbonCurrent as any).mockResolvedValue(carbonResponseFor('IN-TG', 350));
    (sustainabilityApi.getCurrentTariff as any).mockResolvedValue(tariffResponseFor('IN-TG', 'INR', 7.15));
    render(<RegionsPage />);

    await waitFor(() => expect(screen.getByText('Telangana')).toBeInTheDocument());
    expect(screen.getByText('₹7.15 INR/kWh')).toBeInTheDocument();
    expect(screen.queryByText(/\$7\.15/)).not.toBeInTheDocument();
  });

  it('USA displays its real native USD tariff', async () => {
    setupRegions([usaRegion]);
    (sustainabilityApi.getCarbonCurrent as any).mockResolvedValue(carbonResponseFor('US-CA', 220));
    (sustainabilityApi.getCurrentTariff as any).mockResolvedValue(tariffResponseFor('US-CA', 'USD', 0.1148));
    render(<RegionsPage />);

    await waitFor(() => expect(screen.getByText('California')).toBeInTheDocument());
    expect(screen.getByText('$0.1148 USD/kWh')).toBeInTheDocument();
  });

  it('Australia displays its real native AUD tariff, with no USD assumption anywhere', async () => {
    setupRegions([australiaRegion]);
    (sustainabilityApi.getCarbonCurrent as any).mockResolvedValue(carbonResponseFor('AU-SA-Small', 400));
    (sustainabilityApi.getCurrentTariff as any).mockResolvedValue(tariffResponseFor('AU-SA-Small', 'AUD', 0.28));
    render(<RegionsPage />);

    await waitFor(() => expect(screen.getByText('South Australia (Small)')).toBeInTheDocument());
    expect(screen.getByText('A$0.28 AUD/kWh')).toBeInTheDocument();
    // The tariff endpoint's own USD-normalized figure (0.28/80 = 0.0035) must
    // never leak into the display, and no bare (non-"A$") "$" for AUD.
    expect(screen.queryByText(/(?<!A)\$0\.28(?!\d)/)).not.toBeInTheDocument();
    expect(screen.queryByText('$0.0035')).not.toBeInTheDocument();
  });

  it('shows an honest unavailable state, not a fabricated tariff, when the tariff request fails', async () => {
    setupRegions([australiaRegion]);
    (sustainabilityApi.getCarbonCurrent as any).mockResolvedValue(carbonResponseFor('AU-SA-Small', 400));
    (sustainabilityApi.getCurrentTariff as any).mockRejectedValue(new Error('network'));
    render(<RegionsPage />);

    await waitFor(() => expect(screen.getByText('South Australia (Small)')).toBeInTheDocument());
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.queryByText(/A\$0\.00/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\$0\.00/)).not.toBeInTheDocument();
  });

  it('shows an honest unavailable state, not a fabricated carbon value, when the carbon request fails', async () => {
    setupRegions([indiaRegion]);
    (sustainabilityApi.getCarbonCurrent as any).mockRejectedValue(new Error('network'));
    (sustainabilityApi.getCurrentTariff as any).mockResolvedValue(tariffResponseFor('IN-TG', 'INR', 7.15));
    render(<RegionsPage />);

    await waitFor(() => expect(screen.getByText('Telangana')).toBeInTheDocument());
    expect(screen.getByText('DATA UNAVAILABLE')).toBeInTheDocument();
  });

  it('shows a backend error state with a working Retry button, not zeroed-out cards', async () => {
    const user = userEvent.setup();
    (sustainabilityApi.getRegions as any).mockRejectedValueOnce(new Error('down'));
    (dispatchApi.getK8sState as any).mockResolvedValue(null);
    (workloadsApi.getJobs as any).mockResolvedValue([]);
    render(<RegionsPage />);

    expect(await screen.findByText('Failed to load regional cluster data from backend.')).toBeInTheDocument();

    setupRegions([indiaRegion]);
    (sustainabilityApi.getCarbonCurrent as any).mockResolvedValue(carbonResponseFor('IN-TG', 350));
    (sustainabilityApi.getCurrentTariff as any).mockResolvedValue(tariffResponseFor('IN-TG', 'INR', 7.15));
    await user.click(screen.getByRole('button', { name: /retry/i }));

    await waitFor(() => expect(screen.getByText('Telangana')).toBeInTheDocument());
  });
});
