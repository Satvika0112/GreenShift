import React from 'react';
import { GlassCard } from '../common/GlassCard';
import { FormField } from './FormField';
import { SubmitWorkloadFieldErrors, SubmitWorkloadFormState } from '../../utils/submitWorkloadForm';
import { formatRegionalDateTime } from '../../utils/dateTime';

interface SchedulingPolicySectionProps {
  form: SubmitWorkloadFormState;
  errors: SubmitWorkloadFieldErrors;
  disabled: boolean;
  onChange: <K extends keyof SubmitWorkloadFormState>(key: K, value: SubmitWorkloadFormState[K]) => void;
  regionTimezone?: string;
  // When set, `form.earliestStart`/`form.deadline` hold the dataset's raw
  // UTC ISO values (not `datetime-local` strings) and are shown read-only —
  // the user must explicitly opt in via `onOverrideDatasetTiming` before
  // editing them, so a dataset-backed timestamp is never silently changed.
  datasetLocked?: boolean;
  datasetJobId?: string;
  datasetSubmitTime?: string;
  onOverrideDatasetTiming?: () => void;
}

export const SchedulingPolicySection: React.FC<SchedulingPolicySectionProps> = ({
  form,
  errors,
  disabled,
  onChange,
  regionTimezone,
  datasetLocked,
  datasetJobId,
  datasetSubmitTime,
  onOverrideDatasetTiming,
}) => (
  <GlassCard title="Scheduling Policy">
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      {datasetLocked ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
              gap: '0.75rem',
              padding: '0.85rem 1rem',
              background: 'var(--bg-surface-elevated)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
            }}
          >
            <DatasetTimeField
              label="Dataset Job ID"
              value={datasetJobId || '—'}
            />
            <DatasetTimeField
              label="Dataset Submit Time"
              value={formatRegionalDateTime(datasetSubmitTime, regionTimezone)}
            />
            <DatasetTimeField
              label="Earliest Start"
              value={formatRegionalDateTime(form.earliestStart, regionTimezone)}
            />
            <DatasetTimeField
              label="SLA Deadline"
              value={formatRegionalDateTime(form.deadline, regionTimezone)}
            />
          </div>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
            Earliest start and deadline come from the selected dataset workload
            {regionTimezone ? ` (shown in ${regionTimezone})` : ''} and are not editable by default.{' '}
            {onOverrideDatasetTiming && (
              <button
                type="button"
                className="btn-link"
                onClick={onOverrideDatasetTiming}
                disabled={disabled}
                style={{ padding: 0, font: 'inherit', color: 'var(--accent)', textDecoration: 'underline', cursor: 'pointer' }}
              >
                Override dataset timing
              </button>
            )}
          </div>
        </div>
      ) : (
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
      )}

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

const DatasetTimeField: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div>
    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{label}</div>
    <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)', marginTop: '0.15rem' }}>{value}</div>
  </div>
);
