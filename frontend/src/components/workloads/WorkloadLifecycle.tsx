import React from 'react';
import { CheckCircle } from 'lucide-react';
import { GlassCard } from '../common/GlassCard';
import { InlineBanner } from '../common/InlineBanner';
import { AuditEvent, WorkloadDetail } from '../../types/api';
import { formatDateTime } from '../../utils/workloadDisplay';

interface WorkloadLifecycleProps {
  job: WorkloadDetail;
  auditEvents: AuditEvent[];
  timezoneName?: string;
}

const STAGE_LABELS = ['SUBMITTED', 'VALIDATED', 'SCHEDULED', 'PENDING APPROVAL', 'APPROVED', 'QUEUED', 'RUNNING', 'COMPLETED'];

const TERMINAL_PROBLEM_STATUSES = ['DECLINED', 'REJECTED', 'FAILED', 'CANCELLED'];

function eventTimestamp(events: AuditEvent[], types: string[]): string | undefined {
  return events.find((e) => types.includes(e.event_type))?.timestamp;
}

// Derives how far the workload has genuinely progressed using only real
// signals already on the record (status, presence of a schedule decision,
// real Kubernetes timestamps) — never a guessed or fabricated timestamp.
function currentStageIndex(job: WorkloadDetail): number {
  const status = job.status;
  if (status === 'COMPLETED' || job.kubernetes?.actual_end) return 7;
  if (status === 'RUNNING' || job.kubernetes?.actual_start) return 6;
  if (['DISPATCHING', 'QUEUED', 'CLAIMING', 'READY'].includes(status)) return 5;
  if (status === 'APPROVED') return 4;
  if (status === 'PENDING_APPROVAL' || status === 'DECLINED' || status === 'REJECTED') return 3;
  if (job.schedule_decision) return 2;
  if (status === 'VALIDATED') return 1;
  if (status === 'FAILED' || status === 'CANCELLED') {
    if (job.kubernetes?.actual_start) return 6;
    if (job.schedule_decision) return 2;
    return 0;
  }
  return 0;
}

export const WorkloadLifecycle: React.FC<WorkloadLifecycleProps> = ({ job, auditEvents, timezoneName }) => {
  const currentIdx = currentStageIndex(job);
  const isTerminalProblem = TERMINAL_PROBLEM_STATUSES.includes(job.status);

  const stageTimestamps = [
    eventTimestamp(auditEvents, ['JOB_SUBMITTED']) || job.submitted_at,
    eventTimestamp(auditEvents, ['JOB_VALIDATED']),
    eventTimestamp(auditEvents, ['JOB_SCHEDULED', 'SCHEDULE_PROPOSED']),
    undefined, // PENDING_APPROVAL has no distinct event of its own
    eventTimestamp(auditEvents, ['APPROVAL_GRANTED']),
    undefined, // QUEUED
    eventTimestamp(auditEvents, ['DISPATCH_STARTED', 'K8S_JOB_STARTED']) || job.kubernetes?.actual_start || undefined,
    eventTimestamp(auditEvents, ['K8S_JOB_COMPLETED']) || job.kubernetes?.actual_end || undefined,
  ];

  return (
    <GlassCard title="Workload Lifecycle">
      {isTerminalProblem && (
        <div style={{ marginBottom: '1rem' }}>
          <InlineBanner variant={job.status === 'CANCELLED' ? 'warning' : 'error'}>
            This workload is {job.status.replace('_', ' ')} and will not proceed further.
          </InlineBanner>
        </div>
      )}
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          position: 'relative',
          overflowX: 'auto',
          padding: '0.75rem 1.5rem 0',
          gap: '0.5rem',
        }}
      >
        <div style={{ position: 'absolute', top: '18px', left: '3rem', right: '3rem', height: '3px', background: 'var(--border-subtle)', zIndex: 1 }} />

        {STAGE_LABELS.map((label, idx) => {
          const isDone = idx < currentIdx || (idx === currentIdx && !isTerminalProblem);
          const isCurrent = idx === currentIdx;
          const markerColor = isTerminalProblem && isCurrent ? '#ef4444' : isDone ? '#10b981' : isCurrent ? '#38bdf8' : 'var(--bg-surface-elevated)';

          return (
            <div key={label} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', zIndex: 2, position: 'relative', minWidth: '80px' }}>
              <div
                style={{
                  width: '36px',
                  height: '36px',
                  borderRadius: 'var(--radius-full)',
                  background: markerColor,
                  border: isCurrent ? `2px solid ${markerColor}` : '2px solid var(--border-default)',
                  color: isDone || isCurrent ? '#080c14' : 'var(--text-muted)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontWeight: 700,
                  fontSize: '0.8rem',
                  marginBottom: '0.5rem',
                }}
              >
                {isDone && !isTerminalProblem ? <CheckCircle size={16} /> : idx + 1}
              </div>
              <span style={{ fontSize: '0.72rem', fontWeight: 600, color: isDone || isCurrent ? 'var(--text-primary)' : 'var(--text-muted)', textAlign: 'center' }}>
                {label}
              </span>
              {stageTimestamps[idx] && (
                <span style={{ fontSize: '0.63rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                  {formatDateTime(stageTimestamps[idx], timezoneName)}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </GlassCard>
  );
};
