import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, RefreshCw, CheckCircle2, AlertTriangle, Download, FileDown } from 'lucide-react';
import { PageHeader } from '../../components/layout/PageHeader';
import { GlassCard } from '../../components/common/GlassCard';
import { LoadingSkeleton } from '../../components/common/LoadingSkeleton';
import { InlineBanner } from '../../components/common/InlineBanner';
import { StatusBadge } from '../../components/common/StatusBadge';
import { BrsrMetricList } from '../../components/brsr/BrsrMetricList';
import { brsrApi } from '../../api/endpoints';
import { BrsrExportFormat } from '../../types/api';
import { useAuth } from '../../context/AuthContext';

type TabKey = 'overview' | 'core' | 'environmental' | 'social' | 'governance' | 'other' | 'validation' | 'assessment' | 'audit' | 'export';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'core', label: 'BRSR Core' },
  { key: 'environmental', label: 'Environmental' },
  { key: 'social', label: 'Social' },
  { key: 'governance', label: 'Governance' },
  { key: 'other', label: 'Other Disclosures' },
  { key: 'validation', label: 'Validation' },
  { key: 'assessment', label: 'Assessment / Assurance' },
  { key: 'audit', label: 'Audit Trail' },
  { key: 'export', label: 'Generate & Export' },
];

const NEXT_STATUS: Record<string, string> = {
  DRAFT: 'DATA_COLLECTION',
  DATA_COLLECTION: 'VALIDATED',
  VALIDATED: 'APPROVED',
  APPROVED: 'GENERATED',
};

export const BrsrReportDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const reportId = Number(id);
  const navigate = useNavigate();
  const { user } = useAuth();
  // Company Admin only — see BrsrOverviewPage.tsx for why this can't use
  // the broader app-wide `isCompanyAdmin` (Platform Admin is unconditionally
  // blocked from editing by the backend).
  const isCompanyAdmin = user?.role === 'COMPANY_ADMIN';
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<TabKey>('overview');

  const overviewQ = useQuery({ queryKey: ['brsrOverview', reportId], queryFn: () => brsrApi.getOverview(reportId), enabled: !!reportId });
  const report = overviewQ.data?.report;
  const editable = isCompanyAdmin && !!report && report.status !== 'GENERATED';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <PageHeader
        title={report ? `BRSR Report — FY ${report.financial_year}` : 'BRSR Report'}
        subtitle={report ? `Framework ${report.framework_version}` : undefined}
        badge={report && <StatusBadge status={report.status} />}
        actions={
          <button className="btn btn-secondary btn-sm" onClick={() => navigate('/brsr')}>
            <ArrowLeft size={14} />
            <span>All Reports</span>
          </button>
        }
      />

      {overviewQ.isLoading ? (
        <GlassCard><LoadingSkeleton rows={6} /></GlassCard>
      ) : overviewQ.isError ? (
        <InlineBanner variant="error" action={<button className="btn btn-secondary btn-sm" onClick={() => overviewQ.refetch()}><RefreshCw size={13} /><span>Retry</span></button>}>
          Couldn't load this BRSR report.
        </InlineBanner>
      ) : !overviewQ.data ? null : (
        <>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '0.5rem' }}>
            {TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`btn btn-sm ${tab === t.key ? 'btn-primary' : 'btn-secondary'}`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {tab === 'overview' && <OverviewTab reportId={reportId} />}
          {tab === 'core' && <MetricsTab reportId={reportId} editable={editable} filter={{ section: 'CORE' }} />}
          {tab === 'environmental' && <MetricsTab reportId={reportId} editable={editable} filter={{ principle: 6 }} />}
          {tab === 'social' && <SocialTab reportId={reportId} editable={editable} />}
          {tab === 'governance' && <MetricsTab reportId={reportId} editable={editable} filter={{ section: 'SECTION_B' }} />}
          {tab === 'other' && <OtherTab reportId={reportId} editable={editable} />}
          {tab === 'validation' && <ValidationTab reportId={reportId} editable={editable} />}
          {tab === 'assessment' && <AssessmentTab reportId={reportId} editable={editable} />}
          {tab === 'audit' && <AuditTab reportId={reportId} />}
          {tab === 'export' && <ExportTab reportId={reportId} />}
        </>
      )}
    </div>
  );
};

