import React from 'react';
import { ArrowUpRight, Clock } from 'lucide-react';
import { GlassCard } from '../common/GlassCard';
import { EmptyState } from '../common/EmptyState';
import { WorkloadDetail } from '../../types/api';
import { formatCarbonKg, formatCost, formatDateTime, APPROVAL_LABELS, deriveApprovalStatus } from '../../utils/workloadDisplay';

interface SchedulingSummaryProps {
  job: WorkloadDetail;
  onFindSchedule: () => void;
  isScheduling: boolean;
  onViewFullAnalysis: () => void;
  timezoneName?: string;
}

const Row: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)' }}>
    <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>{label}</span>
    <span style={{ fontSize: '0.82rem', fontWeight: 600, textAlign: 'right' }}>{children}</span>
  </div>
);

export const SchedulingSummary: React.FC<SchedulingSummaryProps> = ({ job, onFindSchedule, isScheduling, onViewFullAnalysis, timezoneName }) => {
  const decision = job.schedule_decision;
  const approval = deriveApprovalStatus({ status: job.status, selected_start: decision?.selected_start });

  return (
    <GlassCard
      title="Scheduling Summary"
      actions={
        decision ? (
          <button className="btn btn-secondary btn-sm" onClick={onViewFullAnalysis}>
            <span>View Full Scheduling Analysis</span>
            <ArrowUpRight size={13} />
          </button>
        ) : undefined
      }
    >
      {!decision ? (
        <EmptyState
          title="Not scheduled yet"
          description="This workload is awaiting a scheduling decision from GreenShift."
          icon={Clock}
          action={{ label: isScheduling ? 'Scheduling…' : 'Find Schedule', onClick: onFindSchedule }}
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.9rem' }}>
          <Row label="Recommended Region"><span style={{ fontFamily: 'var(--font-mono)' }}>{decision.region_id || '—'}</span></Row>
          <Row label="Recommended Start">{formatDateTime(decision.selected_start, timezoneName)}</Row>
          <Row label="Estimated Carbon">{formatCarbonKg(decision.carbon_emission, { estimated: true })}</Row>
          <Row label="Estimated Cost">{formatCost(decision)}</Row>
          <Row label="Carbon Budget">{job.carbon_budget_kg ? `${job.carbon_budget_kg} kg CO₂` : 'Unconstrained'}</Row>
          <Row label="Deadline">{formatDateTime(job.deadline, timezoneName)}</Row>
          <Row label="Approval">{APPROVAL_LABELS[approval]}</Row>
        </div>
      )}
    </GlassCard>
  );
};
