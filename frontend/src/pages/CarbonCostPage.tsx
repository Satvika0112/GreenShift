import React, { useState, useEffect } from 'react';
import {
  Zap,
  TrendingDown,
  Clock,
  DollarSign,
  Leaf,
  Globe,
  RefreshCw,
} from 'lucide-react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from 'recharts';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassCard } from '../components/common/GlassCard';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { EmptyState } from '../components/common/EmptyState';
import { InlineBanner } from '../components/common/InlineBanner';
import { sustainabilityApi } from '../api/endpoints';
import { RegionInfo, CurrentTariffResponse } from '../types/api';
import { formatRate, currencyRateUnitLabel } from '../utils/currency';

interface HourlyDataPoint {
  hour: string;
  carbon_intensity: number;
  // Native regional tariff rate for this hour — undefined (not zero) when
  // the backend genuinely has no tariff reading for that hour.
  tariff_price?: number;
  is_fallback?: boolean;
}

export const CarbonCostPage: React.FC = () => {
  const [regions, setRegions] = useState<RegionInfo[]>([]);
  const [selectedRegion, setSelectedRegion] = useState('IN-TG');
  const [chartData, setChartData] = useState<HourlyDataPoint[]>([]);
  const [currentTariff, setCurrentTariff] = useState<CurrentTariffResponse | null>(null);
  const [currentCarbon, setCurrentCarbon] = useState<any | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Load available regions
  useEffect(() => {
    const fetchRegions = async () => {
      try {
        const res = await sustainabilityApi.getRegions();
        if (Array.isArray(res) && res.length > 0) {
          setRegions(res);
          if (!selectedRegion) setSelectedRegion(res[0].region_id);
        }
      } catch {
        // Fallback to standard regions
      }
    };
    fetchRegions();
  }, []);

  // Fetch carbon and tariff curves for selected region
  const fetchCurves = async () => {
    if (!selectedRegion) return;
    setIsLoading(true);
    setErrorMsg(null);
    try {
      const [carbonRes, tariffRes, currentCRes, currentTRes] = await Promise.allSettled([
        sustainabilityApi.getCarbonData(selectedRegion),
        sustainabilityApi.getRegionHourlyTariffs(selectedRegion),
        sustainabilityApi.getCarbonCurrent(selectedRegion),
        sustainabilityApi.getCurrentTariff(selectedRegion),
      ]);

      if (currentCRes.status === 'fulfilled') setCurrentCarbon(currentCRes.value);
      if (currentTRes.status === 'fulfilled') setCurrentTariff(currentTRes.value);

      const carbonPoints = carbonRes.status === 'fulfilled' ? carbonRes.value?.data || [] : [];
      const tariffPoints = tariffRes.status === 'fulfilled' ? tariffRes.value?.tariffs || [] : [];

      // Merge into 24-hour chart array
      const points: HourlyDataPoint[] = [];

      if (tariffPoints.length > 0) {
        tariffPoints.forEach((t: any, idx: number) => {
          const hourLabel = t.time_interval || `${String(idx).padStart(2, '0')}:00`;
          const cPoint = carbonPoints[idx] || carbonPoints[idx % (carbonPoints.length || 1)];
          if (cPoint?.carbon_gco2_kwh !== undefined) {
            points.push({
              hour: hourLabel,
              carbon_intensity: cPoint.carbon_gco2_kwh,
              // Native regional rate — never the USD-normalized figure.
              tariff_price: t.effective_price,
              is_fallback: cPoint?.is_fallback,
            });
          }
        });
      } else if (carbonPoints.length > 0) {
        // Tariff data is genuinely unavailable for this region/window — plot
        // carbon alone rather than inventing a tariff figure for it.
        carbonPoints.forEach((c: any) => {
          const d = new Date(c.timestamp);
          points.push({
            hour: `${String(d.getUTCHours()).padStart(2, '0')}:00`,
            carbon_intensity: c.carbon_gco2_kwh,
            tariff_price: undefined,
            is_fallback: c.is_fallback,
          });
        });
      }

      setChartData(points);
      if (carbonRes.status === 'rejected' && tariffRes.status === 'rejected') {
        setErrorMsg('Failed to load carbon and tariff profiles for ' + selectedRegion);
      }
    } catch (err: any) {
      setErrorMsg('Failed to load carbon and tariff profiles for ' + selectedRegion);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchCurves();
  }, [selectedRegion]);

  const activeRegionObj = regions.find((r) => r.region_id === selectedRegion);
  // The region's own registered currency is the single source of truth for
  // every currency-aware label on this page and its chart — never assumed,
  // never USD by default.
  const chartCurrency = currentTariff?.currency || activeRegionObj?.currency;
  const tariffSeriesName = chartCurrency ? `Tariff (${currencyRateUnitLabel(chartCurrency)})` : 'Tariff';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      <PageHeader
        title="Carbon Intensity & Electricity Tariffs"
        subtitle="24-hour marginal emissions curves, Time-of-Day (ToD) electricity price tiers, and optimal green scheduling windows"
        actions={
          <button className="btn btn-secondary" onClick={fetchCurves} disabled={isLoading}>
            <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
            <span>Sync Grid Data</span>
          </button>
        }
      />

      {errorMsg && <InlineBanner variant="error">{errorMsg}</InlineBanner>}

      {/* Region Selector & Status */}
      <GlassCard>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '1rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
            <label className="form-label" style={{ marginBottom: 0, fontWeight: 700 }}>
              Select Interconnection Grid:
            </label>
            <select
              className="select"
              style={{ width: '260px' }}
              value={selectedRegion}
              onChange={(e) => setSelectedRegion(e.target.value)}
            >
              {regions.map((r) => (
                <option key={r.region_id} value={r.region_id}>
                  {r.region_name} ({r.region_id}) • {r.country}
                </option>
              ))}
            </select>
          </div>

          <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
            Grid Zone: <strong style={{ color: '#38bdf8' }}>{activeRegionObj?.electricity_maps_zone || selectedRegion}</strong> •
            Timezone: <strong style={{ color: '#ffffff' }}>{activeRegionObj?.timezone || 'UTC'}</strong> •
            Currency: <strong style={{ color: '#10b981' }}>{activeRegionObj?.currency || '—'}</strong>
          </div>
        </div>
      </GlassCard>

      {/* Live Reading Row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem' }}>
        <div style={{ background: 'var(--bg-surface)', padding: '1.25rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Current Marginal Carbon Intensity</div>
          <div style={{ fontSize: '1.6rem', fontWeight: 800, color: currentCarbon?.carbon_gco2_kwh !== undefined ? '#10b981' : 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginTop: '0.2rem' }}>
            {currentCarbon?.carbon_gco2_kwh !== undefined ? `${currentCarbon.carbon_gco2_kwh.toFixed(0)} gCO₂/kWh` : 'DATA UNAVAILABLE'}
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
            Feed: {currentCarbon?.source || (currentCarbon?.is_fallback ? 'Controlled Fallback' : 'Electricity Maps Live')}
          </div>
        </div>

        <div style={{ background: 'var(--bg-surface)', padding: '1.25rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Effective Electricity Rate</div>
          <div
            style={{
              fontSize: '1.6rem',
              fontWeight: 800,
              color: currentTariff?.current_tariff?.effective_price !== undefined ? '#38bdf8' : 'var(--text-muted)',
              fontFamily: 'var(--font-mono)',
              marginTop: '0.2rem',
            }}
          >
            {formatRate(currentTariff?.current_tariff?.effective_price, currentTariff?.currency)}
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
            Plan: {currentTariff?.current_tariff?.tariff_type || activeRegionObj?.default_plan || '—'}
          </div>
        </div>

        <div style={{ background: 'var(--bg-surface)', padding: '1.25rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Active ToD Tariff Tier</div>
          <div style={{ fontSize: '1.3rem', fontWeight: 800, color: '#f59e0b', fontFamily: 'var(--font-mono)', marginTop: '0.2rem' }}>
            {currentTariff?.current_tariff?.time_of_day || 'STANDARD / NORMAL'}
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
            Interval: {currentTariff?.current_tariff?.time_interval || 'All Hours'}
          </div>
        </div>
      </div>

      {/* 24-Hour Carbon Intensity Forecast Chart */}
      <GlassCard
        title={`24-Hour Carbon Intensity & Tariff Curve — ${selectedRegion}`}
        subtitle="Hourly marginal carbon intensity (gCO₂/kWh) & Time-of-Day electricity pricing"
      >
        {isLoading ? (
          <LoadingSkeleton rows={5} height={50} />
        ) : chartData.length === 0 ? (
          <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
            No telemetry points available for this region.
          </div>
        ) : (
          <div style={{ width: '100%', height: '340px', marginTop: '0.5rem' }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorCarbon" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="colorTariff" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#38bdf8" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="hour" stroke="#64748b" tick={{ fontSize: 11 }} />
                <YAxis yAxisId="left" stroke="#10b981" tick={{ fontSize: 11 }} unit=" g" />
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  stroke="#38bdf8"
                  tick={{ fontSize: 11 }}
                  tickFormatter={(value: number) => formatRate(value, chartCurrency)}
                  label={{ value: `Tariff (${currencyRateUnitLabel(chartCurrency)})`, angle: 90, position: 'insideRight', fontSize: 11, fill: '#38bdf8' }}
                />
                <Tooltip
                  contentStyle={{
                    background: '#0e1422',
                    border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: '6px',
                    fontSize: '0.8rem',
                  }}
                  formatter={(value, name) =>
                    name === tariffSeriesName ? [formatRate(Number(value), chartCurrency), name] : [value, name]
                  }
                />
                <Legend />
                <Area
                  yAxisId="left"
                  type="monotone"
                  dataKey="carbon_intensity"
                  name="Carbon Intensity (gCO₂/kWh)"
                  stroke="#10b981"
                  strokeWidth={2}
                  fillOpacity={1}
                  fill="url(#colorCarbon)"
                />
                <Area
                  yAxisId="right"
                  type="monotone"
                  dataKey="tariff_price"
                  name={tariffSeriesName}
                  stroke="#38bdf8"
                  strokeWidth={2}
                  fillOpacity={1}
                  fill="url(#colorTariff)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </GlassCard>
    </div>
  );
};
