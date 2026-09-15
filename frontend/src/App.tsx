import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from './context/AuthContext';
import { RealtimeNotificationProvider } from './context/RealtimeNotificationContext';
import { NotificationToastStack } from './components/notifications/NotificationToastStack';
import { ProtectedRoute } from './routes/ProtectedRoute';
import { AppShell } from './components/layout/AppShell';
import { LoginPage } from './pages/LoginPage';
import { RequestAccessPage } from './pages/RequestAccessPage';
import { RegisterCompanyPage } from './pages/RegisterCompanyPage';

// Pages other than Login are code-split — each route's chunk loads on demand.
const DashboardPage = lazy(() => import('./pages/DashboardPage').then((m) => ({ default: m.DashboardPage })));
const WorkloadsPage = lazy(() => import('./pages/WorkloadsPage').then((m) => ({ default: m.WorkloadsPage })));
const WorkloadDetailPage = lazy(() => import('./pages/WorkloadDetailPage').then((m) => ({ default: m.WorkloadDetailPage })));
const SubmitWorkloadPage = lazy(() => import('./pages/SubmitWorkloadPage').then((m) => ({ default: m.SubmitWorkloadPage })));
const SchedulingPage = lazy(() => import('./pages/SchedulingPage').then((m) => ({ default: m.SchedulingPage })));
const ApprovalsPage = lazy(() => import('./pages/ApprovalsPage').then((m) => ({ default: m.ApprovalsPage })));
const JobMonitoringPage = lazy(() => import('./pages/JobMonitoringPage').then((m) => ({ default: m.JobMonitoringPage })));
const CarbonCostPage = lazy(() => import('./pages/CarbonCostPage').then((m) => ({ default: m.CarbonCostPage })));
const RegionsPage = lazy(() => import('./pages/RegionsPage').then((m) => ({ default: m.RegionsPage })));
const ImpactReportsPage = lazy(() => import('./pages/ImpactReportsPage').then((m) => ({ default: m.ImpactReportsPage })));
const AuditTrustPage = lazy(() => import('./pages/AuditTrustPage').then((m) => ({ default: m.AuditTrustPage })));
const AlertsPage = lazy(() => import('./pages/AlertsPage').then((m) => ({ default: m.AlertsPage })));
const SystemHealthPage = lazy(() => import('./pages/SystemHealthPage').then((m) => ({ default: m.SystemHealthPage })));
const UsersAccessPage = lazy(() => import('./pages/UsersAccessPage').then((m) => ({ default: m.UsersAccessPage })));
const SettingsPage = lazy(() => import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 30000,
      retry: 1,
    },
  },
});

const RouteFallback: React.FC = () => (
  <div
    style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: '60vh',
      color: 'var(--text-muted)',
      fontSize: '0.85rem',
    }}
  >
    Loading…
  </div>
);

export const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <RealtimeNotificationProvider>
            <NotificationToastStack />
            <Suspense fallback={<RouteFallback />}>
              <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/register" element={<RequestAccessPage />} />
              <Route path="/register-company" element={<RegisterCompanyPage />} />

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
                  {/* Settings: reachable by every authenticated role; the page itself
                      shows role-aware sections (see SettingsPage). */}
                  <Route path="/settings" element={<SettingsPage />} />

                  {/* Admin Role Routes */}
                  <Route element={<ProtectedRoute allowedRoles={['PLATFORM_ADMIN', 'COMPANY_ADMIN']} />}>
                    <Route path="/health" element={<SystemHealthPage />} />
                    <Route path="/users" element={<UsersAccessPage />} />
                  </Route>
                </Route>
              </Route>

              {/* Fallback */}
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
          </RealtimeNotificationProvider>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
};

export default App;
