import React from 'react';
import { Outlet } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { approvalsApi, monitoringApi } from '../../api/endpoints';
import { useAuth } from '../../context/AuthContext';

interface AppShellProps {
  pendingApprovalsCount?: number;
  activeJobsCount?: number;
  onRefresh?: () => void;
  isRefreshing?: boolean;
}

export const AppShell: React.FC<AppShellProps> = ({
  pendingApprovalsCount: propPendingCount,
  activeJobsCount: propActiveCount,
  onRefresh,
  isRefreshing,
}) => {
  const { user, isAdmin, isAuthenticated } = useAuth();

  // Query live pending approvals for current user / team
  const { data: pendingData } = useQuery({
    queryKey: ['sidebarPendingApprovals', user?.team_id, isAdmin],
    queryFn: async () => {
      try {
        const items = await approvalsApi.getPendingApprovals(isAdmin ? undefined : user?.team_id);
        return Array.isArray(items) ? items.length : 0;
      } catch {
        return 0;
      }
    },
    enabled: isAuthenticated,
    refetchInterval: 15000,
  });

  // Query live active jobs count
  const { data: summaryData } = useQuery({
    queryKey: ['sidebarActiveJobsSummary'],
    queryFn: async () => {
      try {
        const summary = await monitoringApi.getDashboardSummary();
        return summary?.active_jobs ?? 0;
      } catch {
        return 0;
      }
    },
    enabled: isAuthenticated,
    refetchInterval: 15000,
  });

  const effectivePendingCount = propPendingCount !== undefined ? propPendingCount : (pendingData ?? 0);
  const effectiveActiveCount = propActiveCount !== undefined ? propActiveCount : (summaryData ?? 0);

  return (
    <div style={{ display: 'flex', minHeight: '100vh', width: '100vw', background: 'var(--bg-base)' }}>
      {/* Fixed Sidebar */}
      <Sidebar
        pendingApprovalsCount={effectivePendingCount}
        activeJobsCount={effectiveActiveCount}
      />

      {/* Main Workspace Area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflowX: 'hidden' }}>
        <Header onRefresh={onRefresh} isRefreshing={isRefreshing} />

        <main
          style={{
            flex: 1,
            padding: '1.75rem 2rem 3rem',
            maxWidth: '1600px',
            width: '100%',
            margin: '0 auto',
            animation: 'fadeIn 0.2s ease-in',
          }}
        >
          <Outlet />
        </main>
      </div>
    </div>
  );
};