function OverviewTab({ reportId }: { reportId: number }) {
  const overviewQ = useQuery({ queryKey: ['brsrOverview', reportId], queryFn: () => brsrApi.getOverview(reportId) });
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const isCompanyAdmin = user?.role === 'COMPANY_ADMIN';
  const transitionMutation = useMutation({
    mutationFn: (target: string) => brsrApi.transitionStatus(reportId, target),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['brsrOverview', reportId] });
      queryClient.invalidateQueries({ queryKey: ['brsrReports'] });
    },
  });

  const data = overviewQ.data;
  if (!data) return null;
  const nextStatus = NEXT_STATUS[data.report.status];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '0.85rem' }}>
        <Stat label="Completion" value={`${data.completion_pct}%`} />
        <Stat label="Required Filled" value={`${data.required_metrics_filled} / ${data.required_metrics_total}`} />
        <Stat label="BRSR Core Completion" value={`${data.brsr_core_completion_pct}%`} />
        <Stat label="Missing Required" value={String(data.missing_required_count)} accent={data.missing_required_count > 0 ? '#f59e0b' : '#10b981'} />
      </div>

      <GlassCard title="Data Quality Summary">
        <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
          <QualityChip label="High" value={data.data_quality.high} color="#10b981" />
          <QualityChip label="Medium" value={data.data_quality.medium} color="#38bdf8" />
          <QualityChip label="Low" value={data.data_quality.low} color="#f59e0b" />
          <QualityChip label="Missing" value={data.data_quality.missing} color="#94a3b8" />
        </div>
      </GlassCard>

      {isCompanyAdmin && nextStatus && (
        <GlassCard title="Workflow">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <button
              className="btn btn-primary btn-sm"
              disabled={transitionMutation.isPending || (nextStatus === 'APPROVED' && !data.can_approve) || (nextStatus === 'GENERATED' && !data.can_generate)}
              onClick={() => transitionMutation.mutate(nextStatus)}
            >
              <CheckCircle2 size={14} />
              <span>Move to {nextStatus.replace('_', ' ')}</span>
            </button>
            {transitionMutation.isError && (
              <span style={{ color: '#ef4444', fontSize: '0.78rem' }}>
                {(transitionMutation.error as any)?.response?.data?.detail || 'Transition failed.'}
              </span>
            )}
          </div>
        </GlassCard>
      )}
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div style={{ padding: '0.9rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
      <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>{label}</div>
      <div style={{ fontSize: '1.4rem', fontWeight: 800, color: accent || 'var(--text-primary)' }}>{value}</div>
    </div>
  );
}

function QualityChip({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
      <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: color }} />
      <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{label}: <strong style={{ color: 'var(--text-primary)' }}>{value}</strong></span>
    </div>
  );
}

function MetricsTab({ reportId, editable, filter }: { reportId: number; editable: boolean; filter: { section?: string; principle?: number } }) {
  const metricsQ = useQuery({
    queryKey: ['brsrMetrics', reportId, filter],
    queryFn: () => brsrApi.getMetrics(reportId, filter),
  });
  return (
    <GlassCard>
      <BrsrMetricList reportId={reportId} metrics={metricsQ.data || []} editable={editable} isLoading={metricsQ.isLoading} />
    </GlassCard>
  );
}

function SocialTab({ reportId, editable }: { reportId: number; editable: boolean }) {
  const p3 = useQuery({ queryKey: ['brsrMetrics', reportId, { principle: 3 }], queryFn: () => brsrApi.getMetrics(reportId, { principle: 3 }) });
  const p4 = useQuery({ queryKey: ['brsrMetrics', reportId, { principle: 4 }], queryFn: () => brsrApi.getMetrics(reportId, { principle: 4 }) });
  const p5 = useQuery({ queryKey: ['brsrMetrics', reportId, { principle: 5 }], queryFn: () => brsrApi.getMetrics(reportId, { principle: 5 }) });
  const combined = [...(p3.data || []), ...(p4.data || []), ...(p5.data || [])];
  return (
    <GlassCard subtitle="Principles 3 (Employee Well-being), 4 (Stakeholders), 5 (Human Rights)">
      <BrsrMetricList reportId={reportId} metrics={combined} editable={editable} isLoading={p3.isLoading || p4.isLoading || p5.isLoading} />
    </GlassCard>
  );
}

function OtherTab({ reportId, editable }: { reportId: number; editable: boolean }) {
  const sectionA = useQuery({ queryKey: ['brsrMetrics', reportId, { section: 'SECTION_A' }], queryFn: () => brsrApi.getMetrics(reportId, { section: 'SECTION_A' }) });
  const others = useQuery({ queryKey: ['brsrMetrics', reportId, 'other-principles'], queryFn: () => brsrApi.getMetrics(reportId, {}) });
  const filtered = (others.data || []).filter((m) => [1, 2, 7, 8, 9].includes(m.principle || 0));
  const combined = [...(sectionA.data || []), ...filtered];
  return (
    <GlassCard subtitle="Section A general disclosures, plus Principles 1, 2, 7, 8, 9">
      <BrsrMetricList reportId={reportId} metrics={combined} editable={editable} isLoading={sectionA.isLoading || others.isLoading} />
    </GlassCard>
  );
}

