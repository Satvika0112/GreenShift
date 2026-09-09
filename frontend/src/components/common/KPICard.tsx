import React from 'react';
import { LucideIcon } from 'lucide-react';

interface KPICardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: LucideIcon;
  change?: string;
  trend?: 'up' | 'down' | 'neutral';
  color?: 'emerald' | 'cyan' | 'indigo' | 'amber' | 'rose';
  onClick?: () => void;
}

export const KPICard: React.FC<KPICardProps> = ({
  title,
  value,
  subtitle,
  icon: Icon,
  change,
  trend,
  color = 'emerald',
  onClick,
}) => {
  const colorMap = {
    emerald: {
      border: 'rgba(16, 185, 129, 0.25)',
      iconBg: 'rgba(16, 185, 129, 0.12)',
      iconColor: '#10b981',
      glow: 'rgba(16, 185, 129, 0.15)',
    },
    cyan: {
      border: 'rgba(6, 182, 212, 0.25)',
      iconBg: 'rgba(6, 182, 212, 0.12)',
      iconColor: '#06b6d4',
      glow: 'rgba(6, 182, 212, 0.15)',
    },
    indigo: {
      border: 'rgba(99, 102, 241, 0.25)',
      iconBg: 'rgba(99, 102, 241, 0.12)',
      iconColor: '#6366f1',
      glow: 'rgba(99, 102, 241, 0.15)',
    },
    amber: {
      border: 'rgba(245, 158, 11, 0.25)',
      iconBg: 'rgba(245, 158, 11, 0.12)',
      iconColor: '#f59e0b',
      glow: 'rgba(245, 158, 11, 0.15)',
    },
    rose: {
      border: 'rgba(244, 63, 94, 0.25)',
      iconBg: 'rgba(244, 63, 94, 0.12)',
      iconColor: '#f43f5e',
      glow: 'rgba(244, 63, 94, 0.15)',
    },
  };

  const scheme = colorMap[color];

  return (
    <div
      onClick={onClick}
      style={{
        background: 'var(--bg-surface)',
        border: `1px solid ${scheme.border}`,
        borderRadius: 'var(--radius-md)',
        padding: '1.25rem',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.75rem',
        cursor: onClick ? 'pointer' : 'default',
        transition: 'transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease',
        position: 'relative',
        overflow: 'hidden',
      }}
      className="glass-panel-interactive"
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <span
          style={{
            fontSize: '0.8rem',
            fontWeight: 600,
            color: 'var(--text-secondary)',
            letterSpacing: '0.02em',
            textTransform: 'uppercase',
          }}
        >
          {title}
        </span>
        <div
          style={{
            width: '36px',
            height: '36px',
            borderRadius: 'var(--radius-sm)',
            background: scheme.iconBg,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: scheme.iconColor,
          }}
        >
          <Icon size={18} />
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.5rem' }}>
        <div
          style={{
            fontSize: '1.85rem',
            fontWeight: 800,
            color: 'var(--text-primary)',
            fontFamily: 'var(--font-mono)',
            letterSpacing: '-0.03em',
            lineHeight: 1,
          }}
        >
          {value}
        </div>
        {change && (
          <span
            style={{
              fontSize: '0.75rem',
              fontWeight: 600,
              color: trend === 'up' ? '#10b981' : trend === 'down' ? '#ef4444' : 'var(--text-secondary)',
            }}
          >
            {trend === 'up' ? '▲' : trend === 'down' ? '▼' : ''} {change}
          </span>
        )}
      </div>

      {subtitle && (
        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          {subtitle}
        </div>
      )}
    </div>
  );
};
