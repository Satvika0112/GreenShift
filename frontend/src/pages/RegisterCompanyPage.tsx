import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { Eye, EyeOff, Lock, Mail, User, Building2, Globe, MapPin, CheckCircle2, ArrowRight, ArrowLeft } from 'lucide-react';
import { AuthLayout } from '../components/auth/AuthLayout';
import { InlineBanner } from '../components/common/InlineBanner';
import { companiesApi } from '../api/endpoints';
import { CompanyRegisterResponse } from '../types/api';

interface FormState {
  company_name: string;
  legal_name: string;
  company_email: string;
  website: string;
  industry: string;
  sector: string;
  country: string;
  address: string;
  admin_name: string;
  admin_email: string;
  password: string;
  confirm_password: string;
}

const EMPTY_FORM: FormState = {
  company_name: '', legal_name: '', company_email: '', website: '',
  industry: '', sector: '', country: '', address: '',
  admin_name: '', admin_email: '', password: '', confirm_password: '',
};

// Extracts a human-readable message from either a plain-string `detail`
// (business-logic errors like duplicate company/email — see
// app.companies.service) or FastAPI's default Pydantic-validation `detail`
// array (a 422 from CompanyRegisterRequest's own field validators).
function extractErrorMessage(err: any): string {
  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    return detail.map((d: any) => d.msg || String(d)).join(' ');
  }
  return 'Registration failed. Please check your details and try again.';
}