function ValidationTab({ reportId, editable }: { reportId: number; editable: boolean }) {
  const queryClient = useQueryClient();
  const validationQ = useQuery({ queryKey: ['brsrValidation', reportId], queryFn: () => brsrApi.getLatestValidation(reportId) });
  const runMutation = useMutation({
    mutationFn: () => brsrApi.runValidation(reportId),
    onSuccess: (data) => {
      queryClient.setQueryData(['brsrValidation', reportId], data);
      queryClient.invalidateQueries({ queryKey: ['brsrOverview', reportId] });
    },
  });

  const run = runMutation.data || validationQ.data;

  return (
    <GlassCard
      title="Validation"
      actions={
        editable && (
          <button className="btn btn-primary btn-sm" onClick={() => runMutation.mutate()} disabled={runMutation.isPending}>
            <RefreshCw size={14} />
            <span>{runMutation.isPending ? 'Running…' : 'Run Validation'}</span>
          </button>
        )
      }
    >
      {validationQ.isLoading ? (
        <LoadingSkeleton rows={3} />
      ) : !run ? (
        <p style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>No validation has been run yet.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
          <div style={{ display: 'flex', gap: '1rem' }}>
            <span style={{ color: '#ef4444', fontWeight: 700 }}>{run.error_count} Errors</span>
            <span style={{ color: '#f59e0b', fontWeight: 700 }}>{run.warning_count} Warnings</span>
            <span style={{ color: '#38bdf8', fontWeight: 700 }}>{run.info_count} Info</span>
          </div>
          {run.issues.length === 0 ? (
            <p style={{ color: '#10b981', fontSize: '0.82rem' }}>No issues found.</p>
          ) : (
            run.issues.map((issue, i) => (
              <div key={i} style={{ padding: '0.6rem 0.8rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <AlertTriangle size={13} color={issue.severity === 'ERROR' ? '#ef4444' : issue.severity === 'WARNING' ? '#f59e0b' : '#38bdf8'} />
                  <strong style={{ fontSize: '0.78rem' }}>{issue.code}</strong>
                  {issue.metric_code && <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>({issue.metric_code})</span>}
                </div>
                <p style={{ fontSize: '0.78rem', margin: '0.3rem 0 0' }}>{issue.message}</p>
                {issue.suggested_resolution && (
                  <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', margin: '0.2rem 0 0' }}>→ {issue.suggested_resolution}</p>
                )}
              </div>
            ))
          )}
        </div>
      )}
    </GlassCard>
  );
}

function AssessmentTab({ reportId, editable }: { reportId: number; editable: boolean }) {
  const queryClient = useQueryClient();
  const assessmentQ = useQuery({ queryKey: ['brsrAssessment', reportId], queryFn: () => brsrApi.getAssessment(reportId) });
  const [form, setForm] = useState<{ assessment_status: string; assessor_name: string; assessor_type: string; scope: string; notes: string }>({
    assessment_status: '', assessor_name: '', assessor_type: '', scope: '', notes: '',
  });

  React.useEffect(() => {
    if (assessmentQ.data) {
      setForm({
        assessment_status: assessmentQ.data.assessment_status || '',
        assessor_name: assessmentQ.data.assessor_name || '',
        assessor_type: assessmentQ.data.assessor_type || '',
        scope: assessmentQ.data.scope || '',
        notes: assessmentQ.data.notes || '',
      });
    }
  }, [assessmentQ.data]);

  const saveMutation = useMutation({
    mutationFn: () =>
      brsrApi.updateAssessment(reportId, {
        ...form,
        assessor_type: (form.assessor_type || null) as 'INTERNAL' | 'EXTERNAL' | null,
      }),
    onSuccess: (data) => queryClient.setQueryData(['brsrAssessment', reportId], data),
  });

  return (
    <GlassCard title="Assessment / Assurance">
      <InlineBanner variant="info">
        GreenShift prepares traceable ESG information for reporting; it does not replace independent assessment or assurance.
        This section records company-provided assurance information only.
      </InlineBanner>
      {assessmentQ.isLoading ? (
        <LoadingSkeleton rows={3} />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.7rem' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '0.7rem' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.72rem', color: 'var(--text-muted)' }}>Status</label>
              <select className="select" disabled={!editable} value={form.assessment_status} onChange={(e) => setForm((f) => ({ ...f, assessment_status: e.target.value }))}>
                <option value="">Not assessed</option>
                <option value="NOT_ASSESSED">Not assessed</option>
                <option value="INTERNAL_REVIEW">Internal review</option>
                <option value="EXTERNAL_ASSURANCE">External assurance</option>
              </select>
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '0.72rem', color: 'var(--text-muted)' }}>Assessor Name</label>
              <input className="input" disabled={!editable} value={form.assessor_name} onChange={(e) => setForm((f) => ({ ...f, assessor_name: e.target.value }))} />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '0.72rem', color: 'var(--text-muted)' }}>Assessor Type</label>
              <select className="select" disabled={!editable} value={form.assessor_type} onChange={(e) => setForm((f) => ({ ...f, assessor_type: e.target.value }))}>
                <option value="">Not set</option>
                <option value="INTERNAL">Internal</option>
                <option value="EXTERNAL">External</option>
              </select>
            </div>
          </div>
          <div>
            <label style={{ display: 'block', fontSize: '0.72rem', color: 'var(--text-muted)' }}>Scope</label>
            <textarea className="input" style={{ width: '100%' }} rows={2} disabled={!editable} value={form.scope} onChange={(e) => setForm((f) => ({ ...f, scope: e.target.value }))} />
          </div>
          <div>
            <label style={{ display: 'block', fontSize: '0.72rem', color: 'var(--text-muted)' }}>Notes</label>
            <textarea className="input" style={{ width: '100%' }} rows={2} disabled={!editable} value={form.notes} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} />
          </div>
          {editable && (
            <button className="btn btn-primary btn-sm" style={{ alignSelf: 'flex-start' }} onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
              Save
            </button>
          )}
        </div>
      )}
    </GlassCard>
  );
}

