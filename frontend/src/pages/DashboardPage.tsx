import React from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Layers,
  Leaf,
  DollarSign,
  TrendingDown,
  Globe,
  PlusCircle,
  CheckCircle2,
  XCircle,
  ArrowUpRight,
  RefreshCw,
  AlertTriangle,
  Activity,
  ShieldCheck,
} from 'lucide-react';
import { KPICard } from '../components/common/KPICard';
import { GlassCard } from '../components/common/GlassCard';
import { StatusBadge } from '../components/common/StatusBadge';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { EmptyState } from '../components/common/EmptyState';
import { InlineBanner } from '../components/common/InlineBanner';
import { PageHeader } from '../components/layout/PageHeader';
import { JobStatus } from '../types/api';
import { useAuth } from '../context/AuthContext';
import {
  useDashboardSummary,
  useFleetHeadline,
  useRecentWorkloads,
  useRegions,
  useRegionCarbon,
  usePendingApprovalsPreview,
  useSystemHealth,
} from '../hooks/useDashboard';

// Only statuses the backend actually models (app/shared/models.py JobStatus)
// in the order the workload moves through them. CLAIMING/QUEUED/DECLINED/
// REJECTED/CANCELLED are real statuses too but are shown as exceptions, not
// the primary pipeline.
const PIPELINE_STAGES: { status: JobStatus; label: string }[] = [
  { status: 'SUBMITTED', label: 'Submitted' },
  { status: 'VALIDATED', label: 'Validated' },
  { status: 'SCHEDULED', label: 'Scheduled' },
  { status: 'PENDING_APPROVAL', label: 'Pending Approval' },
  { status: 'APPROVED', label: 'Approved' },
  { status: 'READY', label: 'Ready / Queued' },
  { status: 'DISPATCHING', label: 'Dispatching' },
  { status: 'RUNNING', label: 'Running' },
  { status: 'COMPLETED', label: 'Completed' },
];

function carbonColor(val: number | undefined): string {
  if (val === undefined) return 'var(--text-muted)';
  if (val < 200) return '#10b981';
  if (val < 450) return '#f59e0b';
  return '#ef4444';
}

