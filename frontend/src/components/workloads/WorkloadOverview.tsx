import React from 'react';
import { GlassCard } from '../common/GlassCard';
import { StatusBadge } from '../common/StatusBadge';
import { WorkloadDetail } from '../../types/api';
import { formatDateTime, formatPriority, workloadDisplayName } from '../../utils/workloadDisplay';

interface WorkloadOverviewProps {
  job: WorkloadDetail;
  timezoneName?: string;
}

const Row: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)' }}>
    <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>{label}</span>
    <span style={{ fontSize: '0.82rem', fontWeight: 600, textAlign: 'right' }}>{children}</span>
  </div>
);

export const WorkloadOverview: React.FC<WorkloadOverviewProps> = ({ job, timezoneName }) => (
  <GlassCard title="Overview">
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.9rem' }}>
      <Row label="Workload">{workloadDisplayName(job)}</Row>
      <Row label="Job ID"><span style={{ fontFamily: 'var(--font-mono)' }}>{job.job_id}</span></Row>
      <Row label="Status"><StatusBadge status={job.status} size="sm" /></Row>
      <Row label="Priority">{formatPriority(job.priority)}</Row>
      <Row label="Team"><span style={{ color: '#38bdf8', fontFamily: 'var(--font-mono)' }}>{job.team_id || '—'}</span></Row>
      <Row label="Job Type">{job.job_type || '—'}</Row>
      <Row label="Submitted At">{formatDateTime(job.submitted_at, timezoneName)}</Row>
      <Row label="Deadline">{formatDateTime(job.deadline, timezoneName)}</Row>
      <Row label="Deferrable">{job.deferrable === undefined ? '—' : job.deferrable ? 'Yes' : 'No'}</Row>
    </div>
  </GlassCard>
);
