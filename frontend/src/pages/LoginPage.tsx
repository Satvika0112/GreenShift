import React, { useEffect, useState } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { Eye, EyeOff, Lock, User, ArrowRight } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { AuthLayout } from '../components/auth/AuthLayout';
import { InlineBanner } from '../components/common/InlineBanner';

// The backend distinguishes these account/company states with a fixed,
// safe-to-display `detail` string on a 403 response (see
// app/api/routers/auth.py). Mapping on those exact strings lets the login
// page show a dedicated status view without inventing any new backend
// contract.
type AccountStatus = 'PENDING' | 'REJECTED' | 'INACTIVE_ACCOUNT' | 'INACTIVE_COMPANY';

const ACCOUNT_STATUS_BY_DETAIL: Record<string, AccountStatus> = {
  'Account pending approval': 'PENDING',
  'User account registration was declined': 'REJECTED',
  'User account is deactivated': 'INACTIVE_ACCOUNT',
  'Company account is inactive': 'INACTIVE_COMPANY',
};

const ACCOUNT_STATUS_CONTENT: Record<AccountStatus, { title: string; message: string }> = {
  PENDING: {
    title: 'Pending Access',
    message: 'Your access request is pending approval. You will be able to sign in once an administrator approves your account.',
  },
  REJECTED: {
    title: 'Access Rejected',
    message: 'Your access request was not approved. Contact your administrator if you believe this is a mistake.',
  },
  INACTIVE_ACCOUNT: {
    title: 'Account Inactive',
    message: 'Your account has been deactivated. Contact your administrator to restore access.',
  },
  INACTIVE_COMPANY: {
    title: 'Company Inactive',
    message: "Your company's account is inactive. Contact your administrator for assistance.",
  },
};

export const LoginPage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useAuth();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessionExpiredNotice, setSessionExpiredNotice] = useState<string | null>(null);
  const [accountStatus, setAccountStatus] = useState<AccountStatus | null>(null);

  const from = (location.state as any)?.from?.pathname || '/';

  useEffect(() => {
    if (sessionStorage.getItem('greenshift_session_expired')) {
      sessionStorage.removeItem('greenshift_session_expired');
      setSessionExpiredNotice('Your session has expired. Please sign in again.');
    }
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isLoading) return; // prevent duplicate submissions
    setIsLoading(true);
    setError(null);
    setSessionExpiredNotice(null);

    try {
      // The backend is the sole source of truth for identity and role —
      // this call never selects or influences which role is granted.
      await login(username, password);
      navigate(from, { replace: true });
    } catch (err: any) {
      const status = err.response?.status;
      const detail = err.response?.data?.detail;

      if (status === 403 && typeof detail === 'string' && ACCOUNT_STATUS_BY_DETAIL[detail]) {
        setAccountStatus(ACCOUNT_STATUS_BY_DETAIL[detail]);
      } else if (status === 401) {
        setError('Invalid username or password.');
      } else {
        // Never surface raw backend exceptions / network details.
        setError('Unable to sign in right now. Please try again.');
      }
      setIsLoading(false);
    }
  };

  if (accountStatus) {
    const content = ACCOUNT_STATUS_CONTENT[accountStatus];
    return (
      <AuthLayout subtitle="Sign in to your account">
        <div style={{ textAlign: 'center', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <h2 style={{ fontSize: '1.1rem', fontWeight: 700 }}>{content.title}</h2>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', margin: 0 }}>{content.message}</p>
          <button
            type="button"
            className="btn btn-secondary"
            style={{ alignSelf: 'center' }}
            onClick={() => {
              setAccountStatus(null);
              setPassword('');
            }}
          >
            Back to Sign In
          </button>
        </div>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout subtitle="Sign in to your account">
      {error && (
        <div style={{ marginBottom: '1.25rem' }}>
          <InlineBanner variant="error">{error}</InlineBanner>
        </div>
      )}

      {sessionExpiredNotice && (
        <div style={{ marginBottom: '1.25rem' }}>
          <InlineBanner variant="info">{sessionExpiredNotice}</InlineBanner>
        </div>
      )}

      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1.1rem' }}>
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label className="form-label" htmlFor="login-username">
            <User size={13} />
            <span>Username or Email</span>
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
            <span>Password</span>
          </label>
          <div style={{ position: 'relative' }}>
            <input
              id="login-password"
              type={showPassword ? 'text' : 'password'}
              className="input"
              style={{ paddingRight: '2.5rem' }}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
              disabled={isLoading}
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              disabled={isLoading}
              style={{
                position: 'absolute',
                right: '0.6rem',
                top: '50%',
                transform: 'translateY(-50%)',
                background: 'transparent',
                border: 'none',
                padding: '0.2rem',
                cursor: 'pointer',
                color: 'var(--text-secondary)',
                display: 'flex',
                alignItems: 'center',
              }}
            >
              {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
        </div>

        <button
          type="submit"
          className="btn btn-primary"
          style={{ width: '100%', marginTop: '0.5rem', padding: '0.7rem' }}
          disabled={isLoading}
        >
          <span>{isLoading ? 'Signing in…' : 'Sign In'}</span>
          <ArrowRight size={15} />
        </button>
      </form>

      <p style={{ textAlign: 'center', fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '1.25rem', marginBottom: 0 }}>
        Don&apos;t have an account?{' '}
        <Link to="/register" style={{ color: '#10b981', fontWeight: 600, textDecoration: 'none' }}>
          Request access
        </Link>
      </p>
    </AuthLayout>
  );
};
