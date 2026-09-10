import React, { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Leaf,
  Lock,
  User,
  Shield,
  ArrowRight,
  Sparkles,
} from 'lucide-react';
import { useAuth, PRESET_CREDENTIALS } from '../context/AuthContext';
import { InlineBanner } from '../components/common/InlineBanner';

export const LoginPage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useAuth();

  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('admin123');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const from = (location.state as any)?.from?.pathname || '/';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError(null);

    try {
      await login(username, password);
      navigate(from, { replace: true });
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Authentication failed. Please check credentials or backend connection.';
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg));
    } finally {
      setIsLoading(false);
    }
  };

  const handleQuickLogin = async (userKey: string, defaultPw: string) => {
    setUsername(userKey);
    setPassword(defaultPw);
    setIsLoading(true);
    setError(null);
    try {
      await login(userKey, defaultPw);
      navigate(from, { replace: true });
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Authentication failed for seed persona.';
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg));
    } finally {
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
            Enterprise Carbon-Aware Orchestration Control Plane
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

          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1.1rem' }}>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label">
                <User size={13} />
                <span>Identity / Username</span>
              </label>
              <input
                type="text"
                className="input"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                disabled={isLoading}
              />
            </div>

            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label">
                <Lock size={13} />
                <span>Credential / Password</span>
              </label>
              <input
                type="password"
                className="input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={isLoading}
              />
            </div>

            <button
              type="submit"
              className="btn btn-primary"
              style={{ width: '100%', marginTop: '0.5rem', padding: '0.7rem' }}
              disabled={isLoading}
            >
              <span>{isLoading ? 'Authenticating with Backend...' : 'Sign In to Control Plane'}</span>
              <ArrowRight size={15} />
            </button>
          </form>

          {/* Seed Personas for Verified Real Authentication */}
          <div style={{ marginTop: '1.75rem', paddingTop: '1.25rem', borderTop: '1px solid var(--border-subtle)' }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.4rem',
                fontSize: '0.75rem',
                fontWeight: 700,
                color: 'var(--text-muted)',
                marginBottom: '0.75rem',
                textTransform: 'uppercase',
                letterSpacing: '0.04em',
              }}
            >
              <Sparkles size={13} color="#10b981" />
              <span>Quick Seed Personas (Authenticates via Backend)</span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.6rem' }}>
              {PRESET_CREDENTIALS.map((cred) => (
                <button
                  key={cred.key}
                  type="button"
                  className="btn btn-secondary btn-sm"
                  style={{ justifyContent: 'flex-start' }}
                  disabled={isLoading}
                  onClick={() => handleQuickLogin(cred.username, cred.password)}
                >
                  <Shield size={12} color="#10b981" />
                  <span>{cred.label} ({cred.role})</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
