import React, { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { CheckCheck, RefreshCw, ShieldCheck, ArrowRight, Check } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassCard } from '../components/common/GlassCard';
import { EmptyState } from '../components/common/EmptyState';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { InlineBanner } from '../components/common/InlineBanner';
import { notificationsApi } from '../api/endpoints';
import { NotificationItem } from '../types/api';
import { severityIcon, severityColor, timeAgo, categoryLabel } from '../utils/notificationDisplay';

/** Matches the axios-error-to-message convention already used across the app
 * (e.g. WorkloadDetailPage, SchedulingPage: `err.response?.data?.detail || fallback`). */
function getErrorMessage(error: unknown): string {
  const err = error as any;
  const status = err?.response?.status;
  const detail = err?.response?.data?.detail;
  if (status === 401) return 'Your session has expired. Please sign in again.';
  if (status === 403) return "You don't have permission to view notifications.";
  if (status === 429) return 'Too many requests. Please try again shortly.';
  if (status === 503) return 'GreenShift backend is temporarily unavailable.';
  if (status >= 500) return 'An unexpected server error occurred while loading notifications.';
  if (!err?.response) return 'Unable to reach the GreenShift backend. Check your connection.';
  return detail || 'Failed to load notifications.';
}

type FilterTab = 'all' | 'unread' | string;

