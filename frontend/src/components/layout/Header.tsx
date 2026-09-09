import React, { useState } from 'react';
import { useAuth, PRESET_CREDENTIALS } from '../../context/AuthContext';
import { UserCheck, Shield, LogOut, Check, Activity, RefreshCw } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

interface HeaderProps {
  onRefresh?: () => void;
  isRefreshing?: boolean;
}

export const Header: React.FC<HeaderProps> = ({ onRefresh, isRefreshing = false }) => {
  const { user, login, logout } = useAuth();
  const [showRoleMenu, setShowRoleMenu] = useState(false);
  const [switching, setSwitching] = useState(false);
  const navigate = useNavigate();

  const handleSwitchUser = async (cred: typeof PRESET_CREDENTIALS[0]) => {
    setSwitching(true);
    try {
      await login(cred.username, cred.password);
      setShowRoleMenu(false);
      window.location.reload();
    } catch (err) {
      alert(`Failed to switch to ${cred.username}: backend auth error`);
    } finally {
      setSwitching(false);
    }
  };

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
        padding: '0 1.75rem',
        position: 'sticky',
        top: 0,
        zIndex: 30,
      }}
    >
      {/* Left: Cluster Grid Telemetry Status */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem' }}>
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '0.5rem',
            background: 'rgba(16, 185, 129, 0.08)',
            border: '1px solid rgba(16, 185, 129, 0.2)',
            padding: '0.35rem 0.75rem',
            borderRadius: 'var(--radius-full)',
          }}
        >
          <span className="pulse-dot" style={{ color: '#10b981' }} />
          <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#10b981', letterSpacing: '0.02em' }}>
            GRID TELEMETRY: CONNECTED
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
          <Activity size={14} />
          <span>Multi-Region Carbon Dispatch Engine</span>
        </div>
      </div>

      {/* Right: Persona Switcher, Refresh, User Profile */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
        {onRefresh && (
          <button
            className="btn btn-secondary btn-sm"
            onClick={onRefresh}
            disabled={isRefreshing}
            title="Refresh Control Plane Data"
          >
            <RefreshCw size={14} className={isRefreshing ? 'animate-spin' : ''} />
            <span>Sync</span>
          </button>
        )}

        {/* Development Persona Switcher (Authenticates against backend) */}
        {(import.meta.env.DEV || import.meta.env.VITE_ENABLE_DEMO_PERSONAS === 'true') && (
          <div style={{ position: 'relative' }}>
            <button
              className="btn btn-secondary btn-sm"
              style={{
                borderColor: 'rgba(56, 189, 248, 0.3)',
                background: 'rgba(56, 189, 248, 0.05)',
                color: '#38bdf8',
                gap: '0.4rem',
              }}
              onClick={() => setShowRoleMenu(!showRoleMenu)}
              disabled={switching}
            >
              <Shield size={14} />
              <span>Switch Role / Team</span>
            </button>

            {showRoleMenu && (
              <div
                style={{
                  position: 'absolute',
                  top: '120%',
                  right: 0,
                  width: '260px',
                  background: 'var(--bg-surface-elevated)',
                  border: '1px solid var(--border-strong)',
                  borderRadius: 'var(--radius-md)',
                  boxShadow: 'var(--shadow-lg)',
                  padding: '0.5rem',
                  zIndex: 50,
                }}
              >
                <div
                  style={{
                    fontSize: '0.7rem',
                    fontWeight: 700,
                    color: 'var(--text-muted)',
                    textTransform: 'uppercase',
                    padding: '0.35rem 0.5rem',
                    letterSpacing: '0.04em',
                  }}
                >
                  Switch Persona (Backend Authenticated)
                </div>
                {PRESET_CREDENTIALS.map((cred) => {
                  const isSelected = user?.username === cred.username;
                  return (
                    <button
                      key={cred.key}
                      onClick={() => handleSwitchUser(cred)}
                      disabled={switching}
                      style={{
                        width: '100%',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '0.45rem 0.6rem',
                        borderRadius: 'var(--radius-sm)',
                        border: 'none',
                        background: isSelected ? 'rgba(16, 185, 129, 0.1)' : 'transparent',
                        color: isSelected ? '#10b981' : 'var(--text-primary)',
                        cursor: 'pointer',
                        textAlign: 'left',
                      }}
                    >
                      <div>
                        <div style={{ fontSize: '0.82rem', fontWeight: 600 }}>{cred.username}</div>
                        <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>
                          {cred.role} • {cred.team}
                        </div>
                      </div>
                      {isSelected && <Check size={14} color="#10b981" />}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        )}

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
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <span style={{ fontSize: '0.82rem', fontWeight: 700 }}>{user?.username}</span>
            <span style={{ fontSize: '0.68rem', color: '#10b981', fontWeight: 600 }}>{user?.role}</span>
          </div>
        </div>

        {/* User logout */}
        <button
          className="btn btn-secondary btn-sm"
          style={{ padding: '0.4rem 0.6rem', marginLeft: '0.5rem' }}
          onClick={handleLogout}
          title="Sign Out"
        >
          <LogOut size={15} color="#94a3b8" />
        </button>
      </div>
    </header>
  );
};
