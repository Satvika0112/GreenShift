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
                gap: '0.5rem',
              }}
            >
              <div style={{ minWidth: 0 }}>
                <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{auditEventLabel(evt.event_type)}</span>
                {(evt.actor_username || evt.actor_type) && (
                  <span style={{ color: 'var(--text-muted)', fontSize: '0.7rem', marginLeft: '0.5rem' }}>
                    by {evt.actor_username || 'SYSTEM'}{evt.actor_role ? ` (${evt.actor_role})` : ''}
                    {evt.source_service ? ` · ${evt.source_service}` : ''}
                  </span>
                )}
                {evt.reason && (
                  <div style={{ color: '#f59e0b', fontSize: '0.7rem', marginTop: '0.1rem' }}>{evt.reason}</div>
                )}
              </div>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem', flexShrink: 0 }}>{formatDateTime(evt.timestamp, timezoneName)}</span>
            </div>
          ))}
        </div>
      )}
    </GlassCard>
  );
};
