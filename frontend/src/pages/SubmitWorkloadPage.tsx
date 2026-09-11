import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { PlusCircle } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { InlineBanner } from '../components/common/InlineBanner';
import { WorkloadInformationSection } from '../components/submit/WorkloadInformationSection';
import { ExecutionRequirementsSection } from '../components/submit/ExecutionRequirementsSection';
import { SchedulingPolicySection } from '../components/submit/SchedulingPolicySection';
import { SustainabilityConstraintsSection } from '../components/submit/SustainabilityConstraintsSection';
import { DatasetWorkloadPicker } from '../components/submit/DatasetWorkloadPicker';
import { WhatHappensNext } from '../components/submit/WhatHappensNext';
import { SubmissionSuccess } from '../components/submit/SubmissionSuccess';
import { workloadsApi } from '../api/endpoints';
import { CreateJobInput, DatasetWorkloadItem, JobSubmitResult } from '../types/api';
import { useAuth } from '../context/AuthContext';
import { useRegions } from '../hooks/useDashboard';
import { toRegionalInputValue } from '../utils/dateTime';
import {
  SubmitWorkloadFormState,
  validateSubmitWorkloadForm,
  mapSubmitWorkloadError,
  SubmitWorkloadErrorSummary,
} from '../utils/submitWorkloadForm';

type WorkloadSource = 'new' | 'dataset';

const INITIAL_FORM: SubmitWorkloadFormState = {
  workloadName: '',
  jobType: '',
  priority: 'MEDIUM',
  containerImage: '',
  region: '',
  runtimeMinutes: '120',
  powerKw: '3.0',
  cpuRequest: '500m',
  memoryRequest: '512Mi',
  earliestStart: '',
  deadline: '',
  deferrable: true,
  carbonBudgetKg: '',
};

