import React, { useState, useRef, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Bell, CheckCheck, Inbox } from 'lucide-react';
import { notificationsApi } from '../../api/endpoints';
import { NotificationItem } from '../../types/api';
import { useAuth } from '../../context/AuthContext';
import { severityIcon, timeAgo } from '../../utils/notificationDisplay';

export const NotificationBell: React.FC = () => {
  const { isAuthenticated } = useAuth();
  const [isOpen, setIsOpen] = useState(false);
  const [filter, setFilter] = useState<'all' | 'unread'>('all');
  const containerRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  // Unread count: polled continuously (used for the badge, even while closed).
  const { data: unreadData } = useQuery({
    queryKey: ['notificationsUnreadCount'],
    queryFn: () => notificationsApi.getUnreadCount(),
    enabled: isAuthenticated,
    refetchInterval: 30000,
  });
  const unreadCount = unreadData?.unread_count ?? 0;

  // Full list: only fetched while the panel is open.
  const { data: notifications, isLoading } = useQuery({
    queryKey: ['notifications', filter],
    queryFn: () => notificationsApi.getNotifications({ unread_only: filter === 'unread', limit: 50 }),
    enabled: isAuthenticated && isOpen,
    refetchInterval: isOpen ? 20000 : false,
  });

  const markReadMutation = useMutation({
    mutationFn: (id: number) => notificationsApi.markRead(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
      queryClient.invalidateQueries({ queryKey: ['notificationsUnreadCount'] });
    },
  });

  const markAllReadMutation = useMutation({
    mutationFn: () => notificationsApi.markAllRead(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
      queryClient.invalidateQueries({ queryKey: ['notificationsUnreadCount'] });
    },
  });

  // Close on outside click or Escape key
  useEffect(() => {
    if (!isOpen) return;
    const handleOutsideClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleOutsideClick);
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleOutsideClick);
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen]);

  if (!isAuthenticated) return null;

  const items: NotificationItem[] = notifications ?? [];

  return (
    <div ref={containerRef} style={{ position: 'relative' }}>
      <button
        className="btn btn-secondary btn-sm"
        style={{ position: 'relative', padding: '0.45rem 0.6rem' }}
        onClick={() => setIsOpen((v) => !v)}
        title="Notifications"
        aria-label="Notifications"
        aria-haspopup="dialog"
        aria-expanded={isOpen}
      >
        <Bell size={15} color="#94a3b8" />
        {unreadCount > 0 && (
          <span
            style={{
              position: 'absolute',
              top: '-4px',
              right: '-4px',
              minWidth: '16px',
              height: '16px',
              padding: '0 4px',
              borderRadius: 'var(--radius-full)',
              background: '#ef4444',
              color: '#fff',
              fontSize: '0.62rem',
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              lineHeight: 1,
            }}
          >
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <div
          role="region"
          aria-label="Notifications Panel"
          style={{
            position: 'absolute',
            top: '120%',
            right: 0,
            width: '380px',
            maxHeight: '480px',
            display: 'flex',
            flexDirection: 'column',
            background: 'var(--bg-surface-elevated)',
            border: '1px solid var(--border-strong)',
            borderRadius: 'var(--radius-md)',
            boxShadow: 'var(--shadow-lg)',
            zIndex: 60,
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '0.75rem 1rem',
              borderBottom: '1px solid var(--border-subtle)',
            }}
          >
            <span style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-primary)' }}>
              Notifications
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <div style={{ display: 'flex', background: 'rgba(255,255,255,0.04)', borderRadius: 'var(--radius-sm)', padding: '2px' }}>
                <button
                  onClick={() => setFilter('all')}
                  style={{
                    border: 'none',
                    background: filter === 'all' ? 'rgba(16,185,129,0.15)' : 'transparent',
                    color: filter === 'all' ? '#10b981' : 'var(--text-muted)',
                    fontSize: '0.68rem',
                    fontWeight: 600,
                    padding: '0.25rem 0.5rem',
                    borderRadius: 'var(--radius-sm)',
                    cursor: 'pointer',
                  }}
                >
                  All
                </button>
                <button
                  onClick={() => setFilter('unread')}
                  style={{
                    border: 'none',
                    background: filter === 'unread' ? 'rgba(16,185,129,0.15)' : 'transparent',
                    color: filter === 'unread' ? '#10b981' : 'var(--text-muted)',
                    fontSize: '0.68rem',
                    fontWeight: 600,
                    padding: '0.25rem 0.5rem',
                    borderRadius: 'var(--radius-sm)',
                    cursor: 'pointer',
                  }}
                >
                  Unread
                </button>
              </div>
              {unreadCount > 0 && (
                <button
                  onClick={() => markAllReadMutation.mutate()}
                  disabled={markAllReadMutation.isPending}
                  title="Mark all as read"
                  aria-label="Mark all notifications as read"
                  style={{
                    border: 'none',
                    background: 'transparent',
                    color: 'var(--text-muted)',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                  }}
                >
                  <CheckCheck size={15} />
                </button>
              )}
            </div>
          </div>

          <div style={{ overflowY: 'auto', flex: 1 }}>
            {isLoading ? (
              <div style={{ padding: '1.5rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                Loading...
              </div>
            ) : items.length === 0 ? (
              <div style={{ padding: '2.5rem 1.5rem', textAlign: 'center' }}>
                <Inbox size={28} color="var(--text-muted)" style={{ marginBottom: '0.5rem' }} />
                <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                  {filter === 'unread' ? 'No unread notifications' : 'No notifications yet'}
                </div>
              </div>
            ) : (
              items.map((n) => (
                <div
                  key={n.id}
                  onClick={() => !n.is_read && markReadMutation.mutate(n.id)}
                  style={{
                    display: 'flex',
                    gap: '0.65rem',
                    padding: '0.75rem 1rem',
                    borderBottom: '1px solid var(--border-subtle)',
                    background: n.is_read ? 'transparent' : 'rgba(16, 185, 129, 0.04)',
                    cursor: n.is_read ? 'default' : 'pointer',
                  }}
                >
                  <div style={{ flexShrink: 0, marginTop: '0.15rem' }}>{severityIcon(n.severity)}</div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                      <span style={{ fontSize: '0.8rem', fontWeight: n.is_read ? 500 : 700, color: 'var(--text-primary)' }}>
                        {n.title}
                      </span>
                      {!n.is_read && (
                        <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#10b981', flexShrink: 0 }} />
                      )}
                    </div>
                    <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', margin: '0.2rem 0 0.3rem', lineHeight: 1.4 }}>
                      {n.message}
                    </p>
                    <div style={{ display: 'flex', gap: '0.5rem', fontSize: '0.66rem', color: 'var(--text-muted)' }}>
                      <span>{n.category}</span>
                      <span>•</span>
                      <span>{timeAgo(n.created_at)}</span>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
};
