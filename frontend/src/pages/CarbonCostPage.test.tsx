import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { CarbonCostPage } from './CarbonCostPage';
import { sustainabilityApi } from '../api/endpoints';

// Recharts' ResponsiveContainer measures real layout (offsetWidth/Height),
// which jsdom always reports as 0 — it renders nothing in tests regardless
// of the app code. Mocking the library at this boundary lets us verify what
// THIS page computes and passes to it (series names, axis label, tick and
// tooltip formatters) without asserting on the third-party library's own
// internal rendering.
vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: any) => <div>{children}</div>,
  AreaChart: ({ children }: any) => <div data-testid="area-chart">{children}</div>,
  Area: ({ name }: any) => <div data-testid="chart-series-name">{name}</div>,
  XAxis: () => null,
  YAxis: ({ label, tickFormatter, orientation }: any) => (
    <div data-testid={orientation === 'right' ? 'y-axis-right' : 'y-axis-left'}>
      {label && <span data-testid="y-axis-label">{typeof label === 'object' ? label.value : label}</span>}
      {tickFormatter && <span data-testid="y-axis-tick-sample">{tickFormatter(0.28)}</span>}
    </div>
  ),
  Tooltip: ({ formatter }: any) =>
    formatter ? <div data-testid="tooltip-sample">{formatter(0.28, 'Tariff (A$/kWh)')[0]}</div> : null,
  CartesianGrid: () => null,
  Legend: () => <div data-testid="legend" />,
}));

vi.mock('../api/endpoints', () => ({
  sustainabilityApi: {
    getRegions: vi.fn(),
    getCarbonData: vi.fn(),
    getRegionHourlyTariffs: vi.fn(),
    getCarbonCurrent: vi.fn(),
    getCurrentTariff: vi.fn(),
  },
}));

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

function hourlyTariffsResponse(regionId: string, currency: string) {
  return {
    region: regionId,
    region_id: regionId,
    currency,
    season: 'All-Year',
    tariffs: [
      { hour: 0, time_interval: '00:00-01:00', time_of_day: 'Night', base_charge: 1, adder_charge: 0, effective_price: 1.5, currency, tariff_type: 'ToD', season: 'All-Year', price_per_kwh_usd: 1.5 / 80 },
      { hour: 1, time_interval: '01:00-02:00', time_of_day: 'Night', base_charge: 1, adder_charge: 0, effective_price: 1.6, currency, tariff_type: 'ToD', season: 'All-Year', price_per_kwh_usd: 1.6 / 80 },
    ],
  };
}

function carbonCurveResponse(regionId: string) {
  return {
    region: regionId,
    data: [
      { timestamp: '2026-09-11T00:00:00Z', region: regionId, carbon_gco2_kwh: 300, source: 'Electricity Maps', em_zone: regionId, is_fallback: false },
      { timestamp: '2026-09-11T01:00:00Z', region: regionId, carbon_gco2_kwh: 310, source: 'Electricity Maps', em_zone: regionId, is_fallback: false },
    ],
  };
}

function currentTariffResponse(regionId: string, currency: string, effectivePrice: number) {
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
      price_per_kwh_usd: effectivePrice / 80,
    },
  };
}

function setupRegion(region: typeof indiaRegion, effectivePrice: number) {
  (sustainabilityApi.getRegions as any).mockResolvedValue([region]);
  (sustainabilityApi.getCarbonData as any).mockResolvedValue(carbonCurveResponse(region.region_id));
  (sustainabilityApi.getRegionHourlyTariffs as any).mockResolvedValue(hourlyTariffsResponse(region.region_id, region.currency));
  (sustainabilityApi.getCarbonCurrent as any).mockResolvedValue({ region: region.region_id, carbon_gco2_kwh: 300, timestamp: '2026-09-11T00:00:00Z', source: 'Electricity Maps', is_fallback: false });
  (sustainabilityApi.getCurrentTariff as any).mockResolvedValue(currentTariffResponse(region.region_id, region.currency, effectivePrice));
}

