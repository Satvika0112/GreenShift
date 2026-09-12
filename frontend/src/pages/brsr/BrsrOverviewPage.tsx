import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { FileText, Plus, RefreshCw, Building2 } from 'lucide-react';
import { PageHeader } from '../../components/layout/PageHeader';
import { GlassCard } from '../../components/common/GlassCard';
import { LoadingSkeleton } from '../../components/common/LoadingSkeleton';
import { EmptyState } from '../../components/common/EmptyState';
import { InlineBanner } from '../../components/common/InlineBanner';
import { StatusBadge } from '../../components/common/StatusBadge';
import { brsrApi } from '../../api/endpoints';
import { BrsrReportCreate } from '../../types/api';
import { useAuth } from '../../context/AuthContext';

function currentFinancialYear(): string {
  const now = new Date();
  const year = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1; // FY starts April
  return `${year}-${String((year + 1) % 100).padStart(2, '0')}`;
}

export const BrsrOverviewPage: React.FC = () => {
  const { user } = useAuth();
  // BRSR create/edit is Company Admin only — deliberately narrower than the
  // app-wide `isCompanyAdmin` flag (which also covers Platform Admin).
  // The backend (app.brsr.service.require_edit_access) unconditionally
  // forbids Platform Admin from creating/editing a company's BRSR data —
  // this must match exactly, or the UI would offer an action that always
  // fails with 403.
  const isCompanyAdmin = user?.role === 'COMPANY_ADMIN';
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [financialYear, setFinancialYear] = useState(currentFinancialYear());

  const reportsQ = useQuery({
    queryKey: ['brsrReports'],
    queryFn: () => brsrApi.getReports(),
  });

  const createMutation = useMutation({
    mutationFn: (input: BrsrReportCreate) => brsrApi.createReport(input),
    onSuccess: (report) => {
      queryClient.invalidateQueries({ queryKey: ['brsrReports'] });
      setShowCreateForm(false);
      navigate(`/brsr/reports/${report.id}`);
    },
  });

  const handleCreate = () => {
    const [startYear] = financialYear.split('-');
    const y = parseInt(startYear, 10);
    createMutation.mutate({
      financial_year: financialYear,
      reporting_period_start: `${y}-04-01T00:00:00Z`,
      reporting_period_end: `${y + 1}-03-31T00:00:00Z`,
      framework_version: 'BRSR-2023',
    });
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <PageHeader
        title="BRSR Reporting"
        subtitle="SEBI-aligned Business Responsibility and Sustainability Reports, combining GreenShift operational data with company-provided ESG disclosures."
        actions={
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button className="btn btn-secondary btn-sm" onClick={() => navigate('/brsr/company-profile')}>
              <Building2 size={14} />
              <span>Company Profile</span>
            </button>
            {isCompanyAdmin && (
              <button className="btn btn-primary btn-sm" onClick={() => setShowCreateForm((v) => !v)}>
                <Plus size={14} />
                <span>New BRSR Report</span>
              </button>
            )}
          </div>
        }
      />

      {showCreateForm && (
        <GlassCard title="Start a new BRSR report">
          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '0.3rem' }}>
                Financial Year
              </label>
              <input
                className="input"
                value={financialYear}
                onChange={(e) => setFinancialYear(e.target.value)}
                placeholder="2025-26"
                pattern="\d{4}-\d{2}"
              />
            </div>
            <button className="btn btn-primary btn-sm" onClick={handleCreate} disabled={createMutation.isPending}>
              {createMutation.isPending ? 'Creating…' : 'Create Report'}
            </button>
          </div>
          {createMutation.isError && (
            <InlineBanner variant="error">
              {(createMutation.error as any)?.response?.data?.detail || 'Could not create the report.'}
            </InlineBanner>
          )}
        </GlassCard>
      )}

      <GlassCard title="Reports">
        {reportsQ.isLoading ? (
          <LoadingSkeleton rows={4} />
        ) : reportsQ.isError ? (
          <InlineBanner
            variant="error"
            action={
              <button className="btn btn-secondary btn-sm" onClick={() => reportsQ.refetch()}>
                <RefreshCw size={13} />
                <span>Retry</span>
              </button>
            }
          >
            Couldn't load BRSR reports.
          </InlineBanner>
        ) : !reportsQ.data || reportsQ.data.length === 0 ? (
          <EmptyState
            title="No BRSR reports yet"
            description="Create your first BRSR report to begin data collection."
            icon={FileText}
            action={isCompanyAdmin ? { label: 'New BRSR Report', onClick: () => setShowCreateForm(true) } : undefined}
          />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            {reportsQ.data.map((report) => (
              <div
                key={report.id}
                onClick={() => navigate(`/brsr/reports/${report.id}`)}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '0.85rem 1rem', borderRadius: 'var(--radius-md)',
                  border: '1px solid var(--border-subtle)', cursor: 'pointer',
                }}
              >
                <div>
                  <div style={{ fontWeight: 700, color: 'var(--text-primary)' }}>FY {report.financial_year}</div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    Framework {report.framework_version} · Created {new Date(report.created_at).toLocaleDateString()}
                  </div>
                </div>
                <StatusBadge status={report.status} />
              </div>
            ))}
          </div>
        )}
      </GlassCard>
    </div>
  );
};
