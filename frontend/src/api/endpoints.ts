import apiClient, { API_BASE_URL } from './client';
import {
  Job,
  ScheduleDecision,
  Approval,
  PendingApprovalItem,
  ApprovalHistoryItem,
  KubernetesExecution,
  KubernetesClusterState,
  AuditEvent,
  DashboardSummary,
  FleetHeadline,
  RegionInfo,
  CurrentTariffResponse,
  RegionHourlyTariffsResponse,
  SystemHealthReport,
  CreateJobInput,
  JobSubmitResult,
  User,
  WorkloadDetail,
  ActualImpactResult,
  AuthTokenResponse,
  NotificationItem,
  UnreadCountResponse,
  NotificationPreferences,
  NotificationPreferencesUpdate,
  AuditVerifyResponse,
  AnchorStatus,
  AnchorCreateResult,
  DatasetWorkloadsResponse,
} from '../types/api';

// ==========================================
// AUTHENTICATION & ADMIN
// ==========================================
export const authApi = {
  login: async (formData: { username: string; password: string }): Promise<AuthTokenResponse> => {
    try {
      const res = await apiClient.post<AuthTokenResponse>('/api/v1/auth/login', {
        username: formData.username,
        password: formData.password,
      });
      return res.data;
    } catch (err: any) {
      if (err.response?.status === 404) {
        // Fallback mount path
        const res = await apiClient.post<AuthTokenResponse>('/auth/login', {
          username: formData.username,
          password: formData.password,
        });
        return res.data;
      }
      throw err;
    }
  },

  getCurrentUser: async (): Promise<User> => {
    try {
      const res = await apiClient.get<User>('/api/v1/auth/me');
      return res.data;
    } catch (err: any) {
      if (err.response?.status === 404) {
        const res = await apiClient.get<User>('/auth/me');
        return res.data;
      }
      throw err;
    }
  },

  getUsers: async (tenantId?: string): Promise<User[]> => {
    const res = await apiClient.get<User[]>('/api/v1/admin/users', {
      params: tenantId ? { tenant_id: tenantId } : undefined,
    });
    return res.data;
  },

  register: async (userData: {
    username: string;
    email: string;
    password: string;
    team_id?: string;
  }): Promise<User> => {
    const res = await apiClient.post<User>('/api/v1/auth/register', userData);
    return res.data;
  },

  adminCreateUser: async (userData: {
    username?: string;
    email: string;
    password: string;
    role: string;
    team_id?: string;
    tenant_id?: string;
  }): Promise<User> => {
    const res = await apiClient.post<User>('/api/v1/admin/users', userData);
    return res.data;
  },

  updateUserStatus: async (
    userId: number | string,
    data: { is_active?: boolean; approval_status?: string; role?: string }
  ): Promise<User> => {
    const res = await apiClient.patch<User>(`/api/v1/admin/users/${userId}/status`, data);
    return res.data;
  },

  deactivateUser: async (userId: number | string): Promise<{ user_id: number | string; status: string }> => {
    const res = await apiClient.delete(`/api/v1/admin/users/${userId}`);
    return res.data;
  },

  listApiKeys: async (tenantId?: string): Promise<any[]> => {
    const res = await apiClient.get('/api/v1/admin/api-keys', {
      params: tenantId ? { tenant_id: tenantId } : undefined,
    });
    return res.data;
  },

  createApiKey: async (data: { label: string; role: string; tenant_id?: string }): Promise<any> => {
    const res = await apiClient.post('/api/v1/admin/api-keys', data);
    return res.data;
  },

  deleteApiKey: async (keyId: string): Promise<any> => {
    const res = await apiClient.delete(`/api/v1/admin/api-keys/${keyId}`);
    return res.data;
  },
};

// ==========================================
// COMPANIES / TENANTS (ADMIN)
// ==========================================
export const companyApi = {
  getCompanies: async (): Promise<any[]> => {
    const res = await apiClient.get('/api/v1/admin/companies');
    return res.data;
  },

  getCompany: async (companyId: string): Promise<any> => {
    const res = await apiClient.get(`/api/v1/admin/companies/${companyId}`);
    return res.data;
  },

  createCompany: async (data: { id?: string; name: string; is_active?: boolean }): Promise<any> => {
    const res = await apiClient.post('/api/v1/admin/companies', data);
    return res.data;
  },

  updateCompany: async (companyId: string, data: { name?: string; is_active?: boolean }): Promise<any> => {
    const res = await apiClient.put(`/api/v1/admin/companies/${companyId}`, data);
    return res.data;
  },
};

