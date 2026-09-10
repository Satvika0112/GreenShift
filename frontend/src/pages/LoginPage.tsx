import React, { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Leaf,
  Lock,
  User,
  ShieldCheck,
  Building2,
  UserCircle,
  ArrowRight,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { InlineBanner } from '../components/common/InlineBanner';
import { UserRole } from '../types/api';

// UI-only labels for the three roles GreenShift actually supports
// (app.shared.models.UserRole). This selection never authenticates anyone —
// it is a preference the backend-verified role is compared against after
// login, purely to surface a clear message on mismatch.
const ROLE_OPTIONS: { value: UserRole; label: string; icon: typeof ShieldCheck; description: string }[] = [
  { value: 'PLATFORM_ADMIN', label: 'Platform Admin', icon: ShieldCheck, description: 'Global platform administration' },
  { value: 'COMPANY_ADMIN', label: 'Company Admin', icon: Building2, description: 'Manage your company/tenant' },
  { value: 'COMPANY_USER', label: 'Company User', icon: UserCircle, description: 'Standard company access' },
];

export const LoginPage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useAuth();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [selectedRole, setSelectedRole] = useState<UserRole | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [roleMismatchNotice, setRoleMismatchNotice] = useState<string | null>(null);

  const from = (location.state as any)?.from?.pathname || '/';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isLoading) return; // prevent duplicate submissions
    setIsLoading(true);
    setError(null);
    setRoleMismatchNotice(null);

    try {
      // The backend is the sole source of truth for identity and role.
      // selectedRole is never sent to the backend and never influences
      // which account is authenticated.
      await login(username, password);

      const authenticatedUser = JSON.parse(sessionStorage.getItem('greenshift_user') || 'null');
      if (selectedRole && authenticatedUser && authenticatedUser.role !== selectedRole) {
        setRoleMismatchNotice(
          `You selected "${ROLE_OPTIONS.find((r) => r.value === selectedRole)?.label}", but your account's actual role is ${authenticatedUser.role}. Signing you in with your real permissions.`
        );
        setTimeout(() => navigate(from, { replace: true }), 1400);
        setIsLoading(false);
        return;
      }

      navigate(from, { replace: true });
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Authentication failed. Please check credentials or backend connection.';
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg));
      setIsLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        width: '100vw',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'radial-gradient(ellipse at top, #141d30 0%, #080c14 70%)',
        padding: '1.5rem',
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: '460px',
          display: 'flex',
          flexDirection: 'column',
          gap: '1.5rem',
        }}
      >
        {/* Brand Header */}
        <div style={{ textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <div
            style={{
              width: '52px',
              height: '52px',
              borderRadius: 'var(--radius-md)',
              background: 'linear-gradient(135deg, rgba(16, 185, 129, 0.25), rgba(6, 182, 212, 0.25))',
              border: '1px solid rgba(16, 185, 129, 0.4)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#10b981',
              marginBottom: '1rem',
              boxShadow: '0 0 25px rgba(16, 185, 129, 0.25)',
            }}
          >
            <Leaf size={28} />
          </div>
          <h1 style={{ fontSize: '1.75rem', fontWeight: 800 }}>
            Green<span style={{ color: '#10b981' }}>Shift</span>
          </h1>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
            Carbon-Aware Workload Control Plane
          </p>
        </div>

        {/* Login Card */}
        <div
          style={{
            background: 'var(--bg-surface-glass)',
            backdropFilter: 'blur(16px)',
            WebkitBackdropFilter: 'blur(16px)',
            border: '1px solid var(--border-default)',
            borderRadius: 'var(--radius-lg)',
            padding: '2rem',
            boxShadow: 'var(--shadow-lg)',
          }}
        >
          {error && (
            <div style={{ marginBottom: '1.25rem' }}>
              <InlineBanner variant="error">{error}</InlineBanner>
            </div>
          )}

          {roleMismatchNotice && (
            <div style={{ marginBottom: '1.25rem' }}>
              <InlineBanner variant="info">{roleMismatchNotice}</InlineBanner>
            </div>
          )}

          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1.1rem' }}>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label" htmlFor="login-username">
                <User size={13} />
                <span>Identity / Username</span>
              </label>
              <input
                id="login-username"
                type="text"
                className="input"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                required
                disabled={isLoading}
              />
            </div>

            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label" htmlFor="login-password">
                <Lock size={13} />
                <span>Credential / Password</span>
              </label>
              <input
                id="login-password"
                type="password"
                className="input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
                disabled={isLoading}
              />
            </div>

            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label">Login Role</label>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.5rem' }}>
                {ROLE_OPTIONS.map((opt) => {
                  const isSelected = selectedRole === opt.value;
                  return (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setSelectedRole(isSelected ? null : opt.value)}
                      disabled={isLoading}
                      aria-pressed={isSelected}
                      style={{
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        gap: '0.3rem',
                        padding: '0.65rem 0.4rem',
                        borderRadius: 'var(--radius-sm)',
                        border: `1px solid ${isSelected ? '#10b981' : 'var(--border-default)'}`,
                        background: isSelected ? 'rgba(16, 185, 129, 0.1)' : 'transparent',
                        color: isSelected ? '#10b981' : 'var(--text-secondary)',
                        cursor: 'pointer',
                        textAlign: 'center',
                      }}
                    >
                      <opt.icon size={16} />
                      <span style={{ fontSize: '0.7rem', fontWeight: 600 }}>{opt.label}</span>
                    </button>
                  );
                })}
              </div>
              <p style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: '0.4rem', marginBottom: 0 }}>
                This is a preference only — your actual access is always determined by your account on the backend.
              </p>
            </div>

            <button
              type="submit"
              className="btn btn-primary"
              style={{ width: '100%', marginTop: '0.5rem', padding: '0.7rem' }}
              disabled={isLoading}
            >
              <span>{isLoading ? 'Authenticating…' : 'Sign In to Control Plane'}</span>
              <ArrowRight size={15} />
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};
