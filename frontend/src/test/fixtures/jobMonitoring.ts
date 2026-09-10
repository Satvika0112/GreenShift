import { KubernetesExecution, KubernetesClusterState } from '../../types/api';

// Matches GET /api/v1/dispatch/executions exactly.
export const runningExecution: KubernetesExecution = {
  job_id: 'job-9001',
  execution_id: 501,
  kubernetes_job_name: 'gs-job-9001',
  namespace: 'greenshift',
  kubernetes_namespace: 'greenshift',
  pod_name: 'gs-job-9001-pod-abc12',
  planned_start: '2026-09-10T09:00:00Z',
  actual_start: '2026-09-10T09:00:05Z',
  actual_end: null,
  k8s_status: 'RUNNING',
  gs_status: 'RUNNING',
  error_message: null,
};

export const failedExecution: KubernetesExecution = {
  job_id: 'job-8800',
  execution_id: 500,
  kubernetes_job_name: 'gs-job-8800',
  namespace: 'greenshift',
  kubernetes_namespace: 'greenshift',
  pod_name: 'gs-job-8800-pod-xyz99',
  planned_start: '2026-09-10T08:00:00Z',
  actual_start: '2026-09-10T08:00:05Z',
  actual_end: '2026-09-10T08:05:00Z',
  k8s_status: 'FAILED',
  gs_status: 'FAILED',
  error_message: 'OOMKilled: container exceeded memory limit',
};

export const clusterState: KubernetesClusterState = {
  connected: true,
  cluster_health: 'healthy',
  total_nodes: 4,
  ready_nodes: 4,
  total_cpu_cores: 32,
  allocatable_cpu_cores: 30,
  used_cpu_cores: 12,
  free_cpu_cores: 18,
  total_memory_mib: 131072,
  allocatable_memory_mib: 122880,
  used_memory_mib: 40960,
  free_memory_mib: 81920,
  total_gpus: 0,
  allocatable_gpus: 0,
  used_gpus: 0,
  free_gpus: 0,
  timestamp: '2026-09-10T09:00:00Z',
  nodes: [],
};

export const k8sHealthAvailable = { kubernetes_available: true, namespace: 'greenshift' };
export const k8sHealthSimulated = { kubernetes_available: false, namespace: 'greenshift' };
