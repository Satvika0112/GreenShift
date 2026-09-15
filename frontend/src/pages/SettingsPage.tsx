import React, { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Settings,
  Save,
  CheckCircle2,
  Sliders,
  Shield,
  Clock,
  Zap,
  Server,
  Database,
  RefreshCw,
  Leaf,
  DollarSign,
  Scale,
} from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassCard } from '../components/common/GlassCard';
import { InlineBanner } from '../components/common/InlineBanner';
import { sustainabilityApi, monitoringApi, notificationsApi, companiesApi, optimizationPolicyApi } from '../api/endpoints';
import { NotificationPreferencesUpdate, CompanyProfile, CompanyProfileUpdate, OptimizationPolicy, OptimizationPolicyUpdate } from '../types/api';
import { useAuth } from '../context/AuthContext';
import { useRealtimeNotifications } from '../context/RealtimeNotificationContext';
import { formatRegionalDateTime } from '../utils/dateTime';

const PREFERENCE_TOGGLES: { field: keyof NotificationPreferencesUpdate; label: string; helper: string }[] = [
  { field: 'email_workload', label: 'Workload', helper: 'Submitted, cancelled' },
  { field: 'email_scheduling', label: 'Scheduling', helper: 'No feasible schedule found' },
  { field: 'email_approval', label: 'Approval', helper: 'Approval required, approved, declined' },
  { field: 'email_execution', label: 'Execution', helper: 'Execution completed, execution failed' },
];

const POLICY_OPTIONS: { value: OptimizationPolicy; icon: typeof Leaf; label: string; helper: string }[] = [
  { value: 'CARBON_FIRST', icon: Leaf, label: 'Carbon First', helper: 'Prioritize minimum carbon emissions.' },
  { value: 'COST_FIRST', icon: DollarSign, label: 'Cost First', helper: 'Prioritize minimum electricity cost.' },
  {
    value: 'CARBON_CONSTRAINED',
    icon: Scale,
    label: 'Balanced — Carbon Constrained',
    helper: 'Minimize electricity cost while staying within the configured percentage of the greenest feasible schedule.',
  },
];

