import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { Eye, EyeOff, Lock, Mail, User } from 'lucide-react';
import { AuthLayout } from '../components/auth/AuthLayout';
import { InlineBanner } from '../components/common/InlineBanner';
import { authApi } from '../api/endpoints';

// Backed by the real POST /auth/register endpoint. When auth is enabled
// (production) it creates a COMPANY_USER pending admin approval; there is no
// separate "request access" concept in the backend beyond registration, so
// this page is a thin, honest front end for that one real endpoint.
export const RequestAccessPage: React.FC = () => {
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submittedStatus, setSubmittedStatus] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isLoading) return;
    setError(null);

    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }

    setIsLoading(true);
    try {
      const user = await authApi.register({ username, email, password });
      setSubmittedStatus(user.approval_status || 'PENDING');
    } catch (err: any) {
      const status = err.response?.status;
      const detail = err.response?.data?.detail;
      if (status === 409 && typeof detail === 'string') {
        // Safe, backend-provided conflict message (e.g. username taken).
        setError(detail);
      } else if (status === 422) {
        setError('Please check your username, email, and password and try again.');
      } else {
        setError('Unable to submit your request right now. Please try again.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  if (submittedStatus) {
    const isPending = submittedStatus === 'PENDING';
    return (
      <AuthLayout subtitle="Request access">
        <div style={{ textAlign: 'center', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <h2 style={{ fontSize: '1.1rem', fontWeight: 700 }}>
            {isPending ? 'Request Submitted' : 'Account Created'}
          </h2>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', margin: 0 }}>
            {isPending
              ? 'Your access request has been submitted for approval. You will be able to sign in once an administrator approves your account.'
              : 'Your account has been created. You can now sign in.'}
          </p>
          <Link to="/login" className="btn btn-primary" style={{ alignSelf: 'center', textDecoration: 'none' }}>
            Back to Sign In
          </Link>
        </div>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout subtitle="Request access">
      {error && (
        <div style={{ marginBottom: '1.25rem' }}>
          <InlineBanner variant="error">{error}</InlineBanner>
        </div>
      )}

      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1.1rem' }}>
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label className="form-label" htmlFor="register-username">
            <User size={13} />
            <span>Username</span>
          </label>
          <input
            id="register-username"
            type="text"
            className="input"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            minLength={3}
            maxLength={50}
            required
            disabled={isLoading}
          />
        </div>

        <div className="form-group" style={{ marginBottom: 0 }}>
          <label className="form-label" htmlFor="register-email">
            <Mail size={13} />
            <span>Email</span>
          </label>
          <input
            id="register-email"
            type="email"
            className="input"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            required
            disabled={isLoading}
          />
        </div>

        <div className="form-group" style={{ marginBottom: 0 }}>
          <label className="form-label" htmlFor="register-password">
            <Lock size={13} />
            <span>Password</span>
          </label>
          <div style={{ position: 'relative' }}>
            <input
              id="register-password"
              type={showPassword ? 'text' : 'password'}
              className="input"
              style={{ paddingRight: '2.5rem' }}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              minLength={6}
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

        <div className="form-group" style={{ marginBottom: 0 }}>
          <label className="form-label" htmlFor="register-confirm-password">
            <Lock size={13} />
            <span>Confirm Password</span>
          </label>
          <input
            id="register-confirm-password"
            type={showPassword ? 'text' : 'password'}
            className="input"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            autoComplete="new-password"
            minLength={6}
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
          {isLoading ? 'Submitting…' : 'Request Access'}
        </button>
      </form>

      <p style={{ textAlign: 'center', fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '1.25rem', marginBottom: 0 }}>
        Already have an account?{' '}
        <Link to="/login" style={{ color: '#10b981', fontWeight: 600, textDecoration: 'none' }}>
          Sign in
        </Link>
      </p>
    </AuthLayout>
  );
};
