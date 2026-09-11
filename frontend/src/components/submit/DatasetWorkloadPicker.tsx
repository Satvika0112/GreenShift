import React, { useEffect, useMemo, useState } from 'react';
import { RotateCcw, Search } from 'lucide-react';
import { GlassCard } from '../common/GlassCard';
import { InlineBanner } from '../common/InlineBanner';
import { LoadingSkeleton } from '../common/LoadingSkeleton';
import { workloadsApi } from '../../api/endpoints';
import { DatasetWorkloadItem } from '../../types/api';
import { JOB_TYPE_OPTIONS } from '../../utils/submitWorkloadForm';

const jobTypeLabel = (jobType: string): string =>
  JOB_TYPE_OPTIONS.find((o) => o.value === jobType)?.label || jobType || 'Workload';

interface DatasetWorkloadPickerProps {
  selected: DatasetWorkloadItem | null;
  onSelect: (item: DatasetWorkloadItem) => void;
  disabled?: boolean;
}

// Real dataset rows only — sourced live from GET /api/v1/dataset/workloads
// (backed by data/greenshift_workloads_final.csv). No hardcoded options.
export const DatasetWorkloadPicker: React.FC<DatasetWorkloadPickerProps> = ({ selected, onSelect, disabled }) => {
  const [workloads, setWorkloads] = useState<DatasetWorkloadItem[] | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(false);
  const [search, setSearch] = useState('');

  const load = () => {
    setIsLoading(true);
    setError(false);
    workloadsApi
      .getDatasetWorkloads()
      .then((res) => setWorkloads(res.workloads))
      .catch(() => setError(true))
      .finally(() => setIsLoading(false));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filtered = useMemo(() => {
    const list = workloads || [];
    const q = search.trim().toLowerCase();
    if (!q) return list;
    return list.filter(
      (w) =>
        w.job_id.toLowerCase().includes(q) ||
        w.job_type.toLowerCase().includes(q) ||
        w.team.toLowerCase().includes(q) ||
        w.region.toLowerCase().includes(q)
    );
  }, [workloads, search]);

  return (
    <GlassCard title="Select Workload from Dataset">
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
        <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', margin: 0 }}>
          Choose a real row from the GreenShift workload dataset. Its characteristics (type, region, runtime, power,
          timing) prefill the form below — team ownership always comes from your account, never the dataset.
        </p>

        {error ? (
          <InlineBanner
            variant="error"
            action={
              <button type="button" className="btn btn-secondary btn-sm" onClick={load}>
                <RotateCcw size={13} />
                <span>Retry</span>
              </button>
            }
          >
            Unable to load the workload dataset.
          </InlineBanner>
        ) : isLoading ? (
          <LoadingSkeleton rows={3} height={40} />
        ) : (workloads || []).length === 0 ? (
          <InlineBanner variant="warning">No workloads found in the dataset.</InlineBanner>
        ) : (
          <>
            <div style={{ position: 'relative' }}>
              <Search size={14} style={{ position: 'absolute', left: '0.75rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
              <input
                type="text"
                className="input"
                style={{ paddingLeft: '2.1rem' }}
                placeholder="Search by job ID, type, team, or region…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                disabled={disabled}
              />
            </div>

            <select
              className="select"
              aria-label="Select workload"
              value={selected?.job_id || ''}
              onChange={(e) => {
                const item = (workloads || []).find((w) => w.job_id === e.target.value);
                if (item) onSelect(item);
              }}
              disabled={disabled}
              size={Math.min(8, Math.max(4, filtered.length))}
              style={{ height: 'auto' }}
            >
              {!selected && <option value="">Select a dataset workload…</option>}
              {filtered.map((w) => (
                <option key={w.job_id} value={w.job_id}>
                  {jobTypeLabel(w.job_type)} — {w.job_id} — {w.team} ({w.region})
                </option>
              ))}
            </select>

            {selected && (
              <InlineBanner variant="info">
                Selected: {jobTypeLabel(selected.job_type)} — {selected.job_id} · {selected.region} · {selected.runtime_hours}h runtime
              </InlineBanner>
            )}
          </>
        )}
      </div>
    </GlassCard>
  );
};
