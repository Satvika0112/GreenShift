import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Cpu,
  Send,
  XCircle,
  Clock,
  Terminal,
  ShieldCheck,
  Zap,
  Server,
  Activity,
  CheckCircle,
  Copy,
  Leaf,
  Layers,
  AlertCircle,
  RefreshCw,
  Play,
} from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassCard } from '../components/common/GlassCard';
import { StatusBadge } from '../components/common/StatusBadge';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { EmptyState } from '../components/common/EmptyState';
import { InlineBanner } from '../components/common/InlineBanner';
import { workloadsApi, schedulingApi, dispatchApi } from '../api/endpoints';
import { Job, ScheduleDecision, KubernetesExecution, AuditEvent } from '../types/api';
import { useAuth } from '../context/AuthContext';
import { GreenShiftRecommendation } from '../components/decision/GreenShiftRecommendation';
import { WhyThisWindow } from '../components/decision/WhyThisWindow';
import { ImmediateVsGreenShift } from '../components/decision/ImmediateVsGreenShift';

export const WorkloadDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();

  const [job, setJob] = useState<any | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copiedLog, setCopiedLog] = useState(false);
  const [actionNotice, setActionNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [isScheduling, setIsScheduling] = useState(false);
  const [isDispatching, setIsDispatching] = useState(false);

  const fetchJobData = async () => {
    if (!id) return;
    setIsLoading(true);
    setError(null);
    try {
      const res = await workloadsApi.getJobHistory(id);
      if (res) {
        setJob(res);
        setAuditEvents(res.audit_events || []);
      }
    } catch (err: any) {
      // If history endpoint fails, try getJobById
      try {
        const directJob = await workloadsApi.getJobById(id);
        setJob(directJob);
      } catch (directErr: any) {
        setError(directErr.response?.data?.detail || err.response?.data?.detail || `Workload '${id}' not found in backend.`);
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchJobData();
  }, [id, user]);

  const handleCopyLogs = (logs: string[]) => {
    if (logs && logs.length > 0) {
      navigator.clipboard.writeText(logs.join('\n'));
      setCopiedLog(true);
      setTimeout(() => setCopiedLog(false), 2500);
    }
  };

  const handleTriggerSchedule = async () => {
    if (!id) return;
    setIsScheduling(true);
    setActionNotice(null);
    try {
      await schedulingApi.scheduleJob(id, true);
      setActionNotice({ type: 'success', text: `Carbon-aware schedule successfully generated for ${id}.` });
      await fetchJobData();
    } catch (err: any) {
      setActionNotice({ type: 'error', text: err.response?.data?.detail || 'Failed to trigger schedule calculation.' });
    } finally {
      setIsScheduling(false);
    }
  };

  const handleDispatch = async () => {
    if (!id) return;
    setIsDispatching(true);
    setActionNotice(null);
    try {
      const res = await dispatchApi.dispatchJob(id);
      setActionNotice({
        type: 'success',
        text: `Workload dispatched to Kubernetes (${res.kubernetes_job_name || 'k8s-pod-dispatched'}).`,
      });
      await fetchJobData();
    } catch (err: any) {
      setActionNotice({ type: 'error', text: err.response?.data?.detail || 'Dispatch failed. Verify cluster readiness or approval status.' });
    } finally {
      setIsDispatching(false);
    }
  };

  const handleCancel = async () => {
    if (!id) return;
    if (!window.confirm(`Are you sure you want to cancel workload ${id}?`)) return;
    try {
      await workloadsApi.cancelJob(id);
      setActionNotice({ type: 'success', text: `Workload ${id} cancelled.` });
      await fetchJobData();
    } catch (err: any) {
      setActionNotice({ type: 'error', text: err.response?.data?.detail || 'Cancel failed.' });
    }
  };

  if (isLoading) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        <button className="btn btn-secondary btn-sm" onClick={() => navigate('/workloads')}>
          <ArrowLeft size={14} />
          <span>Back to Workloads</span>
        </button>
        <LoadingSkeleton rows={8} height={50} />
      </div>
    );
  }

  if (error || !job) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        <button className="btn btn-secondary btn-sm" onClick={() => navigate('/workloads')}>
          <ArrowLeft size={14} />
          <span>Back to Workloads</span>
        </button>
        <EmptyState
          title="Workload Not Found"
          description={error || `Workload with ID '${id}' could not be located in the system of record.`}
          icon={AlertCircle}
          action={{
            label: 'View Workloads Registry',
            onClick: () => navigate('/workloads'),
          }}
        />
      </div>
    );
  }

  const decision = job.schedule_decision;
  const execution = job.kubernetes || job.kubernetes_execution;

  // Build live lifecycle timeline stages
  const isSubmitted = !!job.submitted_at;
  const isScheduled = !!decision || ['SCHEDULED', 'AWAITING_APPROVAL', 'APPROVED', 'READY', 'CLAIMING', 'DISPATCHING', 'RUNNING', 'COMPLETED'].includes(job.status);
  const isApproved = ['APPROVED', 'READY', 'CLAIMING', 'DISPATCHING', 'RUNNING', 'COMPLETED'].includes(job.status);
  const isDispatched = ['DISPATCHING', 'RUNNING', 'COMPLETED'].includes(job.status) || !!execution?.actual_start;
  const isCompleted = job.status === 'COMPLETED';

  const lifecycleStages = [
    { label: 'INGESTED', done: isSubmitted, time: job.submitted_at },
    { label: 'SCHEDULED', done: isScheduled, time: decision?.selected_start },
    { label: 'APPROVED', done: isApproved, time: null },
    { label: 'DISPATCHED', done: isDispatched, time: execution?.actual_start || execution?.planned_start },
    { label: 'EXECUTION', done: isCompleted, active: job.status === 'RUNNING', time: execution?.actual_end },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      {/* Back button & Header */}
      <div>
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => navigate('/workloads')}
          style={{ marginBottom: '1rem' }}
        >
          <ArrowLeft size={14} />
          <span>Back to Workloads</span>
        </button>

        <PageHeader
          title={job.name ? `${job.name} (${job.job_id})` : job.job_id}
          subtitle={`Team: ${job.team_id} • Region: ${job.region} • Ingested: ${new Date(job.submitted_at).toLocaleString()}`}
          badge={<StatusBadge status={job.status} size="md" />}
          actions={
            <div style={{ display: 'flex', gap: '0.6rem' }}>
              <button className="btn btn-secondary" onClick={fetchJobData} title="Refresh telemetry">
                <RefreshCw size={14} />
                <span>Refresh</span>
              </button>
              {job.status === 'SUBMITTED' && (
                <button
                  className="btn btn-primary"
                  onClick={handleTriggerSchedule}
                  disabled={isScheduling}
                >
                  <SparklesIcon size={14} />
                  <span>{isScheduling ? 'Calculating...' : 'Schedule Now'}</span>
                </button>
              )}
              {['APPROVED', 'READY', 'SCHEDULED'].includes(job.status) && (
                <button
                  className="btn btn-primary"
                  onClick={handleDispatch}
                  disabled={isDispatching}
                >
                  <Send size={14} />
                  <span>{isDispatching ? 'Dispatching...' : 'Dispatch Pod'}</span>
                </button>
              )}
              {!['COMPLETED', 'FAILED', 'CANCELLED'].includes(job.status) && (
                <button
                  className="btn btn-danger"
                  onClick={handleCancel}
                >
                  <XCircle size={14} />
                  <span>Cancel Job</span>
                </button>
              )}
            </div>
          }
        />
      </div>

      {actionNotice && (
        <InlineBanner variant={actionNotice.type === 'success' ? 'success' : 'error'}>
          {actionNotice.text}
        </InlineBanner>
      )}

      {/* Lifecycle Progress Bar */}
      <GlassCard title="Workload Lifecycle State Machine">
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            position: 'relative',
            marginTop: '0.75rem',
            padding: '0 1.5rem',
          }}
        >
          <div
            style={{
              position: 'absolute',
              top: '18px',
              left: '3rem',
              right: '3rem',
              height: '3px',
              background: 'var(--border-subtle)',
              zIndex: 1,
            }}
          />

          {lifecycleStages.map((stage, idx) => {
            const isStageDone = stage.done;
            const isStageCurrent = stage.active;

            return (
              <div
                key={stage.label}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  zIndex: 2,
                  position: 'relative',
                }}
              >
                <div
                  style={{
                    width: '36px',
                    height: '36px',
                    borderRadius: 'var(--radius-full)',
                    background: isStageDone
                      ? '#10b981'
                      : isStageCurrent
                      ? '#38bdf8'
                      : 'var(--bg-surface-elevated)',
                    border: isStageCurrent ? '2px solid #38bdf8' : '2px solid var(--border-default)',
                    color: isStageDone || isStageCurrent ? '#080c14' : 'var(--text-muted)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontWeight: 700,
                    fontSize: '0.8rem',
                    marginBottom: '0.5rem',
                    boxShadow: isStageCurrent ? '0 0 12px rgba(56, 189, 248, 0.5)' : undefined,
                  }}
                >
                  {isStageDone ? <CheckCircle size={16} /> : idx + 1}
                </div>
                <span
                  style={{
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    color: isStageDone || isStageCurrent ? 'var(--text-primary)' : 'var(--text-muted)',
                    textAlign: 'center',
                  }}
                >
                  {stage.label}
                </span>
                {stage.time && (
                  <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                    {new Date(stage.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </GlassCard>

      {/* Job Specifications */}
      <GlassCard title="Compute & Workload Specification">
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.9rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)' }}>
              <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>Container Image</span>
              <span style={{ fontSize: '0.8rem', fontFamily: 'var(--font-mono)', color: '#38bdf8', maxWidth: '280px', wordBreak: 'break-all', textAlign: 'right' }}>
                {job.container_image}
              </span>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)' }}>
              <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>Target Grid Region</span>
              <span style={{ fontSize: '0.82rem', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                {job.region}
              </span>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)' }}>
              <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>Estimated Runtime</span>
              <span style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                {job.runtime_minutes} minutes ({Math.round((job.runtime_minutes / 60) * 10) / 10}h)
              </span>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)' }}>
              <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>Power Rating</span>
              <span style={{ fontSize: '0.82rem', fontWeight: 600, color: '#f59e0b' }}>
                {job.power_kw} kW {job.energy_kwh ? `(${job.energy_kwh} kWh)` : ''}
              </span>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)' }}>
              <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>Resource Requests</span>
              <span style={{ fontSize: '0.82rem', fontFamily: 'var(--font-mono)' }}>
                {job.cpu_request || '—'} CPU • {job.memory_request || '—'} RAM
              </span>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)' }}>
              <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>Deadline (UTC)</span>
              <span style={{ fontSize: '0.82rem', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>
                {new Date(job.deadline).toLocaleString()}
              </span>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)' }}>
              <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>Carbon Budget Threshold</span>
              <span style={{ fontSize: '0.82rem', fontWeight: 700, color: '#10b981', fontFamily: 'var(--font-mono)' }}>
                {job.carbon_budget_kg ? `${job.carbon_budget_kg} kg CO₂e` : 'Unconstrained'}
              </span>
            </div>
          </div>
        </GlassCard>

        {decision ? (
        <>
          <GreenShiftRecommendation decision={decision} fallbackRegion={job.region} />
          <ImmediateVsGreenShift decision={decision} />
          <WhyThisWindow decision={decision} />
        </>
        ) : (
          <GlassCard title="GreenShift Recommendation" badge={<span className="badge badge-neutral">PENDING</span>}>
            <EmptyState
              title="No Scheduling Decision"
              description="This workload is awaiting automated scheduling or manual optimizer execution."
              icon={Clock}
              action={{
                label: 'Run Carbon Scheduler',
                onClick: handleTriggerSchedule,
              }}
            />
          </GlassCard>
        )}

      {/* Kubernetes Execution & Container Logs */}
      <GlassCard
        title="Kubernetes Pod Telemetry & Logs"
        subtitle={execution ? `Job: ${execution.kubernetes_job_name || '—'} • Pod: ${execution.pod_name || '—'} • Namespace: ${execution.kubernetes_namespace || execution.namespace || '—'}` : 'Execution status'}
        actions={
          execution?.pod_name ? (
            <button className="btn btn-secondary btn-sm" onClick={() => handleCopyLogs([`Pod: ${execution.pod_name}`, `Status: ${execution.k8s_status || execution.gs_status}`, `Planned Start: ${execution.planned_start}`])}>
              <Copy size={13} />
              <span>{copiedLog ? 'Copied!' : 'Copy Telemetry'}</span>
            </button>
          ) : null
        }
      >
        {execution ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '0.75rem', fontSize: '0.8rem' }}>
              <div style={{ background: 'var(--bg-surface-elevated)', padding: '0.75rem', borderRadius: 'var(--radius-sm)' }}>
                <span style={{ color: 'var(--text-muted)' }}>Kubernetes Status: </span>
                <span style={{ fontWeight: 700, color: '#10b981' }}>{execution.k8s_status || execution.gs_status || 'DATA UNAVAILABLE'}</span>
              </div>
              <div style={{ background: 'var(--bg-surface-elevated)', padding: '0.75rem', borderRadius: 'var(--radius-sm)' }}>
                <span style={{ color: 'var(--text-muted)' }}>Planned Start: </span>
                <span style={{ fontFamily: 'var(--font-mono)' }}>{execution.planned_start ? new Date(execution.planned_start).toLocaleTimeString() : 'Immediate'}</span>
              </div>
              <div style={{ background: 'var(--bg-surface-elevated)', padding: '0.75rem', borderRadius: 'var(--radius-sm)' }}>
                <span style={{ color: 'var(--text-muted)' }}>Actual Start: </span>
                <span style={{ fontFamily: 'var(--font-mono)' }}>{execution.actual_start ? new Date(execution.actual_start).toLocaleTimeString() : 'Pending'}</span>
              </div>
            </div>

            <div
              style={{
                background: '#04070e',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                padding: '1rem',
                fontFamily: 'var(--font-mono)',
                fontSize: '0.8rem',
                color: '#34d399',
                lineHeight: 1.6,
                maxHeight: '180px',
                overflowY: 'auto',
              }}
            >
              <div>[k8s-event] Workload assigned to namespace: {execution.kubernetes_namespace || 'DATA UNAVAILABLE'}</div>
              <div>[k8s-event] Pod spec: image={job.container_image}, cpu={job.cpu_request || '—'}, memory={job.memory_request || '—'}</div>
              <div>[k8s-status] Current state: {execution.k8s_status || execution.gs_status || 'DATA UNAVAILABLE'}</div>
              {execution.actual_start && <div>[k8s-telemetry] Pod execution initiated at {new Date(execution.actual_start).toISOString()}</div>}
              {execution.actual_end && <div>[k8s-telemetry] Pod execution concluded at {new Date(execution.actual_end).toISOString()}</div>}
              {execution.error_message && <div style={{ color: '#ef4444' }}>[k8s-error] {execution.error_message}</div>}
            </div>
          </div>
        ) : (
          <EmptyState
            title="Workload Not Yet Dispatched"
            description={['APPROVED', 'READY'].includes(job.status) ? "Workload is approved and ready for dispatch to Kubernetes." : "Workload must complete scheduling and approval before Kubernetes dispatch."}
            icon={Server}
            action={['APPROVED', 'READY'].includes(job.status) ? {
              label: 'Dispatch Workload',
              onClick: handleDispatch,
            } : undefined}
          />
        )}
      </GlassCard>

      {/* SHA-256 Cryptographic Audit Ledger */}
      <GlassCard
        title="Cryptographic Proof & SHA-256 Audit Trail"
        subtitle="Tamper-evident hash-chained provenance recorded for this workload"
        badge={<span className="badge badge-success"><ShieldCheck size={13} /> {auditEvents.length} EVENTS</span>}
      >
        {auditEvents.length > 0 ? (
          <div className="data-table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Seq</th>
                  <th>Event Type</th>
                  <th>Timestamp</th>
                  <th>Previous Hash (SHA-256)</th>
                  <th>Current Block Hash</th>
                </tr>
              </thead>
              <tbody>
                {auditEvents.map((evt: any, i: number) => (
                  <tr key={evt.id || i}>
                    <td>
                      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--text-muted)' }}>
                        #{evt.sequence ?? i + 1}
                      </span>
                    </td>
                    <td>
                      <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{evt.event_type}</span>
                    </td>
                    <td>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        {evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : 'N/A'}
                      </span>
                    </td>
                    <td>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                        {evt.previous_hash ? `${evt.previous_hash.substring(0, 16)}...` : 'GENESIS'}
                      </span>
                    </td>
                    <td>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: '#10b981' }}>
                        {evt.current_hash ? `${evt.current_hash.substring(0, 16)}...` : 'N/A'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div style={{ padding: '1.5rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
            No audit events recorded for this workload yet. Audit entries are appended on submission, scheduling, approval, and dispatch.
          </div>
        )}
      </GlassCard>
    </div>
  );
};

// Simple Sparkles icon helper
function SparklesIcon(props: any) {
  return <Zap {...props} />;
}
