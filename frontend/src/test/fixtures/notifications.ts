import { NotificationItem } from '../../types/api';

/**
 * Fixture notifications matching the real `NotificationResponse` shape
 * (app/shared/models.py), verified live against `GET /api/v1/notifications`
 * during this session. `category` values (ACCOUNT/APPROVAL/EXECUTION/
 * SCHEDULING) and `severity` values (INFO/WARNING/CRITICAL) are the actual
 * values emitted by app/notify/service.py call sites — not invented.
 */
export const unreadScheduleNotification: NotificationItem = {
  id: 1,
  job_id: 'JOB-AAF97A1F',
  event_type: 'SCHEDULE_PROPOSED',
  category: 'SCHEDULING',
  severity: 'INFO',
  title: "Workload JOB-AAF97A1F ready for approval",
  message:
    "A schedule for workload 'JOB-AAF97A1F' is ready for review (carbon: 0.4060 kg CO2, start: 2026-09-10T08:00:00+00:00).",
  action_url: null,
  created_at: '2026-09-10T06:10:13.775090',
  read_at: null,
  is_read: false,
};

export const readApprovalNotification: NotificationItem = {
  id: 2,
  job_id: 'JOB-AAF97A1F',
  event_type: 'APPROVAL_GRANTED',
  category: 'APPROVAL',
  severity: 'INFO',
  title: 'Schedule approved',
  message: "Schedule for workload 'JOB-AAF97A1F' was approved by company_user.",
  action_url: null,
  created_at: '2026-09-10T06:11:00.000000',
  read_at: '2026-09-10T06:12:00.000000',
  is_read: true,
};

export const criticalExecutionNotification: NotificationItem = {
  id: 3,
  job_id: 'JOB-B22C0001',
  event_type: 'K8S_JOB_FAILED',
  category: 'EXECUTION',
  severity: 'CRITICAL',
  title: 'Workload execution failed',
  message: "Kubernetes execution for workload 'JOB-B22C0001' failed.",
  action_url: null,
  created_at: '2026-09-10T05:00:00.000000',
  read_at: null,
  is_read: false,
};

export const notificationList: NotificationItem[] = [
  unreadScheduleNotification,
  readApprovalNotification,
  criticalExecutionNotification,
];
