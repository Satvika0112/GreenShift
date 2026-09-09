import React, { useState, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import {
  Cpu,
  Zap,
  Leaf,
  DollarSign,
  TrendingDown,
  CheckCircle2,
  AlertCircle,
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
import { schedulingApi, workloadsApi } from '../api/endpoints';
import { Job, ScheduleDecision } from '../types/api';
import { useAuth } from '../context/AuthContext';

export const SchedulingPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { user, isViewer } = useAuth();
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
          description="The queue is currently empty. Ingest or bulk-load workloads into the system to run the carbon-aware optimizer."
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
        subtitle="Multi-region candidate evaluation, Pareto frontier trade-off optimization, and explainable grid dispatch"
        actions={
          <button className="btn btn-secondary" onClick={fetchJobs} title="Sync workload queue">
            <RefreshCw size={14} />
            <span>Sync Queue</span>
          </button>
        }
      />

      {errorMessage && (
        <div
          style={{
            background: 'rgba(239, 68, 68, 0.15)',
            border: '1px solid #ef4444',
            color: '#ef4444',
            padding: '1rem',
            borderRadius: 'var(--radius-md)',
            fontSize: '0.85rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.75rem',
          }}
        >
          <AlertCircle size={18} />
          <span>{errorMessage}</span>
        </div>
      )}

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
            disabled={isCalculating || !selectedJobId || isViewer}
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

      {/* Decision Summary Banner */}
      {decision ? (
        <div
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid rgba(16, 185, 129, 0.3)',
            borderRadius: 'var(--radius-md)',
            padding: '1.5rem',
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: '1.25rem',
          }}
        >
          <div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Recommended Region</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 800, color: '#ffffff', fontFamily: 'var(--font-mono)' }}>
              {decision.region_id || decision.recommended_region || selectedJob?.region || 'IN-TG'}
            </div>
            <div style={{ fontSize: '0.75rem', color: '#10b981', marginTop: '0.2rem' }}>
              Grid Intensity: {decision.carbon_intensity ? `${decision.carbon_intensity.toFixed(1)} gCO₂/kWh` : 'N/A'}
            </div>
          </div>

          <div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Target Execution Window</div>
            <div style={{ fontSize: '0.9rem', fontWeight: 700, color: '#38bdf8', fontFamily: 'var(--font-mono)' }}>
              {decision.selected_start ? new Date(decision.selected_start).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : 'Immediate'}
            </div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
              Duration: {selectedJob?.runtime_minutes || 60} mins
            </div>
          </div>

          <div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Emissions Reduction</div>
            <div style={{ fontSize: '1.4rem', fontWeight: 800, color: '#10b981', fontFamily: 'var(--font-mono)' }}>
              {decision.carbon_reduction_pct !== undefined ? `-${decision.carbon_reduction_pct.toFixed(1)}%` : 'N/A'}
            </div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
              Avoids {decision.carbon_avoided ? `${decision.carbon_avoided.toFixed(2)} kg CO₂e` : '0 kg'} vs baseline
            </div>
          </div>

          <div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Cost Savings</div>
            <div style={{ fontSize: '1.4rem', fontWeight: 800, color: '#38bdf8', fontFamily: 'var(--font-mono)' }}>
              {decision.cost_difference ? `$${decision.cost_difference.toFixed(2)}` : decision.cost_saved_usd ? `$${decision.cost_saved_usd}` : '$0.00'}
            </div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
              {decision.cost_reduction_pct ? `-${decision.cost_reduction_pct.toFixed(1)}% TOD tariff savings` : 'Time-of-Day Tariff'}
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end' }}>
            <button
              className="btn btn-secondary"
              onClick={() => navigate(`/workloads/${selectedJobId}`)}
            >
              <span>Inspect Workload</span>
              <ArrowRight size={14} />
            </button>
          </div>
        </div>
      ) : (
        <div style={{ background: 'var(--bg-surface)', padding: '1.5rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)', textAlign: 'center' }}>
          <Clock size={28} style={{ color: 'var(--text-muted)', margin: '0 auto 0.5rem auto' }} />
          <div style={{ fontWeight: 600, color: '#ffffff' }}>No Decision Calculated for Workload '{selectedJobId}'</div>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
            Click "Run Scheduling Engine" above to trigger carbon-aware slot evaluation across grid forecasts.
          </div>
        </div>
      )}

      {/* Explainability & Rejection Breakdown */}
      {decision && (
        <GlassCard title="Explainability Matrix & Rejection Taxonomy">
          <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: '1.5rem' }}>
            <div>
              <h4 style={{ fontSize: '0.9rem', marginBottom: '0.5rem', color: '#ffffff' }}>Deterministic Scoring Rationale</h4>
              <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                {decision.reason || 'GreenShift evaluated regional 15-minute generation forecasts against Time-of-Day electricity tariffs and Kubernetes cluster capacity constraints.'}
              </p>
              <div style={{ marginTop: '0.75rem', padding: '0.75rem', background: 'var(--bg-surface-elevated)', borderRadius: 'var(--radius-sm)', fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: '#38bdf8' }}>
                Deterministic Ranking #{decision.deterministic_rank || decision.deterministic_ranking || 1} • Evaluated {decision.candidates_evaluated || 0} Candidates ({decision.feasible_candidates_count || 0} Feasible)
              </div>
            </div>

            <div>
              <h4 style={{ fontSize: '0.9rem', marginBottom: '0.5rem', color: '#ffffff' }}>Window Rejection Breakdown</h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                {decision.rejection_summary && Object.keys(decision.rejection_summary).length > 0 ? (
                  Object.entries(decision.rejection_summary).map(([reason, count]) => (
                    <div
                      key={reason}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        padding: '0.5rem 0.75rem',
                        background: 'var(--bg-surface-elevated)',
                        borderRadius: 'var(--radius-sm)',
                        fontSize: '0.8rem',
                      }}
                    >
                      <span style={{ color: 'var(--text-secondary)' }}>{reason.replace(/_/g, ' ')}</span>
                      <span style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', color: '#ef4444' }}>{String(count)} windows</span>
                    </div>
                  ))
                ) : (
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    All evaluated candidate slots met SLA deadline and resource feasibility constraints.
                  </div>
                )}
              </div>
            </div>
          </div>
        </GlassCard>
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
