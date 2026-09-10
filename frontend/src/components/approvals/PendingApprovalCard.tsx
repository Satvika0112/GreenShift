import React from 'react';
import { GlassCard } from '../common/GlassCard';
import { StatusBadge } from '../common/StatusBadge';
import { PendingApprovalItem } from '../../types/api';
import { formatDateTime, formatPriority, recommendedStartDisplay } from '../../utils/workloadDisplay';
import {
  estimatedCarbonDisplay,
  estimatedCostDisplay,
  carbonReductionDisplay,
  carbonBudgetStatus,
  slaStatus,
} from '../../utils/approvalDisplay';
import { ApprovalContext } from './ApprovalContext';

interface PendingApprovalCardProps {
  item: PendingApprovalItem;
  onReview: () => void;
}

export const PendingApprovalCard: React.FC<PendingApprovalCardProps> = ({ item, onReview }) => {
  const reduction = carbonReductionDisplay(item);
  const budget = carbonBudgetStatus(item);
  const sla = slaStatus(item);

  return (
    <GlassCard>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.9rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '0.75rem' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              <h3 style={{ fontSize: '1.05rem', margin: 0 }}>{item.workload_name || item.job_id}</h3>
              <StatusBadge status="PENDING" size="sm" />
            </div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginTop: '0.15rem' }}>
              {item.job_id}
            </div>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '0.35rem' }}>
              {formatPriority(item.priority)} • Team {item.team_id} • {item.region}
            </div>
          </div>

          <button className="btn btn-primary btn-sm" onClick={onReview}>
            Review Schedule
          </button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '0.85rem', fontSize: '0.8rem' }}>
          <Metric label="Deadline" value={formatDateTime(item.deadline_local)} />
          <Metric label="Recommended Start" value={recommendedStartDisplay({ status: item.status, selected_start: item.selected_start_local, actual_start: undefined })} />
          <Metric label="Estimated Carbon" value={estimatedCarbonDisplay(item)} accent="#10b981" />
          <Metric label="Estimated Cost" value={estimatedCostDisplay(item)} accent="#38bdf8" />
          {reduction && <Metric label="vs Immediate Execution" value={reduction} accent="#10b981" />}
          <Metric label="Carbon Budget" value={budget.text} accent={budget.withinBudget === false ? '#ef4444' : undefined} />
          <Metric label="SLA Status" value={sla.label} accent={sla.status === 'DEADLINE_CONFLICT' ? '#ef4444' : undefined} />
        </div>

        <ApprovalContext reason={item.reason} />
      </div>
    </GlassCard>
  );
};

const Metric: React.FC<{ label: string; value: string; accent?: string }> = ({ label, value, accent }) => (
  <div>
    <div style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>{label}</div>
    <div style={{ fontWeight: 600, fontFamily: 'var(--font-mono)', color: accent || 'var(--text-primary)' }}>{value}</div>
  </div>
);