// ==========================================
// WORKLOADS (INGEST)
// ==========================================
export const workloadsApi = {
  getJobs: async (params?: { team_id?: string; status?: string; limit?: number }): Promise<Job[]> => {
    const res = await apiClient.get<Job[]>('/api/v1/jobs', { params });
    return res.data;
  },

  getJobById: async (id: string): Promise<Job> => {
    const res = await apiClient.get<Job>(`/api/v1/jobs/${id}`);
    return res.data;
  },

  getJobHistory: async (id: string): Promise<WorkloadDetail> => {
    const res = await apiClient.get<WorkloadDetail>(`/api/v1/jobs/${id}/history`);
    return res.data;
  },

  createJob: async (jobData: CreateJobInput, autoSchedule = false): Promise<JobSubmitResult> => {
    const res = await apiClient.post<JobSubmitResult>('/api/v1/jobs', jobData, {
      params: { auto_schedule: autoSchedule },
    });
    return res.data;
  },

  cancelJob: async (id: string): Promise<{ message: string; job_id: string }> => {
    const res = await apiClient.post<{ message: string; job_id: string }>(`/api/v1/jobs/${id}/cancel`);
    return res.data;
  },

  bulkLoadFromCsv: async (csvPath?: string): Promise<any> => {
    const res = await apiClient.post('/api/v1/jobs/bulk-load', null, {
      params: { csv_path: csvPath },
    });
    return res.data;
  },

  // Read-only browse of the real workload dataset for the Submit Workload
  // "Use Existing Workload Dataset" picker — never writes to the database.
  getDatasetWorkloads: async (params?: { region?: string }): Promise<DatasetWorkloadsResponse> => {
    const res = await apiClient.get<DatasetWorkloadsResponse>('/api/v1/dataset/workloads', { params });
    return res.data;
  },
};

// ==========================================
// SCHEDULING & EXPLAINABILITY
// ==========================================
export const schedulingApi = {
  scheduleJob: async (jobId: string, recordAudit = true): Promise<ScheduleDecision> => {
    const res = await apiClient.post<ScheduleDecision>(`/api/v1/schedule/${jobId}`, null, {
      params: { record_audit: recordAudit },
    });
    return res.data;
  },

  getScheduleDecision: async (jobId: string): Promise<ScheduleDecision> => {
    const res = await apiClient.get<ScheduleDecision>(`/api/v1/schedule/${jobId}`);
    return res.data;
  },

  getExplainability: async (jobId: string): Promise<ScheduleDecision> => {
    const res = await apiClient.get<ScheduleDecision>(`/api/v1/schedule/${jobId}/explain`);
    return res.data;
  },

  batchSchedule: async (data?: {
    job_ids?: string[];
    use_demand_forecast?: boolean;
    max_jobs?: number;
    record_audit?: boolean;
  }): Promise<any> => {
    const res = await apiClient.post('/api/v1/schedule/batch', data || {});
    return res.data;
  },

  getCapacityMap: async (): Promise<any> => {
    const res = await apiClient.get('/api/v1/scheduler/capacity-map');
    return res.data;
  },

  getDemandForecasterStatus: async (): Promise<any> => {
    const res = await apiClient.get('/api/v1/demand-forecaster/status');
    return res.data;
  },
};

// ==========================================
// APPROVALS
// ==========================================
export const approvalsApi = {
  getPendingApprovals: async (teamId?: string): Promise<PendingApprovalItem[]> => {
    const res = await apiClient.get<PendingApprovalItem[]>('/api/v1/approvals/pending', {
      params: teamId ? { team_id: teamId } : undefined,
    });
    return res.data;
  },

  getApprovalHistory: async (teamId?: string): Promise<ApprovalHistoryItem[]> => {
    const res = await apiClient.get<ApprovalHistoryItem[]>('/api/v1/approvals/history', {
      params: teamId ? { team_id: teamId } : undefined,
    });
    return res.data;
  },

  approveJob: async (jobId: string, scheduleId: number, reason?: string): Promise<Approval> => {
    const res = await apiClient.post<Approval>(`/api/v1/approval/${jobId}/approve`, {
      schedule_id: scheduleId,
      reason,
    });
    return res.data;
  },

  declineJob: async (jobId: string, scheduleId: number, reason: string): Promise<Approval> => {
    const res = await apiClient.post<Approval>(`/api/v1/approval/${jobId}/decline`, {
      schedule_id: scheduleId,
      reason,
    });
    return res.data;
  },
};

