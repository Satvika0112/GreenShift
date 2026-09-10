import React from 'react';
import { GlassCard } from '../common/GlassCard';
import { FormField } from './FormField';
import { SubmitWorkloadFieldErrors, SubmitWorkloadFormState } from '../../utils/submitWorkloadForm';

interface SchedulingPolicySectionProps {
  form: SubmitWorkloadFormState;
  errors: SubmitWorkloadFieldErrors;
  disabled: boolean;
  onChange: <K extends keyof SubmitWorkloadFormState>(key: K, value: SubmitWorkloadFormState[K]) => void;
  regionTimezone?: string;
}

export const SchedulingPolicySection: React.FC<SchedulingPolicySectionProps> = ({ form, errors, disabled, onChange, regionTimezone }) => (
  <GlassCard title="Scheduling Policy">
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.25rem' }}>
        <FormField
          label="Earliest Start"
          htmlFor="earliest-start"
          error={errors.earliestStart}
          helper="The workload cannot begin before this time. Optional."
        >
          <input
            id="earliest-start"
            type="datetime-local"
            className="input"
            value={form.earliestStart}
            onChange={(e) => onChange('earliestStart', e.target.value)}
            disabled={disabled}
            aria-invalid={!!errors.earliestStart}
            aria-describedby={errors.earliestStart ? 'earliest-start-error' : undefined}
          />
        </FormField>

        <FormField
          label="SLA Deadline"
          htmlFor="sla-deadline"
          required
          error={errors.deadline}
          helper={
            regionTimezone
              ? `GreenShift must complete the workload within this deadline (${regionTimezone}).`
              : 'GreenShift must complete the workload within this deadline.'
          }
        >
          <input
            id="sla-deadline"
            type="datetime-local"
            className="input"
            value={form.deadline}
            onChange={(e) => onChange('deadline', e.target.value)}
            disabled={disabled}
            aria-invalid={!!errors.deadline}
            aria-describedby={errors.deadline ? 'sla-deadline-error' : undefined}
            required
          />
        </FormField>
      </div>

      <FormField label="Scheduling Flexibility" htmlFor="scheduling-flexibility">
        <select
          id="scheduling-flexibility"
          className="select"
          value={form.deferrable ? 'DEFERRABLE' : 'IMMEDIATE'}
          onChange={(e) => onChange('deferrable', e.target.value === 'DEFERRABLE')}
          disabled={disabled}
        >
          <option value="DEFERRABLE">Deferrable — GreenShift may shift execution to reduce carbon and cost</option>
          <option value="IMMEDIATE">Immediate / Non-deferrable — run as soon as possible</option>
        </select>
      </FormField>
    </div>
  </GlassCard>
);
