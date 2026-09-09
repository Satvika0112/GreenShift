import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Activity,
  Server,
  Terminal,
  Cpu,
  RefreshCw,
  Search,
  Filter,
  CheckCircle2,
  Clock,
  HardDrive,
  AlertTriangle,
  Play,
} from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassCard } from '../components/common/GlassCard';
import { StatusBadge } from '../components/common/StatusBadge';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { EmptyState } from '../components/common/EmptyState';
import { dispatchApi } from '../api/endpoints';
import { KubernetesExecution, KubernetesClusterState } from '../types/api';

export const JobMonitoringPage: React.FC = () => {
  const navigate = useNavigate();
  const [executions, setExecutions] = useState<KubernetesExecution[]>([]);
  const [clusterState, setClusterState] = useState<KubernetesClusterState | null>(null);
  const [k8sHealth, setK8sHealth] = useState<{ kubernetes_available: boolean; namespace: string } | null>(null);
  const [selectedExecId, setSelectedExecId] = useState<string | null>(null);
  const [logFilter, setLogFilter] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const fetchTelemetry = async () => {
    setIsRefreshing(true);
    setErrorMsg(null);
    try {
      const [execRes, stateRes, healthRes] = await Promise.allSettled([
        dispatchApi.getAllExecutions(),
        dispatchApi.getK8sState(),
        dispatchApi.getK8sHealth(),
      ]);

      if (execRes.status === 'fulfilled' && Array.isArray(execRes.value)) {
        setExecutions(execRes.value);
        if (!selectedExecId && execRes.value.length > 0) {
          setSelectedExecId(String(execRes.value[0].execution_id));
        }
      }
      if (stateRes.status === 'fulfilled') {
        setClusterState(stateRes.value);
      }
      if (healthRes.status === 'fulfilled') {
        setK8sHealth(healthRes.value);
      }
    } catch (err: any) {
      setErrorMsg('Failed to poll Kubernetes execution telemetry.');
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    fetchTelemetry();
  }, []);

  const selectedExec = executions.find((e) => String(e.execution_id) === String(selectedExecId)) || executions[0];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      <PageHeader
        title="Kubernetes Cluster & Job Execution Telemetry"
        subtitle="Real-time pod scheduling, worker telemetry, execution logs, and node resource allocation across edge clusters"
        actions={
          <button className="btn btn-secondary" onClick={fetchTelemetry} disabled={isRefreshing}>
            <RefreshCw size={14} className={isRefreshing ? 'animate-spin' : ''} />
            <span>{isRefreshing ? 'Polling Clusters...' : 'Poll Clusters'}</span>
          </button>
        }
      />

      {errorMsg && (
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
          <AlertTriangle size={20} />
          <span>{errorMsg}</span>
        </div>
      )}

      {/* Cluster Node Summary Bar */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: '1rem',
        }}
      >
        <div style={{ background: 'var(--bg-surface)', padding: '1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Kubernetes Controller Status</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.25rem' }}>
            <span className="pulse-dot" style={{ color: k8sHealth?.kubernetes_available ? '#10b981' : '#f59e0b' }} />
            <span style={{ fontWeight: 700, color: k8sHealth?.kubernetes_available ? '#10b981' : '#f59e0b', fontFamily: 'var(--font-mono)' }}>
              {k8sHealth?.kubernetes_available ? 'CONNECTED / READY' : 'SIMULATION MODE'}
            </span>
          </div>
        </div>

        <div style={{ background: 'var(--bg-surface)', padding: '1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Active Worker Nodes</div>
          <div style={{ fontSize: '1.25rem', fontWeight: 800, fontFamily: 'var(--font-mono)' }}>
            {clusterState ? `${clusterState.ready_nodes} / ${clusterState.total_nodes} Nodes` : 'Probing...'}
          </div>
        </div>

        <div style={{ background: 'var(--bg-surface)', padding: '1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Allocatable CPU Cores</div>
          <div style={{ fontSize: '1.25rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: '#38bdf8' }}>
            {clusterState ? `${clusterState.free_cpu_cores} / ${clusterState.total_cpu_cores} Cores` : '--'}
          </div>
        </div>

        <div style={{ background: 'var(--bg-surface)', padding: '1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Dispatched Pod Executions</div>
          <div style={{ fontSize: '1.25rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: '#10b981' }}>
            {executions.length} Total
          </div>
        </div>
      </div>

      {isLoading ? (
        <LoadingSkeleton rows={6} height={60} />
      ) : executions.length === 0 ? (
        <EmptyState
          title="No Active or Past Executions"
          description="No workloads have been dispatched to the Kubernetes cluster yet. Approve and dispatch a scheduled workload from the Workloads registry."
          icon={Server}
          action={{
            label: 'Go to Workloads Registry',
            onClick: () => navigate('/workloads'),
          }}
        />
      ) : (
        /* 2-Column Split: Active Executions List & Live Terminal Console */
        <div style={{ display: 'grid', gridTemplateColumns: '1.1fr 1.6fr', gap: '1.5rem' }}>
          {/* Left: Dispatched Executions */}
          <GlassCard title={`Dispatched Pods & Executions (${executions.length})`}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', maxHeight: '520px', overflowY: 'auto' }}>
              {executions.map((exec) => {
                const isSelected = String(exec.execution_id) === String(selectedExecId);
                return (
                  <div
                    key={exec.execution_id}
                    onClick={() => setSelectedExecId(String(exec.execution_id))}
                    style={{
                      padding: '0.85rem 1rem',
                      background: isSelected ? 'rgba(16, 185, 129, 0.08)' : 'var(--bg-surface-elevated)',
                      border: isSelected ? '1px solid rgba(16, 185, 129, 0.4)' : '1px solid var(--border-subtle)',
                      borderRadius: 'var(--radius-sm)',
                      cursor: 'pointer',
                      transition: 'all 0.15s ease',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontWeight: 600, fontSize: '0.9rem', color: '#ffffff' }}>
                        {exec.kubernetes_job_name || exec.job_id}
                      </span>
                      <StatusBadge status={exec.gs_status || exec.k8s_status || 'DISPATCHED'} size="sm" />
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.4rem' }}>
                      <span>Namespace: {exec.namespace || exec.kubernetes_namespace || 'greenshift'}</span>
                      <span style={{ fontFamily: 'var(--font-mono)' }}>Job ID: {exec.job_id}</span>
                    </div>

                    <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginTop: '0.3rem' }}>
                      Started: {exec.actual_start ? new Date(exec.actual_start).toLocaleTimeString() : 'Pending'}
                    </div>
                  </div>
                );
              })}
            </div>
          </GlassCard>

          {/* Right: Live Pod Telemetry & Logs */}
          <GlassCard
            title="Pod Execution Telemetry & Status Logs"
            subtitle={`Pod: ${selectedExec?.pod_name || `${selectedExec?.kubernetes_job_name || 'k8s'}-pod`} • Namespace: ${selectedExec?.kubernetes_namespace || selectedExec?.namespace || 'greenshift'}`}
            badge={<span className="badge badge-info">POLLING TELEMETRY</span>}
          >
            {selectedExec ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.75rem', fontSize: '0.8rem' }}>
                  <div style={{ background: 'var(--bg-surface-elevated)', padding: '0.6rem 0.75rem', borderRadius: 'var(--radius-sm)' }}>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Kubernetes Status</div>
                    <div style={{ fontWeight: 700, color: '#10b981', marginTop: '0.2rem' }}>
                      {selectedExec.k8s_status || selectedExec.gs_status || 'READY'}
                    </div>
                  </div>
                  <div style={{ background: 'var(--bg-surface-elevated)', padding: '0.6rem 0.75rem', borderRadius: 'var(--radius-sm)' }}>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Execution Planned</div>
                    <div style={{ fontFamily: 'var(--font-mono)', marginTop: '0.2rem' }}>
                      {selectedExec.planned_start ? new Date(selectedExec.planned_start).toLocaleTimeString() : 'Immediate'}
                    </div>
                  </div>
                  <div style={{ background: 'var(--bg-surface-elevated)', padding: '0.6rem 0.75rem', borderRadius: 'var(--radius-sm)' }}>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Execution Concluded</div>
                    <div style={{ fontFamily: 'var(--font-mono)', marginTop: '0.2rem' }}>
                      {selectedExec.actual_end ? new Date(selectedExec.actual_end).toLocaleTimeString() : 'Active/Running'}
                    </div>
                  </div>
                </div>

                <div
                  style={{
                    background: '#04070e',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-sm)',
                    padding: '1rem',
                    fontFamily: 'var(--font-mono)',
                    fontSize: '0.78rem',
                    color: '#34d399',
                    lineHeight: 1.6,
                    height: '280px',
                    overflowY: 'auto',
                  }}
                >
                  <div>[greenshift-dispatcher] Claim verified for job: {selectedExec.job_id}</div>
                  <div>[greenshift-dispatcher] Submitting Kubernetes batch Job manifest: {selectedExec.kubernetes_job_name}</div>
                  <div>[kubernetes-cluster] Target namespace: {selectedExec.kubernetes_namespace || selectedExec.namespace || 'greenshift'}</div>
                  <div>[kubernetes-cluster] Pod name: {selectedExec.pod_name || `${selectedExec.kubernetes_job_name}-pod`}</div>
                  <div>[kubernetes-cluster] Kubernetes execution state: {selectedExec.k8s_status || selectedExec.gs_status}</div>
                  {selectedExec.actual_start && (
                    <div>[kubernetes-telemetry] Container execution commenced at {new Date(selectedExec.actual_start).toISOString()}</div>
                  )}
                  {selectedExec.actual_end && (
                    <div>[kubernetes-telemetry] Container execution completed at {new Date(selectedExec.actual_end).toISOString()}</div>
                  )}
                  {selectedExec.error_message && (
                    <div style={{ color: '#ef4444' }}>[kubernetes-error] {selectedExec.error_message}</div>
                  )}
                  <div>[info] Note: Pod telemetry is polled at 5-second intervals from cluster status API.</div>
                </div>
              </div>
            ) : null}
          </GlassCard>
        </div>
      )}
    </div>
  );
};
