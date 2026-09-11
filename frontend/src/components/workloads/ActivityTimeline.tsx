import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowUpRight } from 'lucide-react';
import { GlassCard } from '../common/GlassCard';
import { AuditEvent } from '../../types/api';
import { auditEventLabel, formatDateTime } from '../../utils/workloadDisplay';

interface ActivityTimelineProps {
  events: AuditEvent[];
  timezoneName?: string;
}

export const ActivityTimeline: React.FC<ActivityTimelineProps> = ({ events, timezoneName }) => {
  const navigate = useNavigate();
  const ordered = [...events].sort((a, b) => (a.sequence ?? 0) - (b.sequence ?? 0));

  return (
    <GlassCard
      title="Activity"
      subtitle="Key lifecycle events for this workload"
      actions={
        <button className="btn btn-secondary btn-sm" onClick={() => navigate('/audit')}>
          <span>View Audit Trail</span>
          <ArrowUpRight size={13} />
        </button>
      }
    >
      {ordered.length === 0 ? (
        <div style={{ padding: '1rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
          No lifecycle events recorded yet.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
          {ordered.map((evt, i) => (
            <div
              key={evt.event_id || i}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '0.55rem 0.75rem',
                background: 'var(--bg-surface-elevated)',
                borderRadius: 'var(--radius-sm)',
                fontSize: '0.8rem',
              }}
            >
              <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{auditEventLabel(evt.event_type)}</span>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>{formatDateTime(evt.timestamp, timezoneName)}</span>
            </div>
          ))}
        </div>
      )}
    </GlassCard>
  );
};