export const DashboardPage: React.FC = () => {
  const navigate = useNavigate();
  const { user, isPlatformAdmin, isAdmin } = useAuth();

  const summaryQ = useDashboardSummary();
  const headlineQ = useFleetHeadline();
  const jobsQ = useRecentWorkloads(10);
  const regionsQ = useRegions();
  const healthQ = useSystemHealth();
  const pendingQ = usePendingApprovalsPreview(user?.team_id, isAdmin);

  const regionIds = (regionsQ.data || []).map((r) => r.region_id);
  const carbonQ = useRegionCarbon(regionIds);

  const summary = summaryQ.data;
  const headline = headlineQ.data;
  const jobs = jobsQ.data || [];
  const regions = regionsQ.data || [];
  const regionCarbon = carbonQ.data || {};
  const pendingApprovals = pendingQ.data || [];

  const isLoading = summaryQ.isLoading || jobsQ.isLoading;

  const jobCounts = summary?.jobs || {};
  const pendingApprovalCount = jobCounts.PENDING_APPROVAL ?? 0;
  const failedCount = jobCounts.FAILED ?? 0;
  const declinedCount = jobCounts.DECLINED ?? 0;
  const activeCount = summary?.active_jobs ?? jobs.filter((j) => j.status === 'RUNNING' || j.status === 'DISPATCHING').length;

  const carbonAvoidedKg = summary?.carbon?.carbon_avoided_kg ?? headline?.total_carbon_avoided_kg;
  const costSavedUsd = summary?.cost?.cost_difference ?? headline?.total_cost_saved_usd;
  const avgReduction = headline?.avg_carbon_reduction_pct;
  const slaCompliance = headline?.sla_compliance_pct;

  const handleRefresh = () => {
    summaryQ.refetch();
    headlineQ.refetch();
    jobsQ.refetch();
    regionsQ.refetch();
    pendingQ.refetch();
  };

  const attentionItems = [
    { key: 'approvals', count: pendingApprovalCount, label: 'Pending Approvals', desc: 'Awaiting human-in-the-loop review', icon: CheckCircle2, color: '#f59e0b', onClick: () => navigate('/approvals') },
    { key: 'failed', count: failedCount, label: 'Execution Failures', desc: 'Jobs that failed during dispatch or run', icon: XCircle, color: '#ef4444', onClick: () => navigate('/workloads?status=FAILED') },
    { key: 'declined', count: declinedCount, label: 'Declined Schedules', desc: 'Recommendations declined by an approver', icon: AlertTriangle, color: '#ef4444', onClick: () => navigate('/approvals') },
  ].filter((i) => i.count > 0);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      {/* Page Header */}
      <PageHeader
        title="Carbon-Aware Operations Command Center"
        subtitle={`Constraint-first, carbon-primary workload orchestration across multi-region Kubernetes clusters. Scope: ${isPlatformAdmin ? 'Global Organization (All Teams)' : `Team: ${user?.team_id}`}`}
        actions={
          <div style={{ display: 'flex', gap: '0.6rem' }}>
            <button className="btn btn-secondary" onClick={handleRefresh} disabled={isLoading}>
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

      {(summaryQ.isError && headlineQ.isError) && (
        <InlineBanner variant="error">Unable to retrieve fleet metrics from backend. Ensure the API service is running.</InlineBanner>
      )}

      {/* Needs Your Attention */}
      {attentionItems.length > 0 && (
        <GlassCard
          title={
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <AlertTriangle size={15} color="#f59e0b" />
              <span>Needs Your Attention</span>
            </span>
          }
        >
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.85rem' }}>
            {attentionItems.map((item) => (
              <div
                key={item.key}
                onClick={item.onClick}
                className="glass-panel-interactive"
                style={{
                  cursor: 'pointer',
                  background: 'var(--bg-surface-elevated)',
                  border: `1px solid ${item.color}33`,
                  borderRadius: 'var(--radius-sm)',
                  padding: '0.85rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.75rem',
                }}
              >
                <item.icon size={20} color={item.color} />
                <div>
                  <div style={{ fontSize: '1.1rem', fontWeight: 800, color: item.color, fontFamily: 'var(--font-mono)' }}>{item.count}</div>
                  <div style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-primary)' }}>{item.label}</div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{item.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </GlassCard>
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
              Carbon-Primary Scheduling Impact
            </div>
            <div style={{ fontSize: '1.15rem', fontWeight: 700, color: '#ffffff', marginTop: '0.1rem' }}>
              {avgReduction !== undefined
                ? <>Fleet achieved <span style={{ color: '#10b981', fontFamily: 'var(--font-mono)' }}>{avgReduction.toFixed(1)}%</span> carbon reduction vs baseline (immediate) dispatch.</>
                : 'No impact data available yet from the backend.'}
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '1.5rem', alignItems: 'center' }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Avoided Emissions</div>
            <div style={{ fontSize: '1.1rem', fontWeight: 700, color: carbonAvoidedKg !== undefined ? '#10b981' : 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              {carbonAvoidedKg !== undefined ? `${carbonAvoidedKg.toFixed(2)} kg CO₂e` : 'DATA UNAVAILABLE'}
            </div>
          </div>
          <div style={{ width: '1px', height: '30px', background: 'var(--border-default)' }} />
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Avoided Cost</div>
            <div style={{ fontSize: '1.1rem', fontWeight: 700, color: costSavedUsd !== undefined ? '#38bdf8' : 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              {costSavedUsd !== undefined ? `$${costSavedUsd.toFixed(2)}` : 'DATA UNAVAILABLE'}
            </div>
          </div>
          <div style={{ width: '1px', height: '30px', background: 'var(--border-default)' }} />
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>SLA Compliance</div>
            <div style={{ fontSize: '1.1rem', fontWeight: 700, color: slaCompliance !== undefined ? '#a78bfa' : 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              {slaCompliance !== undefined ? `${slaCompliance.toFixed(1)}%` : 'DATA UNAVAILABLE'}
            </div>
          </div>
        </div>
      </div>

      {/* KPI Cards Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem' }}>
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
          value={carbonAvoidedKg !== undefined ? `${carbonAvoidedKg.toFixed(1)} kg` : 'DATA UNAVAILABLE'}
          subtitle="Emissions avoided vs immediate-execution baseline"
          icon={TrendingDown}
          color="cyan"
          onClick={() => navigate('/impact')}
        />
        <KPICard
          title="Electricity Cost Saved"
          value={costSavedUsd !== undefined ? `$${costSavedUsd.toFixed(2)}` : 'DATA UNAVAILABLE'}
          subtitle="Time-of-day tariff optimization"
          icon={DollarSign}
          color="indigo"
          onClick={() => navigate('/carbon-cost')}
        />
        <KPICard
          title="Pending Approvals"
          value={pendingApprovalCount}
          subtitle="Human-in-the-loop review required"
          icon={CheckCircle2}
          color={pendingApprovalCount > 0 ? 'amber' : 'emerald'}
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

      {/* Workload Pipeline */}
      <GlassCard
        title="Workload Pipeline"
        subtitle="Live count of workloads at each lifecycle stage (app.shared.models.JobStatus)"
      >
        {isLoading ? (
          <LoadingSkeleton rows={1} height={60} />
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', overflowX: 'auto', gap: '0.4rem', paddingBottom: '0.25rem' }}>
            {PIPELINE_STAGES.map((stage, idx) => {
              const count = jobCounts[stage.status] ?? 0;
              return (
                <React.Fragment key={stage.status}>
                  <div
                    style={{
                      flex: '0 0 auto',
                      minWidth: '108px',
                      background: count > 0 ? 'rgba(16, 185, 129, 0.08)' : 'var(--bg-surface-elevated)',
                      border: `1px solid ${count > 0 ? 'rgba(16, 185, 129, 0.25)' : 'var(--border-subtle)'}`,
                      borderRadius: 'var(--radius-sm)',
                      padding: '0.6rem 0.7rem',
                      textAlign: 'center',
                    }}
                  >
                    <div style={{ fontSize: '1.15rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: count > 0 ? '#10b981' : 'var(--text-muted)' }}>
                      {count}
                    </div>
                    <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)', marginTop: '0.15rem', whiteSpace: 'nowrap' }}>
                      {stage.label}
                    </div>
                  </div>
                  {idx < PIPELINE_STAGES.length - 1 && (
                    <ArrowUpRight size={14} style={{ flexShrink: 0, transform: 'rotate(45deg)', color: 'var(--text-muted)' }} />
                  )}
                </React.Fragment>
              );
            })}
          </div>
        )}
      </GlassCard>

      {/* 2-Column Split: Active Workloads & Regional Carbon Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.7fr 1fr', gap: '1.5rem' }}>
        {/* Left: Active & Recent Workloads */}
        <GlassCard
          title="Recent Workloads"
          subtitle="Real-time execution state from database"
          actions={
            <button className="btn btn-secondary btn-sm" onClick={() => navigate('/workloads')}>
              <span>View All ({jobs.length})</span>
              <ArrowUpRight size={13} />
            </button>
          }
        >
          {isLoading ? (
            <LoadingSkeleton rows={4} />
          ) : jobs.length === 0 ? (
            <EmptyState
              title="No Workloads Yet"
              description="Your team has not submitted any workloads."
              action={{
                label: 'Submit Workload',
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
          title="Grid Intelligence"
          subtitle="Live gCO₂/kWh from Regional Ingest Layer"
          actions={
            <button className="btn btn-secondary btn-sm" onClick={() => navigate('/regions')}>
              <span>All Regions</span>
              <ArrowUpRight size={13} />
            </button>
          }
        >
          {regionsQ.isLoading ? (
            <LoadingSkeleton rows={4} />
          ) : regions.length === 0 ? (
            <div style={{ padding: '1rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.82rem' }}>
              DATA UNAVAILABLE — no regions returned by backend.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
              {regions.map((r) => {
                const carbonVal = regionCarbon[r.region_id];
                const intensityColor = carbonColor(carbonVal);

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
                        {carbonVal !== undefined ? `${carbonVal} gCO₂/kWh` : 'DATA UNAVAILABLE'}
                      </span>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                      <span>Currency: {r.currency} • Zone: {r.electricity_maps_zone}</span>
                      <span style={{ color: '#10b981' }}>{r.default_plan}</span>
                    </div>

                    {/* Intensity Meter Bar */}
                    {carbonVal !== undefined && (
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
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </GlassCard>
      </div>

      {/* Pending Approvals preview */}
      {pendingApprovals.length > 0 && (
        <GlassCard
          title="Pending Approvals"
          subtitle="GreenShift's recommended windows awaiting your sign-off"
          actions={
            <button className="btn btn-secondary btn-sm" onClick={() => navigate('/approvals')}>
              <span>Review All ({pendingApprovals.length})</span>
              <ArrowUpRight size={13} />
            </button>
          }
        >
          <div className="data-table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Job ID</th>
                  <th>Region</th>
                  <th>Carbon Emission</th>
                  <th>Electricity Cost</th>
                  <th>Deadline</th>
                </tr>
              </thead>
              <tbody>
                {pendingApprovals.slice(0, 5).map((a) => (
                  <tr key={a.job_id} style={{ cursor: 'pointer' }} onClick={() => navigate('/approvals')}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{a.job_id}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>{a.region}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: '#10b981' }}>
                      {a.carbon_emission_kg !== undefined ? `${a.carbon_emission_kg.toFixed(3)} kg` : '—'}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: '#38bdf8' }}>
                      {a.electricity_cost_usd !== undefined ? `$${a.electricity_cost_usd.toFixed(2)}` : '—'}
                    </td>
                    <td style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                      {a.deadline_local ? new Date(a.deadline_local).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </GlassCard>
      )}

      {/* Platform health strip — only shown when the backend actually answered */}
      {healthQ.data && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.6rem',
            padding: '0.65rem 1rem',
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-sm)',
            fontSize: '0.78rem',
            color: 'var(--text-muted)',
          }}
        >
          <Activity size={14} color={healthQ.data.status === 'healthy' ? '#10b981' : healthQ.data.status === 'degraded' ? '#f59e0b' : '#ef4444'} />
          <span>Platform status:</span>
          <StatusBadge status={healthQ.data.status.toUpperCase()} size="sm" />
          <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
            <ShieldCheck size={13} />
            {summary?.audit?.event_count !== undefined ? `${summary.audit.event_count} audit events recorded` : 'Audit trail status unavailable'}
          </span>
        </div>
      )}
    </div>
  );
};
