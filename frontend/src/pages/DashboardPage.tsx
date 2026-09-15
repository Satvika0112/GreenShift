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
  Server,
  RotateCcw,
  LucideIcon,
} from 'lucide-react';
import { KPICard } from '../components/common/KPICard';
import { GlassCard } from '../components/common/GlassCard';
import { StatusBadge } from '../components/common/StatusBadge';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { EmptyState } from '../components/common/EmptyState';
import { InlineBanner } from '../components/common/InlineBanner';
import { PageHeader } from '../components/layout/PageHeader';
import { LifecycleStrip } from '../components/dashboard/LifecycleStrip';
import { JobStatus } from '../types/api';
import { useAuth } from '../context/AuthContext';
import { formatCurrency } from '../utils/currency';
import { formatRegionalDateTime } from '../utils/dateTime';
import {
  useDashboardSummary,
  useFleetHeadline,
  useRecentWorkloads,
  useRegions,
  useRegionCarbon,
  usePendingApprovalsPreview,
  useSystemHealth,
  useK8sState,
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

function clusterHealthColor(status: string | undefined): string {
  if (status === 'healthy') return '#10b981';
  if (status === 'degraded') return '#f59e0b';
  if (status) return '#ef4444';
  return 'var(--text-muted)';
}

// Compact inline error + retry, used per-section so one failed query never
// takes down the rest of the Dashboard.
const SectionError: React.FC<{ message: string; onRetry: () => void }> = ({ message, onRetry }) => (
  <InlineBanner
    variant="error"
    action={
      <button className="btn btn-secondary btn-sm" onClick={onRetry}>
        <RotateCcw size={13} />
        <span>Retry</span>
      </button>
    }
  >
    {message}
  </InlineBanner>
);

export const DashboardPage: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useAuth();

  // The authenticated backend role is the ONLY thing that decides which
  // dashboard experience is shown — never a URL param, localStorage, or a
  // frontend selection. `user.role` comes from /auth/me via AuthContext.
  const role = user?.role;
  const isCompanyUser = role === 'COMPANY_USER';
  const isCompanyAdmin = role === 'COMPANY_ADMIN';
  const isPlatformAdmin = role === 'PLATFORM_ADMIN';

  const summaryQ = useDashboardSummary();
  const headlineQ = useFleetHeadline();
  const jobsQ = useRecentWorkloads(10);
  const regionsQ = useRegions();
  const healthQ = useSystemHealth(!isCompanyUser);
  const pendingQ = usePendingApprovalsPreview(user?.team_id, !isCompanyUser, !isCompanyUser);
  const k8sStateQ = useK8sState(isPlatformAdmin);

  const regionIds = (regionsQ.data || []).map((r) => r.region_id);
  const carbonQ = useRegionCarbon(regionIds);

  const summary = summaryQ.data;
  const headline = headlineQ.data;
  const jobs = jobsQ.data || [];
  const regions = regionsQ.data || [];
  const regionCarbon = carbonQ.data || {};
  const pendingApprovals = pendingQ.data || [];
  const k8sState = k8sStateQ.data;

  const jobCounts = summary?.jobs || {};
  const pendingApprovalCount = jobCounts.PENDING_APPROVAL ?? 0;
  const failedCount = jobCounts.FAILED ?? 0;
  const declinedCount = jobCounts.DECLINED ?? 0;
  const activeCount = summary?.active_jobs ?? jobs.filter((j) => j.status === 'RUNNING' || j.status === 'DISPATCHING').length;

  const carbonAvoidedKg = summary?.carbon?.carbon_avoided_kg ?? headline?.total_carbon_avoided_kg;
  const costSavedUsd = summary?.cost?.cost_difference ?? headline?.total_cost_saved_usd;
  const avgReduction = headline?.avg_carbon_reduction_pct;
  const slaCompliance = headline?.sla_compliance_pct;

  // Per-metric loading: a KPI shows a placeholder while its own query is
  // still in flight, never a fabricated zero.
  const summaryLoading = summaryQ.isLoading;
  const carbonCostLoading = summaryQ.isLoading && headlineQ.isLoading;
  const activeDisplay = summaryLoading ? '—' : activeCount;
  const pendingApprovalDisplay = summaryLoading ? '—' : pendingApprovalCount;
  const carbonAvoidedDisplay = carbonAvoidedKg !== undefined ? `${carbonAvoidedKg.toFixed(1)} kg` : carbonCostLoading ? '—' : 'DATA UNAVAILABLE';
  // cost_difference / total_cost_saved_usd are both always USD by model
  // contract (unlike native_cost) — this is a genuine cross-region USD
  // aggregate, labeled explicitly since the fleet now spans multiple
  // native currencies (INR/USD/AUD/SEK) and a bare "$" would be ambiguous.
  const costSavedDisplay = costSavedUsd !== undefined ? `${formatCurrency(costSavedUsd, 'USD')} (USD)` : carbonCostLoading ? '—' : 'DATA UNAVAILABLE';
  const regionsDisplay = regionsQ.isLoading ? '—' : regions.length;
  const k8sReadyDisplay = k8sStateQ.isLoading ? '—' : k8sState ? `${k8sState.ready_nodes}/${k8sState.total_nodes}` : 'DATA UNAVAILABLE';

  const handleRefresh = () => {
    summaryQ.refetch();
    headlineQ.refetch();
    jobsQ.refetch();
    regionsQ.refetch();
    if (!isCompanyUser) {
      pendingQ.refetch();
      healthQ.refetch();
    }
    if (isPlatformAdmin) {
      k8sStateQ.refetch();
    }
  };

  const attentionItems = [
    { key: 'approvals', count: pendingApprovalCount, label: 'Pending Approvals', desc: 'Awaiting human-in-the-loop review', icon: CheckCircle2, color: '#f59e0b', onClick: () => navigate('/approvals') },
    { key: 'failed', count: failedCount, label: 'Execution Failures', desc: 'Jobs that failed during dispatch or run', icon: XCircle, color: '#ef4444', onClick: () => navigate('/workloads?status=FAILED') },
    { key: 'declined', count: declinedCount, label: 'Declined Schedules', desc: 'Recommendations declined by an approver', icon: AlertTriangle, color: '#ef4444', onClick: () => navigate('/approvals') },
  ].filter((i) => i.count > 0);

  // ---- Role-specific header, primary action, and workload-list framing ----
  const headerTitle = isPlatformAdmin ? 'Platform Command Center' : isCompanyAdmin ? 'Company Operations' : 'Workload Operations';
  const headerSubtitle = isPlatformAdmin
    ? 'Platform-wide workload, regional grid, and Kubernetes execution health.'
    : isCompanyAdmin
      ? `Company-wide workload, approval, and impact overview${user?.company_name ? ` for ${user.company_name}` : ''}.`
      : 'Your workloads, scheduling recommendations, and carbon-aware execution status.';

  const primaryAction = isCompanyAdmin
    ? { label: 'Review', icon: CheckCircle2, onClick: () => navigate('/approvals') }
    : isPlatformAdmin
      ? { label: 'Review Regions', icon: Globe, onClick: () => navigate('/regions') }
      : { label: 'Submit Workload', icon: PlusCircle, onClick: () => navigate('/submit') };

  const workloadsCardTitle = isCompanyUser ? 'My Workloads' : isPlatformAdmin ? 'Recent Platform Activity' : 'Recent Workloads';
  const workloadsEmptyDescription = isCompanyUser
    ? "You haven't submitted any workloads yet."
    : isPlatformAdmin
      ? 'No workloads have been submitted across the platform yet.'
      : 'No workloads have been submitted yet.';

  // ---- Role-specific KPI row ----
  type KPIColor = 'emerald' | 'cyan' | 'indigo' | 'amber' | 'rose';
  interface KPIItem {
    key: string;
    title: string;
    value: string | number;
    subtitle: string;
    icon: LucideIcon;
    color: KPIColor;
    onClick: () => void;
  }

  const kpiCards: KPIItem[] = [
    { key: 'active', title: 'Active Workloads', value: activeDisplay, subtitle: `${summary?.total_jobs ?? jobs.length} total registered`, icon: Layers, color: 'emerald', onClick: () => navigate('/workloads') },
    { key: 'carbon', title: 'Carbon Avoided', value: carbonAvoidedDisplay, subtitle: 'Emissions avoided vs immediate-execution baseline', icon: TrendingDown, color: 'cyan', onClick: () => navigate('/impact') },
    { key: 'cost', title: 'Electricity Cost Saved', value: costSavedDisplay, subtitle: 'Time-of-day tariff optimization', icon: DollarSign, color: 'indigo', onClick: () => navigate('/carbon-cost') },
  ];
  if (!isPlatformAdmin) {
    kpiCards.push({ key: 'approvals', title: 'Pending Approvals', value: pendingApprovalDisplay, subtitle: 'Human-in-the-loop review required', icon: CheckCircle2, color: pendingApprovalCount > 0 ? 'amber' : 'emerald', onClick: () => navigate('/approvals') });
  }
  if (!isCompanyUser) {
    kpiCards.push({ key: 'regions', title: 'Connected Regions', value: regionsDisplay, subtitle: 'All active regional grid layers', icon: Globe, color: 'emerald', onClick: () => navigate('/regions') });
  }
  if (isPlatformAdmin) {
    kpiCards.push({ key: 'k8s', title: 'Kubernetes Ready Nodes', value: k8sReadyDisplay, subtitle: 'Cluster nodes ready to receive workloads', icon: Server, color: k8sState?.connected ? 'emerald' : 'rose', onClick: () => navigate('/health') });
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      {/* Page Header */}
      <PageHeader
        title={headerTitle}
        subtitle={headerSubtitle}
        actions={
          <div style={{ display: 'flex', gap: '0.6rem' }}>
            <button className="btn btn-secondary" onClick={handleRefresh} disabled={summaryQ.isFetching}>
              <RefreshCw size={14} className={summaryQ.isFetching ? 'animate-spin' : ''} />
              <span>Refresh</span>
            </button>
            <button className="btn btn-primary" onClick={primaryAction.onClick}>
              <primaryAction.icon size={15} />
              <span>{primaryAction.label}</span>
            </button>
          </div>
        }
      />

      <LifecycleStrip />

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

      {attentionItems.length === 0 && !summaryQ.isLoading && (
        <InlineBanner variant="success">Nothing requires your attention right now.</InlineBanner>
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
                ? <>Carbon-primary scheduling reduced emissions by <span style={{ color: '#10b981', fontFamily: 'var(--font-mono)' }}>{avgReduction.toFixed(1)}%</span> vs. immediate (non-deferred) dispatch.</>
                : headlineQ.isLoading
                  ? 'Loading impact data…'
                  : 'No impact data available yet from the backend.'}
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '1.5rem', alignItems: 'center' }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Avoided Emissions</div>
            <div style={{ fontSize: '1.1rem', fontWeight: 700, color: carbonAvoidedKg !== undefined ? '#10b981' : 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              {carbonAvoidedDisplay}
            </div>
          </div>
          <div style={{ width: '1px', height: '30px', background: 'var(--border-default)' }} />
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Avoided Cost</div>
            <div style={{ fontSize: '1.1rem', fontWeight: 700, color: costSavedUsd !== undefined ? '#38bdf8' : 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              {costSavedDisplay}
            </div>
          </div>
          <div style={{ width: '1px', height: '30px', background: 'var(--border-default)' }} />
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>SLA Compliance</div>
            <div style={{ fontSize: '1.1rem', fontWeight: 700, color: slaCompliance !== undefined ? '#a78bfa' : 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              {slaCompliance !== undefined ? `${slaCompliance.toFixed(1)}%` : headlineQ.isLoading ? '—' : 'DATA UNAVAILABLE'}
            </div>
          </div>
        </div>
      </div>

      {/* KPI Cards Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem' }}>
        {kpiCards.map((card) => (
          <KPICard
            key={card.key}
            title={card.title}
            value={card.value}
            subtitle={card.subtitle}
            icon={card.icon}
            color={card.color}
            onClick={card.onClick}
          />
        ))}
      </div>

      {/* Workload Pipeline */}
      <GlassCard
        title="Workload Pipeline"
        subtitle="Live count of workloads at each lifecycle stage (app.shared.models.JobStatus)"
      >
        {summaryQ.isError ? (
          <SectionError message="Unable to load workload pipeline data." onRetry={() => summaryQ.refetch()} />
        ) : summaryQ.isLoading ? (
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
          title={workloadsCardTitle}
          subtitle="Real-time execution state from database"
          actions={
            <button className="btn btn-secondary btn-sm" onClick={() => navigate('/workloads')}>
              <span>View All ({jobs.length})</span>
              <ArrowUpRight size={13} />
            </button>
          }
        >
          {jobsQ.isError ? (
            <SectionError message="Unable to load workload data." onRetry={() => jobsQ.refetch()} />
          ) : jobsQ.isLoading ? (
            <LoadingSkeleton rows={4} />
          ) : jobs.length === 0 ? (
            <EmptyState
              title="No Workloads Yet"
              description={workloadsEmptyDescription}
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
              <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.6rem', marginBottom: 0 }}>
                Open a workload to see its full GreenShift Recommendation vs. immediate-dispatch comparison.
              </p>
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
          {regionsQ.isError ? (
            <SectionError message="Unable to load regional grid data." onRetry={() => regionsQ.refetch()} />
          ) : regionsQ.isLoading ? (
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

      {/* Kubernetes Cluster Health — Platform Admin only */}
      {isPlatformAdmin && (
        <GlassCard
          title="Kubernetes Cluster Health"
          subtitle="Live node and resource telemetry across the execution cluster"
          actions={
            <button className="btn btn-secondary btn-sm" onClick={() => navigate('/health')}>
              <span>Full Health Report</span>
              <ArrowUpRight size={13} />
            </button>
          }
        >
          {k8sStateQ.isError ? (
            <SectionError message="Unable to load Kubernetes cluster telemetry." onRetry={() => k8sStateQ.refetch()} />
          ) : k8sStateQ.isLoading ? (
            <LoadingSkeleton rows={2} />
          ) : !k8sState ? (
            <div style={{ padding: '1rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.82rem' }}>
              DATA UNAVAILABLE — Kubernetes telemetry was not returned by the backend.
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '1rem' }}>
              <div>
                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Cluster Status</div>
                <div style={{ marginTop: '0.3rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                  <Activity size={14} color={clusterHealthColor(k8sState.cluster_health)} />
                  <StatusBadge status={k8sState.cluster_health.toUpperCase()} size="sm" />
                </div>
              </div>
              <div>
                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Nodes Ready</div>
                <div style={{ fontSize: '1.05rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                  {k8sState.ready_nodes} / {k8sState.total_nodes}
                </div>
              </div>
              <div>
                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>CPU Used / Allocatable</div>
                <div style={{ fontSize: '1.05rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                  {k8sState.used_cpu_cores.toFixed(1)} / {k8sState.allocatable_cpu_cores.toFixed(1)} cores
                </div>
              </div>
              <div>
                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Memory Used / Allocatable</div>
                <div style={{ fontSize: '1.05rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                  {(k8sState.used_memory_mib / 1024).toFixed(1)} / {(k8sState.allocatable_memory_mib / 1024).toFixed(1)} GiB
                </div>
              </div>
              {k8sState.total_gpus > 0 && (
                <div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>GPUs Used / Allocatable</div>
                  <div style={{ fontSize: '1.05rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                    {k8sState.used_gpus} / {k8sState.allocatable_gpus}
                  </div>
                </div>
              )}
            </div>
          )}
        </GlassCard>
      )}

      {/* Pending Approvals preview — Company Admin / Platform Admin only */}
      {!isCompanyUser && pendingApprovals.length > 0 && (
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
                      {a.native_cost !== undefined && a.native_cost !== null && a.currency
                        ? formatCurrency(a.native_cost, a.currency)
                        : a.electricity_cost_usd !== undefined
                        ? formatCurrency(a.electricity_cost_usd, 'USD')
                        : '—'}
                    </td>
                    <td style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                      {formatRegionalDateTime(a.deadline_utc, a.timezone)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </GlassCard>
      )}

      {/* Execution health strip — Company Admin / Platform Admin only, and only
          shown once the backend has actually answered. */}
      {!isCompanyUser && healthQ.data && (
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
          <span>{isPlatformAdmin ? 'Platform status:' : 'Execution health:'}</span>
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
