import React from 'react';
import { Leaf } from 'lucide-react';

interface AuthLayoutProps {
  subtitle: string;
  children: React.ReactNode;
}

// Shared shell for the two public authentication entry points (Login and
// Request Access) so both present the same brand header and card frame.
export const AuthLayout: React.FC<AuthLayoutProps> = ({ subtitle, children }) => {
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
            {subtitle}
          </p>
        </div>

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
          {children}
        </div>
      </div>
    </div>
  );
};
