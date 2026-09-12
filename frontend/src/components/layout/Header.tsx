import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '../../context/AuthContext';
import { LogOut, Activity, RefreshCw, Menu } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { NotificationBell } from './NotificationBell';
import { monitoringApi } from '../../api/endpoints';
import { useMediaQuery } from '../../hooks/useMediaQuery';

interface HeaderProps {
  onRefresh?: () => void;
  isRefreshing?: boolean;
  onToggleNav?: () => void;
  isNavOpen?: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  onRefresh,
  isRefreshing = false,
  onToggleNav,
  isNavOpen = false,
}) => {
  const { user, logout, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const isNarrow = useMediaQuery('(max-width: 900px)');

  // Real connectivity probe against GET /live — matches the same 15s cadence
  // already used by the sidebar's badge queries. Replaces a previous always-on
  // "CONNECTED" pill that never reflected actual backend reachability.
  const { data: liveStatus, isError: isLiveError } = useQuery({
    queryKey: ['headerLiveStatus'],
    queryFn: () => monitoringApi.getSystemLive(),
    enabled: isAuthenticated,
    refetchInterval: 15000,
    retry: false,
  });
  const isLive = liveStatus?.status === 'alive';

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <header
      style={{
        height: 'var(--header-height)',
        background: 'var(--bg-surface)',
        borderBottom: '1px solid var(--border-subtle)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: isNarrow ? '0 1rem' : '0 1.75rem',
        position: 'sticky',
        top: 0,
        zIndex: 30,
      }}
    >
      {/* Left: Nav Toggle (mobile) + Cluster Grid Telemetry Status */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem', minWidth: 0 }}>
        {onToggleNav && (
          <button
            className="btn btn-secondary btn-sm"
            onClick={onToggleNav}
            title="Toggle navigation"
            aria-label="Toggle navigation menu"
            aria-expanded={isNavOpen}
            style={{ padding: '0.4rem 0.55rem', flexShrink: 0 }}
          >
            <Menu size={16} />
          </button>
        )}

        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '0.5rem',
            background: isLive ? 'rgba(16, 185, 129, 0.08)' : 'rgba(239, 68, 68, 0.1)',
            border: `1px solid ${isLive ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.25)'}`,
            padding: '0.35rem 0.75rem',
            borderRadius: 'var(--radius-full)',
            flexShrink: 0,
          }}
        >
          <span className="pulse-dot" style={{ color: isLive ? '#10b981' : '#ef4444' }} />
          <span style={{ fontSize: '0.75rem', fontWeight: 600, color: isLive ? '#10b981' : '#ef4444', letterSpacing: '0.02em' }}>
            {isNarrow
              ? isLive ? 'CONNECTED' : isLiveError ? 'UNREACHABLE' : 'CHECKING...'
              : isLive ? 'BACKEND: CONNECTED' : isLiveError ? 'BACKEND: UNREACHABLE' : 'BACKEND: CHECKING...'}
          </span>
        </div>

        {!isNarrow && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            <Activity size={14} />
            <span>Multi-Region Carbon Dispatch Engine</span>
          </div>
        )}
      </div>

      {/* Right: Persona Switcher, Refresh, User Profile */}
      <div style={{ display: 'flex', alignItems: 'center', gap: isNarrow ? '0.5rem' : '0.85rem' }}>
        {onRefresh && (
          <button
            className="btn btn-secondary btn-sm"
            onClick={onRefresh}
            disabled={isRefreshing}
            title="Refresh Control Plane Data"
            aria-label="Refresh Control Plane Data"
          >
            <RefreshCw size={14} className={isRefreshing ? 'animate-spin' : ''} />
            {!isNarrow && <span>Sync</span>}
          </button>
        )}

        <NotificationBell />

        {/* Current User Info */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginLeft: '0.5rem' }}>
          <div
            style={{
              width: '32px',
              height: '32px',
              borderRadius: 'var(--radius-full)',
              background: 'linear-gradient(135deg, #10b981, #06b6d4)',
              color: '#080c14',
              fontWeight: 800,
              fontSize: '0.8rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            {user?.username?.charAt(0).toUpperCase() || 'U'}
          </div>
          {!isNarrow && (
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              {user?.company_name && (
                <span style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--text-primary)' }}>{user.company_name}</span>
              )}
              <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)' }}>{user?.username}</span>
              <span style={{ fontSize: '0.68rem', color: '#10b981', fontWeight: 600 }}>{user?.role}</span>
            </div>
          )}
        </div>

        {/* User logout */}
        <button
          className="btn btn-secondary btn-sm"
          style={{ padding: '0.4rem 0.6rem', marginLeft: '0.5rem' }}
          onClick={handleLogout}
          title="Sign Out"
          aria-label="Sign Out"
        >
          <LogOut size={15} color="#94a3b8" />
        </button>
      </div>
    </header>
  );
};
