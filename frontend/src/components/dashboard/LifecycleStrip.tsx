import React from 'react';
import { useNavigate } from 'react-router-dom';
import {
  PlusCircle,
  Sparkles,
  CheckCircle2,
  PlayCircle,
  Activity,
  TrendingDown,
  ShieldCheck,
  ChevronRight,
  LucideIcon,
} from 'lucide-react';

interface LifecycleStep {
  label: string;
  icon: LucideIcon;
  path: string;
}

const STEPS: LifecycleStep[] = [
  { label: 'Submit', icon: PlusCircle, path: '/submit' },
  { label: 'Schedule', icon: Sparkles, path: '/scheduling' },
  { label: 'Approve', icon: CheckCircle2, path: '/approvals' },
  { label: 'Execute', icon: PlayCircle, path: '/workloads' },
  { label: 'Monitor', icon: Activity, path: '/monitoring' },
  { label: 'Measure Impact', icon: TrendingDown, path: '/impact' },
  { label: 'Audit / Notify', icon: ShieldCheck, path: '/audit' },
];

// Read-only navigation aid showing the GreenShift lifecycle the Dashboard's
// sections feed into — clicking a step jumps to the page that owns it.
export const LifecycleStrip: React.FC = () => {
  const navigate = useNavigate();

  return (
    <div
      role="navigation"
      aria-label="GreenShift workload lifecycle"
      style={{
        display: 'flex',
        alignItems: 'center',
        overflowX: 'auto',
        gap: '0.35rem',
        padding: '0.6rem 0.75rem',
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-md)',
      }}
    >
      {STEPS.map((step, idx) => (
        <React.Fragment key={step.label}>
          <button
            type="button"
            onClick={() => navigate(step.path)}
            className="btn btn-secondary btn-sm"
            style={{ flex: '0 0 auto', padding: '0.35rem 0.65rem' }}
          >
            <step.icon size={13} />
            <span>{step.label}</span>
          </button>
          {idx < STEPS.length - 1 && (
            <ChevronRight size={14} style={{ flexShrink: 0, color: 'var(--text-muted)' }} aria-hidden="true" />
          )}
        </React.Fragment>
      ))}
    </div>
  );
};
