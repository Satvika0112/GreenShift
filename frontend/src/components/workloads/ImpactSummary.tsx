import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowUpRight } from 'lucide-react';
import { GlassCard } from '../common/GlassCard';
import { WorkloadDetail } from '../../types/api';
import { monitoringApi } from '../../api/endpoints';
import { formatCarbonKg } from '../../utils/workloadDisplay';
import { formatCurrency } from '../../utils/currency';

interface ImpactSummaryProps {
  job: WorkloadDetail;
}

const Row: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)' }}>
    <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>{label}</span>
    <span style={{ fontSize: '0.82rem', fontWeight: 600, textAlign: 'right' }}>{children}</span>
  </div>
);

export const ImpactSummary: React.FC<ImpactSummaryProps> = ({ job }) => {
  const navigate = useNavigate();
  const decision = job.schedule_decision;

  // Actual (observed) impact only exists once the workload has real
  // execution telemetry; a 404 here just means it isn't available yet, not
  // an error worth surfacing.
  const actualQ = useQuery({
    queryKey: ['actualImpact', job.job_id],
    queryFn: () => monitoringApi.getActualImpact(job.job_id),
    enabled: job.status === 'COMPLETED',
    retry: false,
  });
  const actual = actualQ.data;

  if (!decision) {
    return (
      <GlassCard title="Impact">
        <div style={{ padding: '1rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
          Impact data is not available yet.
        </div>
      </GlassCard>
    );
  }

  return (
    <GlassCard
      title="Impact"
      subtitle={actual ? 'Estimated (at scheduling) vs. observed (from real execution)' : 'Estimated at scheduling time'}
      actions={
        <button className="btn btn-secondary btn-sm" onClick={() => navigate('/impact')}>
          <span>View Impact Report</span>
          <ArrowUpRight size={13} />
        </button>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.9rem' }}>
        <Row label="Immediate Execution Baseline (est.)">{formatCarbonKg(decision.baseline_carbon_emission)}</Row>
        <Row label="GreenShift Execution (est.)">{formatCarbonKg(decision.carbon_emission)}</Row>
        <Row label="Carbon Avoided (est.)">{formatCarbonKg(decision.carbon_avoided)}</Row>
        <Row label="Cost Saved (est., USD)">{formatCurrency(decision.cost_difference, 'USD')}</Row>
        <Row label="Delay Introduced (est.)">{decision.scheduling_delay_hours !== undefined && decision.scheduling_delay_hours !== null ? `${decision.scheduling_delay_hours.toFixed(1)} h` : '—'}</Row>
        <Row label="SLA Compliance (est.)">{decision.sla_met === undefined ? '—' : decision.sla_met ? 'Met' : 'Missed'}</Row>

        {actual && (
          <>
            <div style={{ fontSize: '0.72rem', fontWeight: 700, color: '#38bdf8', textTransform: 'uppercase', letterSpacing: '0.04em', marginTop: '0.4rem' }}>
              Observed / Actual
            </div>
            <Row label="Actual Carbon Emission">{formatCarbonKg(actual.actual_carbon_emission_kg)}</Row>
            <Row label="Actual Cost (USD)">{formatCurrency(actual.actual_cost_usd, 'USD')}</Row>
            <Row label="Actual Carbon Saved vs. Baseline">{formatCarbonKg(actual.actual_vs_baseline_carbon_saved_kg)}</Row>
            <Row label="Estimation Quality">{actual.estimation_quality}</Row>
          </>
        )}
      </div>
    </GlassCard>
  );
};
