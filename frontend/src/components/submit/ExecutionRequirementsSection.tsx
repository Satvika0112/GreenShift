import React from 'react';
import { RotateCcw } from 'lucide-react';
import { GlassCard } from '../common/GlassCard';
import { InlineBanner } from '../common/InlineBanner';
import { FormField } from './FormField';
import { RegionInfo } from '../../types/api';
import { SubmitWorkloadFieldErrors, SubmitWorkloadFormState } from '../../utils/submitWorkloadForm';

interface ExecutionRequirementsSectionProps {
  form: SubmitWorkloadFormState;
  errors: SubmitWorkloadFieldErrors;
  disabled: boolean;
  onChange: <K extends keyof SubmitWorkloadFormState>(key: K, value: SubmitWorkloadFormState[K]) => void;
  regions: RegionInfo[];
  regionsLoading: boolean;
  regionsError: boolean;
  onRetryRegions: () => void;
}

export const ExecutionRequirementsSection: React.FC<ExecutionRequirementsSectionProps> = ({
  form,
  errors,
  disabled,
  onChange,
  regions,
  regionsLoading,
  regionsError,
  onRetryRegions,
}) => {
  const activeRegions = regions.filter((r) => r.is_active);

  return (
    <GlassCard title="Execution Requirements">
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
        <FormField label="Container Image" htmlFor="container-image" required error={errors.containerImage}>
          <input
            id="container-image"
            type="text"
            className="input"
            placeholder="ghcr.io/company/model-training:latest"
            value={form.containerImage}
            onChange={(e) => onChange('containerImage', e.target.value)}
            maxLength={255}
            disabled={disabled}
            aria-invalid={!!errors.containerImage}
            aria-describedby={errors.containerImage ? 'container-image-error' : undefined}
            required
          />
        </FormField>

        <div>
          <label className="form-label" htmlFor="workload-region">
            Region *
          </label>
          <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.1rem', marginBottom: '0.5rem' }}>
            GreenShift optimizes the execution time within this region to minimize carbon emissions and cost.
          </p>

          {regionsError ? (
            <InlineBanner
              variant="error"
              action={
                <button type="button" className="btn btn-secondary btn-sm" onClick={onRetryRegions}>
                  <RotateCcw size={13} />
                  <span>Retry</span>
                </button>
              }
            >
              Unable to load supported regions.
            </InlineBanner>
          ) : (
            <select
              id="workload-region"
              className="select"
              value={form.region}
              onChange={(e) => onChange('region', e.target.value)}
              disabled={disabled || regionsLoading}
              aria-busy={regionsLoading}
              aria-invalid={!!errors.region}
              aria-describedby={errors.region ? 'workload-region-error' : undefined}
            >
              {regionsLoading ? (
                <option value="">Loading regions…</option>
              ) : (
                <>
                  <option value="">Select a region…</option>
                  {activeRegions.map((r) => (
                    <option key={r.region_id} value={r.region_id}>
                      {r.region_name} ({r.region_id}) • {r.country}
                    </option>
                  ))}
                </>
              )}
            </select>
          )}
          {errors.region && (
            <p id="workload-region-error" role="alert" style={{ fontSize: '0.72rem', color: '#ef4444', marginTop: '0.35rem', marginBottom: 0 }}>
              {errors.region}
            </p>
          )}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.25rem' }}>
          <FormField label="Runtime Estimate" htmlFor="runtime-minutes" required error={errors.runtimeMinutes} helper="Expected workload execution duration, in minutes.">
            <input
              id="runtime-minutes"
              type="number"
              min={1}
              max={10080}
              className="input"
              value={form.runtimeMinutes}
              onChange={(e) => onChange('runtimeMinutes', e.target.value)}
              disabled={disabled}
              aria-invalid={!!errors.runtimeMinutes}
              aria-describedby={errors.runtimeMinutes ? 'runtime-minutes-error' : undefined}
              required
            />
          </FormField>

          <FormField label="Average Power Draw" htmlFor="power-kw" required error={errors.powerKw} helper="Estimated average power consumption during execution, in kW.">
            <input
              id="power-kw"
              type="number"
              min={0.1}
              step={0.1}
              className="input"
              value={form.powerKw}
              onChange={(e) => onChange('powerKw', e.target.value)}
              disabled={disabled}
              aria-invalid={!!errors.powerKw}
              aria-describedby={errors.powerKw ? 'power-kw-error' : undefined}
              required
            />
          </FormField>

          <FormField label="CPU Request" htmlFor="cpu-request" required error={errors.cpuRequest}>
            <input
              id="cpu-request"
              type="text"
              className="input"
              placeholder="500m"
              value={form.cpuRequest}
              onChange={(e) => onChange('cpuRequest', e.target.value)}
              disabled={disabled}
              aria-invalid={!!errors.cpuRequest}
              aria-describedby={errors.cpuRequest ? 'cpu-request-error' : undefined}
              required
            />
          </FormField>

          <FormField label="Memory Request" htmlFor="memory-request" required error={errors.memoryRequest}>
            <input
              id="memory-request"
              type="text"
              className="input"
              placeholder="512Mi"
              value={form.memoryRequest}
              onChange={(e) => onChange('memoryRequest', e.target.value)}
              disabled={disabled}
              aria-invalid={!!errors.memoryRequest}
              aria-describedby={errors.memoryRequest ? 'memory-request-error' : undefined}
              required
            />
          </FormField>
        </div>
      </div>
    </GlassCard>
  );
};
