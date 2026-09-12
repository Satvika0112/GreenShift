import React from 'react';
import { Zap, Leaf, ArrowRight } from 'lucide-react';
import { GlassCard } from '../common/GlassCard';
import { formatCost } from '../../utils/workloadDisplay';

interface ImmediateVsGreenShiftProps {
  decision: any;
}

function formatKg(n?: number | null): string {
  if (n === undefined || n === null) return '—';
  return `${n.toFixed(3)} kg`;
}

/**
 * The signature "Immediate Execution vs GreenShift" comparison. Only renders
 * when the backend actually returned baseline figures to compare against —
 * this is never independently computed in the frontend.
 */
export const ImmediateVsGreenShift: React.FC<ImmediateVsGreenShiftProps> = ({ decision }) => {
  if (!decision) return null;

  const hasCarbonBaseline = decision.baseline_carbon_emission !== undefined && decision.baseline_carbon_emission !== null;
  const hasCostBaseline =
    (decision.baseline_cost !== undefined && decision.baseline_cost !== null) ||
    (decision.baseline_native_cost !== undefined && decision.baseline_native_cost !== null);

  // Nothing to compare against — don't fabricate a baseline.
  if (!hasCarbonBaseline && !hasCostBaseline) return null;

  // Execution region native currency is the single source of truth for what
  // the user sees (Currency Consistency Hardening) — prefer native_cost/
  // baseline_native_cost + currency, same precedence as utils/workloadDisplay
  // .formatCost, falling back to the USD-normalized figure only when no
  // native figure is available.
  const optimizedCostDisplay = formatCost({
    native_cost: decision.native_cost,
    currency: decision.currency,
    electricity_cost: decision.electricity_cost,
  });
  const baselineCostDisplay = formatCost({
    native_cost: decision.baseline_native_cost,
    currency: decision.currency,
    electricity_cost: decision.baseline_cost,
  });

  return (
    <GlassCard
      title={
        <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span>Immediate Execution</span>
          <ArrowRight size={14} color="var(--text-muted)" />
          <span style={{ color: '#10b981' }}>GreenShift</span>
        </span>
      }
      subtitle="Estimated impact of running now vs. the recommended carbon-optimal window"
    >
      <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: '1rem', alignItems: 'center' }}>
        {/* Immediate Execution column */}
        <div
          style={{
            background: 'rgba(239, 68, 68, 0.06)',
            border: '1px solid rgba(239, 68, 68, 0.2)',
            borderRadius: 'var(--radius-md)',
            padding: '1.1rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.72rem', color: '#f87171', fontWeight: 700, marginBottom: '0.75rem' }}>
            <Zap size={13} />
            <span>IMMEDIATE EXECUTION</span>
          </div>
          {hasCarbonBaseline && (
            <div style={{ marginBottom: '0.75rem' }}>
              <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>Carbon Emissions</div>
              <div style={{ fontSize: '1.2rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                {formatKg(decision.baseline_carbon_emission)}
              </div>
            </div>
          )}
          {hasCostBaseline && (
            <div>
              <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>Electricity Cost</div>
              <div style={{ fontSize: '1.2rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                {baselineCostDisplay}
              </div>
            </div>
          )}
        </div>

        <ArrowRight size={20} color="var(--text-muted)" style={{ justifySelf: 'center' }} />

        {/* GreenShift column */}
        <div
          style={{
            background: 'rgba(16, 185, 129, 0.06)',
            border: '1px solid rgba(16, 185, 129, 0.3)',
            borderRadius: 'var(--radius-md)',
            padding: '1.1rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.72rem', color: '#10b981', fontWeight: 700, marginBottom: '0.75rem' }}>
            <Leaf size={13} />
            <span>GREENSHIFT</span>
          </div>
          {hasCarbonBaseline && (
            <div style={{ marginBottom: '0.75rem' }}>
              <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>Carbon Emissions</div>
              <div style={{ fontSize: '1.2rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: '#10b981' }}>
                {formatKg(decision.carbon_emission)}
              </div>
              {decision.carbon_reduction_pct !== undefined && (
                <div style={{ fontSize: '0.72rem', color: '#10b981', fontWeight: 600 }}>▼ {decision.carbon_reduction_pct.toFixed(1)}%</div>
              )}
            </div>
          )}
          {hasCostBaseline && (
            <div>
              <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>Electricity Cost</div>
              <div style={{ fontSize: '1.2rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: '#10b981' }}>
                {optimizedCostDisplay}
              </div>
              {decision.cost_reduction_pct !== undefined && (
                <div style={{ fontSize: '0.72rem', color: '#10b981', fontWeight: 600 }}>▼ {decision.cost_reduction_pct.toFixed(1)}%</div>
              )}
            </div>
          )}
        </div>
      </div>

      {(decision.scheduling_delay_hours !== undefined || decision.sla_met !== undefined) && (
        <div style={{ display: 'flex', gap: '1.5rem', marginTop: '0.25rem', paddingTop: '0.85rem', borderTop: '1px solid var(--border-subtle)' }}>
          {decision.scheduling_delay_hours !== undefined && (
            <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
              Scheduling delay: <strong style={{ color: 'var(--text-primary)' }}>{decision.scheduling_delay_hours.toFixed(1)}h</strong>
            </div>
          )}
          {decision.sla_met !== undefined && (
            <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
              SLA:{' '}
              <span className={`badge ${decision.sla_met ? 'badge-success' : 'badge-danger'}`} style={{ marginLeft: '0.3rem' }}>
                {decision.sla_met ? 'MET' : 'AT RISK'}
              </span>
            </div>
          )}
        </div>
      )}
    </GlassCard>
  );
};
