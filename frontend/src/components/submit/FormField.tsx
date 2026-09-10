import React from 'react';

interface FormFieldProps {
  label: string;
  htmlFor: string;
  required?: boolean;
  helper?: string;
  error?: string;
  children: React.ReactNode;
}

// Shared label + input slot + helper/error text used across every Submit
// Workload section, so each field gets consistent spacing, a11y wiring
// (error text linked via aria-describedby at the call site), and styling.
export const FormField: React.FC<FormFieldProps> = ({ label, htmlFor, required, helper, error, children }) => (
  <div className="form-group" style={{ marginBottom: 0 }}>
    <label className="form-label" htmlFor={htmlFor}>
      {label}
      {required && ' *'}
    </label>
    {children}
    {helper && !error && (
      <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.35rem', marginBottom: 0 }}>{helper}</p>
    )}
    {error && (
      <p id={`${htmlFor}-error`} role="alert" style={{ fontSize: '0.72rem', color: '#ef4444', marginTop: '0.35rem', marginBottom: 0 }}>
        {error}
      </p>
    )}
  </div>
);
