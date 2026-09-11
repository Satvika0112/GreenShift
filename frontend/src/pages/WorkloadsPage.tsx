import React, { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Search,
  PlusCircle,
  Eye,
  XCircle,
  RefreshCw,
  Layers,
  Activity,
  CheckCircle2,
  CheckCheck,
  RotateCcw,
} from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassCard } from '../components/common/GlassCard';
import { KPICard } from '../components/common/KPICard';
import { StatusBadge } from '../components/common/StatusBadge';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { EmptyState } from '../components/common/EmptyState';
import { InlineBanner } from '../components/common/InlineBanner';
import { workloadsApi, schedulingApi } from '../api/endpoints';
import { Job, JobStatus } from '../types/api';
import { useAuth } from '../context/AuthContext';
import { useWorkloads } from '../hooks/useWorkloads';
import { useDashboardSummary, useRegions } from '../hooks/useDashboard';
import { resolveRegionTimezone } from '../utils/dateTime';
import {
  formatCarbonKg,
  formatCost,
  formatDateTime,
  formatPriority,
  recommendedStartDisplay,
  deriveApprovalStatus,
  APPROVAL_LABELS,
  ApprovalDisplayStatus,
  contextualActionForStatus,
  workloadDisplayName,
} from '../utils/workloadDisplay';

const STATUS_OPTIONS: JobStatus[] = [
  'SUBMITTED', 'VALIDATED', 'SCHEDULED', 'PENDING_APPROVAL', 'APPROVED', 'READY',
  'QUEUED', 'CLAIMING', 'DISPATCHING', 'RUNNING', 'COMPLETED', 'DECLINED', 'REJECTED', 'FAILED', 'CANCELLED',
];

// Backend-validated priority values (app.shared.models field description:
// "CRITICAL/HIGH/MEDIUM/LOW") — real enum values, not invented ones.
const PRIORITY_OPTIONS = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];

const APPROVAL_OPTIONS: ApprovalDisplayStatus[] = ['PENDING', 'APPROVED', 'DECLINED', 'NOT_REQUIRED'];

type SortKey = 'submitted' | 'deadline' | 'priority' | 'status';

const PRIORITY_RANK: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 };