// ==========================================
// DISPATCH & KUBERNETES
// ==========================================
export const dispatchApi = {
  dispatchJob: async (jobId: string): Promise<any> => {
    const res = await apiClient.post(`/api/v1/dispatch/${jobId}`);
    return res.data;
  },

  getDispatchStatus: async (jobId: string): Promise<KubernetesExecution> => {
    const res = await apiClient.get<KubernetesExecution>(`/api/v1/dispatch/${jobId}/status`);
    return res.data;
  },

  getAllExecutions: async (): Promise<KubernetesExecution[]> => {
    const res = await apiClient.get<KubernetesExecution[]>('/api/v1/dispatch/executions');
    return res.data;
  },

  getK8sHealth: async (): Promise<{ kubernetes_available: boolean; namespace: string }> => {
    const res = await apiClient.get('/api/v1/kubernetes/health');
    return res.data;
  },

  getK8sState: async (): Promise<KubernetesClusterState> => {
    const res = await apiClient.get<KubernetesClusterState>('/api/v1/kubernetes/state');
    return res.data;
  },

  getWorkers: async (): Promise<any> => {
    const res = await apiClient.get('/api/v1/dispatch/workers');
    return res.data;
  },
};

// ==========================================
// DASHBOARD, IMPACT & METRICS
// ==========================================
export const monitoringApi = {
  getDashboardSummary: async (): Promise<DashboardSummary> => {
    const res = await apiClient.get<DashboardSummary>('/api/v1/dashboard/summary');
    return res.data;
  },

  getFleetHeadline: async (): Promise<FleetHeadline> => {
    const res = await apiClient.get<FleetHeadline>('/api/v1/impact/fleet/headline');
    return res.data;
  },

  getFleetImpact: async (params?: { team_id?: string; region_id?: string }): Promise<any> => {
    const res = await apiClient.get('/api/v1/impact/fleet', { params });
    return res.data;
  },

  getActualImpact: async (jobId: string): Promise<ActualImpactResult> => {
    const res = await apiClient.get<ActualImpactResult>(`/api/v1/impact/job/${jobId}/actual`);
    return res.data;
  },

  getFleetActualImpact: async (): Promise<any> => {
    const res = await apiClient.get('/api/v1/impact/fleet/actual');
    return res.data;
  },

  getSystemHealth: async (): Promise<SystemHealthReport> => {
    const res = await apiClient.get<SystemHealthReport>('/health');
    return res.data;
  },

  getSystemLive: async (): Promise<any> => {
    const res = await apiClient.get('/live');
    return res.data;
  },

  getSystemReady: async (): Promise<any> => {
    const res = await apiClient.get('/ready');
    return res.data;
  },

  getMetricsSummary: async (): Promise<any> => {
    const res = await apiClient.get('/api/v1/metrics/summary');
    return res.data;
  },

  getPrometheusMetrics: async (): Promise<string> => {
    const res = await apiClient.get<string>('/metrics', {
      headers: { Accept: 'text/plain' },
    });
    return res.data;
  },
};

// ==========================================
// SUSTAINABILITY, TARIFFS & REGIONS
// ==========================================
export const sustainabilityApi = {
  getRegions: async (): Promise<RegionInfo[]> => {
    const res = await apiClient.get<RegionInfo[]>('/api/v1/regions');
    return res.data;
  },

  getRegionDetail: async (regionId: string): Promise<any> => {
    const res = await apiClient.get(`/api/v1/regions/${regionId}`);
    return res.data;
  },

  getTariffRegions: async (): Promise<{ count: number; regions: any[] }> => {
    const res = await apiClient.get('/api/v1/tariffs/regions');
    return res.data;
  },

  getRegionHourlyTariffs: async (region: string, season?: string): Promise<RegionHourlyTariffsResponse> => {
    const res = await apiClient.get<RegionHourlyTariffsResponse>(`/api/v1/tariffs/${region}`, {
      params: season ? { season } : undefined,
    });
    return res.data;
  },

  getCurrentTariff: async (region: string): Promise<CurrentTariffResponse> => {
    const res = await apiClient.get<CurrentTariffResponse>(`/api/v1/tariffs/${region}/current`);
    return res.data;
  },

  getCarbonData: async (region: string, start?: string, end?: string): Promise<{ region: string; data: any[] }> => {
    const res = await apiClient.get('/api/v1/carbon', {
      params: { region, start, end },
    });
    return res.data;
  },

  getCarbonCurrent: async (region = 'IN-TG'): Promise<{ region: string; carbon_gco2_kwh: number; timestamp: string; source: string; is_fallback: boolean }> => {
    const res = await apiClient.get('/api/v1/carbon/current', {
      params: { region },
    });
    return res.data;
  },

  getRegionalInventory: async (): Promise<any> => {
    const res = await apiClient.get('/api/v1/regional/inventory');
    return res.data;
  },

  getDataSourcesStatus: async (): Promise<any> => {
    const res = await apiClient.get('/api/v1/data-sources/status');
    return res.data;
  },
};

