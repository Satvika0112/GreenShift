import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Search,
  PlusCircle,
  Cpu,
  Send,
  XCircle,
  Eye,
  RefreshCw,
} from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassCard } from '../components/common/GlassCard';
import { StatusBadge } from '../components/common/StatusBadge';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { EmptyState } from '../components/common/EmptyState';
import { InlineBanner } from '../components/common/InlineBanner';
import { workloadsApi, schedulingApi, dispatchApi, sustainabilityApi } from '../api/endpoints';
import { Job } from '../types/api';
import { useAuth } from '../context/AuthContext';

export const WorkloadsPage: React.FC = () => {
  const navigate = useNavigate();
  const { user, isAdmin } = useAuth();

  const [jobs, setJobs] = useState<Job[]>([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('ALL');
  const [regionFilter, setRegionFilter] = useState<string>('ALL');
  const [availableRegions, setAvailableRegions] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [actionMessage, setActionMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const fetchJobs = async () => {
    setIsLoading(true);
    setActionMessage(null);
    try {
      const [resJobs, resRegions] = await Promise.allSettled([
        workloadsApi.getJobs({
          team_id: isAdmin ? undefined : user?.team_id,
          limit: 200,
        }),
        sustainabilityApi.getRegions(),
      ]);

      if (resJobs.status === 'fulfilled') {
        setJobs(resJobs.value || []);
      } else if (resJobs.status === 'rejected') {
        setActionMessage({ type: 'error', text: 'Failed to load workloads from backend.' });
      }
      if (resRegions.status === 'fulfilled') {
        setAvailableRegions((resRegions.value || []).map((r) => r.region_id));
      }
    } catch (err: any) {
      setActionMessage({ type: 'error', text: 'Failed to load workloads from backend.' });
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchJobs();
  }, [user]);

  const handleTriggerSchedule = async (jobId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await schedulingApi.scheduleJob(jobId, true);
      setActionMessage({ type: 'success', text: `Optimal schedule calculated for ${jobId}.` });
      await fetchJobs();
      navigate(`/scheduling?jobId=${jobId}`);
    } catch (err: any) {
      const msg = err.response?.data?.detail || 'Scheduling failed.';
      setActionMessage({ type: 'error', text: msg });
    }
  };

  const handleDispatch = async (jobId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const res = await dispatchApi.dispatchJob(jobId);
      setActionMessage({ type: 'success', text: `Job ${jobId} successfully dispatched to Kubernetes (${res.kubernetes_job_name || 'k8s-runner'}).` });
      await fetchJobs();
    } catch (err: any) {
      const msg = err.response?.data?.detail || 'Dispatch failed.';
      setActionMessage({ type: 'error', text: msg });
    }
  };

  const handleCancel = async (jobId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!window.confirm(`Are you sure you want to cancel workload ${jobId}?`)) return;
    try {
      await workloadsApi.cancelJob(jobId);
      setActionMessage({ type: 'success', text: `Workload ${jobId} has been cancelled.` });
      await fetchJobs();
    } catch (err: any) {
      const msg = err.response?.data?.detail || 'Cancel failed.';
      setActionMessage({ type: 'error', text: msg });
    }
  };

  // Filter workloads
  const filteredJobs = jobs.filter((job) => {
    const term = searchTerm.toLowerCase();
    const matchesSearch =
      job.job_id.toLowerCase().includes(term) ||
      (job.name && job.name.toLowerCase().includes(term)) ||
      (job.container_image && job.container_image.toLowerCase().includes(term)) ||
      (job.job_type && job.job_type.toLowerCase().includes(term));

    const matchesStatus = statusFilter === 'ALL' || job.status === statusFilter;
    const matchesRegion = regionFilter === 'ALL' || job.region === regionFilter;

    return matchesSearch && matchesStatus && matchesRegion;
  });

  const uniqueRegions = Array.from(new Set([...availableRegions, ...jobs.map((j) => j.region)])).filter(Boolean);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      <PageHeader
        title="Workloads Registry"
        subtitle="Manage and monitor batch compute workloads, execution states, and carbon constraints"
        actions={
          <div style={{ display: 'flex', gap: '0.6rem' }}>
            <button className="btn btn-secondary" onClick={fetchJobs} disabled={isLoading}>
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

      {actionMessage && (
        <InlineBanner variant={actionMessage.type === 'success' ? 'success' : 'error'}>
          {actionMessage.text}
        </InlineBanner>
      )}

      {/* Filter & Search Bar */}
      <GlassCard>
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: '1rem',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          {/* Search Box */}
          <div style={{ position: 'relative', flex: 1, minWidth: '240px' }}>
            <Search
              size={16}
              style={{
                position: 'absolute',
                left: '12px',
                top: '50%',
                transform: 'translateY(-50%)',
                color: 'var(--text-muted)',
              }}
            />
            <input
              type="text"
              placeholder="Search by job ID, type, image..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="input"
              style={{ paddingLeft: '2.25rem' }}
            />
          </div>

          {/* Status Filter */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Status:</span>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="select"
              style={{ width: '180px' }}
            >
              <option value="ALL">All Statuses</option>
              <option value="SUBMITTED">SUBMITTED</option>
              <option value="SCHEDULED">SCHEDULED</option>
              <option value="PENDING_APPROVAL">PENDING APPROVAL</option>
              <option value="APPROVED">APPROVED</option>
              <option value="READY">READY</option>
              <option value="RUNNING">RUNNING</option>
              <option value="COMPLETED">COMPLETED</option>
              <option value="FAILED">FAILED</option>
              <option value="CANCELLED">CANCELLED</option>
            </select>
          </div>

          {/* Region Filter */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Region:</span>
            <select
              value={regionFilter}
              onChange={(e) => setRegionFilter(e.target.value)}
              className="select"
              style={{ width: '150px' }}
            >
              <option value="ALL">All Regions</option>
              {uniqueRegions.map((reg) => (
                <option key={reg} value={reg}>
                  {reg}
                </option>
              ))}
            </select>
          </div>
        </div>
      </GlassCard>

      {/* Workloads Table */}
      <GlassCard title={`Workloads (${filteredJobs.length})`}>
        {isLoading ? (
          <LoadingSkeleton rows={6} />
        ) : filteredJobs.length === 0 ? (
          <EmptyState
            title={jobs.length === 0 ? "No Workloads Yet" : "No Workloads Found"}
            description={jobs.length === 0 ? "Your team has not submitted any workloads." : "No workloads match the current search or filters."}
            action={jobs.length === 0 ? {
              label: "Submit Workload",
              onClick: () => navigate('/submit'),
            } : undefined}
          />
        ) : (
          <div className="data-table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Job ID / Type</th>
                  <th>Status</th>
                  <th>Team</th>
                  <th>Compute Requirements</th>
                  <th>Carbon Budget</th>
                  <th>Target Region</th>
                  <th>Submitted</th>
                  <th style={{ textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredJobs.map((job) => (
                  <tr
                    key={job.job_id}
                    onClick={() => navigate(`/workloads/${job.job_id}`)}
                    style={{ cursor: 'pointer' }}
                  >
                    <td>
                      <div>
                        <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                          {job.job_id}
                        </div>
                        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                          {job.job_type || 'BATCH'}{job.priority !== undefined && job.priority !== null ? ` • Priority ${job.priority}` : ''}
                        </div>
                      </div>
                    </td>
                    <td>
                      <StatusBadge status={job.status} size="sm" />
                    </td>
                    <td>
                      <span style={{ fontSize: '0.78rem', color: '#38bdf8', fontFamily: 'var(--font-mono)' }}>
                        {job.team_id}
                      </span>
                    </td>
                    <td>
                      <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                        {job.runtime_minutes}m • {job.power_kw}kW
                      </div>
                      <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                        {job.cpu_request || '—'} CPU • {job.memory_request || '—'}
                      </div>
                    </td>
                    <td>
                      <span
                        style={{
                          fontSize: '0.8rem',
                          fontWeight: 600,
                          color: '#10b981',
                          fontFamily: 'var(--font-mono)',
                        }}
                      >
                        {job.carbon_budget_kg ? `${job.carbon_budget_kg} kg` : 'Uncapped'}
                      </span>
                    </td>
                    <td>
                      <span
                        style={{
                          fontSize: '0.78rem',
                          fontFamily: 'var(--font-mono)',
                          color: 'var(--text-secondary)',
                        }}
                      >
                        {job.region}
                      </span>
                    </td>
                    <td>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        {job.submitted_at ? new Date(job.submitted_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Recent'}
                      </div>
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'flex-end',
                          gap: '0.35rem',
                        }}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <button
                          className="btn btn-secondary btn-sm"
                          style={{ padding: '0.3rem 0.5rem' }}
                          title="View Details"
                          onClick={() => navigate(`/workloads/${job.job_id}`)}
                        >
                          <Eye size={13} />
                        </button>

                        {(job.status === 'SUBMITTED' || job.status === 'VALIDATED') && (
                          <button
                            className="btn btn-outline-emerald btn-sm"
                            style={{ padding: '0.3rem 0.5rem' }}
                            title="Trigger Optimizer"
                            onClick={(e) => handleTriggerSchedule(job.job_id, e)}
                          >
                            <Cpu size={13} />
                          </button>
                        )}

                        {(job.status === 'SCHEDULED' || job.status === 'APPROVED' || job.status === 'READY') && (
                          <button
                            className="btn btn-primary btn-sm"
                            style={{ padding: '0.3rem 0.5rem' }}
                            title="Dispatch to Kubernetes"
                            onClick={(e) => handleDispatch(job.job_id, e)}
                          >
                            <Send size={13} />
                          </button>
                        )}

                        {job.status !== 'COMPLETED' && job.status !== 'CANCELLED' && job.status !== 'FAILED' && (
                          <button
                            className="btn btn-secondary btn-sm"
                            style={{ padding: '0.3rem 0.5rem', color: '#ef4444' }}
                            title="Cancel Job"
                            onClick={(e) => handleCancel(job.job_id, e)}
                          >
                            <XCircle size={13} />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
    </div>
  );
};