function AuditTab({ reportId }: { reportId: number }) {
  const auditQ = useQuery({ queryKey: ['brsrAudit', reportId], queryFn: () => brsrApi.getAuditTrail(reportId) });
  return (
    <GlassCard title="Audit Trail">
      {auditQ.isLoading ? (
        <LoadingSkeleton rows={4} />
      ) : !auditQ.data || auditQ.data.length === 0 ? (
        <p style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>No BRSR audit events yet.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {auditQ.data.map((e) => (
            <div key={e.event_id} style={{ padding: '0.6rem 0.8rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', fontSize: '0.78rem' }}>
              <strong>{e.event_type}</strong> · seq {e.sequence} · {new Date(e.timestamp).toLocaleString()}
              {(e.actor_username || e.actor_type) && (
                <span style={{ color: 'var(--text-muted)' }}>
                  {' '}· by {e.actor_username || 'SYSTEM'}{e.actor_role ? ` (${e.actor_role})` : ''}
                </span>
              )}
              {e.request_id && (
                <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '0.68rem' }}>
                  {' '}· req {e.request_id.substring(0, 8)}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </GlassCard>
  );
}

function ExportTab({ reportId }: { reportId: number }) {
  const overviewQ = useQuery({ queryKey: ['brsrOverview', reportId], queryFn: () => brsrApi.getOverview(reportId) });
  const [downloading, setDownloading] = useState<BrsrExportFormat | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isGenerated = overviewQ.data?.report.status === 'GENERATED';

  const download = async (format: BrsrExportFormat) => {
    setError(null);
    setDownloading(format);
    try {
      const blob = await brsrApi.exportReport(reportId, format);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `brsr_report_${reportId}.${format === 'excel' ? 'xlsx' : format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Export failed.');
    } finally {
      setDownloading(null);
    }
  };

  return (
    <GlassCard title="Generate & Export">
      {!isGenerated ? (
        <InlineBanner variant="warning">
          This report must reach GENERATED status (validated and approved first) before it can be exported.
        </InlineBanner>
      ) : (
        <div style={{ display: 'flex', gap: '0.6rem', flexWrap: 'wrap' }}>
          {(['pdf', 'excel', 'csv', 'json'] as BrsrExportFormat[]).map((format) => (
            <button key={format} className="btn btn-secondary btn-sm" onClick={() => download(format)} disabled={downloading === format}>
              {format === 'pdf' ? <FileDown size={14} /> : <Download size={14} />}
              <span>{downloading === format ? 'Downloading…' : format.toUpperCase()}</span>
            </button>
          ))}
        </div>
      )}
      {error && <InlineBanner variant="error">{error}</InlineBanner>}
    </GlassCard>
  );
}
