import React from 'react';
import { PendingApprovalItem } from '../../types/api';
import { formatDateTime } from '../../utils/workloadDisplay';
import { estimatedCarbonDisplay, estimatedCostDisplay, carbonBudgetStatus, slaStatus } from '../../utils/approvalDisplay';

interface ApprovalSummaryProps {
  item: PendingApprovalItem;
}

const Row: React.FC<{ label: string; children: React.ReactNode; accent?: string }> = ({ label, children, accent }) => (
  <div>
    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{label}</div>
    <div style={{ fontSize: '0.9rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: accent || 'var(--text-primary)' }}>{children}</div>
  </div>
);

export const ApprovalSummary: React.FC<ApprovalSummaryProps> = ({ item }) => {
  const budget = carbonBudgetStatus(item);
  const sla = slaStatus(item);

  return (
    <div>
      <h4 style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text-muted)', marginBottom: '0.75rem' }}>
        Summary
      </h4>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '1rem' }}>
        <Row label="Recommended Region">{item.region}</Row>
        <Row label="Recommended Start">{formatDateTime(item.selected_start_local)}</Row>
        <Row label="Deadline">{formatDateTime(item.deadline_local)}</Row>
        <Row label="Estimated Carbon" accent="#10b981">{estimatedCarbonDisplay(item)}</Row>
        <Row label="Estimated Cost" accent="#38bdf8">{estimatedCostDisplay(item)}</Row>
        <Row label="Carbon Budget" accent={budget.withinBudget === false ? '#ef4444' : undefined}>{budget.text}</Row>
        <Row label="SLA Status" accent={sla.status === 'DEADLINE_CONFLICT' ? '#ef4444' : undefined}>{sla.label}</Row>
      </div>
    </div>
  );
};
