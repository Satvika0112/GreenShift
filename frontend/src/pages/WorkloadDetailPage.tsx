import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Send, XCircle, AlertCircle, RefreshCw } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { StatusBadge } from '../components/common/StatusBadge';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { EmptyState } from '../components/common/EmptyState';
import { InlineBanner } from '../components/common/InlineBanner';
import { schedulingApi, dispatchApi, workloadsApi } from '../api/endpoints';
import { useWorkload } from '../hooks/useWorkloads';
import { workloadDisplayName } from '../utils/workloadDisplay';
import { WorkloadOverview } from '../components/workloads/WorkloadOverview';
import { WorkloadLifecycle } from '../components/workloads/WorkloadLifecycle';
import { ComputeRequirements } from '../components/workloads/ComputeRequirements';
import { SchedulingSummary } from '../components/workloads/SchedulingSummary';
import { ExecutionSummary } from '../components/workloads/ExecutionSummary';
import { ImpactSummary } from '../components/workloads/ImpactSummary';
import { ActivityTimeline } from '../components/workloads/ActivityTimeline';

// Backend's real dispatch-eligible statuses (app/dispatch/dispatcher.py) —
// mirrored here only so the button isn't offered where it would just be
// rejected; the backend remains the actual enforcement point.
const DISPATCH_ELIGIBLE = ['APPROVED', 'SCHEDULED', 'READY', 'CLAIMING', 'QUEUED'];
const CANCEL_BLOCKED = ['COMPLETED', 'FAILED', 'CANCELLED'];

export const WorkloadDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const workloadQ = useWorkload(id);
  const job = workloadQ.data;

  const [actionNotice, setActionNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [isScheduling, setIsScheduling] = useState(false);
  const [isDispatching, setIsDispatching] = useState(false);

  const handleFindSchedule = async () => {
    if (!id) return;
    setIsScheduling(true);
    setActionNotice(null);
    try {
      await schedulingApi.scheduleJob(id, true);
      setActionNotice({ type: 'success', text: `Schedule generated for ${id}.` });
      await workloadQ.refetch();
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
      setActionNotice({ type: 'success', text: `Workload dispatched to Kubernetes (${res.kubernetes_job_name || 'k8s-pod-dispatched'}).` });
      await workloadQ.refetch();
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
      await workloadQ.refetch();
    } catch (err: any) {
      setActionNotice({ type: 'error', text: err.response?.data?.detail || 'Cancel failed.' });
    }
  };

  if (workloadQ.isLoading) {
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

  if (workloadQ.isError || !job) {
    const detail = (workloadQ.error as any)?.response?.data?.detail;
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        <button className="btn btn-secondary btn-sm" onClick={() => navigate('/workloads')}>
          <ArrowLeft size={14} />
          <span>Back to Workloads</span>
        </button>
        <EmptyState
          title="Workload Not Found"
          description={detail || `Workload with ID '${id}' could not be located in the system of record.`}
          icon={AlertCircle}
          action={{ label: 'View Workloads Registry', onClick: () => navigate('/workloads') }}
        />
      </div>
    );
  }

  const canDispatch = DISPATCH_ELIGIBLE.includes(job.status);
  const canCancel = !CANCEL_BLOCKED.includes(job.status);
  const auditEvents = job.audit_events || [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      <div>
        <button className="btn btn-secondary btn-sm" onClick={() => navigate('/workloads')} style={{ marginBottom: '1rem' }}>
          <ArrowLeft size={14} />
          <span>Back to Workloads</span>
        </button>

        <PageHeader
          title={`${workloadDisplayName(job)}${job.name ? ` (${job.job_id})` : ''}`}
          subtitle={`Team: ${job.team_id || '—'} • Region: ${job.region || '—'} • Submitted: ${job.submitted_at ? new Date(job.submitted_at).toLocaleString() : '—'}`}
          badge={<StatusBadge status={job.status} size="md" />}
          actions={
            <div style={{ display: 'flex', gap: '0.6rem' }}>
              <button className="btn btn-secondary" onClick={() => workloadQ.refetch()} title="Refresh">
                <RefreshCw size={14} />
                <span>Refresh</span>
              </button>
              {canDispatch && (
                <button className="btn btn-primary" onClick={handleDispatch} disabled={isDispatching}>
                  <Send size={14} />
                  <span>{isDispatching ? 'Dispatching…' : 'Dispatch'}</span>
                </button>
              )}
              {canCancel && (
                <button className="btn btn-danger" onClick={handleCancel}>
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

      <WorkloadLifecycle job={job} auditEvents={auditEvents} />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '1.5rem' }}>
        <WorkloadOverview job={job} />
        <ComputeRequirements job={job} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '1.5rem' }}>
        <SchedulingSummary
          job={job}
          onFindSchedule={handleFindSchedule}
          isScheduling={isScheduling}
          onViewFullAnalysis={() => navigate(`/scheduling?jobId=${job.job_id}`)}
        />
        <ExecutionSummary job={job} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '1.5rem' }}>
        <ImpactSummary job={job} />
        <ActivityTimeline events={auditEvents} />
      </div>
    </div>
  );
};