// ==========================================
// REPORTS & EXPORTS
// ==========================================
export const reportsApi = {
  getReportSummary: async (params?: { team_id?: string; start_date?: string; end_date?: string }): Promise<any> => {
    const res = await apiClient.get('/api/v1/report/summary', { params });
    return res.data;
  },

  downloadReportCsv: async (teamId?: string): Promise<string> => {
    const res = await apiClient.get('/api/v1/report/csv', {
      params: teamId ? { team_id: teamId } : undefined,
      headers: { Accept: 'text/csv' },
    });
    return res.data;
  },

  getReportMarkdown: async (teamId?: string): Promise<string> => {
    const res = await apiClient.get('/api/v1/report/markdown', {
      params: teamId ? { team_id: teamId } : undefined,
      headers: { Accept: 'text/markdown' },
    });
    return res.data;
  },
};

// ==========================================
// NOTIFICATIONS
// ==========================================
export const notificationsApi = {
  getNotifications: async (params?: { unread_only?: boolean; limit?: number }): Promise<NotificationItem[]> => {
    const res = await apiClient.get<NotificationItem[]>('/api/v1/notifications', { params });
    return res.data;
  },

  getUnreadCount: async (): Promise<UnreadCountResponse> => {
    const res = await apiClient.get<UnreadCountResponse>('/api/v1/notifications/unread-count');
    return res.data;
  },

  markRead: async (notificationId: number): Promise<NotificationItem> => {
    const res = await apiClient.patch<NotificationItem>(`/api/v1/notifications/${notificationId}/read`);
    return res.data;
  },

  markAllRead: async (): Promise<{ marked_read: number }> => {
    const res = await apiClient.patch<{ marked_read: number }>('/api/v1/notifications/read-all');
    return res.data;
  },

  getPreferences: async (): Promise<NotificationPreferences> => {
    const res = await apiClient.get<NotificationPreferences>('/api/v1/notifications/preferences');
    return res.data;
  },

  updatePreferences: async (update: NotificationPreferencesUpdate): Promise<NotificationPreferences> => {
    const res = await apiClient.put<NotificationPreferences>('/api/v1/notifications/preferences', update);
    return res.data;
  },
};

// ==========================================
// AUDIT & TRUST CHAIN
// ==========================================
export const auditApi = {
  getAuditEvents: async (limit = 50, jobId?: string): Promise<{ events: AuditEvent[] }> => {
    const res = await apiClient.get<{ events: AuditEvent[] }>('/api/v1/trust/events', {
      params: { limit, job_id: jobId },
    });
    return res.data;
  },

  getJobAuditTrail: async (jobId: string): Promise<{ job_id: string; event_count: number; events: AuditEvent[] }> => {
    const res = await apiClient.get(`/api/v1/trust/jobs/${jobId}`);
    return res.data;
  },

  verifyTrustChain: async (): Promise<AuditVerifyResponse> => {
    const res = await apiClient.get<AuditVerifyResponse>('/api/v1/trust/verify');
    return res.data;
  },

  verifyAnchor: async (): Promise<AnchorStatus> => {
    const res = await apiClient.get<AnchorStatus>('/api/v1/trust/anchor/verify');
    return res.data;
  },

  createAnchor: async (): Promise<AnchorCreateResult> => {
    const res = await apiClient.post<AnchorCreateResult>('/api/v1/trust/anchor/create');
    return res.data;
  },
};