export const AlertsPage: React.FC = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<FilterTab>('all');

  const {
    data: notifications,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['alertsPageNotifications'],
    queryFn: () => notificationsApi.getNotifications({ limit: 100 }),
  });

  const invalidateNotificationCaches = () => {
    // Keep the header bell's independent queries in sync with this page's mutations.
    queryClient.invalidateQueries({ queryKey: ['alertsPageNotifications'] });
    queryClient.invalidateQueries({ queryKey: ['notifications'] });
    queryClient.invalidateQueries({ queryKey: ['notificationsUnreadCount'] });
  };

  const markReadMutation = useMutation({
    mutationFn: (id: number) => notificationsApi.markRead(id),
    onSuccess: invalidateNotificationCaches,
  });

  const markAllReadMutation = useMutation({
    mutationFn: () => notificationsApi.markAllRead(),
    onSuccess: invalidateNotificationCaches,
  });

  const items: NotificationItem[] = notifications ?? [];
  const unreadCount = items.filter((n) => !n.is_read).length;

  // Category tabs are derived from the notifications actually returned —
  // never a hardcoded list, since `category` is a free-form backend string.
  const categories = useMemo(() => {
    return Array.from(new Set(items.map((n) => n.category))).sort();
  }, [items]);

  const filteredItems = useMemo(() => {
    if (filter === 'all') return items;
    if (filter === 'unread') return items.filter((n) => !n.is_read);
    return items.filter((n) => n.category === filter);
  }, [items, filter]);

  const errorMessage = isError ? getErrorMessage(error) : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      <PageHeader
        title="Alerts & Notifications"
        subtitle="Real-time events from workload scheduling, approvals, execution, and account activity — sourced from your own notification feed"
        badge={
          <span className={`badge ${unreadCount > 0 ? 'badge-warning' : 'badge-success'}`}>
            {unreadCount} UNREAD
          </span>
        }
        actions={
          <div style={{ display: 'flex', gap: '0.6rem' }}>
            {unreadCount > 0 && (
              <button
                className="btn btn-secondary"
                onClick={() => markAllReadMutation.mutate()}
                disabled={markAllReadMutation.isPending}
              >
                <CheckCheck size={14} />
                <span>Mark All Read</span>
              </button>
            )}
            <button className="btn btn-secondary" onClick={() => refetch()} disabled={isFetching}>
              <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} />
              <span>Refresh</span>
            </button>
          </div>
        }
      />

      {/* Filter tabs — All / Unread / one per category actually present in the data */}
      {items.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
          <FilterChip label={`All (${items.length})`} active={filter === 'all'} onClick={() => setFilter('all')} />
          <FilterChip label={`Unread (${unreadCount})`} active={filter === 'unread'} onClick={() => setFilter('unread')} />
          {categories.map((c) => (
            <FilterChip
              key={c}
              label={`${categoryLabel(c)} (${items.filter((n) => n.category === c).length})`}
              active={filter === c}
              onClick={() => setFilter(c)}
            />
          ))}
        </div>
      )}

      {isLoading ? (
        <LoadingSkeleton rows={4} height={70} />
      ) : errorMessage ? (
        <InlineBanner
          variant="error"
          action={
            <button className="btn btn-secondary btn-sm" onClick={() => refetch()}>
              Retry
            </button>
          }
        >
          {errorMessage}
        </InlineBanner>
      ) : filteredItems.length === 0 ? (
        <EmptyState
          title={
            items.length === 0
              ? 'No Notifications Yet'
              : filter === 'unread'
              ? 'No Unread Notifications'
              : `No ${filter === 'all' ? '' : categoryLabel(filter)} Notifications`
          }
          description={
            items.length === 0
              ? 'GreenShift will notify you here as workloads are scheduled, approved, declined, or completed.'
              : 'Nothing matches this filter right now.'
          }
          icon={ShieldCheck}
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
          {filteredItems.map((n) => (
            <GlassCard
              key={n.id}
              style={{
                borderColor: n.is_read ? undefined : `${severityColor(n.severity)}66`,
                opacity: n.is_read ? 0.75 : 1,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
                <div style={{ display: 'flex', gap: '1rem', alignItems: 'flex-start' }}>
                  <div
                    style={{
                      width: '36px',
                      height: '36px',
                      borderRadius: 'var(--radius-sm)',
                      background: `${severityColor(n.severity)}26`,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      flexShrink: 0,
                    }}
                  >
                    {severityIcon(n.severity, 18)}
                  </div>

                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
                      <h4 style={{ fontSize: '0.95rem', margin: 0 }}>{n.title}</h4>
                      <span
                        className={`badge ${
                          n.severity === 'CRITICAL' ? 'badge-danger' : n.severity === 'WARNING' ? 'badge-warning' : 'badge-info'
                        }`}
                      >
                        {n.severity}
                      </span>
                      <span className="badge badge-neutral">{categoryLabel(n.category)}</span>
                    </div>

                    <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginTop: '0.4rem', lineHeight: 1.5 }}>
                      {n.message}
                    </p>

                    <div style={{ display: 'flex', gap: '1rem', fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.5rem', flexWrap: 'wrap' }}>
                      <span>Detected: {timeAgo(n.created_at)}</span>
                      {n.job_id && (
                        <button
                          onClick={() => navigate(`/workloads/${n.job_id}`)}
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '0.25rem',
                            background: 'none',
                            border: 'none',
                            color: '#38bdf8',
                            cursor: 'pointer',
                            padding: 0,
                            fontSize: '0.72rem',
                          }}
                        >
                          <span>View Workload {n.job_id}</span>
                          <ArrowRight size={11} />
                        </button>
                      )}
                    </div>
                  </div>
                </div>

                {!n.is_read ? (
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => markReadMutation.mutate(n.id)}
                    disabled={markReadMutation.isPending}
                  >
                    <Check size={14} />
                    <span>Mark Read</span>
                  </button>
                ) : (
                  <span style={{ fontSize: '0.75rem', color: '#10b981', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                    <Check size={13} />
                    Read
                  </span>
                )}
              </div>
            </GlassCard>
          ))}
        </div>
      )}
    </div>
  );
};

const FilterChip: React.FC<{ label: string; active: boolean; onClick: () => void }> = ({ label, active, onClick }) => (
  <button
    onClick={onClick}
    style={{
      border: '1px solid ' + (active ? 'rgba(16,185,129,0.4)' : 'var(--border-subtle)'),
      background: active ? 'rgba(16,185,129,0.12)' : 'var(--bg-surface-elevated)',
      color: active ? '#10b981' : 'var(--text-secondary)',
      fontSize: '0.75rem',
      fontWeight: 600,
      padding: '0.4rem 0.8rem',
      borderRadius: 'var(--radius-full)',
      cursor: 'pointer',
    }}
  >
    {label}
  </button>
);