export const WorkloadsPage: React.FC = () => {
  const navigate = useNavigate();
  const { user, isPlatformAdmin } = useAuth();
  const isCompanyUserRole = user?.role === 'COMPANY_USER';
  const isCompanyAdminRole = user?.role === 'COMPANY_ADMIN';

  const [teamFilter, setTeamFilter] = useState('ALL');
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [priorityFilter, setPriorityFilter] = useState('ALL');
  const [jobTypeFilter, setJobTypeFilter] = useState('ALL');
  const [regionFilter, setRegionFilter] = useState('ALL');
  const [approvalFilter, setApprovalFilter] = useState('ALL');
  const [sortKey, setSortKey] = useState<SortKey>('submitted');
  const [actionMessage, setActionMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [schedulingJobId, setSchedulingJobId] = useState<string | null>(null);

  const summaryQ = useDashboardSummary();
  const workloadsQ = useWorkloads({ teamId: isPlatformAdmin && teamFilter !== 'ALL' ? teamFilter : undefined });
  const jobs = workloadsQ.data || [];
  const regionsQ = useRegions();
  const regions = regionsQ.data || [];

  const handleRefresh = () => {
    summaryQ.refetch();
    workloadsQ.refetch();
  };

  const handleFindSchedule = async (jobId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setSchedulingJobId(jobId);
    setActionMessage(null);
    try {
      await schedulingApi.scheduleJob(jobId, true);
      setActionMessage({ type: 'success', text: `Schedule calculated for ${jobId}.` });
      await workloadsQ.refetch();
    } catch (err: any) {
      setActionMessage({ type: 'error', text: err.response?.data?.detail || 'Scheduling failed.' });
    } finally {
      setSchedulingJobId(null);
    }
  };

  const handleCancel = async (jobId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!window.confirm(`Are you sure you want to cancel workload ${jobId}?`)) return;
    try {
      await workloadsApi.cancelJob(jobId);
      setActionMessage({ type: 'success', text: `Workload ${jobId} has been cancelled.` });
      await workloadsQ.refetch();
    } catch (err: any) {
      setActionMessage({ type: 'error', text: err.response?.data?.detail || 'Cancel failed.' });
    }
  };

  const uniqueJobTypes = useMemo(() => Array.from(new Set(jobs.map((j) => j.job_type).filter(Boolean))) as string[], [jobs]);
  const uniqueRegions = useMemo(() => Array.from(new Set(jobs.map((j) => j.region).filter(Boolean))), [jobs]);
  const uniqueTeams = useMemo(() => Array.from(new Set(jobs.map((j) => j.team_id).filter(Boolean))), [jobs]);

  const filteredJobs = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    let result = jobs.filter((job) => {
      const matchesSearch =
        !term ||
        job.job_id.toLowerCase().includes(term) ||
        (job.name && job.name.toLowerCase().includes(term)) ||
        (job.job_type && job.job_type.toLowerCase().includes(term));
      const matchesStatus = statusFilter === 'ALL' || job.status === statusFilter;
      const matchesPriority = priorityFilter === 'ALL' || (job.priority && String(job.priority).toUpperCase() === priorityFilter);
      const matchesJobType = jobTypeFilter === 'ALL' || job.job_type === jobTypeFilter;
      const matchesRegion = regionFilter === 'ALL' || job.region === regionFilter;
      const matchesApproval = approvalFilter === 'ALL' || deriveApprovalStatus(job) === approvalFilter;
      return matchesSearch && matchesStatus && matchesPriority && matchesJobType && matchesRegion && matchesApproval;
    });

    result = [...result].sort((a, b) => {
      switch (sortKey) {
        case 'deadline':
          return new Date(a.deadline).getTime() - new Date(b.deadline).getTime();
        case 'priority':
          return (PRIORITY_RANK[String(a.priority).toUpperCase()] ?? 99) - (PRIORITY_RANK[String(b.priority).toUpperCase()] ?? 99);
        case 'status':
          return a.status.localeCompare(b.status);
        case 'submitted':
        default:
          return new Date(b.submitted_at).getTime() - new Date(a.submitted_at).getTime();
      }
    });

    return result;
  }, [jobs, searchTerm, statusFilter, priorityFilter, jobTypeFilter, regionFilter, approvalFilter, sortKey]);

  const hasActiveFilters =
    searchTerm !== '' || statusFilter !== 'ALL' || priorityFilter !== 'ALL' || jobTypeFilter !== 'ALL' || regionFilter !== 'ALL' || approvalFilter !== 'ALL';

  const clearFilters = () => {
    setSearchTerm('');
    setStatusFilter('ALL');
    setPriorityFilter('ALL');
    setJobTypeFilter('ALL');
    setRegionFilter('ALL');
    setApprovalFilter('ALL');
  };

  const summary = summaryQ.data;
  const jobCounts = summary?.jobs || {};
  const summaryLoading = summaryQ.isLoading;
  const kpiValue = (n: number | undefined) => (summaryLoading ? '—' : n !== undefined ? n : 'DATA UNAVAILABLE');

  const registryTitle = isCompanyUserRole ? 'My Workloads' : isPlatformAdmin ? 'Platform Workloads' : 'Recent Workloads';
  const emptyDescription = isCompanyUserRole
    ? "You haven't submitted any workloads yet."
    : 'No workloads have been submitted yet.';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      <PageHeader
        title="Workloads"
        subtitle="Monitor, review, and manage workload execution across GreenShift."
        actions={
          <div style={{ display: 'flex', gap: '0.6rem' }}>
            <button className="btn btn-secondary" onClick={handleRefresh} disabled={workloadsQ.isFetching}>
              <RefreshCw size={14} className={workloadsQ.isFetching ? 'animate-spin' : ''} />
              <span>Refresh</span>
            </button>
            <button className="btn btn-primary" onClick={() => navigate('/submit')}>
              <PlusCircle size={15} />
              <span>Submit Workload</span>
            </button>
          </div>
        }
      />

      {actionMessage && (
        <InlineBanner variant={actionMessage.type === 'success' ? 'success' : 'error'}>
          {actionMessage.text}
        </InlineBanner>
      )}

      {/* KPI Strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1rem' }}>
        <KPICard title="Total Workloads" value={kpiValue(summary?.total_jobs)} subtitle="Visible to your account" icon={Layers} color="emerald" />
        <KPICard title="Running" value={kpiValue(jobCounts.RUNNING)} subtitle="Currently executing" icon={Activity} color="cyan" />
        <KPICard title="Pending Approval" value={kpiValue(jobCounts.PENDING_APPROVAL)} subtitle="Awaiting human review" icon={CheckCircle2} color="amber" />
        <KPICard title="Completed" value={kpiValue(jobCounts.COMPLETED)} subtitle="Finished successfully" icon={CheckCheck} color="emerald" />
        <KPICard title="Failed" value={kpiValue(jobCounts.FAILED)} subtitle="Failed or aborted" icon={XCircle} color="rose" />
      </div>
      {(isCompanyUserRole || isCompanyAdminRole) && (
        <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', margin: 0 }}>
          The KPI strip reflects your whole company; the table below reflects your team's own workloads (the backend's current scope for this endpoint).
        </p>
      )}

      {/* Filter & Search Bar */}
      <GlassCard>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.85rem', alignItems: 'center' }}>
          <div style={{ position: 'relative', flex: '1 1 240px', minWidth: '220px' }}>
            <Search size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
            <input
              type="text"
              placeholder="Search workloads by name, ID, or type..."
              aria-label="Search workloads by name, ID, or type"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="input"
              style={{ paddingLeft: '2.25rem' }}
            />
          </div>

          <FilterSelect label="Status" value={statusFilter} onChange={setStatusFilter} options={STATUS_OPTIONS} />
          <FilterSelect label="Priority" value={priorityFilter} onChange={setPriorityFilter} options={PRIORITY_OPTIONS} formatOption={formatPriority} />
          {uniqueJobTypes.length > 0 && (
            <FilterSelect label="Job Type" value={jobTypeFilter} onChange={setJobTypeFilter} options={uniqueJobTypes} />
          )}
          {uniqueRegions.length > 0 && (
            <FilterSelect label="Region" value={regionFilter} onChange={setRegionFilter} options={uniqueRegions} />
          )}
          <FilterSelect
            label="Approval"
            value={approvalFilter}
            onChange={setApprovalFilter}
            options={APPROVAL_OPTIONS}
            formatOption={(v) => APPROVAL_LABELS[v as ApprovalDisplayStatus] || v}
          />
          {isPlatformAdmin && uniqueTeams.length > 0 && (
            <FilterSelect label="Team" value={teamFilter} onChange={setTeamFilter} options={uniqueTeams} />
          )}

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Sort:</span>
            <select value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)} className="select" style={{ width: '150px' }} aria-label="Sort workloads by">
              <option value="submitted">Submitted</option>
              <option value="deadline">Deadline</option>
              <option value="priority">Priority</option>
              <option value="status">Status</option>
            </select>
          </div>

          {hasActiveFilters && (
            <button className="btn btn-secondary btn-sm" onClick={clearFilters}>
              <RotateCcw size={13} />
              <span>Clear Filters</span>
            </button>
          )}
        </div>
      </GlassCard>

      {/* Workloads Table */}
      <GlassCard title={`${registryTitle} (${filteredJobs.length})`}>
        {workloadsQ.isError ? (
          <InlineBanner
            variant="error"
            action={
              <button className="btn btn-secondary btn-sm" onClick={() => workloadsQ.refetch()}>
                <RotateCcw size={13} />
                <span>Retry</span>
              </button>
            }
          >
            We couldn't retrieve the workload registry.
          </InlineBanner>
        ) : workloadsQ.isLoading ? (
          <LoadingSkeleton rows={6} />
        ) : filteredJobs.length === 0 ? (
          <EmptyState
            title={jobs.length === 0 ? 'No workloads yet' : 'No Workloads Found'}
            description={jobs.length === 0 ? emptyDescription : 'No workloads match your filters.'}
            action={
              jobs.length === 0
                ? { label: 'Submit Workload', onClick: () => navigate('/submit') }
                : { label: 'Clear Filters', onClick: clearFilters }
            }
          />
        ) : (
          <div className="data-table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Workload</th>
                  <th>Status</th>
                  <th>Priority</th>
                  <th>Team</th>
                  <th>Region</th>
                  <th>Deadline</th>
                  <th>Recommended Start</th>
                  <th>Carbon</th>
                  <th>Cost</th>
                  <th>Approval</th>
                  <th style={{ textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredJobs.map((job) => (
                  <WorkloadRow
                    key={job.job_id}
                    job={job}
                    timezoneName={resolveRegionTimezone(regions, job.region)}
                    isScheduling={schedulingJobId === job.job_id}
                    onOpen={() => navigate(`/workloads/${job.job_id}`)}
                    onFindSchedule={(e) => handleFindSchedule(job.job_id, e)}
                    onCancel={(e) => handleCancel(job.job_id, e)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
    </div>
  );
};

interface FilterSelectProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
  formatOption?: (v: string) => string;
}

const FilterSelect: React.FC<FilterSelectProps> = ({ label, value, onChange, options, formatOption }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
    <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{label}:</span>
    <select value={value} onChange={(e) => onChange(e.target.value)} className="select" style={{ width: '150px' }} aria-label={`Filter by ${label}`}>
      <option value="ALL">All</option>
      {options.map((opt) => (
        <option key={opt} value={opt}>
          {formatOption ? formatOption(opt) : opt.replace('_', ' ')}
        </option>
      ))}
    </select>
  </div>
);

interface WorkloadRowProps {
  job: Job;
  timezoneName?: string;
  isScheduling: boolean;
  onOpen: () => void;
  onFindSchedule: (e: React.MouseEvent) => void;
  onCancel: (e: React.MouseEvent) => void;
}

const WorkloadRow: React.FC<WorkloadRowProps> = ({ job, timezoneName, isScheduling, onOpen, onFindSchedule, onCancel }) => {
  const approval = deriveApprovalStatus(job);
  const action = contextualActionForStatus(job.status);
  const isCancellable = !['COMPLETED', 'CANCELLED', 'FAILED'].includes(job.status);

  return (
    <tr onClick={onOpen} style={{ cursor: 'pointer' }} data-testid={`workload-row-${job.job_id}`}>
      <td>
        <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{workloadDisplayName(job)}</div>
        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{job.job_id}</div>
      </td>
      <td><StatusBadge status={job.status} size="sm" /></td>
      <td><span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{formatPriority(job.priority)}</span></td>
      <td><span style={{ fontSize: '0.78rem', color: '#38bdf8', fontFamily: 'var(--font-mono)' }}>{job.team_id || '—'}</span></td>
      <td><span style={{ fontSize: '0.78rem', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>{job.region || '—'}</span></td>
      <td><span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>{formatDateTime(job.deadline, timezoneName)}</span></td>
      <td><span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>{recommendedStartDisplay(job, timezoneName)}</span></td>
      <td><span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#10b981', fontFamily: 'var(--font-mono)' }}>{formatCarbonKg(job.carbon_emission, { estimated: true })}</span></td>
      <td><span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#38bdf8', fontFamily: 'var(--font-mono)' }}>{formatCost(job)}</span></td>
      <td><span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>{APPROVAL_LABELS[approval]}</span></td>
      <td style={{ textAlign: 'right' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '0.4rem' }} onClick={(e) => e.stopPropagation()}>
          <button className="btn btn-secondary btn-sm" style={{ padding: '0.3rem 0.5rem' }} title="View Details" aria-label={`View details for ${job.job_id}`} onClick={onOpen}>
            <Eye size={13} />
          </button>

          {action && action.kind === 'find-schedule' && (
            <button className="btn btn-outline-emerald btn-sm" onClick={onFindSchedule} disabled={isScheduling}>
              <span>{isScheduling ? 'Scheduling…' : action.label}</span>
            </button>
          )}
          {action && action.kind !== 'find-schedule' && (
            <button className="btn btn-secondary btn-sm" onClick={(e) => { e.stopPropagation(); onOpen(); }}>
              <span>{action.label}</span>
            </button>
          )}

          {isCancellable && (
            <button className="btn btn-secondary btn-sm" style={{ padding: '0.3rem 0.5rem', color: '#ef4444' }} title="Cancel Job" aria-label={`Cancel ${job.job_id}`} onClick={onCancel}>
              <XCircle size={13} />
            </button>
          )}
        </div>
      </td>
    </tr>
  );
};
