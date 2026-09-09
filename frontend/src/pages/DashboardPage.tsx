import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Layers,
  Leaf,
  DollarSign,
  TrendingDown,
  Globe,
  PlusCircle,
  Cpu,
  CheckCircle2,
  ArrowUpRight,
  RefreshCw,
  AlertTriangle,
  UploadCloud,
} from 'lucide-react';
import { KPICard } from '../components/common/KPICard';
import { GlassCard } from '../components/common/GlassCard';
import { StatusBadge } from '../components/common/StatusBadge';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { EmptyState } from '../components/common/EmptyState';
import { PageHeader } from '../components/layout/PageHeader';
import { monitoringApi, workloadsApi, sustainabilityApi } from '../api/endpoints';
import { Job, DashboardSummary, FleetHeadline, RegionInfo } from '../types/api';
import { useAuth } from '../context/AuthContext';

export const DashboardPage: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useAuth();

  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [headline, setHeadline] = useState<FleetHeadline | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [regions, setRegions] = useState<RegionInfo[]>([]);
  const [regionCarbon, setRegionCarbon] = useState<Record<string, number>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isSeedingJobs, setIsSeedingJobs] = useState(false);

  const fetchData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [sumRes, headRes, jobsRes, regRes] = await Promise.allSettled([
        monitoringApi.getDashboardSummary(),
        monitoringApi.getFleetHeadline(),
        workloadsApi.getJobs({ limit: 10 }),
        sustainabilityApi.getRegions(),
      ]);

      if (sumRes.status === 'fulfilled') setSummary(sumRes.value);
      if (headRes.status === 'fulfilled') setHeadline(headRes.value);
      if (jobsRes.status === 'fulfilled') setJobs(jobsRes.value || []);
      if (regRes.status === 'fulfilled') {
        const regList = regRes.value || [];
        setRegions(regList);
        // Fetch real carbon for each region
        regList.forEach(async (r) => {
          try {
            const cRes = await sustainabilityApi.getCarbonCurrent(r.region_id);
            if (cRes?.carbon_gco2_kwh !== undefined) {
              setRegionCarbon((prev) => ({ ...prev, [r.region_id]: cRes.carbon_gco2_kwh }));
            }
          } catch {
            // Ignore regional carbon error
          }
        });
      }
    } catch (err: any) {
      setError('Unable to retrieve fleet metrics from backend. Ensure FastAPI service is running.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [user]);

  const handleBulkLoadDemo = async () => {
    setIsSeedingJobs(true);
    try {
      await workloadsApi.bulkLoadFromCsv();
      await fetchData();
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to load initial dataset');
    } finally {
      setIsSeedingJobs(false);
    }
  };

  const pendingApprovalsCount = summary?.jobs?.PENDING_APPROVAL || 0;
  const activeCount = summary?.active_jobs ?? jobs.filter((j) => j.status === 'RUNNING' || j.status === 'DISPATCHING').length;
  const carbonAvoidedKg = summary?.carbon?.carbon_avoided_kg ?? headline?.total_carbon_avoided_kg ?? 0;
  const costSavedUsd = summary?.cost?.cost_difference ?? headline?.total_cost_saved_usd ?? 0;
  const avgReduction = headline?.avg_carbon_reduction_pct ?? 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      {/* Page Header */}
      <PageHeader
        title="Fleet Operations Control Plane"
        subtitle={`Real-time carbon-aware workload orchestration across multi-region Kubernetes clusters. Active Scope: ${user?.role === 'ADMIN' ? 'Global Organization (All Teams)' : `Team: ${user?.team_id}`}`}
        actions={
          <div style={{ display: 'flex', gap: '0.6rem' }}>
            <button className="btn btn-secondary" onClick={fetchData} disabled={isLoading}>
              <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
              <span>Refresh</span>
            </button>
            <button className="btn btn-primary" onClick={() => navigate('/submit')}>
              <PlusCircle size={15} />
              <span>Submit Workload</span>
            </button>
          </div>
        }
      />

      {error && (
        <div
          style={{
            background: 'rgba(239, 68, 68, 0.15)',
            border: '1px solid #ef4444',
            color: '#ef4444',
            padding: '1rem',
            borderRadius: 'var(--radius-md)',
            fontSize: '0.85rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.75rem',
          }}
        >
          <AlertTriangle size={20} />
          <span>{error}</span>
        </div>
      )}

      {/* Headline Carbon Impact Banner */}
      <div
        style={{
          background: 'linear-gradient(135deg, rgba(16, 185, 129, 0.15) 0%, rgba(6, 182, 212, 0.08) 50%, rgba(14, 20, 34, 0.8) 100%)',
          border: '1px solid rgba(16, 185, 129, 0.3)',
          borderRadius: 'var(--radius-md)',
          padding: '1.25rem 1.5rem',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '1rem',
          boxShadow: '0 4px 20px rgba(16, 185, 129, 0.1)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <div
            style={{
              width: '42px',
              height: '42px',
              borderRadius: 'var(--radius-full)',
              background: 'rgba(16, 185, 129, 0.2)',
              border: '1px solid rgba(16, 185, 129, 0.4)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#10b981',
            }}
          >
            <Leaf size={22} />
          </div>
          <div>
            <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#10b981', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
              Carbon-First Dispatch Efficiency
            </div>
            <div style={{ fontSize: '1.15rem', fontWeight: 700, color: '#ffffff', marginTop: '0.1rem' }}>
              Fleet achieved <span style={{ color: '#10b981', fontFamily: 'var(--font-mono)' }}>{avgReduction.toFixed(1)}%</span> carbon reduction vs baseline dispatch.
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '1.5rem', alignItems: 'center' }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Avoided Emissions</div>
            <div style={{ fontSize: '1.1rem', fontWeight: 700, color: '#10b981', fontFamily: 'var(--font-mono)' }}>
              {carbonAvoidedKg.toFixed(2)} kg CO₂e
            </div>
          </div>
          <div style={{ width: '1px', height: '30px', background: 'var(--border-default)' }} />
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Avoided Cost</div>
            <div style={{ fontSize: '1.1rem', fontWeight: 700, color: '#38bdf8', fontFamily: 'var(--font-mono)' }}>
              ${costSavedUsd.toFixed(2)}
            </div>
          </div>
        </div>
      </div>

      {/* KPI Cards Grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: '1rem',
        }}
      >
        <KPICard
          title="Active Workloads"
          value={activeCount}
          subtitle={`${summary?.total_jobs ?? jobs.length} total registered`}
          icon={Layers}
          color="emerald"
          onClick={() => navigate('/workloads')}
        />
        <KPICard
          title="Carbon Avoided"
          value={`${carbonAvoidedKg.toFixed(1)} kg`}
          subtitle={`Emissions avoided vs counterfactual`}
          icon={TrendingDown}
          color="cyan"
          onClick={() => navigate('/impact')}
        />
        <KPICard
          title="Electricity Cost Saved"
          value={`$${costSavedUsd.toFixed(2)}`}
          subtitle="Time-of-day tariff optimization"
          icon={DollarSign}
          color="indigo"
          onClick={() => navigate('/carbon-cost')}
        />
        <KPICard
          title="Pending Approvals"
          value={pendingApprovalsCount}
          subtitle="Human-in-the-loop review required"
          icon={CheckCircle2}
          color={pendingApprovalsCount > 0 ? 'amber' : 'emerald'}
          onClick={() => navigate('/approvals')}
        />
        <KPICard
          title="Connected Regions"
          value={regions.length}
          subtitle="All active regional grid layers"
          icon={Globe}
          color="emerald"
          onClick={() => navigate('/regions')}
        />
      </div>

      {/* 2-Column Split: Active Workloads & Regional Carbon Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.7fr 1fr', gap: '1.5rem' }}>
        {/* Left: Active & Recent Workloads */}
        <GlassCard
          title="Workload Control Queue"
          subtitle="Real-time execution state from database"
          actions={
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              {jobs.length === 0 && (
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={handleBulkLoadDemo}
                  disabled={isSeedingJobs}
                  title="Bulk load workload dataset into database"
                >
                  <UploadCloud size={13} />
                  <span>{isSeedingJobs ? 'Loading...' : 'Load Dataset'}</span>
                </button>
              )}
              <button className="btn btn-secondary btn-sm" onClick={() => navigate('/workloads')}>
                <span>View All ({jobs.length})</span>
                <ArrowUpRight size={13} />
              </button>
            </div>
          }
        >
          {isLoading ? (
            <LoadingSkeleton rows={4} />
          ) : jobs.length === 0 ? (
            <EmptyState
              title="No Workloads Ingested"
              description="There are currently no active or historical workloads in the database for your team."
              action={{
                label: 'Submit First Workload',
                onClick: () => navigate('/submit'),
              }}
            />
          ) : (
            <div className="data-table-container">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Job ID</th>
                    <th>Status</th>
                    <th>Region</th>
                    <th>Runtime / Power</th>
                    <th>Carbon Budget</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.slice(0, 5).map((job) => (
                    <tr key={job.job_id}>
                      <td>
                        <div>
                          <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                            {job.job_id}
                          </div>
                          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                            {job.team_id} • {job.job_type || 'BATCH'}
                          </div>
                        </div>
                      </td>
                      <td>
                        <StatusBadge status={job.status} size="sm" />
                      </td>
                      <td>
                        <span style={{ fontSize: '0.8rem', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>
                          {job.region}
                        </span>
                      </td>
                      <td>
                        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                          {job.runtime_minutes}m • {job.power_kw} kW
                        </div>
                      </td>
                      <td>
                        <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#10b981', fontFamily: 'var(--font-mono)' }}>
                          {job.carbon_budget_kg ? `${job.carbon_budget_kg} kg` : 'Uncapped'}
                        </span>
                      </td>
                      <td>
                        <button
                          className="btn btn-secondary btn-sm"
                          style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem' }}
                          onClick={() => navigate(`/workloads/${job.job_id}`)}
                        >
                          Inspect
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassCard>

        {/* Right: Regional Grid Intensity */}
        <GlassCard
          title="Regional Grid Intensity"
          subtitle="Live gCO₂/kWh from Regional Ingest Layer"
          actions={
            <button className="btn btn-secondary btn-sm" onClick={() => navigate('/regions')}>
              <span>All Regions</span>
              <ArrowUpRight size={13} />
            </button>
          }
        >
          {isLoading ? (
            <LoadingSkeleton rows={4} />
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
              {regions.map((r) => {
                const carbonVal = regionCarbon[r.region_id] ?? 380;
                const isGreen = carbonVal < 200;
                const isModerate = carbonVal >= 200 && carbonVal < 450;
                const intensityColor = isGreen ? '#10b981' : isModerate ? '#f59e0b' : '#ef4444';

                return (
                  <div
                    key={r.region_id}
                    style={{
                      background: 'var(--bg-surface-elevated)',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 'var(--radius-sm)',
                      padding: '0.75rem 0.85rem',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '0.4rem',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                        <span style={{ fontWeight: 600, fontSize: '0.82rem' }}>{r.region_name}</span>
                        <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>({r.region_id})</span>
                      </div>
                      <span
                        style={{
                          fontSize: '0.72rem',
                          fontWeight: 700,
                          color: intensityColor,
                          fontFamily: 'var(--font-mono)',
                        }}
                      >
                        {carbonVal} gCO₂/kWh
                      </span>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                      <span>Currency: {r.currency} • Zone: {r.electricity_maps_zone}</span>
                      <span style={{ color: '#10b981' }}>{r.default_plan}</span>
                    </div>

                    {/* Intensity Meter Bar */}
                    <div style={{ width: '100%', height: '4px', background: 'rgba(255,255,255,0.06)', borderRadius: '2px', overflow: 'hidden' }}>
                      <div
                        style={{
                          width: `${Math.min(100, (carbonVal / 700) * 100)}%`,
                          height: '100%',
                          background: intensityColor,
                          borderRadius: '2px',
                        }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </GlassCard>
      </div>
    </div>
  );
};
