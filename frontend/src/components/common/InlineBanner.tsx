import React from 'react';
import { LucideIcon, AlertTriangle, CheckCircle2, Info } from 'lucide-react';

type BannerVariant = 'error' | 'success' | 'warning' | 'info';

interface InlineBannerProps {
  variant: BannerVariant;
  children: React.ReactNode;
  icon?: LucideIcon;
  action?: React.ReactNode;
}

const VARIANT_STYLES: Record<BannerVariant, { bg: string; border: string; color: string; icon: LucideIcon }> = {
  error: { bg: 'rgba(239, 68, 68, 0.15)', border: '#ef4444', color: '#ef4444', icon: AlertTriangle },
  success: { bg: 'rgba(16, 185, 129, 0.12)', border: '#10b981', color: '#10b981', icon: CheckCircle2 },
  warning: { bg: 'rgba(245, 158, 11, 0.12)', border: '#f59e0b', color: '#f59e0b', icon: AlertTriangle },
  info: { bg: 'rgba(56, 189, 248, 0.08)', border: 'rgba(56, 189, 248, 0.25)', color: '#38bdf8', icon: Info },
};

// Shared visual treatment for the inline status banner pattern that was
// previously duplicated with minor drift (icon size, padding) across most
// pages — same appearance, one place to maintain it.
export const InlineBanner: React.FC<InlineBannerProps> = ({ variant, children, icon, action }) => {
  const scheme = VARIANT_STYLES[variant];
  const Icon = icon || scheme.icon;

  return (
    <div
      style={{
        background: scheme.bg,
        border: `1px solid ${scheme.border}`,
        color: scheme.color,
        padding: '0.85rem 1.1rem',
        borderRadius: 'var(--radius-md)',
        fontSize: '0.85rem',
        fontWeight: variant === 'success' ? 600 : 400,
        display: 'flex',
        alignItems: 'center',
        justifyContent: action ? 'space-between' : 'flex-start',
        flexWrap: 'wrap',
        gap: '0.75rem',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
        <Icon size={18} style={{ flexShrink: 0 }} />
        <span>{children}</span>
      </div>
      {action}
    </div>
  );
};