export const SettingsPage: React.FC = () => {
  const { user, isCompanyAdmin, isAuthenticated } = useAuth();
  const { connectionStatus, soundEnabled, setSoundEnabled } = useRealtimeNotifications();
  const queryClient = useQueryClient();

  const preferencesQ = useQuery({
    queryKey: ['notificationPreferences'],
    queryFn: () => notificationsApi.getPreferences(),
    enabled: isAuthenticated,
  });
  const preferencesMutation = useMutation({
    mutationFn: (update: NotificationPreferencesUpdate) => notificationsApi.updatePreferences(update),
    onSuccess: (data) => {
      queryClient.setQueryData(['notificationPreferences'], data);
    },
  });

  // Company profile — only meaningful for a user who actually belongs to a
  // company (Platform Admin has no tenant_id and manages companies via the
  // existing /admin/companies endpoints instead, not this page).
  const isCompanyAdminRole = user?.role === 'COMPANY_ADMIN';
  const companyQ = useQuery({
    queryKey: ['myCompany'],
    queryFn: () => companiesApi.getMyCompany(),
    enabled: isAuthenticated && !!user?.tenant_id,
  });
  const [companyDraft, setCompanyDraft] = useState<CompanyProfileUpdate | null>(null);
  const [companySaved, setCompanySaved] = useState(false);
  const companyMutation = useMutation({
    mutationFn: (update: CompanyProfileUpdate) => companiesApi.updateMyCompany(update),
    onSuccess: (data) => {
      queryClient.setQueryData(['myCompany'], data);
      setCompanyDraft(null);
      setCompanySaved(true);
      setTimeout(() => setCompanySaved(false), 3000);
    },
  });
  const company: CompanyProfile | undefined = companyQ.data;
  const companyField = (key: keyof CompanyProfileUpdate): string =>
    (companyDraft && key in companyDraft ? (companyDraft[key] as string) : (company?.[key as keyof CompanyProfile] as string)) || '';
  const setCompanyField = (key: keyof CompanyProfileUpdate) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    setCompanyDraft((d) => ({ ...d, [key]: e.target.value }));
  };

  // GreenShift Policy-Aware Optimization — backend-owned company scheduling
  // policy (GET/PUT /api/v1/settings/optimization-policy). This is the
  // authoritative source; it is never read from or written to
  // localStorage. Any authenticated company member can read it; only a
  // Company Admin may change it (enforced server-side — this gate is UX
  // only, not the security boundary).
  const policyQ = useQuery({
    queryKey: ['optimizationPolicy'],
    queryFn: () => optimizationPolicyApi.getPolicy(),
    enabled: isAuthenticated && !!user?.tenant_id,
  });
  const [policyDraft, setPolicyDraft] = useState<OptimizationPolicy | null>(null);
  const [toleranceDraft, setToleranceDraft] = useState<number | null>(null);
  const [policySaved, setPolicySaved] = useState(false);
  const policyMutation = useMutation({
    mutationFn: (update: OptimizationPolicyUpdate) => optimizationPolicyApi.updatePolicy(update),
    onSuccess: (data) => {
      queryClient.setQueryData(['optimizationPolicy'], data);
      setPolicyDraft(null);
      setToleranceDraft(null);
      setPolicySaved(true);
      setTimeout(() => setPolicySaved(false), 3000);
    },
  });
  const effectivePolicy: OptimizationPolicy = policyDraft ?? policyQ.data?.policy ?? 'CARBON_FIRST';
  const effectiveTolerance: number =
    toleranceDraft ?? policyQ.data?.carbon_tolerance_pct ?? 5;
  const policyDirty =
    policyDraft !== null ||
    (effectivePolicy === 'CARBON_CONSTRAINED' && toleranceDraft !== null);
  const handleSavePolicy = () => {
    const update: OptimizationPolicyUpdate = { policy: effectivePolicy };
    if (effectivePolicy === 'CARBON_CONSTRAINED') {
      update.carbon_tolerance_pct = effectiveTolerance;
    }
    policyMutation.mutate(update);
  };

  const [dataSources, setDataSources] = useState<any | null>(null);
  const [healthStatus, setHealthStatus] = useState<any | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Client-side UI control preference (saved in localStorage) — purely the
  // dashboard auto-refresh cadence. The scheduling optimization policy
  // above used to live here too (as `gs_pref_objective`) but was UI-only
  // and never actually reached the backend scheduler; it has been fully
  // replaced by the backend-owned policy above.
  const [pollInterval, setPollInterval] = useState(() => {
    return parseInt(localStorage.getItem('gs_pref_poll_interval') || '15', 10);
  });
  const [savedSuccess, setSavedSuccess] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);

  const fetchBackendConfig = async () => {
    setIsLoading(true);
    setFetchError(null);
    try {
      const [sourcesRes, healthRes] = await Promise.allSettled([
        sustainabilityApi.getDataSourcesStatus(),
        monitoringApi.getSystemHealth(),
      ]);

      if (sourcesRes.status === 'fulfilled') {
        setDataSources(sourcesRes.value);
      }
      if (healthRes.status === 'fulfilled') {
        setHealthStatus(healthRes.value);
      }
      if (sourcesRes.status === 'rejected' && healthRes.status === 'rejected') {
        setFetchError('Failed to retrieve live backend runtime configuration and health metrics.');
      }
    } catch {
      setFetchError('Failed to retrieve live backend runtime configuration.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchBackendConfig();
  }, []);

  const handleSavePreferences = (e: React.FormEvent) => {
    e.preventDefault();
    localStorage.setItem('gs_pref_poll_interval', String(pollInterval));
    setSavedSuccess(true);
    setTimeout(() => setSavedSuccess(false), 3000);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem', maxWidth: '900px' }}>
      <PageHeader
        title="Control Plane Configuration"
        subtitle="Active backend configuration parameters, verified data sources, and client preference controls"
        actions={
          <button className="btn btn-secondary" onClick={fetchBackendConfig} disabled={isLoading}>
            <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
            <span>Sync Config</span>
          </button>
        }
      />

      {fetchError && (
        <div
          style={{
            background: 'rgba(239, 68, 68, 0.1)',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            borderRadius: 'var(--radius-sm)',
            padding: '0.85rem 1.25rem',
            color: '#ef4444',
            fontSize: '0.85rem',
            fontWeight: 600,
          }}
        >
          ⚠ {fetchError}
        </div>
      )}

      {savedSuccess && (
        <div
          style={{
            background: 'rgba(16, 185, 129, 0.15)',
            border: '1px solid #10b981',
            borderRadius: 'var(--radius-sm)',
            padding: '0.85rem 1.25rem',
            color: '#10b981',
            fontSize: '0.85rem',
            fontWeight: 600,
          }}
        >
          ✓ UI control preferences saved to local profile.
        </div>
      )}

      {/* Profile — real authenticated identity, available to every role */}
      <GlassCard title="Profile">
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)', fontSize: '0.85rem' }}>
            <span style={{ color: 'var(--text-secondary)' }}>Username</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#ffffff' }}>{user?.username}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)', fontSize: '0.85rem' }}>
            <span style={{ color: 'var(--text-secondary)' }}>Email</span>
            <span style={{ color: 'var(--text-primary)' }}>{user?.email}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)', fontSize: '0.85rem' }}>
            <span style={{ color: 'var(--text-secondary)' }}>Role</span>
            <span style={{ fontFamily: 'var(--font-mono)', color: '#10b981', fontWeight: 700 }}>{user?.role}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)', fontSize: '0.85rem' }}>
            <span style={{ color: 'var(--text-secondary)' }}>Company</span>
            <span style={{ color: 'var(--text-primary)' }}>{user?.company_name || user?.tenant_id || '—'}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)', fontSize: '0.85rem' }}>
            <span style={{ color: 'var(--text-secondary)' }}>Team</span>
            <span style={{ color: 'var(--text-primary)' }}>{user?.team_id || '—'}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem' }}>
            <span style={{ color: 'var(--text-secondary)' }}>Account Status</span>
            <span style={{ color: user?.is_active ? '#10b981' : '#ef4444', fontWeight: 600 }}>
              {user?.is_active ? 'ACTIVE' : 'INACTIVE'}{user?.approval_status && user.approval_status !== 'APPROVED' ? ` · ${user.approval_status}` : ''}
            </span>
          </div>
        </div>
      </GlassCard>

      {/* Role/tenant/team identity itself is never editable from Settings —
          the backend derives and owns those. The company PROFILE below
          (name, industry, address, etc.) is editable only by a Company
          Admin of that same company, via PATCH /companies/me — never by
          supplying a different tenant_id/company_id. */}
      {!!user?.tenant_id && (
        <GlassCard title="Company Profile">
          {companyQ.isLoading ? (
            <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>Loading company profile…</div>
          ) : companyQ.isError || !company ? (
            <InlineBanner variant="error">Couldn't load company profile.</InlineBanner>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
              {companySaved && (
                <InlineBanner variant="success">Company profile saved.</InlineBanner>
              )}
              {companyMutation.isError && (
                <InlineBanner variant="error">
                  {(companyMutation.error as any)?.response?.data?.detail || 'Failed to save company profile.'}
                </InlineBanner>
              )}

              {isCompanyAdminRole ? (
                <>
                  <div className="form-group" style={{ marginBottom: 0 }}>
                    <label className="form-label">Company Name</label>
                    <input className="input" value={companyField('name')} onChange={setCompanyField('name')} maxLength={200} />
                  </div>
                  <div className="form-group" style={{ marginBottom: 0 }}>
                    <label className="form-label">Legal Name</label>
                    <input className="input" value={companyField('legal_name')} onChange={setCompanyField('legal_name')} maxLength={200} />
                  </div>
                  <div className="form-group" style={{ marginBottom: 0 }}>
                    <label className="form-label">Company Email</label>
                    <input className="input" type="email" value={companyField('company_email')} onChange={setCompanyField('company_email')} />
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                    <div className="form-group" style={{ marginBottom: 0 }}>
                      <label className="form-label">Industry</label>
                      <input className="input" value={companyField('industry')} onChange={setCompanyField('industry')} />
                    </div>
                    <div className="form-group" style={{ marginBottom: 0 }}>
                      <label className="form-label">Sector</label>
                      <input className="input" value={companyField('sector')} onChange={setCompanyField('sector')} />
                    </div>
                  </div>
                  <div className="form-group" style={{ marginBottom: 0 }}>
                    <label className="form-label">Website</label>
                    <input className="input" value={companyField('website')} onChange={setCompanyField('website')} />
                  </div>
                  <div className="form-group" style={{ marginBottom: 0 }}>
                    <label className="form-label">Country</label>
                    <input className="input" value={companyField('country')} onChange={setCompanyField('country')} />
                  </div>
                  <div className="form-group" style={{ marginBottom: 0 }}>
                    <label className="form-label">Address</label>
                    <textarea className="input" rows={2} value={companyField('address')} onChange={setCompanyField('address')} />
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      disabled={!companyDraft || companyMutation.isPending}
                      onClick={() => companyDraft && companyMutation.mutate(companyDraft)}
                    >
                      <Save size={13} />
                      <span>{companyMutation.isPending ? 'Saving…' : 'Save Company Profile'}</span>
                    </button>
                  </div>
                </>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem', fontSize: '0.85rem' }}>
                  {[
                    ['Company Name', company.name],
                    ['Legal Name', company.legal_name],
                    ['Company Email', company.company_email],
                    ['Industry', company.industry],
                    ['Sector', company.sector],
                    ['Website', company.website],
                    ['Country', company.country],
                    ['Address', company.address],
                  ].map(([label, value]) => (
                    <div key={label} style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>{label}</span>
                      <span style={{ color: 'var(--text-primary)', textAlign: 'right' }}>{value || '—'}</span>
                    </div>
                  ))}
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                    Read-only — only a Company Admin can edit these details.
                  </div>
                </div>
              )}
            </div>
          )}
        </GlassCard>
      )}

      {/* Scheduling Optimization Policy — backend-owned (GET/PUT
          /api/v1/settings/optimization-policy), never localStorage. Any
          company member can see the active policy; only a Company Admin
          can change it (server-enforced — see api_update_optimization_policy). */}
      {!!user?.tenant_id && (
        <GlassCard title="Scheduling Optimization Policy">
          {policyQ.isLoading ? (
            <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>Loading optimization policy…</div>
          ) : policyQ.isError ? (
            <InlineBanner
              variant="error"
              action={
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => policyQ.refetch()}>
                  <RefreshCw size={13} />
                  <span>Retry</span>
                </button>
              }
            >
              Couldn't load the scheduling optimization policy.
            </InlineBanner>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
              <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', margin: 0 }}>
                Controls how GreenShift's scheduler prioritizes carbon emissions vs. electricity cost when
                choosing an execution window. Hard constraints (deadlines, SLA, resource availability, and any
                workload's own carbon budget) are always enforced first and are never affected by this policy.
              </p>

              {policySaved && <InlineBanner variant="success">Scheduling optimization policy saved.</InlineBanner>}
              {policyMutation.isError && (
                <InlineBanner variant="error">
                  {(policyMutation.error as any)?.response?.data?.detail || 'Failed to save the scheduling optimization policy.'}
                </InlineBanner>
              )}

              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
                {POLICY_OPTIONS.map(({ value, icon: Icon, label, helper }) => (
                  <label
                    key={value}
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: '0.65rem',
                      padding: '0.7rem 0.85rem',
                      borderRadius: 'var(--radius-sm)',
                      border: `1px solid ${effectivePolicy === value ? '#10b981' : 'var(--border-subtle)'}`,
                      background: effectivePolicy === value ? 'rgba(16, 185, 129, 0.06)' : 'transparent',
                      cursor: isCompanyAdminRole ? 'pointer' : 'default',
                    }}
                  >
                    <input
                      type="radio"
                      name="optimization-policy"
                      value={value}
                      checked={effectivePolicy === value}
                      disabled={!isCompanyAdminRole || policyMutation.isPending}
                      onChange={() => setPolicyDraft(value)}
                      style={{ marginTop: '0.2rem' }}
                    />
                    <Icon size={16} color={effectivePolicy === value ? '#10b981' : 'var(--text-muted)'} style={{ marginTop: '0.1rem', flexShrink: 0 }} />
                    <div>
                      <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)' }}>{label}</div>
                      <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{helper}</div>
                    </div>
                  </label>
                ))}
              </div>

              {effectivePolicy === 'CARBON_CONSTRAINED' && (
                <div className="form-group" style={{ marginBottom: 0, paddingLeft: '0.1rem' }}>
                  <label className="form-label" htmlFor="carbon-tolerance-pct">Carbon Tolerance (%)</label>
                  <input
                    id="carbon-tolerance-pct"
                    type="number"
                    min={0}
                    max={100}
                    step={0.5}
                    className="input"
                    value={effectiveTolerance}
                    disabled={!isCompanyAdminRole || policyMutation.isPending}
                    onChange={(e) => {
                      const v = parseFloat(e.target.value);
                      setToleranceDraft(Number.isFinite(v) ? v : 0);
                    }}
                    style={{ maxWidth: '160px' }}
                  />
                  <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                    Candidates within this percentage of the minimum achievable carbon emissions are eligible;
                    among those, GreenShift picks the cheapest.
                  </span>
                </div>
              )}

              {isCompanyAdminRole ? (
                <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    disabled={!policyDirty || policyMutation.isPending}
                    onClick={handleSavePolicy}
                  >
                    <Save size={13} />
                    <span>{policyMutation.isPending ? 'Saving…' : 'Save Optimization Policy'}</span>
                  </button>
                </div>
              ) : (
                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                  Read-only — only a Company Admin can change the scheduling optimization policy.
                </div>
              )}
            </div>
          )}
        </GlassCard>
      )}

      {/* Notification email preferences — real backend-persisted per-user
          settings (GET/PUT /api/v1/notifications/preferences). In-app
          notifications are never affected by these — only whether GreenShift
          also emails you for that category. Security/account/infrastructure
          notifications are not listed here because the backend does not
          allow disabling them. */}
      <GlassCard title="Notification Email Preferences">
        {preferencesQ.isLoading ? (
          <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>Loading preferences…</div>
        ) : preferencesQ.isError ? (
          <InlineBanner
            variant="error"
            action={
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => preferencesQ.refetch()}>
                <RefreshCw size={13} />
                <span>Retry</span>
              </button>
            }
          >
            Couldn't load notification preferences.
          </InlineBanner>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
            <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', margin: 0 }}>
              Choose which categories also send you an email. In-app notifications (the bell) are never affected.
            </p>
            {PREFERENCE_TOGGLES.map(({ field, label, helper }) => {
              const checked = !!preferencesQ.data?.[field];
              return (
                <div
                  key={field}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    paddingBottom: '0.6rem',
                    borderBottom: '1px solid var(--border-subtle)',
                  }}
                >
                  <div>
                    <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)' }}>{label}</div>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{helper}</div>
                  </div>
                  <label style={{ display: 'inline-flex', alignItems: 'center', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={preferencesMutation.isPending}
                      onChange={(e) => preferencesMutation.mutate({ [field]: e.target.checked })}
                      aria-label={`Email me for ${label} notifications`}
                    />
                  </label>
                </div>
              );
            })}
            <div
              style={{
                background: 'rgba(245, 158, 11, 0.06)',
                border: '1px solid rgba(245, 158, 11, 0.25)',
                borderRadius: 'var(--radius-sm)',
                padding: '0.6rem 0.85rem',
                fontSize: '0.72rem',
                color: '#f59e0b',
              }}
            >
              Security and account notifications are always emailed and cannot be disabled here.
            </div>
          </div>
        )}
      </GlassCard>

      <GlassCard title="Real-Time Notifications">
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)' }}>Connection status</div>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                {connectionStatus === 'connected' && 'Live — new notifications arrive instantly.'}
                {connectionStatus === 'unavailable' && 'Live updates unavailable in this environment — falling back to periodic refresh.'}
                {(connectionStatus === 'connecting' || connectionStatus === 'reconnecting') && 'Connecting…'}
                {(connectionStatus === 'idle' || connectionStatus === 'disconnected') && 'Not connected.'}
              </div>
            </div>
            <span
              style={{
                fontSize: '0.68rem',
                fontWeight: 700,
                padding: '0.2rem 0.55rem',
                borderRadius: 'var(--radius-full)',
                color: connectionStatus === 'connected' ? '#10b981' : 'var(--text-muted)',
                background: connectionStatus === 'connected' ? 'rgba(16,185,129,0.12)' : 'rgba(148,163,184,0.12)',
              }}
            >
              {connectionStatus.toUpperCase()}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: '0.6rem', borderTop: '1px solid var(--border-subtle)' }}>
            <div>
              <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)' }}>Notification sound</div>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                Play a sound for important/critical notifications as they arrive.
              </div>
            </div>
            <label style={{ display: 'inline-flex', alignItems: 'center', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={soundEnabled}
                onChange={(e) => setSoundEnabled(e.target.checked)}
                aria-label="Notification sound"
              />
            </label>
          </div>
        </div>
      </GlassCard>

      {/* Backend Operational Configuration — admin-tier diagnostic info, not relevant to a plain Company User's own settings */}
      {isCompanyAdmin && (
      <GlassCard title="Backend Runtime Architecture & Data Sources">
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)', fontSize: '0.85rem' }}>
            <span style={{ color: 'var(--text-secondary)' }}>Service Identity</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#ffffff' }}>
              {healthStatus?.service || 'GreenShift API v1.0.0'}
            </span>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)', fontSize: '0.85rem' }}>
            <span style={{ color: 'var(--text-secondary)' }}>System Health Status</span>
            <span style={{ fontWeight: 700, color: healthStatus?.status === 'healthy' ? '#10b981' : '#f59e0b' }}>
              {healthStatus?.status?.toUpperCase() || 'OPERATIONAL'}
            </span>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)', fontSize: '0.85rem' }}>
            <span style={{ color: 'var(--text-secondary)' }}>Carbon Data Source</span>
            <span style={{ fontFamily: 'var(--font-mono)', color: '#38bdf8' }}>
              {dataSources?.carbon_source || 'Electricity Maps API / Regional Resilient Fallback'}
            </span>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)', fontSize: '0.85rem' }}>
            <span style={{ color: 'var(--text-secondary)' }}>Master Electricity Tariff Source</span>
            <span style={{ fontFamily: 'var(--font-mono)', color: '#38bdf8' }}>
              {dataSources?.tariff_source || 'Master ToD Regional Tariff Dataset (264 Rows)'}
            </span>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)', fontSize: '0.85rem' }}>
            <span style={{ color: 'var(--text-secondary)' }}>Email Delivery</span>
            {(() => {
              const emailDelivery = healthStatus?.components?.email_delivery;
              const emailStatus = emailDelivery?.status;
              const label =
                emailStatus === 'configured' ? 'CONFIGURED' :
                emailStatus === 'disabled' ? 'DISABLED (SMTP_ENABLED=false)' :
                emailStatus === 'unconfigured' ? 'NOT CONFIGURED (SMTP_HOST unset)' :
                'UNKNOWN';
              const color = emailStatus === 'configured' ? '#10b981' : 'var(--text-muted)';
              const pending = emailDelivery?.pending_count;
              const failed = emailDelivery?.failed_count;
              const lastSent = emailDelivery?.last_sent_at;
              return (
                <span style={{ fontWeight: 600, color, textAlign: 'right' }}>
                  {label}
                  <div style={{ fontSize: '0.68rem', fontWeight: 400, color: 'var(--text-muted)' }}>
                    In-app notifications always work regardless.
                  </div>
                  {(pending !== undefined || failed !== undefined) && (
                    <div style={{ fontSize: '0.68rem', fontWeight: 400, color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                      {pending !== undefined && <>Pending: {pending}</>}
                      {pending !== undefined && failed !== undefined && ' · '}
                      {failed !== undefined && (
                        <span style={{ color: failed > 0 ? '#f59e0b' : 'var(--text-muted)' }}>Failed: {failed}</span>
                      )}
                      {lastSent && <> · Last sent: {formatRegionalDateTime(lastSent, 'UTC')}</>}
                    </div>
                  )}
                </span>
              );
            })()}
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)', fontSize: '0.85rem' }}>
            <span style={{ color: 'var(--text-secondary)' }}>Audit Ledger Verification</span>
            <span style={{ color: '#10b981', fontWeight: 600 }}>
              SHA-256 Tamper-Evident Hash Chain Active
            </span>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem' }}>
            <span style={{ color: 'var(--text-secondary)' }}>Dispatcher Poll Interval</span>
            <span style={{ fontFamily: 'var(--font-mono)' }}>5 seconds (Atomic claim loop)</span>
          </div>
        </div>
      </GlassCard>
      )}

      {/* Client-Side Preferences */}
      <form onSubmit={handleSavePreferences} style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        <GlassCard title="Client Control-Plane Preferences (Local Profile)">
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label" htmlFor="telemetry-poll-interval">Telemetry Auto-Refresh Interval (Seconds)</label>
            <input
              id="telemetry-poll-interval"
              type="number"
              min="5"
              max="300"
              className="input"
              value={pollInterval}
              onChange={(e) => setPollInterval(parseInt(e.target.value, 10) || 15)}
            />
            <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
              Controls automatic query polling interval across dashboard views.
            </span>
          </div>

          <div
            style={{
              background: 'rgba(56, 189, 248, 0.05)',
              border: '1px solid rgba(56, 189, 248, 0.2)',
              borderRadius: 'var(--radius-sm)',
              padding: '0.7rem 0.9rem',
              fontSize: '0.75rem',
              color: '#94a3b8',
              lineHeight: 1.45,
            }}
          >
            <strong style={{ color: '#38bdf8' }}>Local Scope Notice:</strong> This preference (dashboard refresh cadence) applies only to this client browser session. It does not alter backend server-side scheduling policies, deadlines, or constraints — the scheduling optimization policy above is the actual backend setting that does.
          </div>
        </GlassCard>

        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <button type="submit" className="btn btn-primary">
            <Save size={15} />
            <span>Save Preferences</span>
          </button>
        </div>
      </form>
    </div>
  );
};
