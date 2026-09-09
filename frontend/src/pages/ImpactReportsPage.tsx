import React, { useState, useEffect } from 'react';
import {
  TrendingDown,
  Download,
  FileText,
  FileSpreadsheet,
  Leaf,
  DollarSign,
  TreeDeciduous,
  Car,
  ShieldCheck,
  Calendar,
  RefreshCw,
  AlertTriangle,
} from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassCard } from '../components/common/GlassCard';
import { KPICard } from '../components/common/KPICard';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { EmptyState } from '../components/common/EmptyState';
import { monitoringApi, reportsApi } from '../api/endpoints';
import { useAuth } from '../context/AuthContext';

export const ImpactReportsPage: React.FC = () => {
  const { user, isAdmin } = useAuth();
  const [fleetImpact, setFleetImpact] = useState<any | null>(null);
  const [headline, setHeadline] = useState<any | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isDownloadingCsv, setIsDownloadingCsv] = useState(false);
  const [isDownloadingMd, setIsDownloadingMd] = useState(false);
  const [downloadNotice, setDownloadNotice] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const fetchImpactData = async () => {
    setIsLoading(true);
    setErrorMsg(null);
    try {
      const [impactRes, headRes] = await Promise.allSettled([
        monitoringApi.getFleetImpact({ team_id: isAdmin ? undefined : user?.team_id }),
        monitoringApi.getFleetHeadline(),
      ]);

      if (impactRes.status === 'fulfilled') {
        setFleetImpact(impactRes.value);
      }
      if (headRes.status === 'fulfilled') {
        setHeadline(headRes.value);
      }
    } catch (err: any) {
      setErrorMsg('Failed to fetch fleet impact metrics from backend.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchImpactData();
  }, [user]);

  const handleDownloadCsv = async () => {
    setIsDownloadingCsv(true);
    try {
      const csvData = await reportsApi.downloadReportCsv(isAdmin ? undefined : user?.team_id);
      const blob = new Blob([csvData], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `greenshift_brsr_report_${new Date().toISOString().slice(0, 10)}.csv`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      setDownloadNotice('BRSR compliance CSV report downloaded successfully from backend.');
      setTimeout(() => setDownloadNotice(null), 4000);
    } catch (err: any) {
      alert('Failed to download CSV report: ' + (err.response?.data?.detail || err.message));
    } finally {
      setIsDownloadingCsv(false);
    }
  };

  const handleDownloadMarkdown = async () => {
    setIsDownloadingMd(true);
    try {
      const mdData = await reportsApi.getReportMarkdown(isAdmin ? undefined : user?.team_id);
      const blob = new Blob([mdData], { type: 'text/markdown;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `greenshift_sustainability_report_${new Date().toISOString().slice(0, 10)}.md`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      setDownloadNotice('BRSR Markdown executive summary generated and downloaded from backend.');
      setTimeout(() => setDownloadNotice(null), 4000);
    } catch (err: any) {
      alert('Failed to download Markdown report: ' + (err.response?.data?.detail || err.message));
    } finally {
      setIsDownloadingMd(false);
    }
  };

  const totalCarbonAvoided = fleetImpact?.total_carbon_avoided_kg ?? headline?.total_carbon_avoided_kg ?? 0;
  const avgReductionPct = fleetImpact?.avg_carbon_reduction_pct ?? headline?.avg_carbon_reduction_pct ?? 0;
  const totalCostSaved = fleetImpact?.total_cost_saved_usd ?? headline?.total_cost_saved_usd ?? 0;
  const totalJobs = fleetImpact?.total_jobs_with_decisions ?? headline?.total_jobs ?? 0;
  const treesPlanted = fleetImpact?.trees_equivalent_annual ?? Math.round(totalCarbonAvoided / 20.0);
  const carMiles = fleetImpact?.car_miles_avoided ?? Math.round(totalCarbonAvoided * 2.47);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      <PageHeader
        title="Fleet Sustainability & ESG Impact"
        subtitle="Auditable carbon avoidance accounting, energy efficiency metrics, and executive exportable compliance reports"
        actions={
          <div style={{ display: 'flex', gap: '0.6rem' }}>
            <button className="btn btn-secondary" onClick={handleDownloadCsv} disabled={isDownloadingCsv}>
              <FileSpreadsheet size={15} />
              <span>{isDownloadingCsv ? 'Generating...' : 'Export BRSR CSV'}</span>
            </button>
            <button className="btn btn-primary" onClick={handleDownloadMarkdown} disabled={isDownloadingMd}>
              <FileText size={15} />
              <span>{isDownloadingMd ? 'Generating...' : 'Export Audit Markdown'}</span>
            </button>
          </div>
        }
      />

      {downloadNotice && (
        <div
          style={{
            background: 'rgba(16, 185, 129, 0.12)',
            border: '1px solid rgba(16, 185, 129, 0.4)',
            color: '#10b981',
            padding: '0.75rem 1rem',
            borderRadius: 'var(--radius-sm)',
            fontSize: '0.85rem',
            fontWeight: 600,
          }}
        >
          ✓ {downloadNotice}
        </div>
      )}

      {errorMsg && (
        <div
          style={{
            background: 'rgba(239, 68, 68, 0.15)',
            border: '1px solid #ef4444',
            color: '#ef4444',
            padding: '1rem',
            borderRadius: 'var(--radius-md)',
            fontSize: '0.85rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.75rem',
          }}
        >
          <AlertTriangle size={20} />
          <span>{errorMsg}</span>
        </div>
      )}

      {isLoading ? (
        <LoadingSkeleton rows={6} height={60} />
      ) : (
        <>
          {/* KPI Cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem' }}>
            <KPICard
              title="Avoided Carbon"
              value={`${totalCarbonAvoided.toFixed(1)} kg`}
              subtitle="Net emissions saved vs baseline"
              icon={Leaf}
              color="emerald"
            />
            <KPICard
              title="Average Reduction"
              value={`${avgReductionPct.toFixed(1)}%`}
              subtitle="Per scheduled workload"
              icon={TrendingDown}
              color="cyan"
            />
            <KPICard
              title="Energy Cost Savings"
              value={`$${totalCostSaved.toFixed(2)}`}
              subtitle="Time-of-Day tariff arbitrage"
              icon={DollarSign}
              color="amber"
            />
            <KPICard
              title="Optimized Workloads"
              value={totalJobs}
              subtitle="Scheduled carbon-first jobs"
              icon={ShieldCheck}
              color="indigo"
            />
          </div>

          {/* Equivalency Impact Banner */}
          <GlassCard title="Environmental Equivalence Conversions (EPA Metric Guidelines)">
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem', background: 'var(--bg-surface-elevated)', padding: '1.25rem', borderRadius: 'var(--radius-sm)' }}>
                <div
                  style={{
                    width: '46px',
                    height: '46px',
                    borderRadius: 'var(--radius-sm)',
                    background: 'rgba(16, 185, 129, 0.15)',
                    color: '#10b981',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <TreeDeciduous size={24} />
                </div>
                <div>
                  <div style={{ fontSize: '1.6rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: '#ffffff' }}>
                    {treesPlanted.toLocaleString()} Trees
                  </div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.15rem' }}>
                    Equivalent carbon sequestered by urban tree seedlings grown for 10 years
                  </div>
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem', background: 'var(--bg-surface-elevated)', padding: '1.25rem', borderRadius: 'var(--radius-sm)' }}>
                <div
                  style={{
                    width: '46px',
                    height: '46px',
                    borderRadius: 'var(--radius-sm)',
                    background: 'rgba(56, 189, 248, 0.15)',
                    color: '#38bdf8',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <Car size={24} />
                </div>
                <div>
                  <div style={{ fontSize: '1.6rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: '#ffffff' }}>
                    {carMiles.toLocaleString()} Miles
                  </div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.15rem' }}>
                    Avoided passenger vehicle gasoline emissions equivalent
                  </div>
                </div>
              </div>
            </div>
          </GlassCard>

          {/* Team Breakdown Table */}
          {fleetImpact?.by_team && Object.keys(fleetImpact.by_team).length > 0 && (
            <GlassCard title="Carbon Avoidance by Engineering Team">
              <div className="data-table-container">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Team Identifier</th>
                      <th>Jobs Scheduled</th>
                      <th>Avoided Emissions (kg CO₂e)</th>
                      <th>Energy Savings (USD)</th>
                      <th>Avg Reduction (%)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(fleetImpact.by_team).map(([team, data]: [string, any]) => (
                      <tr key={team}>
                        <td>
                          <span style={{ fontWeight: 600, color: '#ffffff' }}>{team}</span>
                        </td>
                        <td>
                          <span style={{ fontFamily: 'var(--font-mono)' }}>{data.count || 0}</span>
                        </td>
                        <td>
                          <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#10b981' }}>
                            {data.total_carbon_avoided_kg ? `${data.total_carbon_avoided_kg.toFixed(2)} kg` : '0 kg'}
                          </span>
                        </td>
                        <td>
                          <span style={{ fontFamily: 'var(--font-mono)', color: '#38bdf8' }}>
                            {data.total_cost_saved_usd ? `$${data.total_cost_saved_usd.toFixed(2)}` : '$0.00'}
                          </span>
                        </td>
                        <td>
                          <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#10b981' }}>
                            {data.avg_carbon_reduction_pct ? `${data.avg_carbon_reduction_pct.toFixed(1)}%` : '--'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </GlassCard>
          )}

          {/* Regional Breakdown Table */}
          {fleetImpact?.by_region && Object.keys(fleetImpact.by_region).length > 0 && (
            <GlassCard title="Carbon Avoidance by Grid Region">
              <div className="data-table-container">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Region Code</th>
                      <th>Jobs Dispatched</th>
                      <th>Avoided Emissions (kg CO₂e)</th>
                      <th>Cost Saved (USD)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(fleetImpact.by_region).map(([reg, data]: [string, any]) => (
                      <tr key={reg}>
                        <td>
                          <span style={{ fontWeight: 600, color: '#38bdf8' }}>{reg}</span>
                        </td>
                        <td>
                          <span style={{ fontFamily: 'var(--font-mono)' }}>{data.count || 0}</span>
                        </td>
                        <td>
                          <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#10b981' }}>
                            {data.total_carbon_avoided_kg ? `${data.total_carbon_avoided_kg.toFixed(2)} kg` : '0 kg'}
                          </span>
                        </td>
                        <td>
                          <span style={{ fontFamily: 'var(--font-mono)', color: '#ffffff' }}>
                            {data.total_cost_saved_usd ? `$${data.total_cost_saved_usd.toFixed(2)}` : '$0.00'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </GlassCard>
          )}
        </>
      )}
    </div>
  );
};
