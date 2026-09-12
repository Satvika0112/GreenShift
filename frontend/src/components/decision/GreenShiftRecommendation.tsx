import React from 'react';
import { Sparkles, Leaf, DollarSign, Clock, MapPin } from 'lucide-react';
import { GlassCard } from '../common/GlassCard';
import { formatRegionalDateTime, getTimezoneLabel } from '../../utils/dateTime';
import { formatCost } from '../../utils/workloadDisplay';

interface GreenShiftRecommendationProps {
  decision: any;
  fallbackRegion?: string;
  regionName?: string;
  timezoneName?: string;
}

/**
 * The headline "GreenShift Recommendation" card — the backend scheduler's chosen
 * execution window, rendered exactly as returned (no frontend recalculation).
 */
export const GreenShiftRecommendation: React.FC<GreenShiftRecommendationProps> = ({ decision, fallbackRegion, regionName, timezoneName }) => {
  if (!decision) return null;

  const rank = decision.deterministic_rank ?? decision.deterministic_ranking;
  const region = decision.region_id || fallbackRegion || '—';

  return (
    <GlassCard
      title={
        <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Sparkles size={15} color="#10b981" />
          <span>GreenShift Recommendation</span>
        </span>
      }
      subtitle={`Objective: ${decision.scheduler_objective || decision.objective || 'CARBON_FIRST'} (carbon → cost → earliest start)${rank !== undefined ? ` · Rank #${rank}` : ''}`}
      badge={<span className="badge badge-success">OPTIMAL WINDOW</span>}
    >
      {(decision.requested_earliest_start || decision.requested_deadline) && (
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: '0.5rem 1.5rem',
            padding: '0.65rem 0.85rem',
            marginBottom: '1rem',
            background: 'var(--bg-surface-elevated)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-sm)',
          }}
        >
          <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontWeight: 700 }}>Requested Window</div>
          <div style={{ fontSize: '0.82rem', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>
            {decision.requested_earliest_start
              ? formatRegionalDateTime(decision.requested_earliest_start, timezoneName)
              : 'As soon as possible'}
            {' – '}
            {decision.requested_deadline ? formatRegionalDateTime(decision.requested_deadline, timezoneName) : '—'}
          </div>
        </div>
      )}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: '1.25rem',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
            <Clock size={12} />
            <span>Recommended Window</span>
          </div>
          <div style={{ fontSize: '0.95rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: '#38bdf8', marginTop: '0.3rem' }}>
            {formatRegionalDateTime(decision.selected_start, timezoneName)}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            → {formatRegionalDateTime(decision.selected_end, timezoneName)}
          </div>
          {timezoneName && (
            <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: '0.15rem' }}>
              {getTimezoneLabel(decision.selected_start, timezoneName)}
            </div>
          )}
        </div>

        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
            <MapPin size={12} />
            <span>Execution Region</span>
          </div>
          <div style={{ fontSize: '1.1rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: '#ffffff', marginTop: '0.3rem' }}>
            {regionName ? `${regionName} (${region})` : region}
          </div>
          {timezoneName && <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{timezoneName}</div>}
          {decision.carbon_intensity !== undefined && (
            <div style={{ fontSize: '0.75rem', color: '#10b981' }}>{decision.carbon_intensity.toFixed(1)} gCO₂/kWh</div>
          )}
        </div>

        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
            <Leaf size={12} />
            <span>Carbon Emissions</span>
          </div>
          <div style={{ fontSize: '1.25rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: '#10b981', marginTop: '0.3rem' }}>
            {decision.carbon_emission !== undefined ? `${decision.carbon_emission.toFixed(3)} kg` : '—'}
          </div>
          {decision.carbon_reduction_pct !== undefined && (
            <div style={{ fontSize: '0.72rem', color: '#10b981' }}>▼ {decision.carbon_reduction_pct.toFixed(1)}% vs baseline</div>
          )}
        </div>

        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
            <DollarSign size={12} />
            <span>Electricity Cost</span>
          </div>
          <div style={{ fontSize: '1.25rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: '#38bdf8', marginTop: '0.3rem' }}>
            {formatCost(decision)}
          </div>
          {decision.cost_reduction_pct !== undefined && (
            <div style={{ fontSize: '0.72rem', color: '#38bdf8' }}>▼ {decision.cost_reduction_pct.toFixed(1)}% vs baseline</div>
          )}
        </div>

        {decision.scheduling_delay_hours !== undefined && (
          <div>
            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Scheduling Delay</div>
            <div style={{ fontSize: '1.1rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: '#f59e0b', marginTop: '0.3rem' }}>
              {decision.scheduling_delay_hours.toFixed(1)}h
            </div>
          </div>
        )}

        {decision.sla_met !== undefined && (
          <div>
            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>SLA Outcome</div>
            <div style={{ marginTop: '0.35rem' }}>
              <span className={`badge ${decision.sla_met ? 'badge-success' : 'badge-danger'}`}>
                {decision.sla_met ? 'SLA MET' : 'SLA AT RISK'}
              </span>
            </div>
          </div>
        )}
      </div>
    </GlassCard>
  );
};
