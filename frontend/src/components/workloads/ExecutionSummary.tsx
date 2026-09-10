import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowUpRight, Server } from 'lucide-react';
import { GlassCard } from '../common/GlassCard';
import { EmptyState } from '../common/EmptyState';
import { WorkloadDetail } from '../../types/api';
import { formatDateTime } from '../../utils/workloadDisplay';

interface ExecutionSummaryProps {
  job: WorkloadDetail;
}

const Row: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)' }}>
    <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>{label}</span>
    <span style={{ fontSize: '0.82rem', fontWeight: 600, textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{children}</span>
  </div>
);

function durationDisplay(startIso?: string | null, endIso?: string | null): string {
  if (!startIso || !endIso) return '—';
  const start = new Date(startIso).getTime();
  const end = new Date(endIso).getTime();
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return '—';
  const minutes = Math.round((end - start) / 60000);
  return `${minutes} min`;
}

export const ExecutionSummary: React.FC<ExecutionSummaryProps> = ({ job }) => {
  const navigate = useNavigate();
  const execution = job.kubernetes;
  const canDispatchSoon = ['APPROVED', 'READY', 'QUEUED', 'CLAIMING'].includes(job.status);

  return (
    <GlassCard
      title="Execution"
      actions={
        execution ? (
          <button className="btn btn-secondary btn-sm" onClick={() => navigate('/monitoring')}>
            <span>Monitor Execution</span>
            <ArrowUpRight size={13} />
          </button>
        ) : undefined
      }
    >
      {!execution ? (
        <EmptyState
          title="Not Yet Dispatched"
          description={canDispatchSoon ? 'This workload is approved and ready for Kubernetes dispatch.' : 'This workload must complete scheduling and approval before dispatch.'}
          icon={Server}
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.9rem' }}>
          <Row label="Execution Status">{execution.gs_status || execution.k8s_status || '—'}</Row>
          <Row label="Queue Time">{durationDisplay(execution.planned_start, execution.actual_start)}</Row>
          <Row label="Start Time">{formatDateTime(execution.actual_start)}</Row>
          <Row label="Completion Time">{formatDateTime(execution.actual_end)}</Row>
          <Row label="Actual Runtime">{durationDisplay(execution.actual_start, execution.actual_end)}</Row>
          <Row label="Kubernetes Job">{execution.kubernetes_job_name || '—'}</Row>
          <Row label="Pod">{execution.pod_name || '—'}</Row>
        </div>
      )}
    </GlassCard>
  );
};
