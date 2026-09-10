import React from 'react';
import { Zap } from 'lucide-react';
import { GlassCard } from '../common/GlassCard';
import { FormField } from './FormField';
import { computeEstimatedEnergyKwh, SubmitWorkloadFieldErrors, SubmitWorkloadFormState } from '../../utils/submitWorkloadForm';

interface SustainabilityConstraintsSectionProps {
  form: SubmitWorkloadFormState;
  errors: SubmitWorkloadFieldErrors;
  disabled: boolean;
  onChange: <K extends keyof SubmitWorkloadFormState>(key: K, value: SubmitWorkloadFormState[K]) => void;
}

export const SustainabilityConstraintsSection: React.FC<SustainabilityConstraintsSectionProps> = ({ form, errors, disabled, onChange }) => {
  const energyKwh = computeEstimatedEnergyKwh(form.powerKw, form.runtimeMinutes);

  return (
    <GlassCard title="Sustainability Constraints">
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
        <FormField
          label="Carbon Budget"
          htmlFor="carbon-budget"
          error={errors.carbonBudgetKg}
          helper={form.carbonBudgetKg.trim() ? 'Maximum estimated workload emissions allowed for scheduling.' : 'No carbon budget constraint.'}
        >
          <input
            id="carbon-budget"
            type="number"
            min={0}
            step={0.5}
            className="input"
            placeholder="e.g. 20 kg CO₂e (leave empty for unconstrained)"
            value={form.carbonBudgetKg}
            onChange={(e) => onChange('carbonBudgetKg', e.target.value)}
            disabled={disabled}
            aria-invalid={!!errors.carbonBudgetKg}
            aria-describedby={errors.carbonBudgetKg ? 'carbon-budget-error' : undefined}
          />
        </FormField>

        {/* Energy is a direct physical computation (power x time) and safe to
            show client-side. Carbon/cost are intentionally NOT estimated here
            — they depend on real regional grid data the scheduler looks up
            server-side after submission. */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.75rem',
            padding: '0.85rem 1rem',
            background: 'var(--bg-surface-elevated)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-sm)',
          }}
        >
          <Zap size={18} color="#38bdf8" />
          <div>
            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Estimated Energy</div>
            <div style={{ fontSize: '1rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
              {energyKwh !== null ? `${energyKwh.toFixed(2)} kWh` : '—'}
            </div>
          </div>
        </div>
      </div>
    </GlassCard>
  );
};
