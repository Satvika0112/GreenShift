import { useQuery } from '@tanstack/react-query';
import { monitoringApi, workloadsApi, sustainabilityApi, approvalsApi, dispatchApi } from '../api/endpoints';
import { RegionInfo, KubernetesClusterState } from '../types/api';

export function useDashboardSummary() {
  return useQuery({
    queryKey: ['dashboardSummary'],
    queryFn: monitoringApi.getDashboardSummary,
    refetchInterval: 30000,
  });
}

export function useFleetHeadline() {
  return useQuery({
    queryKey: ['fleetHeadline'],
    queryFn: monitoringApi.getFleetHeadline,
    refetchInterval: 30000,
  });
}

export function useRecentWorkloads(limit = 10) {
  return useQuery({
    queryKey: ['recentWorkloads', limit],
    queryFn: () => workloadsApi.getJobs({ limit }),
  });
}

export function useRegions() {
  return useQuery<RegionInfo[]>({
    queryKey: ['regions'],
    queryFn: sustainabilityApi.getRegions,
  });
}

// One entry per region_id; value is undefined when the backend could not
// supply a live reading for that region (never a fabricated fallback number).
export function useRegionCarbon(regionIds: string[]) {
  return useQuery({
    queryKey: ['regionCarbon', regionIds.join(',')],
    queryFn: async () => {
      const entries = await Promise.all(
        regionIds.map(async (id) => {
          try {
            const c = await sustainabilityApi.getCarbonCurrent(id);
            return [id, c?.carbon_gco2_kwh] as const;
          } catch {
            return [id, undefined] as const;
          }
        })
      );
      return Object.fromEntries(entries) as Record<string, number | undefined>;
    },
    enabled: regionIds.length > 0,
  });
}

export function usePendingApprovalsPreview(teamId?: string, isAdmin?: boolean, enabled = true) {
  return useQuery({
    queryKey: ['pendingApprovalsPreview', teamId, isAdmin],
    queryFn: () => approvalsApi.getPendingApprovals(isAdmin ? undefined : teamId),
    enabled,
  });
}

export function useSystemHealth(enabled = true) {
  return useQuery({
    queryKey: ['systemHealth'],
    queryFn: monitoringApi.getSystemHealth,
    retry: false,
    refetchInterval: 30000,
    enabled,
  });
}

// Platform-only cluster telemetry — callers should pass `enabled: false` for
// non-platform-admin roles so this request is never made on their behalf.
export function useK8sState(enabled: boolean) {
  return useQuery<KubernetesClusterState>({
    queryKey: ['k8sClusterState'],
    queryFn: dispatchApi.getK8sState,
    enabled,
    retry: false,
    refetchInterval: 30000,
  });
}
