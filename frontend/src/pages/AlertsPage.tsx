import React, { useState, useEffect } from 'react';
import {
  AlertTriangle,
  AlertCircle,
  Info,
  CheckCircle2,
  Bell,
  Clock,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassCard } from '../components/common/GlassCard';
import { EmptyState } from '../components/common/EmptyState';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { monitoringApi } from '../api/endpoints';
import { SystemHealthReport } from '../types/api';

interface RealAlertItem {
  id: string;
  severity: 'critical' | 'warning' | 'info';
  title: string;
  description: string;
  source: string;
  timestamp: string;
  acknowledged: boolean;
}

export const AlertsPage: React.FC = () => {
  const [alerts, setAlerts] = useState<RealAlertItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const fetchAlerts = async () => {
    setIsRefreshing(true);
    try {
      const health: SystemHealthReport = await monitoringApi.getSystemHealth();
      const generatedAlerts: RealAlertItem[] = [];
      const nowStr = new Date().toLocaleTimeString();

      if (health && health.components) {
        const comp = health.components;

        // Database alert
        if (comp.database?.status && comp.database.status !== 'healthy') {
          generatedAlerts.push({
            id: 'alert-db',
            severity: 'critical',
            title: 'Database Connectivity Degradation',
            description: `Database status: ${comp.database.status}. Reason: ${comp.database.reason || 'Failed health check'}. Workload submission and claiming may be impacted.`,
            source: 'PostgreSQL / Database Health Probe',
            timestamp: nowStr,
            acknowledged: false,
          });
        }

        // Redis alert
        if (comp.redis?.status && comp.redis.status !== 'healthy') {
          generatedAlerts.push({
            id: 'alert-redis',
            severity: 'warning',
            title: 'Redis Cache Telemetry Offline',
            description: `Redis status: ${comp.redis.status}. Reason: ${comp.redis.reason || 'Connection refused'}. Carbon observation cache is operating via fallback memory.`,
            source: 'Redis Telemetry Broker',
            timestamp: nowStr,
            acknowledged: false,
          });
        }

        // Kubernetes alert
        if (comp.kubernetes?.status && comp.kubernetes.status !== 'healthy') {
          generatedAlerts.push({
            id: 'alert-k8s',
            severity: 'warning',
            title: 'Kubernetes Cluster Controller Degraded',
            description: `Kubernetes status: ${comp.kubernetes.status}. Reason: ${comp.kubernetes.reason || 'Unreachable API'}. Dispatch loop operating in simulation mode.`,
            source: 'Kubernetes Dispatch Controller',
            timestamp: nowStr,
            acknowledged: false,
          });
        }

        // Carbon data fallback alert
        if (comp.carbon_data?.status && comp.carbon_data.status !== 'healthy') {
          generatedAlerts.push({
            id: 'alert-carbon',
            severity: 'info',
            title: 'Carbon Data Fallback Hierarchy Active',
            description: `Carbon data mode: ${comp.carbon_data.mode || comp.carbon_data.reason || 'Controlled fallback'}. Live marginal data substituted by regional dataset baseline.`,
            source: 'Carbon Telemetry Feed',
            timestamp: nowStr,
            acknowledged: false,
          });
        }
      }

      setAlerts(generatedAlerts);
    } catch {
      // Backend completely unreachable
      setAlerts([
        {
          id: 'alert-backend-down',
          severity: 'critical',
          title: 'FastAPI Control Plane Unreachable',
          description: 'Unable to connect to GreenShift API at http://localhost:8000. Check server logs.',
          source: 'API Client / Health Probe',
          timestamp: new Date().toLocaleTimeString(),
          acknowledged: false,
        },
      ]);
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    fetchAlerts();
  }, []);

  const handleAcknowledge = (id: string) => {
    setAlerts((prev) =>
      prev.map((a) => (a.id === id ? { ...a, acknowledged: true } : a))
    );
  };

  const activeAlerts = alerts.filter((a) => !a.acknowledged);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      <PageHeader
        title="Alerts & Incident Management"
        subtitle="Policy violation warnings, regional grid emissions spikes, and Kubernetes cluster capacity notifications"
        badge={
          <span className={`badge ${activeAlerts.length > 0 ? 'badge-warning' : 'badge-success'}`}>
            {activeAlerts.length} ACTIVE INCIDENTS
          </span>
        }
        actions={
          <button className="btn btn-secondary" onClick={fetchAlerts} disabled={isRefreshing}>
            <RefreshCw size={14} className={isRefreshing ? 'animate-spin' : ''} />
            <span>{isRefreshing ? 'Checking...' : 'Check Incidents'}</span>
          </button>
        }
      />

      {isLoading ? (
        <LoadingSkeleton rows={4} height={70} />
      ) : activeAlerts.length === 0 ? (
        <EmptyState
          title="All Systems Operational"
          description="Zero active incident alerts or policy violations detected. Real-time health probes confirm all database, Redis, and carbon telemetry subsystems are functioning normally."
          icon={ShieldCheck}
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {alerts.map((alt) => {
            const isCritical = alt.severity === 'critical';
            const isWarning = alt.severity === 'warning';
            const borderStyle = isCritical
              ? 'rgba(239, 68, 68, 0.4)'
              : isWarning
              ? 'rgba(245, 158, 11, 0.4)'
              : 'rgba(59, 130, 246, 0.4)';

            return (
              <GlassCard key={alt.id} style={{ borderColor: borderStyle, opacity: alt.acknowledged ? 0.6 : 1 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
                  <div style={{ display: 'flex', gap: '1rem', alignItems: 'flex-start' }}>
                    <div
                      style={{
                        width: '36px',
                        height: '36px',
                        borderRadius: 'var(--radius-sm)',
                        background: isCritical
                          ? 'rgba(239, 68, 68, 0.15)'
                          : isWarning
                          ? 'rgba(245, 158, 11, 0.15)'
                          : 'rgba(59, 130, 246, 0.15)',
                        color: isCritical ? '#ef4444' : isWarning ? '#f59e0b' : '#3b82f6',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        flexShrink: 0,
                      }}
                    >
                      {isCritical ? <AlertTriangle size={20} /> : isWarning ? <AlertCircle size={20} /> : <Info size={20} />}
                    </div>

                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                        <h4 style={{ fontSize: '0.95rem', margin: 0 }}>{alt.title}</h4>
                        <span className={`badge ${isCritical ? 'badge-danger' : isWarning ? 'badge-warning' : 'badge-info'}`}>
                          {alt.severity.toUpperCase()}
                        </span>
                      </div>

                      <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginTop: '0.4rem', lineHeight: 1.5 }}>
                        {alt.description}
                      </p>

                      <div style={{ display: 'flex', gap: '1rem', fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.5rem' }}>
                        <span>Source: <strong style={{ color: 'var(--text-primary)' }}>{alt.source}</strong></span>
                        <span>Detected: {alt.timestamp}</span>
                      </div>
                    </div>
                  </div>

                  {!alt.acknowledged ? (
                    <button className="btn btn-secondary btn-sm" onClick={() => handleAcknowledge(alt.id)}>
                      <CheckCircle2 size={14} />
                      <span>Acknowledge</span>
                    </button>
                  ) : (
                    <span style={{ fontSize: '0.75rem', color: '#10b981', fontWeight: 600 }}>
                      ✓ Acknowledged
                    </span>
                  )}
                </div>
              </GlassCard>
            );
          })}
        </div>
      )}
    </div>
  );
};
