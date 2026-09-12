import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, RefreshCw, Save } from 'lucide-react';
import { PageHeader } from '../../components/layout/PageHeader';
import { GlassCard } from '../../components/common/GlassCard';
import { LoadingSkeleton } from '../../components/common/LoadingSkeleton';
import { InlineBanner } from '../../components/common/InlineBanner';
import { brsrApi } from '../../api/endpoints';
import { BrsrCompanyProfileUpdate } from '../../types/api';
import { useAuth } from '../../context/AuthContext';

const FIELDS: { key: keyof BrsrCompanyProfileUpdate; label: string; type?: string }[] = [
  { key: 'company_name', label: 'Company Name' },
  { key: 'cin', label: 'CIN' },
  { key: 'sector', label: 'Sector' },
  { key: 'industry', label: 'Industry' },
  { key: 'stock_exchange', label: 'Stock Exchange' },
  { key: 'isin', label: 'ISIN' },
  { key: 'employees_count', label: 'Employees', type: 'number' },
  { key: 'workers_count', label: 'Workers', type: 'number' },
  { key: 'revenue', label: 'Revenue', type: 'number' },
  { key: 'revenue_currency', label: 'Revenue Currency (e.g. INR)' },
  { key: 'net_worth', label: 'Net Worth', type: 'number' },
  { key: 'net_worth_currency', label: 'Net Worth Currency' },
  { key: 'capital', label: 'Paid-up Capital', type: 'number' },
  { key: 'capital_currency', label: 'Capital Currency' },
];

export const BrsrCompanyProfilePage: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  // Company Admin only — the backend (require_edit_access) unconditionally
  // forbids Platform Admin from editing a company's BRSR profile, so this
  // must not use the broader app-wide `isCompanyAdmin` (which also covers
  // Platform Admin) or the UI would offer an edit that always 403s.
  const isCompanyAdmin = user?.role === 'COMPANY_ADMIN';
  const queryClient = useQueryClient();
  const [form, setForm] = useState<BrsrCompanyProfileUpdate>({});
  const [savedMsg, setSavedMsg] = useState(false);

  const profileQ = useQuery({ queryKey: ['brsrCompanyProfile'], queryFn: () => brsrApi.getCompanyProfile() });

  useEffect(() => {
    if (profileQ.data) {
      const { tenant_id, source_type, updated_at, currency_conversions, ...editable } = profileQ.data;
      setForm(editable);
    }
  }, [profileQ.data]);

  const saveMutation = useMutation({
    mutationFn: (update: BrsrCompanyProfileUpdate) => brsrApi.updateCompanyProfile(update),
    onSuccess: (data) => {
      queryClient.setQueryData(['brsrCompanyProfile'], data);
      setSavedMsg(true);
      setTimeout(() => setSavedMsg(false), 3000);
    },
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <PageHeader
        title="BRSR Company Profile"
        subtitle="Company-provided identity information used across every BRSR report. Every field here is marked Company Provided."
        actions={
          <button className="btn btn-secondary btn-sm" onClick={() => navigate('/brsr')}>
            <ArrowLeft size={14} />
            <span>Back to BRSR</span>
          </button>
        }
      />

      <GlassCard title="Company Identity" badge={<span className="badge badge-neutral">Company Provided</span>}>
        {profileQ.isLoading ? (
          <LoadingSkeleton rows={6} />
        ) : profileQ.isError ? (
          <InlineBanner
            variant="error"
            action={
              <button className="btn btn-secondary btn-sm" onClick={() => profileQ.refetch()}>
                <RefreshCw size={13} />
                <span>Retry</span>
              </button>
            }
          >
            Couldn't load the company profile.
          </InlineBanner>
        ) : (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.85rem' }}>
              {FIELDS.map(({ key, label, type }) => (
                <div key={key}>
                  <label htmlFor={`brsr-profile-${key}`} style={{ display: 'block', fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>
                    {label}
                  </label>
                  <input
                    id={`brsr-profile-${key}`}
                    className="input"
                    type={type || 'text'}
                    value={(form[key] as any) ?? ''}
                    disabled={!isCompanyAdmin}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        [key]: type === 'number' ? (e.target.value === '' ? null : Number(e.target.value)) : e.target.value,
                      }))
                    }
                  />
                </div>
              ))}
              <div>
                <label style={{ display: 'block', fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>
                  Listed Status
                </label>
                <select
                  className="select"
                  value={form.listed_status ?? ''}
                  disabled={!isCompanyAdmin}
                  onChange={(e) => setForm((f) => ({ ...f, listed_status: e.target.value || null }))}
                >
                  <option value="">Not set</option>
                  <option value="LISTED">Listed</option>
                  <option value="UNLISTED">Unlisted</option>
                </select>
              </div>
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>
                Reporting Boundary
              </label>
              <textarea
                className="input"
                rows={3}
                style={{ width: '100%' }}
                value={form.reporting_boundary ?? ''}
                disabled={!isCompanyAdmin}
                onChange={(e) => setForm((f) => ({ ...f, reporting_boundary: e.target.value }))}
              />
            </div>

            {isCompanyAdmin ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                <button className="btn btn-primary btn-sm" onClick={() => saveMutation.mutate(form)} disabled={saveMutation.isPending}>
                  <Save size={14} />
                  <span>{saveMutation.isPending ? 'Saving…' : 'Save Profile'}</span>
                </button>
                {savedMsg && <span style={{ color: '#10b981', fontSize: '0.8rem' }}>Saved.</span>}
                {saveMutation.isError && (
                  <span style={{ color: '#ef4444', fontSize: '0.8rem' }}>Couldn't save — please retry.</span>
                )}
              </div>
            ) : (
              <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                Read-only — only a Company Admin can edit the company profile.
              </p>
            )}
          </>
        )}
      </GlassCard>
    </div>
  );
};
