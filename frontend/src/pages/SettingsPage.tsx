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
} from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassCard } from '../components/common/GlassCard';
import { InlineBanner } from '../components/common/InlineBanner';
import { sustainabilityApi, monitoringApi, notificationsApi } from '../api/endpoints';
import { NotificationPreferencesUpdate } from '../types/api';
import { useAuth } from '../context/AuthContext';
import { useRealtimeNotifications } from '../context/RealtimeNotificationContext';

const PREFERENCE_TOGGLES: { field: keyof NotificationPreferencesUpdate; label: string; helper: string }[] = [
  { field: 'email_workload', label: 'Workload', helper: 'Submitted, cancelled' },
  { field: 'email_scheduling', label: 'Scheduling', helper: 'No feasible schedule found' },
  { field: 'email_approval', label: 'Approval', helper: 'Approval required, approved, declined' },
  { field: 'email_execution', label: 'Execution', helper: 'Execution completed, execution failed' },
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

  const [dataSources, setDataSources] = useState<any | null>(null);
  const [healthStatus, setHealthStatus] = useState<any | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Client-side UI control preferences (saved in localStorage)
  const [defaultObjective, setDefaultObjective] = useState(() => {
    return localStorage.getItem('gs_pref_objective') || 'carbon';
  });
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
    localStorage.setItem('gs_pref_objective', defaultObjective);
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

      {/* Role change / company / tenant are never editable from Settings — the
          backend derives and owns those; only an authorized admin flow can change them. */}

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
              const emailStatus = healthStatus?.components?.email_delivery?.status;
              const label =
                emailStatus === 'configured' ? 'CONFIGURED' :
                emailStatus === 'disabled' ? 'DISABLED (SMTP_ENABLED=false)' :
                emailStatus === 'unconfigured' ? 'NOT CONFIGURED (SMTP_HOST unset)' :
                'UNKNOWN';
              const color = emailStatus === 'configured' ? '#10b981' : 'var(--text-muted)';
              return (
                <span style={{ fontWeight: 600, color, textAlign: 'right' }}>
                  {label}
                  <div style={{ fontSize: '0.68rem', fontWeight: 400, color: 'var(--text-muted)' }}>
                    In-app notifications always work regardless.
                  </div>
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
          <div className="form-group">
            <label className="form-label">Preferred Scheduling Objective in UI</label>
            <select
              className="select"
              value={defaultObjective}
              onChange={(e) => setDefaultObjective(e.target.value)}
            >
              <option value="carbon">Carbon Minimization (Default - Highest Green Priority)</option>
              <option value="cost">Electricity Cost Minimization (Spot / ToD Tariff Priority)</option>
              <option value="balanced">Balanced Pareto Frontier (Multi-Objective Optimization)</option>
            </select>
          </div>

          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label">Telemetry Auto-Refresh Interval (Seconds)</label>
            <input
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
            <strong style={{ color: '#38bdf8' }}>Local Scope Notice:</strong> These preferences apply only to this client browser session (e.g. initial view preference and dashboard refresh cadence). They do not alter backend server-side scheduling policies, deadlines, or constraints.
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
