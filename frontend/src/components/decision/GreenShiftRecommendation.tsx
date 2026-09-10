import React from 'react';
import { Sparkles, Leaf, DollarSign, Clock, MapPin } from 'lucide-react';
import { GlassCard } from '../common/GlassCard';

interface GreenShiftRecommendationProps {
  decision: any;
  fallbackRegion?: string;
}

function formatWindow(iso?: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * The headline "GreenShift Recommendation" card — the backend scheduler's chosen
 * execution window, rendered exactly as returned (no frontend recalculation).
 */
export const GreenShiftRecommendation: React.FC<GreenShiftRecommendationProps> = ({ decision, fallbackRegion }) => {
  if (!decision) return null;

  const rank = decision.deterministic_rank ?? decision.deterministic_ranking;
  const region = decision.region_id || fallbackRegion || '—';
  // electricity_cost is always USD-normalized; `currency` describes native_cost's
  // denomination, so it must only be applied when actually falling back to native_cost.
  const usingElectricityCost = decision.electricity_cost !== undefined && decision.electricity_cost !== null;
  const cost = usingElectricityCost ? decision.electricity_cost : decision.native_cost;
  const currency = usingElectricityCost ? 'USD' : decision.currency || '';

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
            {formatWindow(decision.selected_start)}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            → {formatWindow(decision.selected_end)}
          </div>
        </div>

        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
            <MapPin size={12} />
            <span>Region</span>
          </div>
          <div style={{ fontSize: '1.1rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: '#ffffff', marginTop: '0.3rem' }}>
            {region}
          </div>
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
            {cost !== undefined ? `${currency === 'USD' ? '$' : ''}${cost.toFixed(2)}${currency && currency !== 'USD' ? ` ${currency}` : ''}` : '—'}
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
