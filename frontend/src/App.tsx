import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from './context/AuthContext';
import { ProtectedRoute } from './routes/ProtectedRoute';
import { AppShell } from './components/layout/AppShell';

// Pages
import { LoginPage } from './pages/LoginPage';
import { DashboardPage } from './pages/DashboardPage';
import { WorkloadsPage } from './pages/WorkloadsPage';
import { WorkloadDetailPage } from './pages/WorkloadDetailPage';
import { SubmitWorkloadPage } from './pages/SubmitWorkloadPage';
import { SchedulingPage } from './pages/SchedulingPage';
import { ApprovalsPage } from './pages/ApprovalsPage';
import { JobMonitoringPage } from './pages/JobMonitoringPage';
import { CarbonCostPage } from './pages/CarbonCostPage';
import { RegionsPage } from './pages/RegionsPage';
import { ImpactReportsPage } from './pages/ImpactReportsPage';
import { AuditTrustPage } from './pages/AuditTrustPage';
import { AlertsPage } from './pages/AlertsPage';
import { SystemHealthPage } from './pages/SystemHealthPage';
import { UsersAccessPage } from './pages/UsersAccessPage';
import { SettingsPage } from './pages/SettingsPage';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 30000,
      retry: 1,
    },
  },
});

export const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />

            {/* Authenticated Workspace */}
            <Route element={<ProtectedRoute />}>
              <Route element={<AppShell />}>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/workloads" element={<WorkloadsPage />} />
                <Route path="/workloads/:id" element={<WorkloadDetailPage />} />
                <Route path="/submit" element={<SubmitWorkloadPage />} />
                <Route path="/scheduling" element={<SchedulingPage />} />
                <Route path="/approvals" element={<ApprovalsPage />} />
                <Route path="/monitoring" element={<JobMonitoringPage />} />
                <Route path="/carbon-cost" element={<CarbonCostPage />} />
                <Route path="/regions" element={<RegionsPage />} />
                <Route path="/impact" element={<ImpactReportsPage />} />
                <Route path="/audit" element={<AuditTrustPage />} />
                <Route path="/alerts" element={<AlertsPage />} />

                {/* Admin Role Routes */}
                <Route element={<ProtectedRoute allowedRoles={['ADMIN']} />}>
                  <Route path="/health" element={<SystemHealthPage />} />
                  <Route path="/users" element={<UsersAccessPage />} />
                  <Route path="/settings" element={<SettingsPage />} />
                </Route>
              </Route>
            </Route>

            {/* Fallback */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
};

export default App;