export const SubmitWorkloadPage: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const regionsQ = useRegions();
  const regions = regionsQ.data || [];

  const [form, setForm] = useState<SubmitWorkloadFormState>(INITIAL_FORM);
  const [errors, setErrors] = useState<ReturnType<typeof validateSubmitWorkloadForm>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<SubmitWorkloadErrorSummary | null>(null);
  const [result, setResult] = useState<JobSubmitResult | null>(null);

  const [workloadSource, setWorkloadSource] = useState<WorkloadSource>('new');
  const [selectedDataset, setSelectedDataset] = useState<DatasetWorkloadItem | null>(null);
  const [datasetTimingOverridden, setDatasetTimingOverridden] = useState(false);

  const updateField = <K extends keyof SubmitWorkloadFormState>(key: K, value: SubmitWorkloadFormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const selectedRegion = regions.find((r) => r.region_id === form.region);

  const handleWorkloadSourceChange = (source: WorkloadSource) => {
    setWorkloadSource(source);
    setSelectedDataset(null);
    setDatasetTimingOverridden(false);
    if (source === 'new') {
      setForm(INITIAL_FORM);
    }
  };

  // Maps every dataset-sourced field into the same form state the manual
  // form uses. `earliestStart`/`deadline` are set to the dataset's raw UTC
  // ISO strings (not datetime-local strings) — normalize_to_utc passes an
  // already-aware timestamp through unchanged, so this does not
  // double-convert. Team is intentionally never populated here.
  const handleDatasetSelect = (item: DatasetWorkloadItem) => {
    setSelectedDataset(item);
    setDatasetTimingOverridden(false);
    setForm((prev) => ({
      ...prev,
      workloadName: prev.workloadName.trim() ? prev.workloadName : `${item.job_type} — ${item.job_id}`,
      jobType: item.job_type,
      priority: item.priority,
      containerImage: item.container_image,
      region: item.region,
      runtimeMinutes: String(item.runtime_minutes),
      powerKw: String(item.power_kw),
      cpuRequest: item.cpu_request,
      memoryRequest: item.memory_request,
      earliestStart: item.earliest_start_time,
      deadline: item.deadline,
      deferrable: item.deferrable,
      carbonBudgetKg: item.carbon_budget_kg !== null && item.carbon_budget_kg !== undefined ? String(item.carbon_budget_kg) : '',
    }));
  };

  const handleOverrideDatasetTiming = () => {
    const regionTz = selectedDataset ? regions.find((r) => r.region_id === selectedDataset.region)?.timezone : undefined;
    setForm((prev) => ({
      ...prev,
      earliestStart: toRegionalInputValue(prev.earliestStart, regionTz),
      deadline: toRegionalInputValue(prev.deadline, regionTz),
    }));
    setDatasetTimingOverridden(true);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isSubmitting) return; // prevent duplicate submission

    // Team ownership always comes from the authenticated identity — never a
    // form field the user could edit or override.
    const teamId = user?.team_id;
    if (!teamId) {
      setSubmitError({ title: "Couldn't submit workload", messages: ['Your account has no team assigned. Contact your administrator before submitting a workload.'] });
      return;
    }

    const activeRegionIds = regions.filter((r) => r.is_active).map((r) => r.region_id);
    const fieldErrors = validateSubmitWorkloadForm(form, activeRegionIds);
    setErrors(fieldErrors);
    if (Object.keys(fieldErrors).length > 0) {
      setSubmitError({ title: 'Please fix the following', messages: Object.values(fieldErrors) });
      return;
    }

    setIsSubmitting(true);
    setSubmitError(null);

    try {
      const input: CreateJobInput = {
        workload_name: form.workloadName.trim(),
        team_id: teamId,
        region: form.region,
        // Create-new / overridden dataset timing: a raw local wall-clock
        // value the backend normalizes to UTC using the region's timezone
        // (app/shared/timezone.py normalize_to_utc). Unmodified dataset
        // timing: already an aware UTC ISO string, which normalize_to_utc
        // passes through unchanged. Either way, not converted client-side.
        deadline: form.deadline,
        earliest_start_time: form.earliestStart || undefined,
        runtime_minutes: Number(form.runtimeMinutes),
        power_kw: Number(form.powerKw),
        container_image: form.containerImage.trim(),
        cpu_request: form.cpuRequest.trim(),
        memory_request: form.memoryRequest.trim(),
        carbon_budget_kg: form.carbonBudgetKg.trim() ? Number(form.carbonBudgetKg) : undefined,
        priority: form.priority,
        job_type: form.jobType,
        deferrable: form.deferrable,
      };

      // auto_schedule stays false: submission registers the workload only —
      // it never triggers dispatch or bypasses the approval workflow.
      const created = await workloadsApi.createJob(input, false);
      setResult(created);
    } catch (err) {
      setSubmitError(mapSubmitWorkloadError(err));
      // Form values are intentionally preserved on failure (no reset here).
    } finally {
      setIsSubmitting(false);
    }
  };

  if (result) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem', maxWidth: '1000px', margin: '0 auto' }}>
        <PageHeader title="Submit Workload" subtitle="Configure and submit a workload for carbon-aware execution." />
        <SubmissionSuccess
          result={result}
          onViewScheduling={() => navigate(`/scheduling?jobId=${result.job_id}`)}
          onViewWorkload={() => navigate(`/workloads/${result.job_id}`)}
        />
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem', maxWidth: '1000px', margin: '0 auto' }}>
      <PageHeader title="Submit Workload" subtitle="Configure and submit a workload for carbon-aware execution." />

      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }} noValidate>
        {submitError && (
          <InlineBanner variant="error">
            <div>
              <strong>{submitError.title}</strong>
              {submitError.messages.length > 1 ? (
                <ul style={{ margin: '0.4rem 0 0', paddingLeft: '1.1rem' }}>
                  {submitError.messages.map((msg, i) => (
                    <li key={i}>{msg}</li>
                  ))}
                </ul>
              ) : (
                <div style={{ marginTop: '0.2rem' }}>{submitError.messages[0]}</div>
              )}
            </div>
          </InlineBanner>
        )}

        <div className="glass-card" style={{ padding: '1rem 1.25rem' }}>
          <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.6rem', color: 'var(--text-secondary)' }}>Workload Source</div>
          <div role="radiogroup" aria-label="Workload source" style={{ display: 'flex', gap: '0.6rem' }}>
            <button
              type="button"
              role="radio"
              aria-checked={workloadSource === 'new'}
              className={workloadSource === 'new' ? 'btn btn-primary btn-sm' : 'btn btn-secondary btn-sm'}
              onClick={() => handleWorkloadSourceChange('new')}
              disabled={isSubmitting}
            >
              Create New Workload
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={workloadSource === 'dataset'}
              className={workloadSource === 'dataset' ? 'btn btn-primary btn-sm' : 'btn btn-secondary btn-sm'}
              onClick={() => handleWorkloadSourceChange('dataset')}
              disabled={isSubmitting}
            >
              Use Existing Workload Dataset
            </button>
          </div>
        </div>

        {workloadSource === 'dataset' && (
          <DatasetWorkloadPicker selected={selectedDataset} onSelect={handleDatasetSelect} disabled={isSubmitting} />
        )}

        <WorkloadInformationSection form={form} errors={errors} disabled={isSubmitting} onChange={updateField} />

        <ExecutionRequirementsSection
          form={form}
          errors={errors}
          disabled={isSubmitting}
          onChange={updateField}
          regions={regions}
          regionsLoading={regionsQ.isLoading}
          regionsError={regionsQ.isError}
          onRetryRegions={() => regionsQ.refetch()}
        />

        <SchedulingPolicySection
          form={form}
          errors={errors}
          disabled={isSubmitting}
          onChange={updateField}
          regionTimezone={selectedRegion?.timezone}
          datasetLocked={workloadSource === 'dataset' && !!selectedDataset && !datasetTimingOverridden}
          datasetJobId={selectedDataset?.job_id}
          datasetSubmitTime={selectedDataset?.dataset_submit_time}
          onOverrideDatasetTiming={handleOverrideDatasetTiming}
        />

        <SustainabilityConstraintsSection form={form} errors={errors} disabled={isSubmitting} onChange={updateField} />

        <WhatHappensNext />

        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
            <PlusCircle size={16} className={isSubmitting ? 'animate-spin' : ''} />
            <span>{isSubmitting ? 'Submitting Workload…' : 'Submit Workload'}</span>
          </button>
        </div>
      </form>
    </div>
  );
};
