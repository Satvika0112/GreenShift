import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { brsrApi } from '../../api/endpoints';
import { BrsrMetricValue, BrsrMetricValueUpdate } from '../../types/api';

const QUALITY_COLOR: Record<string, string> = {
  HIGH: '#10b981',
  MEDIUM: '#38bdf8',
  LOW: '#f59e0b',
  MISSING: '#94a3b8',
};

const SOURCE_LABEL: Record<string, string> = {
  GREENSHIFT_DERIVED: 'GreenShift Derived',
  COMPANY_PROVIDED: 'Company Provided',
  CALCULATED: 'Calculated',
  ESTIMATED: 'Estimated',
  EXTERNAL_SOURCE: 'External Source',
  MISSING: 'Missing',
};

function Badge({ text, color }: { text: string; color: string }) {
  return (
    <span
      style={{
        fontSize: '0.62rem', fontWeight: 700, padding: '0.15rem 0.5rem', borderRadius: 'var(--radius-full)',
        color, background: `${color}22`, textTransform: 'uppercase', letterSpacing: '0.02em',
      }}
    >
      {text}
    </span>
  );
}

interface Props {
  reportId: number;
  metrics: BrsrMetricValue[];
  editable: boolean;
  isLoading?: boolean;
}

export const BrsrMetricList: React.FC<Props> = ({ reportId, metrics, editable, isLoading }) => {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [drafts, setDrafts] = useState<Record<string, BrsrMetricValueUpdate>>({});

  const updateMutation = useMutation({
    mutationFn: ({ metricCode, update }: { metricCode: string; update: BrsrMetricValueUpdate }) =>
      brsrApi.updateMetric(reportId, metricCode, update),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['brsrMetrics', reportId] });
      queryClient.invalidateQueries({ queryKey: ['brsrOverview', reportId] });
    },
  });

  if (isLoading) {
    return <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>Loading metrics…</div>;
  }
  if (metrics.length === 0) {
    return <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>No metrics in this section.</div>;
  }

  const toggle = (code: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
      {metrics.map((m) => {
        const isOpen = expanded.has(m.metric_code);
        const canEditThis = editable && m.source_type !== 'GREENSHIFT_DERIVED' && m.source_type !== 'CALCULATED';
        const draft = drafts[m.metric_code] ?? {};
        const isFilled = m.value !== null || !!m.text_value;

        return (
          <div key={m.metric_code} style={{ border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
            <div
              onClick={() => toggle(m.metric_code)}
              style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.7rem 0.9rem', cursor: 'pointer' }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', minWidth: 0 }}>
                {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                    {m.metric_name} {m.required && <span style={{ color: '#ef4444' }}>*</span>}
                  </div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                    {m.principle ? `Principle ${m.principle}` : m.brsr_core_attribute || m.section}
                  </div>
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexShrink: 0 }}>
                <span style={{ fontSize: '0.82rem', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                  {isFilled ? `${m.value ?? m.text_value}${m.unit ? ` ${m.unit}` : ''}` : 'DATA UNAVAILABLE'}
                </span>
                <Badge text={SOURCE_LABEL[m.source_type] || m.source_type} color="#94a3b8" />
                <Badge text={m.quality} color={QUALITY_COLOR[m.quality] || '#94a3b8'} />
              </div>
            </div>

            {isOpen && (
              <div style={{ padding: '0.85rem 0.9rem 1rem', borderTop: '1px solid var(--border-subtle)', display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
                {m.description && <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', margin: 0 }}>{m.description}</p>}
                {m.calculation_method && (
                  <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', margin: 0 }}>
                    <strong>Method:</strong> {m.calculation_method}
                  </p>
                )}
                {m.source_record && (
                  <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', margin: 0 }}>
                    <strong>Source record:</strong> {m.source_record}
                  </p>
                )}
                {m.estimated && (
                  <InlineNote label="Estimation method" value={m.estimation_method} />
                )}
                {m.assumption && <InlineNote label="Assumption" value={m.assumption} />}
                {m.data_gap && <InlineNote label="Data gap" value={m.data_gap} />}

                {canEditThis ? (
                  <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'flex-end' }}>
                    {m.data_type === 'TEXT' || m.data_type === 'BOOLEAN' ? (
                      <input
                        className="input"
                        placeholder="Value"
                        defaultValue={m.text_value ?? ''}
                        onChange={(e) => setDrafts((d) => ({ ...d, [m.metric_code]: { ...d[m.metric_code], text_value: e.target.value } }))}
                      />
                    ) : (
                      <input
                        className="input"
                        type="number"
                        placeholder="Value"
                        defaultValue={m.value ?? ''}
                        onChange={(e) => setDrafts((d) => ({ ...d, [m.metric_code]: { ...d[m.metric_code], value: e.target.value === '' ? null : Number(e.target.value) } }))}
                      />
                    )}
                    <select
                      className="input"
                      style={{ maxWidth: '11rem' }}
                      defaultValue={m.source_type === 'EXTERNAL_SOURCE' ? 'EXTERNAL_SOURCE' : 'COMPANY_PROVIDED'}
                      title="How was this figure obtained?"
                      onChange={(e) =>
                        setDrafts((d) => ({
                          ...d,
                          [m.metric_code]: { ...d[m.metric_code], source_type: e.target.value as 'COMPANY_PROVIDED' | 'EXTERNAL_SOURCE' },
                        }))
                      }
                    >
                      <option value="COMPANY_PROVIDED">Company Provided</option>
                      <option value="EXTERNAL_SOURCE">External Source (e.g. utility bill)</option>
                    </select>
                    <button
                      className="btn btn-secondary btn-sm"
                      disabled={updateMutation.isPending}
                      onClick={() => updateMutation.mutate({ metricCode: m.metric_code, update: draft })}
                    >
                      Save
                    </button>
                  </div>
                ) : m.source_type === 'GREENSHIFT_DERIVED' || m.source_type === 'CALCULATED' ? (
                  <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', margin: 0 }}>
                    Derived automatically from GreenShift operational data — not manually editable.
                  </p>
                ) : null}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};

function InlineNote({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', margin: 0 }}>
      <strong>{label}:</strong> {value}
    </p>
  );
}
