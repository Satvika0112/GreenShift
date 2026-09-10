import React from 'react';
import { HelpCircle } from 'lucide-react';
import { GlassCard } from '../common/GlassCard';

interface WhyThisWindowProps {
  decision: any;
}

/**
 * The scheduler's own explanation for the recommended window — reason text,
 * deterministic rank, candidate counts, and rejection breakdown, rendered
 * exactly as the backend returns them. Nothing here is computed in the frontend.
 */
export const WhyThisWindow: React.FC<WhyThisWindowProps> = ({ decision }) => {
  if (!decision) return null;

  const rank = decision.deterministic_rank ?? decision.deterministic_ranking;
  const rejectionEntries = decision.rejection_summary ? Object.entries(decision.rejection_summary) : [];
  const rejectionReasons: string[] = decision.rejection_reasons || [];

  return (
    <GlassCard
      title={
        <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <HelpCircle size={15} color="#38bdf8" />
          <span>Why This Window?</span>
        </span>
      }
    >
      <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: '1.5rem' }}>
        <div>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: 1.6, margin: 0 }}>
            {decision.reason || 'No explanation was returned by the scheduler for this decision.'}
          </p>

          <div
            style={{
              marginTop: '0.85rem',
              display: 'flex',
              flexWrap: 'wrap',
              gap: '0.5rem',
            }}
          >
            {rank !== undefined && (
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.72rem',
                  color: '#38bdf8',
                  background: 'var(--bg-surface-elevated)',
                  padding: '0.35rem 0.6rem',
                  borderRadius: 'var(--radius-sm)',
                }}
              >
                Deterministic Rank #{rank}
              </span>
            )}
            {decision.candidates_evaluated !== undefined && (
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.72rem',
                  color: 'var(--text-secondary)',
                  background: 'var(--bg-surface-elevated)',
                  padding: '0.35rem 0.6rem',
                  borderRadius: 'var(--radius-sm)',
                }}
              >
                {decision.candidates_evaluated} candidates evaluated
              </span>
            )}
            {decision.feasible_candidates_count !== undefined && (
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.72rem',
                  color: '#10b981',
                  background: 'var(--bg-surface-elevated)',
                  padding: '0.35rem 0.6rem',
                  borderRadius: 'var(--radius-sm)',
                }}
              >
                {decision.feasible_candidates_count} feasible
              </span>
            )}
          </div>
        </div>

        <div>
          <h4 style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '0.5rem' }}>
            Rejected Windows
          </h4>
          {rejectionEntries.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
              {rejectionEntries.map(([reason, count]) => (
                <div
                  key={reason}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '0.45rem 0.65rem',
                    background: 'var(--bg-surface-elevated)',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '0.78rem',
                  }}
                >
                  <span style={{ color: 'var(--text-secondary)' }}>{reason.replace(/_/g, ' ')}</span>
                  <span style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', color: '#ef4444' }}>{String(count)}</span>
                </div>
              ))}
            </div>
          ) : rejectionReasons.length > 0 ? (
            <ul style={{ margin: 0, paddingLeft: '1.1rem', fontSize: '0.78rem', color: 'var(--text-secondary)', lineHeight: 1.7 }}>
              {rejectionReasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          ) : (
            <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', margin: 0 }}>
              All evaluated windows met feasibility constraints — none were rejected.
            </p>
          )}
        </div>
      </div>
    </GlassCard>
  );
};
