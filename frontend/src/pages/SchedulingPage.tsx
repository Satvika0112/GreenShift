import React, { useState, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import {
  Cpu,
  Zap,
  Leaf,
  DollarSign,
  TrendingDown,
  CheckCircle2,
  Clock,
  Sparkles,
  ArrowRight,
  RefreshCw,
  Layers,
} from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassCard } from '../components/common/GlassCard';
import { EmptyState } from '../components/common/EmptyState';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { InlineBanner } from '../components/common/InlineBanner';
import { schedulingApi, workloadsApi } from '../api/endpoints';
import { Job, ScheduleDecision } from '../types/api';
import { useAuth } from '../context/AuthContext';
import { GreenShiftRecommendation } from '../components/decision/GreenShiftRecommendation';
import { WhyThisWindow } from '../components/decision/WhyThisWindow';
import { ImmediateVsGreenShift } from '../components/decision/ImmediateVsGreenShift';

export const SchedulingPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const initialJobId = searchParams.get('jobId') || '';

  const [selectedJobId, setSelectedJobId] = useState<string>(initialJobId);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [decision, setDecision] = useState<any | null>(null);
  const [capacitySummary, setCapacitySummary] = useState<any | null>(null);
  const [isLoadingJobs, setIsLoadingJobs] = useState(true);
  const [isCalculating, setIsCalculating] = useState(false);
  const [commitSuccess, setCommitSuccess] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const fetchJobs = async () => {
    setIsLoadingJobs(true);
    setErrorMessage(null);
    try {
      const [resJobs, resCap] = await Promise.allSettled([
        workloadsApi.getJobs({ limit: 100 }),
        schedulingApi.getCapacityMap(),
      ]);

      if (resJobs.status === 'fulfilled' && Array.isArray(resJobs.value)) {
        setJobs(resJobs.value);
        if (!selectedJobId && resJobs.value.length > 0) {
          setSelectedJobId(resJobs.value[0].job_id);
        }
      } else if (resJobs.status === 'rejected') {
        setErrorMessage('Failed to load workloads from backend.');
      }
      if (resCap.status === 'fulfilled') {
        setCapacitySummary(resCap.value);
      }
    } catch (err: any) {
      setErrorMessage('Failed to load workloads or capacity map from backend.');
    } finally {
      setIsLoadingJobs(false);
    }
  };

  useEffect(() => {
    fetchJobs();
  }, [user]);

  // When selectedJobId changes, fetch the existing schedule decision if available
  useEffect(() => {
    if (!selectedJobId) {
      setDecision(null);
      return;
    }

    const fetchDecision = async () => {
      try {
        const res = await schedulingApi.getScheduleDecision(selectedJobId);
        setDecision(res);
      } catch {
        // Job might not have a decision yet
        setDecision(null);
      }
    };

    fetchDecision();
  }, [selectedJobId]);

  const handleRunOptimizer = async () => {
    if (!selectedJobId) return;
    setIsCalculating(true);
    setCommitSuccess(false);
    setErrorMessage(null);

    try {
      const res = await schedulingApi.scheduleJob(selectedJobId, true);
      setDecision(res);
      setCommitSuccess(true);
      await fetchJobs();
    } catch (err: any) {
      setErrorMessage(err.response?.data?.detail || 'Failed to compute schedule decision.');
    } finally {
      setIsCalculating(false);
    }
  };

  const selectedJob = jobs.find((j) => j.job_id === selectedJobId);

  if (isLoadingJobs) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
        <PageHeader
          title="Carbon-Aware Scheduling Engine"
          subtitle="Multi-region candidate evaluation, Pareto frontier trade-off optimization, and explainable grid dispatch"
        />
        <LoadingSkeleton rows={6} height={40} />
      </div>
    );
  }

  if (jobs.length === 0) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
        <PageHeader
          title="Carbon-Aware Scheduling Engine"
          subtitle="Multi-region candidate evaluation, Pareto frontier trade-off optimization, and explainable grid dispatch"
        />
        <EmptyState
          title="No Workloads Available for Scheduling"
          description="The queue is currently empty. Submit a workload to run the carbon-aware optimizer."
          icon={Layers}
          action={{
            label: 'Submit Workload',
            onClick: () => navigate('/submit'),
          }}
        />
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      <PageHeader
        title="Carbon-Aware Scheduling Engine"
        subtitle="Constraint-first, carbon-primary candidate evaluation with lexicographic ranking (carbon → cost → earliest start) and explainable grid dispatch"
        actions={
          <button className="btn btn-secondary" onClick={fetchJobs} title="Sync workload queue">
            <RefreshCw size={14} />
            <span>Sync Queue</span>
          </button>
        }
      />

      {errorMessage && <InlineBanner variant="error">{errorMessage}</InlineBanner>}

      {/* Decision policy — matches app/decide/scheduler.py exactly, no frontend math */}
      <GlassCard title="Decision Policy" subtitle="Lexicographic ranking — no arbitrary weights, no blended score">
        <div style={{ display: 'flex', alignItems: 'center', overflowX: 'auto', gap: '0.5rem', padding: '0.25rem 0' }}>
          {[
            { label: 'Hard Constraints', detail: 'Deadline/SLA, region, CPU/RAM/GPU, carbon budget (if set)' },
            { label: 'Feasible Candidates', detail: 'Windows passing every hard constraint' },
            { label: 'Lowest Carbon Emissions', detail: 'Primary ranking key' },
            { label: 'Lowest Electricity Cost', detail: 'Secondary tie-breaker' },
            { label: 'Earliest Start Time', detail: 'Final deterministic tie-breaker' },
          ].map((step, idx, arr) => (
            <React.Fragment key={step.label}>
              <div
                style={{
                  flex: '1 1 0',
                  minWidth: '150px',
                  background: 'var(--bg-surface-elevated)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '0.65rem 0.75rem',
                }}
              >
                <div style={{ fontSize: '0.78rem', fontWeight: 700, color: idx < 2 ? '#38bdf8' : '#10b981' }}>{step.label}</div>
                <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>{step.detail}</div>
              </div>
              {idx < arr.length - 1 && <ArrowRight size={16} style={{ flexShrink: 0, color: 'var(--text-muted)' }} />}
            </React.Fragment>
          ))}
        </div>
      </GlassCard>

      {/* Control Configuration Bar */}
      <GlassCard title="Optimizer Workload Selector">
        <div style={{ display: 'grid', gridTemplateColumns: '1.5fr auto', gap: '1.25rem', alignItems: 'flex-end' }}>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label">Target Workload in Queue ({jobs.length} Available)</label>
            <select
              className="select"
              value={selectedJobId}
              onChange={(e) => setSelectedJobId(e.target.value)}
            >
              {jobs.map((j) => (
                <option key={j.job_id} value={j.job_id}>
                  {j.name ? `${j.name} (${j.job_id})` : j.job_id} • Status: {j.status} • {j.region} • {j.power_kw}kW
                </option>
              ))}
            </select>
          </div>

          <button
            className="btn btn-primary"
            style={{ height: '40px' }}
            onClick={handleRunOptimizer}
            disabled={isCalculating || !selectedJobId}
          >
            <Cpu size={16} className={isCalculating ? 'animate-spin' : ''} />
            <span>{isCalculating ? 'Evaluating Optimal Windows...' : 'Run Scheduling Engine'}</span>
          </button>
        </div>
      </GlassCard>

      {commitSuccess && (
        <div
          style={{
            background: 'rgba(16, 185, 129, 0.15)',
            border: '1px solid #10b981',
            borderRadius: 'var(--radius-sm)',
            padding: '1rem',
            color: '#10b981',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <CheckCircle2 size={20} />
            <span>Schedule window computed and stored in database.</span>
          </div>
          <button className="btn btn-secondary btn-sm" onClick={() => navigate('/approvals')}>
            Go to Approvals Queue
          </button>
        </div>
      )}

      {/* Signature GreenShift decision components */}
      {decision ? (
        <>
          <GreenShiftRecommendation decision={decision} fallbackRegion={selectedJob?.region} />
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button className="btn btn-secondary btn-sm" onClick={() => navigate(`/workloads/${selectedJobId}`)}>
              <span>Inspect Workload</span>
              <ArrowRight size={14} />
            </button>
          </div>
          <ImmediateVsGreenShift decision={decision} />
          <WhyThisWindow decision={decision} />
        </>
      ) : (
        <div style={{ background: 'var(--bg-surface)', padding: '1.5rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)', textAlign: 'center' }}>
          <Clock size={28} style={{ color: 'var(--text-muted)', margin: '0 auto 0.5rem auto' }} />
          <div style={{ fontWeight: 600, color: '#ffffff' }}>No Decision Calculated for Workload '{selectedJobId}'</div>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
            Click "Run Scheduling Engine" above to trigger carbon-aware slot evaluation across grid forecasts.
          </div>
        </div>
      )}

      {/* Real Cluster Capacity Map Summary */}
      {capacitySummary && (
        <GlassCard title="Cluster Capacity & Contention Overview">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem' }}>
            <div style={{ background: 'var(--bg-surface-elevated)', padding: '1rem', borderRadius: 'var(--radius-sm)' }}>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Cluster Limits (CPU)</div>
              <div style={{ fontSize: '1.2rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: '#38bdf8' }}>
                {capacitySummary.cluster_limits?.max_cpu_cores ?? 'N/A'} Cores
              </div>
            </div>
            <div style={{ background: 'var(--bg-surface-elevated)', padding: '1rem', borderRadius: 'var(--radius-sm)' }}>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Cluster Limits (Memory)</div>
              <div style={{ fontSize: '1.2rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: '#10b981' }}>
                {capacitySummary.cluster_limits?.max_memory_mib ?? 'N/A'} MiB
              </div>
            </div>
            <div style={{ background: 'var(--bg-surface-elevated)', padding: '1rem', borderRadius: 'var(--radius-sm)' }}>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Cluster Limits (GPUs)</div>
              <div style={{ fontSize: '1.2rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: '#f59e0b' }}>
                {capacitySummary.cluster_limits?.max_gpus ?? 'N/A'} GPUs
              </div>
            </div>
          </div>
        </GlassCard>
      )}
    </div>
  );
};
