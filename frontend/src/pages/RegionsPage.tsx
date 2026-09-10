import React, { useState, useEffect } from 'react';
import {
  Globe,
  Server,
  Zap,
  Activity,
  Cpu,
  Layers,
  CheckCircle2,
  RefreshCw,
} from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassCard } from '../components/common/GlassCard';
import { StatusBadge } from '../components/common/StatusBadge';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { EmptyState } from '../components/common/EmptyState';
import { InlineBanner } from '../components/common/InlineBanner';
import { sustainabilityApi, dispatchApi, workloadsApi } from '../api/endpoints';
import { RegionInfo, KubernetesClusterState, Job } from '../types/api';

interface EnrichedRegion extends RegionInfo {
  carbonGco2Kwh?: number;
  carbonSource?: string;
  isFallbackCarbon?: boolean;
  tariffUsd?: number;
  tariffCurrency?: string;
  activeJobsCount: number;
}

export const RegionsPage: React.FC = () => {
  const [regions, setRegions] = useState<EnrichedRegion[]>([]);
  const [clusterState, setClusterState] = useState<KubernetesClusterState | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const fetchRegionalData = async () => {
    setIsLoading(true);
    setErrorMsg(null);
    try {
      const [regRes, k8sRes, jobsRes] = await Promise.allSettled([
        sustainabilityApi.getRegions(),
        dispatchApi.getK8sState(),
        workloadsApi.getJobs({ limit: 500 }),
      ]);

      const baseRegions: RegionInfo[] = regRes.status === 'fulfilled' ? regRes.value || [] : [];
      if (regRes.status === 'rejected') {
        setErrorMsg('Failed to load regional cluster data from backend.');
      }
      if (k8sRes.status === 'fulfilled') {
        setClusterState(k8sRes.value);
      }
      const jobs: Job[] = jobsRes.status === 'fulfilled' ? jobsRes.value || [] : [];

      // Calculate jobs per region
      const jobsPerRegion: Record<string, number> = {};
      jobs.forEach((j) => {
        if (j.region) {
          jobsPerRegion[j.region] = (jobsPerRegion[j.region] || 0) + 1;
        }
      });

      // Enrich each region with live carbon and tariff data
      const enriched: EnrichedRegion[] = await Promise.all(
        baseRegions.map(async (r) => {
          let carbonGco2Kwh: number | undefined;
          let carbonSource: string | undefined;
          let isFallbackCarbon: boolean | undefined;
          let tariffUsd: number | undefined;
          let tariffCurrency = r.currency || 'USD';

          try {
            const c = await sustainabilityApi.getCarbonCurrent(r.region_id);
            if (c) {
              carbonGco2Kwh = c.carbon_gco2_kwh;
              carbonSource = c.source;
              isFallbackCarbon = c.is_fallback;
            }
          } catch {
            // ignore individual regional carbon error
          }

          try {
            const t = await sustainabilityApi.getCurrentTariff(r.region_id);
            if (t?.current_tariff) {
              tariffUsd = t.current_tariff.price_per_kwh_usd;
              tariffCurrency = t.currency || tariffCurrency;
            }
          } catch {
            // ignore individual regional tariff error
          }

          return {
            ...r,
            carbonGco2Kwh,
            carbonSource,
            isFallbackCarbon,
            tariffUsd,
            tariffCurrency,
            activeJobsCount: jobsPerRegion[r.region_id] || 0,
          };
        })
      );

      setRegions(enriched);
    } catch (err: any) {
      setErrorMsg('Failed to load regional data from backend.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchRegionalData();
  }, []);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      <PageHeader
        title="Multi-Region Capacity & Grid Health"
        subtitle="Regional grid carbon intensity telemetry, Time-of-Day electricity tariffs, and Kubernetes compute capacity"
        actions={
          <button className="btn btn-secondary" onClick={fetchRegionalData} disabled={isLoading}>
            <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
            <span>Sync Regions</span>
          </button>
        }
      />

      {errorMsg && <InlineBanner variant="error">{errorMsg}</InlineBanner>}

      {/* Cluster Node Summary Bar */}
      {clusterState && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem' }}>
          <div style={{ background: 'var(--bg-surface)', padding: '1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Kubernetes Controller</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.25rem' }}>
              <span className="pulse-dot" style={{ color: clusterState.connected ? '#10b981' : '#f59e0b' }} />
              <span style={{ fontWeight: 700, color: clusterState.connected ? '#10b981' : '#f59e0b', fontFamily: 'var(--font-mono)' }}>
                {clusterState.connected ? 'CONNECTED' : 'SIMULATION MODE'}
              </span>
            </div>
          </div>
          <div style={{ background: 'var(--bg-surface)', padding: '1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Allocatable CPU Cores</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: '#38bdf8' }}>
              {clusterState.free_cpu_cores} / {clusterState.total_cpu_cores} Cores Free
            </div>
          </div>
          <div style={{ background: 'var(--bg-surface)', padding: '1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Allocatable Memory</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: '#10b981' }}>
              {Math.round(clusterState.free_memory_mib / 1024)} GiB Free
            </div>
          </div>
          <div style={{ background: 'var(--bg-surface)', padding: '1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Cluster Worker Nodes</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 800, fontFamily: 'var(--font-mono)' }}>
              {clusterState.ready_nodes} / {clusterState.total_nodes} Ready
            </div>
          </div>
        </div>
      )}

      {isLoading ? (
        <LoadingSkeleton rows={6} height={120} />
      ) : regions.length === 0 ? (
        <EmptyState
          title="No Regional Configurations Available"
          description="Regional registry is empty or could not be loaded from backend."
          icon={Globe}
        />
      ) : (
        /* Grid of Regional Cards */
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
            gap: '1.25rem',
          }}
        >
          {regions.map((r) => {
            const carbonVal = r.carbonGco2Kwh ?? 380;
            const isClean = carbonVal < 150;
            const isModerate = carbonVal >= 150 && carbonVal < 350;
            const statusColor = isClean ? '#10b981' : isModerate ? '#f59e0b' : '#ef4444';

            return (
              <GlassCard key={r.region_id}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                  {/* Region Header */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <h3 style={{ fontSize: '1.1rem' }}>{r.region_name}</h3>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                        {r.region_id} • {r.country} • {r.timezone}
                      </div>
                    </div>
                    <StatusBadge status={r.is_active ? 'ACTIVE' : 'INACTIVE'} size="sm" />
                  </div>

                  {/* Primary Metrics */}
                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: '1fr 1fr',
                      gap: '0.75rem',
                      background: 'var(--bg-surface-elevated)',
                      padding: '0.85rem',
                      borderRadius: 'var(--radius-sm)',
                    }}
                  >
                    <div>
                      <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Grid Intensity</div>
                      <div
                        style={{
                          fontSize: '1.3rem',
                          fontWeight: 800,
                          color: statusColor,
                          fontFamily: 'var(--font-mono)',
                        }}
                      >
                        {r.carbonGco2Kwh !== undefined ? r.carbonGco2Kwh.toFixed(0) : '--'}
                        <span style={{ fontSize: '0.75rem', marginLeft: '0.2rem' }}>gCO₂/kWh</span>
                      </div>
                      <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                        Source: {r.carbonSource || (r.isFallbackCarbon ? 'Fallback' : 'Electricity Maps')}
                      </div>
                    </div>

                    <div>
                      <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Tariff Rate</div>
                      <div
                        style={{
                          fontSize: '1.3rem',
                          fontWeight: 800,
                          color: '#38bdf8',
                          fontFamily: 'var(--font-mono)',
                        }}
                      >
                        {r.tariffUsd !== undefined ? `$${r.tariffUsd.toFixed(4)}` : '--'}
                        <span style={{ fontSize: '0.75rem', marginLeft: '0.2rem' }}>/kWh</span>
                      </div>
                      <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                        Plan: {r.default_plan || 'Industrial ToD'}
                      </div>
                    </div>
                  </div>

                  {/* Supported Tariff Plans */}
                  {r.supported_tariff_plans && r.supported_tariff_plans.length > 0 && (
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Available Plans: </span>
                      {r.supported_tariff_plans.map((p) => p.display_name).join(', ')}
                    </div>
                  )}

                  {/* Active Jobs Running */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.78rem', paddingTop: '0.5rem', borderTop: '1px solid var(--border-subtle)' }}>
                    <span style={{ color: 'var(--text-muted)' }}>Workloads in Queue</span>
                    <span style={{ fontWeight: 600, fontFamily: 'var(--font-mono)', color: r.activeJobsCount > 0 ? '#10b981' : 'var(--text-muted)' }}>
                      {r.activeJobsCount} jobs
                    </span>
                  </div>
                </div>
              </GlassCard>
            );
          })}
        </div>
      )}
    </div>
  );
};
