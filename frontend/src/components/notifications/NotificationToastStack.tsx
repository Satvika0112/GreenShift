import React from 'react';
import { useNavigate } from 'react-router-dom';
import { X } from 'lucide-react';
import { useRealtimeNotifications } from '../../context/RealtimeNotificationContext';
import { severityIcon, categoryLabel } from '../../utils/notificationDisplay';

/**
 * Non-blocking real-time toast popups, stacked top-right. Severity-aware:
 * CRITICAL notifications stay until manually dismissed; everything else
 * auto-dismisses (see RealtimeNotificationContext). Clicking a toast (not
 * its close button) navigates to the notification's backend-resolved
 * action_url, same destination the bell dropdown uses.
 */
export const NotificationToastStack: React.FC = () => {
  const { toasts, dismissToast } = useRealtimeNotifications();
  const navigate = useNavigate();

  if (toasts.length === 0) return null;

  return (
    <div
      role="region"
      aria-label="Notification popups"
      style={{
        position: 'fixed',
        top: '1rem',
        right: '1rem',
        left: 'auto',
        zIndex: 1000,
        display: 'flex',
        flexDirection: 'column',
        gap: '0.6rem',
        width: 'min(360px, calc(100vw - 2rem))',
        maxWidth: 'calc(100vw - 2rem)',
        pointerEvents: 'none',
      }}
    >
      {toasts.map((t) => {
        const n = t.notification;
        const borderColor = n.severity === 'CRITICAL' ? '#ef4444' : n.severity === 'WARNING' ? '#f59e0b' : 'var(--border-strong)';
        return (
          <div
            key={t.toastId}
            role="alert"
            aria-live={t.urgent ? 'assertive' : 'polite'}
            style={{
              pointerEvents: 'auto',
              background: 'var(--bg-surface-elevated)',
              border: `1px solid ${borderColor}`,
              borderLeftWidth: '4px',
              borderRadius: 'var(--radius-md)',
              boxShadow: 'var(--shadow-lg)',
              padding: '0.8rem 0.9rem',
              cursor: n.action_url ? 'pointer' : 'default',
              animation: 'gs-toast-in 0.18s ease-out',
            }}
            onClick={() => {
              if (n.action_url) navigate(n.action_url);
              dismissToast(t.toastId);
            }}
          >
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.6rem' }}>
              <div style={{ flexShrink: 0, marginTop: '0.1rem' }}>{severityIcon(n.severity, 17)}</div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem' }}>
                  <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-primary)' }}>{n.title}</span>
                  <button
                    type="button"
                    aria-label="Dismiss notification"
                    onClick={(e) => {
                      e.stopPropagation();
                      dismissToast(t.toastId);
                    }}
                    style={{
                      border: 'none',
                      background: 'transparent',
                      color: 'var(--text-muted)',
                      cursor: 'pointer',
                      flexShrink: 0,
                      display: 'flex',
                      padding: '0.1rem',
                    }}
                  >
                    <X size={14} />
                  </button>
                </div>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', margin: '0.3rem 0 0.4rem', lineHeight: 1.4 }}>
                  {n.message}
                </p>
                <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.03em' }}>
                  {categoryLabel(n.category)}
                  {n.action_url && <span style={{ marginLeft: '0.5rem', color: '#10b981' }}>Click to view →</span>}
                </div>
              </div>
            </div>
          </div>
        );
      })}
      <style>{`
        @keyframes gs-toast-in {
          from { opacity: 0; transform: translateY(-6px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
};
