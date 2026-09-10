import React from 'react';
import { ArrowDown, CheckCircle2, ClipboardCheck, Search, Sparkles, Cpu } from 'lucide-react';
import { GlassCard } from '../common/GlassCard';

const STEPS = [
  { icon: ClipboardCheck, label: 'Validate' },
  { icon: Search, label: 'Evaluate feasible execution windows' },
  { icon: Sparkles, label: 'Recommend lower-carbon schedule' },
  { icon: CheckCircle2, label: 'Await approval' },
  { icon: Cpu, label: 'Kubernetes executes' },
];

// Explanatory UX only — no scheduling logic lives here. What actually
// happens is computed entirely server-side after submission.
export const WhatHappensNext: React.FC = () => (
  <GlassCard title="What happens after submission?">
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: '0.4rem' }}>
        {STEPS.map((step, idx) => (
          <React.Fragment key={step.label}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
              <div
                style={{
                  width: '28px',
                  height: '28px',
                  borderRadius: 'var(--radius-full)',
                  background: 'rgba(16, 185, 129, 0.12)',
                  color: '#10b981',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                }}
              >
                <step.icon size={14} />
              </div>
              <span style={{ fontSize: '0.85rem', color: 'var(--text-primary)' }}>{step.label}</span>
            </div>
            {idx < STEPS.length - 1 && (
              <ArrowDown size={14} style={{ marginLeft: '13px', color: 'var(--text-muted)' }} aria-hidden="true" />
            )}
          </React.Fragment>
        ))}
      </div>

      <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', margin: 0 }}>
        GreenShift recommends the execution schedule. The workload does not run until the required approval is provided.
      </p>
    </div>
  </GlassCard>
);
