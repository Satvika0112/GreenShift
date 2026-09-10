import React from 'react';
import { GlassCard } from '../common/GlassCard';
import { WorkloadDetail } from '../../types/api';

interface ComputeRequirementsProps {
  job: WorkloadDetail;
}

const Row: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)' }}>
    <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>{label}</span>
    <span style={{ fontSize: '0.82rem', fontFamily: 'var(--font-mono)', fontWeight: 600, textAlign: 'right', maxWidth: '280px', wordBreak: 'break-all' }}>{children}</span>
  </div>
);

export const ComputeRequirements: React.FC<ComputeRequirementsProps> = ({ job }) => (
  <GlassCard title="Compute Requirements">
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.9rem' }}>
      <Row label="CPU Request">{job.cpu_request || '—'}</Row>
      <Row label="Memory Request">{job.memory_request || '—'}</Row>
      <Row label="Runtime">{job.runtime_minutes ? `${job.runtime_minutes} min` : '—'}</Row>
      <Row label="Power">{job.power_kw !== undefined ? `${job.power_kw} kW${job.energy_kwh ? ` (${job.energy_kwh} kWh)` : ''}` : '—'}</Row>
      <Row label="Container Image">{job.container_image || '—'}</Row>
      <Row label="Execution Region">{job.region || '—'}</Row>
    </div>
  </GlassCard>
);