export const RegisterCompanyPage: React.FC = () => {
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CompanyRegisterResponse | null>(null);

  const setField = (field: keyof FormState) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    setForm((f) => ({ ...f, [field]: e.target.value }));
  };

  const validateStep1 = (): string | null => {
    if (!form.company_name.trim() || form.company_name.trim().length < 2) return 'Company name is required.';
    if (!form.company_email.trim()) return 'Company email is required.';
    if (!form.industry.trim()) return 'Industry is required.';
    if (!form.country.trim()) return 'Country is required.';
    return null;
  };

  const validateStep2 = (): string | null => {
    if (!form.admin_name.trim() || form.admin_name.trim().length < 2) return 'Administrator name is required.';
    if (!form.admin_email.trim()) return 'Administrator email is required.';
    if (form.password.length < 8) return 'Password must be at least 8 characters long.';
    if (!/[A-Z]/.test(form.password) || !/[a-z]/.test(form.password) || !/\d/.test(form.password)) {
      return 'Password must contain an uppercase letter, a lowercase letter, and a digit.';
    }
    if (form.password !== form.confirm_password) return 'Password and confirm password do not match.';
    return null;
  };

  const handleNext = () => {
    setError(null);
    const validationError = step === 1 ? validateStep1() : step === 2 ? validateStep2() : null;
    if (validationError) {
      setError(validationError);
      return;
    }
    setStep((s) => (s === 1 ? 2 : s === 2 ? 3 : 3));
  };

  const handleBack = () => {
    setError(null);
    setStep((s) => (s === 3 ? 2 : s === 2 ? 1 : 1));
  };

  const handleSubmit = async () => {
    setIsLoading(true);
    setError(null);
    try {
      // The backend is the sole source of truth for role/tenant_id/team_id —
      // this request body has no such fields, and the server would ignore
      // them even if a hostile client added them.
      const res = await companiesApi.register({
        company_name: form.company_name.trim(),
        legal_name: form.legal_name.trim() || undefined,
        company_email: form.company_email.trim(),
        website: form.website.trim() || undefined,
        industry: form.industry.trim(),
        sector: form.sector.trim() || undefined,
        country: form.country.trim(),
        address: form.address.trim() || undefined,
        admin_name: form.admin_name.trim(),
        admin_email: form.admin_email.trim(),
        password: form.password,
        confirm_password: form.confirm_password,
      });
      setResult(res);
    } catch (err: any) {
      setError(extractErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  };

  if (result) {
    return (
      <AuthLayout subtitle="Company registered">
        <div style={{ textAlign: 'center', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div style={{ display: 'flex', justifyContent: 'center' }}>
            <CheckCircle2 size={40} color="#10b981" />
          </div>
          <h2 style={{ fontSize: '1.15rem', fontWeight: 700 }}>Company registered successfully</h2>
          <div style={{ textAlign: 'left', background: 'var(--bg-surface-elevated)', borderRadius: 'var(--radius-sm)', padding: '1rem', fontSize: '0.85rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Company</span>
              <span style={{ fontWeight: 700 }}>{result.company_name}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Administrator account</span>
              <span style={{ fontWeight: 700 }}>{result.admin.username}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Role</span>
              <span style={{ fontWeight: 700, color: '#10b981' }}>Company Admin</span>
            </div>
          </div>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', margin: 0 }}>
            You can now sign in with your administrator email/username and password.
          </p>
          <Link to="/login" className="btn btn-primary" style={{ alignSelf: 'center', textDecoration: 'none' }}>
            Go to Login
          </Link>
        </div>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout subtitle="Register your organization">
      {error && (
        <div style={{ marginBottom: '1.25rem' }}>
          <InlineBanner variant="error">{error}</InlineBanner>
        </div>
      )}

      {/* Step indicator */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem', marginBottom: '1.25rem' }}>
        {[1, 2, 3].map((n) => (
          <React.Fragment key={n}>
            <div
              style={{
                width: '26px', height: '26px', borderRadius: '50%',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: '0.75rem', fontWeight: 700,
                background: step >= n ? '#10b981' : 'var(--bg-surface-elevated)',
                color: step >= n ? '#080c14' : 'var(--text-muted)',
                border: step >= n ? 'none' : '1px solid var(--border-subtle)',
              }}
            >
              {n}
            </div>
            {n < 3 && <div style={{ width: '28px', height: '2px', background: step > n ? '#10b981' : 'var(--border-subtle)' }} />}
          </React.Fragment>
        ))}
      </div>

      {step === 1 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.1rem' }}>
          <h2 style={{ fontSize: '0.95rem', fontWeight: 700, margin: 0 }}>Company Details</h2>

          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label" htmlFor="company-name"><Building2 size={13} /><span>Company Name *</span></label>
            <input id="company-name" className="input" value={form.company_name} onChange={setField('company_name')} maxLength={200} required disabled={isLoading} />
          </div>

          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label" htmlFor="legal-name"><Building2 size={13} /><span>Legal Name</span></label>
            <input id="legal-name" className="input" value={form.legal_name} onChange={setField('legal_name')} maxLength={200} disabled={isLoading} />
          </div>

          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label" htmlFor="company-email"><Mail size={13} /><span>Company Email *</span></label>
            <input id="company-email" type="email" className="input" value={form.company_email} onChange={setField('company_email')} required disabled={isLoading} />
          </div>

          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label" htmlFor="website"><Globe size={13} /><span>Website</span></label>
            <input id="website" className="input" placeholder="https://" value={form.website} onChange={setField('website')} disabled={isLoading} />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label" htmlFor="industry"><span>Industry *</span></label>
              <input id="industry" className="input" value={form.industry} onChange={setField('industry')} required disabled={isLoading} />
            </div>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label" htmlFor="sector"><span>Sector</span></label>
              <input id="sector" className="input" value={form.sector} onChange={setField('sector')} disabled={isLoading} />
            </div>
          </div>

          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label" htmlFor="country"><MapPin size={13} /><span>Country *</span></label>
            <input id="country" className="input" value={form.country} onChange={setField('country')} required disabled={isLoading} />
          </div>

          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label" htmlFor="address"><MapPin size={13} /><span>Address</span></label>
            <textarea id="address" className="input" rows={2} value={form.address} onChange={setField('address')} disabled={isLoading} />
          </div>

          <button type="button" className="btn btn-primary" style={{ width: '100%', padding: '0.7rem' }} onClick={handleNext} disabled={isLoading}>
            <span>Next: Administrator</span>
            <ArrowRight size={15} />
          </button>
        </div>
      )}

      {step === 2 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.1rem' }}>
          <h2 style={{ fontSize: '0.95rem', fontWeight: 700, margin: 0 }}>Administrator</h2>

          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label" htmlFor="admin-name"><User size={13} /><span>Admin Name *</span></label>
            <input id="admin-name" className="input" value={form.admin_name} onChange={setField('admin_name')} required disabled={isLoading} />
          </div>

          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label" htmlFor="admin-email"><Mail size={13} /><span>Admin Email *</span></label>
            <input id="admin-email" type="email" className="input" value={form.admin_email} onChange={setField('admin_email')} required disabled={isLoading} />
          </div>

          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label" htmlFor="admin-password"><Lock size={13} /><span>Password *</span></label>
            <div style={{ position: 'relative' }}>
              <input
                id="admin-password"
                type={showPassword ? 'text' : 'password'}
                className="input"
                style={{ paddingRight: '2.5rem' }}
                value={form.password}
                onChange={setField('password')}
                autoComplete="new-password"
                required
                disabled={isLoading}
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                disabled={isLoading}
                style={{ position: 'absolute', right: '0.6rem', top: '50%', transform: 'translateY(-50%)', background: 'transparent', border: 'none', padding: '0.2rem', cursor: 'pointer', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center' }}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
            <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>At least 8 characters, with uppercase, lowercase, and a digit.</span>
          </div>

          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label" htmlFor="admin-confirm-password"><Lock size={13} /><span>Confirm Password *</span></label>
            <input
              id="admin-confirm-password"
              type={showPassword ? 'text' : 'password'}
              className="input"
              value={form.confirm_password}
              onChange={setField('confirm_password')}
              autoComplete="new-password"
              required
              disabled={isLoading}
            />
          </div>

          <div style={{ display: 'flex', gap: '0.6rem' }}>
            <button type="button" className="btn btn-secondary" style={{ flex: 1, padding: '0.7rem' }} onClick={handleBack} disabled={isLoading}>
              <ArrowLeft size={15} />
              <span>Back</span>
            </button>
            <button type="button" className="btn btn-primary" style={{ flex: 2, padding: '0.7rem' }} onClick={handleNext} disabled={isLoading}>
              <span>Next: Review</span>
              <ArrowRight size={15} />
            </button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.1rem' }}>
          <h2 style={{ fontSize: '0.95rem', fontWeight: 700, margin: 0 }}>Review</h2>

          <div style={{ background: 'var(--bg-surface-elevated)', borderRadius: 'var(--radius-sm)', padding: '1rem', fontSize: '0.82rem', display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
            <div style={{ fontWeight: 700, color: '#10b981', marginBottom: '0.25rem' }}>Company</div>
            <ReviewRow label="Company Name" value={form.company_name} />
            <ReviewRow label="Legal Name" value={form.legal_name} />
            <ReviewRow label="Company Email" value={form.company_email} />
            <ReviewRow label="Website" value={form.website} />
            <ReviewRow label="Industry" value={form.industry} />
            <ReviewRow label="Sector" value={form.sector} />
            <ReviewRow label="Country" value={form.country} />
            <ReviewRow label="Address" value={form.address} />

            <div style={{ fontWeight: 700, color: '#10b981', marginTop: '0.5rem', marginBottom: '0.25rem' }}>Administrator</div>
            <ReviewRow label="Name" value={form.admin_name} />
            <ReviewRow label="Email" value={form.admin_email} />
            <ReviewRow label="Password" value="••••••••" />
          </div>

          <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', margin: 0 }}>
            Your role, company, and team are determined automatically by GreenShift — you will be the Company Admin of a new company with a default team.
          </p>

          <div style={{ display: 'flex', gap: '0.6rem' }}>
            <button type="button" className="btn btn-secondary" style={{ flex: 1, padding: '0.7rem' }} onClick={handleBack} disabled={isLoading}>
              <ArrowLeft size={15} />
              <span>Back</span>
            </button>
            <button type="button" className="btn btn-primary" style={{ flex: 2, padding: '0.7rem' }} onClick={handleSubmit} disabled={isLoading}>
              <span>{isLoading ? 'Creating…' : 'Create Company Account'}</span>
            </button>
          </div>
        </div>
      )}

      <p style={{ textAlign: 'center', fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '1.25rem', marginBottom: 0 }}>
        Already have an account?{' '}
        <Link to="/login" style={{ color: '#10b981', fontWeight: 600, textDecoration: 'none' }}>
          Sign in
        </Link>
      </p>
    </AuthLayout>
  );
};

const ReviewRow: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
    <span style={{ color: 'var(--text-secondary)', flexShrink: 0 }}>{label}</span>
    <span style={{ fontWeight: 600, textAlign: 'right', wordBreak: 'break-word' }}>{value || '—'}</span>
  </div>
);
