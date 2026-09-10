import { useQuery } from '@tanstack/react-query';
import { approvalsApi } from '../api/endpoints';
import { PendingApprovalItem, ApprovalHistoryItem } from '../types/api';

// `teamId` is only ever sent by the caller when the backend actually
// honors it (non-admin roles) — for admins it's left undefined and the
// backend scopes by JWT identity regardless of what's passed.
export function usePendingApprovals(teamId?: string) {
  return useQuery<PendingApprovalItem[]>({
    queryKey: ['pendingApprovals', teamId],
    queryFn: () => approvalsApi.getPendingApprovals(teamId),
  });
}

export function useApprovalHistory(teamId?: string) {
  return useQuery<ApprovalHistoryItem[]>({
    queryKey: ['approvalHistory', teamId],
    queryFn: () => approvalsApi.getApprovalHistory(teamId),
  });
}