describe('CarbonCostPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('India: chart series name and live reading use ₹', async () => {
    setupRegion(indiaRegion, 7.15);
    render(<CarbonCostPage />);

    await waitFor(() => expect(screen.getByText('₹7.15 INR/kWh')).toBeInTheDocument());
    const seriesNames = screen.getAllByTestId('chart-series-name').map((el) => el.textContent);
    expect(seriesNames).toContain('Tariff (₹/kWh)');
  });

  it('USA: chart series name and live reading use $', async () => {
    setupRegion(usaRegion, 0.1148);
    render(<CarbonCostPage />);

    await waitFor(() => expect(screen.getByText('$0.1148 USD/kWh')).toBeInTheDocument());
    const seriesNames = screen.getAllByTestId('chart-series-name').map((el) => el.textContent);
    expect(seriesNames).toContain('Tariff ($/kWh)');
  });

  it('Australia: chart series name and live reading use A$, never a bare $', async () => {
    setupRegion(australiaRegion, 0.28);
    render(<CarbonCostPage />);

    await waitFor(() => expect(screen.getAllByText('A$0.28 AUD/kWh').length).toBeGreaterThan(0));
    const seriesNames = screen.getAllByTestId('chart-series-name').map((el) => el.textContent);
    expect(seriesNames).toContain('Tariff (A$/kWh)');
    expect(seriesNames).not.toContain('Tariff ($/kWh)');
  });

  it('the Y-axis label is dynamically derived from the selected region currency', async () => {
    setupRegion(australiaRegion, 0.28);
    render(<CarbonCostPage />);

    await waitFor(() => expect(screen.getByTestId('y-axis-label')).toHaveTextContent('Tariff (A$/kWh)'));
  });

  it('the Y-axis tick formatter renders full currency-formatted values, not a raw number', async () => {
    setupRegion(australiaRegion, 0.28);
    render(<CarbonCostPage />);

    await waitFor(() => expect(screen.getByTestId('y-axis-tick-sample')).toHaveTextContent('A$0.28'));
  });

  it('the tooltip formatter dynamically uses the selected currency', async () => {
    setupRegion(australiaRegion, 0.28);
    render(<CarbonCostPage />);

    await waitFor(() => expect(screen.getByTestId('tooltip-sample')).toHaveTextContent('A$0.28'));
  });

  it('never fabricates a tariff fallback when only carbon data is available', async () => {
    (sustainabilityApi.getRegions as any).mockResolvedValue([indiaRegion]);
    (sustainabilityApi.getCarbonData as any).mockResolvedValue(carbonCurveResponse('IN-TG'));
    (sustainabilityApi.getRegionHourlyTariffs as any).mockRejectedValue(new Error('no tariff data'));
    (sustainabilityApi.getCarbonCurrent as any).mockResolvedValue({ region: 'IN-TG', carbon_gco2_kwh: 300, timestamp: '2026-09-11T00:00:00Z', source: 'Electricity Maps', is_fallback: false });
    (sustainabilityApi.getCurrentTariff as any).mockRejectedValue(new Error('no tariff data'));

    render(<CarbonCostPage />);

    await waitFor(() => expect(screen.getByTestId('area-chart')).toBeInTheDocument());
    // The old implementation hardcoded 0.07 here — assert that specific
    // fabricated value never appears anywhere on the page.
    expect(screen.queryByText(/0\.07/)).not.toBeInTheDocument();
    // The Effective Electricity Rate tile shows an honest "—", never a
    // fabricated rate, when the tariff request failed.
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('shows a real backend error rather than a zeroed-out reading', async () => {
    (sustainabilityApi.getRegions as any).mockResolvedValue([indiaRegion]);
    (sustainabilityApi.getCarbonData as any).mockRejectedValue(new Error('down'));
    (sustainabilityApi.getRegionHourlyTariffs as any).mockRejectedValue(new Error('down'));
    (sustainabilityApi.getCarbonCurrent as any).mockRejectedValue(new Error('down'));
    (sustainabilityApi.getCurrentTariff as any).mockRejectedValue(new Error('down'));

    render(<CarbonCostPage />);

    expect(await screen.findByText(/Failed to load carbon and tariff profiles/)).toBeInTheDocument();
    expect(screen.queryByText('$0.00')).not.toBeInTheDocument();
    expect(screen.queryByText('₹0.00')).not.toBeInTheDocument();
  });

  it('does not assume USD when no region has loaded yet for the currency indicator', async () => {
    (sustainabilityApi.getRegions as any).mockResolvedValue([]);
    render(<CarbonCostPage />);
    await waitFor(() => expect(screen.getByText('Select Interconnection Grid:')).toBeInTheDocument());
    expect(screen.queryByText('USD')).not.toBeInTheDocument();
  });
});
