import { SystemHealthReport } from '../../types/api';

// Matches the real GET /health response shape exactly.
export const healthyReport: SystemHealthReport = {
  status: 'healthy',
  service: 'greenshift-api',
  timestamp: '2026-09-10T09:00:00Z',
  checks: { api: 'ok', database: 'ok', kubernetes: 'ok' },
  components: {
    application: { status: 'healthy' },
    database: { status: 'healthy' },
    redis: { status: 'healthy' },
    kubernetes: { status: 'healthy' },
    carbon_data: { status: 'healthy', mode: 'live' },
  },
};

export const degradedReport: SystemHealthReport = {
  status: 'degraded',
  service: 'greenshift-api',
  timestamp: '2026-09-10T09:00:00Z',
  checks: { api: 'ok', database: 'ok', kubernetes: 'degraded' },
  components: {
    application: { status: 'healthy' },
    database: { status: 'healthy' },
    redis: { status: 'degraded', reason: 'high latency' },
    kubernetes: { status: 'unhealthy', reason: 'cluster unreachable' },
    carbon_data: { status: 'degraded', mode: 'fallback', reason: 'primary feed timeout' },
  },
};
