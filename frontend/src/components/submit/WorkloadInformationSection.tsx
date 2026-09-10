import React from 'react';
import { GlassCard } from '../common/GlassCard';
import { FormField } from './FormField';
import { JOB_TYPE_OPTIONS, PRIORITY_OPTIONS, SubmitWorkloadFieldErrors, SubmitWorkloadFormState } from '../../utils/submitWorkloadForm';

interface WorkloadInformationSectionProps {
  form: SubmitWorkloadFormState;
  errors: SubmitWorkloadFieldErrors;
  disabled: boolean;
  onChange: <K extends keyof SubmitWorkloadFormState>(key: K, value: SubmitWorkloadFormState[K]) => void;
}

export const WorkloadInformationSection: React.FC<WorkloadInformationSectionProps> = ({ form, errors, disabled, onChange }) => (
  <GlassCard title="Workload">
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <FormField label="Workload Name" htmlFor="workload-name" required error={errors.workloadName}>
        <input
          id="workload-name"
          type="text"
          className="input"
          placeholder="e.g. customer-churn-model-training"
          value={form.workloadName}
          onChange={(e) => onChange('workloadName', e.target.value)}
          maxLength={200}
          disabled={disabled}
          aria-invalid={!!errors.workloadName}
          aria-describedby={errors.workloadName ? 'workload-name-error' : undefined}
          required
        />
      </FormField>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.25rem' }}>
        <FormField label="Workload Type" htmlFor="workload-type" required error={errors.jobType}>
          <select
            id="workload-type"
            className="select"
            value={form.jobType}
            onChange={(e) => onChange('jobType', e.target.value)}
            disabled={disabled}
            aria-invalid={!!errors.jobType}
            aria-describedby={errors.jobType ? 'workload-type-error' : undefined}
          >
            <option value="">Select a workload type…</option>
            {JOB_TYPE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </FormField>

        <FormField
          label="Priority"
          htmlFor="workload-priority"
          error={errors.priority}
          helper="Workload urgency for dispatch ordering — not a carbon-optimization setting."
        >
          <select
            id="workload-priority"
            className="select"
            value={form.priority}
            onChange={(e) => onChange('priority', e.target.value)}
            disabled={disabled}
          >
            {PRIORITY_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </FormField>
      </div>
    </div>
  </GlassCard>
);
