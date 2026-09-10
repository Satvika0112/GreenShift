import React from 'react';
import { ApprovalHistoryItem } from '../../types/api';
import { formatDateTime } from '../../utils/workloadDisplay';

interface ApprovalHistoryRowProps {
  item: ApprovalHistoryItem;
}

export const ApprovalHistoryRow: React.FC<ApprovalHistoryRowProps> = ({ item }) => {
  const isApproved = item.decision === 'APPROVED';
  return (
    <tr>
      <td>
        <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{item.workload_name || item.job_id}</div>
        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{item.job_id}</div>
      </td>
      <td>
        <span
          className={`badge ${isApproved ? 'badge-success' : 'badge-danger'}`}
          style={{ display: 'inline-flex', alignItems: 'center', fontSize: '0.72rem' }}
        >
          {item.decision}
        </span>
      </td>
      <td><span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>{item.region || '—'}</span></td>
      <td><span style={{ fontSize: '0.8rem' }}>{item.scheduled_start_utc ? formatDateTime(item.scheduled_start_utc) : '—'}</span></td>
      <td><span style={{ color: '#38bdf8', fontSize: '0.8rem' }}>{item.decided_by || '—'}</span></td>
      <td><span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{formatDateTime(item.decided_at)}</span></td>
      <td><span style={{ fontSize: '0.8rem', color: isApproved ? 'var(--text-secondary)' : '#ef4444' }}>{item.reason || '—'}</span></td>
    </tr>
  );
};
