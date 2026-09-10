import { useQuery } from '@tanstack/react-query';
import { workloadsApi } from '../api/endpoints';
import { Job, WorkloadDetail } from '../types/api';

// GET /api/v1/jobs has a `limit` but no true pagination (no offset/cursor),
// so this is the largest single authorized fetch we can honestly request —
// both the KPI-adjacent counts and the table read from this same array, so
// they never contradict each other.
export const WORKLOADS_FETCH_LIMIT = 500;

interface UseWorkloadsParams {
  // Only ever meaningful for PLATFORM_ADMIN — the backend ignores/overrides
  // this filter for any other role and scopes by the caller's own identity
  // instead (see app/api/tenant_scope.py), so it's left undefined elsewhere.
  teamId?: string;
}

export function useWorkloads(params: UseWorkloadsParams = {}) {
  return useQuery<Job[]>({
    queryKey: ['workloads', params.teamId],
    queryFn: () => workloadsApi.getJobs({ team_id: params.teamId, limit: WORKLOADS_FETCH_LIMIT }),
  });
}

export function useWorkload(jobId: string | undefined) {
  return useQuery<WorkloadDetail>({
    queryKey: ['workload', jobId],
    queryFn: () => workloadsApi.getJobHistory(jobId as string),
    enabled: !!jobId,
    retry: false,
  });
}
