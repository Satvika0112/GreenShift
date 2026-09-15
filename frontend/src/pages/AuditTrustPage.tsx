import React, { useState, useEffect } from 'react';
import {
  ShieldCheck,
  CheckCircle2,
  Search,
  Database,
  AlertTriangle,
  Anchor,
  Download,
  Filter,
  X,
} from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassCard } from '../components/common/GlassCard';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { EmptyState } from '../components/common/EmptyState';
import { auditApi } from '../api/endpoints';
import { AuditEvent, AnchorStatus, AuditAnchor, TrustEventFilters } from '../types/api';
import { formatRegionalDateTime } from '../utils/dateTime';
import { useAuth } from '../context/AuthContext';

const EVENT_TYPES = [
  'JOB_SUBMITTED', 'JOB_VALIDATED', 'JOB_SCHEDULED', 'SCHEDULE_PROPOSED',
  'APPROVAL_GRANTED', 'APPROVAL_DECLINED', 'DISPATCH_REQUESTED', 'DISPATCH_BLOCKED',
  'DISPATCH_STARTED', 'DISPATCH_AUTHORIZED', 'K8S_JOB_CREATED', 'K8S_JOB_STARTED',
  'K8S_JOB_COMPLETED', 'K8S_JOB_FAILED', 'JOB_CANCELLED', 'SCHEDULING_FAILED',
  'AUDIT_ANCHOR_CREATED', 'AUTH_LOGIN_SUCCESS', 'AUTH_LOGIN_FAILURE',
  'OPTIMIZATION_POLICY_CHANGED',
];

export const AuditTrustPage: React.FC = () => {
  const { user, isPlatformAdmin, isCompanyAdmin } = useAuth();
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [isVerifying, setIsVerifying] = useState(false);
  const [isCreatingAnchor, setIsCreatingAnchor] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [anchorStatus, setAnchorStatus] = useState<AnchorStatus | null>(null);
  const [anchors, setAnchors] = useState<AuditAnchor[]>([]);
  const [anchorVerifyResult, setAnchorVerifyResult] = useState<Record<number, AnchorStatus>>({});
  const [verificationResult, setVerificationResult] = useState<{
    status: 'VALID' | 'INVALID';
    eventCount: number;
    message: string;
    failedCheck?: string | null;
    failedSequence?: number | null;
  } | null>(null);
  const [lastVerifiedAt, setLastVerifiedAt] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showFilters, setShowFilters] = useState(false);
  const [filters, setFilters] = useState<TrustEventFilters>({});
  const [draftFilters, setDraftFilters] = useState<TrustEventFilters>({});
  const [isExporting, setIsExporting] = useState(false);

  const fetchLedger = async (activeFilters: TrustEventFilters) => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const [eventsRes, anchorRes] = await Promise.allSettled([
        activeFilters.job_id
          ? auditApi.getJobAuditTrail(activeFilters.job_id)
          : auditApi.getAuditEvents(activeFilters),
        auditApi.verifyAnchor(),
      ]);

      if (eventsRes.status === 'fulfilled') {
        setEvents(eventsRes.value?.events || []);
      } else {
        setLoadError('Failed to load cryptographic audit ledger from backend.');
      }
      if (anchorRes.status === 'fulfilled') {
        setAnchorStatus(anchorRes.value);
      }
    } catch {
      setLoadError('Failed to load cryptographic audit ledger from backend.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchLedger(filters);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  useEffect(() => {
    if (isPlatformAdmin) {
      auditApi.listAnchors().then((res) => setAnchors(res.anchors)).catch(() => {});
    }
  }, [isPlatformAdmin]);

  const handleVerifyChain = async () => {
    setIsVerifying(true);
    try {
      const res = await auditApi.verifyTrustChain();
      setVerificationResult({
        status: res.valid ? 'VALID' : 'INVALID',
        eventCount: res.event_count,
        message: res.message,
        failedCheck: res.failed_check,
        failedSequence: res.failed_sequence,
      });
      setLastVerifiedAt(new Date().toISOString());
    } catch (err: any) {
      setVerificationResult({
        status: 'INVALID',
        eventCount: events.length,
        message: err.response?.data?.detail || 'Verification failed. Backend error.',
      });
    } finally {
      setIsVerifying(false);
    }
  };

  const handleCreateAnchor = async () => {
    setIsCreatingAnchor(true);
    try {
      await auditApi.createAnchor();
      const updated = await auditApi.verifyAnchor();
      setAnchorStatus(updated);
      const list = await auditApi.listAnchors();
      setAnchors(list.anchors);
      alert('External cryptographic anchor successfully checkpointed.');
    } catch (err: any) {
      alert('Anchor creation failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setIsCreatingAnchor(false);
    }
  };

  const handleVerifySpecificAnchor = async (anchorId: number) => {
    try {
      const result = await auditApi.verifyAnchorById(anchorId);
      setAnchorVerifyResult((prev) => ({ ...prev, [anchorId]: result }));
    } catch (err: any) {
      setAnchorVerifyResult((prev) => ({
        ...prev,
        [anchorId]: { status: 'error', verified: false, message: err.response?.data?.detail || 'Verification failed.' },
      }));
    }
  };

  const handleApplyFilters = () => {
    setFilters(draftFilters);
    setShowFilters(false);
  };

  const handleClearFilters = () => {
    setDraftFilters({});
    setFilters({});
  };

  const handleExport = async (format: 'csv' | 'json') => {
    setIsExporting(true);
    try {
      const blob = await auditApi.exportEvents(filters, format);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `audit_export.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err: any) {
      alert('Export failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setIsExporting(false);
    }
  };

  const filteredEvents = events.filter((e) => {
    const term = searchTerm.toLowerCase();
    return (
      (e.job_id && e.job_id.toLowerCase().includes(term)) ||
      (e.event_type && e.event_type.toLowerCase().includes(term)) ||
      (e.current_hash && e.current_hash.toLowerCase().includes(term))
    );
  });

  const activeFilterCount = Object.values(filters).filter(Boolean).length;
  const visibilityLabel = isPlatformAdmin
    ? 'Global (all companies)'
    : isCompanyAdmin
    ? `Company-wide — ${user?.company_name || user?.tenant_id || 'your company'}`
    : `Your team — ${user?.team_id || 'unassigned'}`;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      <PageHeader
        title="Cryptographic Audit & Trust Ledger"
        subtitle="Immutable SHA-256 hash-chained event provenance protecting against tampering, unauthorized overrides, and dispatch discrepancies"
        actions={
          <div style={{ display: 'flex', gap: '0.6rem', flexWrap: 'wrap' }}>
            <button className="btn btn-secondary" onClick={() => setShowFilters((s) => !s)}>
              <Filter size={15} />
              <span>Filters{activeFilterCount > 0 ? ` (${activeFilterCount})` : ''}</span>
            </button>
            <button className="btn btn-secondary" onClick={() => handleExport('csv')} disabled={isExporting}>
              <Download size={15} />
              <span>Export CSV</span>
            </button>
            {isPlatformAdmin && (
              <>
                <button
                  className="btn btn-secondary"
                  onClick={handleCreateAnchor}
                  disabled={isCreatingAnchor}
                  title="Create immutable checkpoint anchor"
                >
                  <Anchor size={15} className={isCreatingAnchor ? 'animate-spin' : ''} />
                  <span>{isCreatingAnchor ? 'Anchoring...' : 'Create Anchor'}</span>
                </button>
                <button
                  className="btn btn-primary"
                  onClick={handleVerifyChain}
                  disabled={isVerifying}
                >
                  <ShieldCheck size={16} className={isVerifying ? 'animate-spin' : ''} />
                  <span>{isVerifying ? 'Verifying Hashes...' : 'Verify Cryptographic Chain'}</span>
                </button>
              </>
            )}
          </div>
        }
      />

      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
        Visibility scope: <strong style={{ color: 'var(--text-primary)' }}>{visibilityLabel}</strong>
        {!isPlatformAdmin && (
          <span> — chain verification and anchor management are Platform Admin-only.</span>
        )}
      </div>

      {showFilters && (
        <GlassCard title="Filters" subtitle="Applied on top of your authorized visibility scope — never bypasses it">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '0.75rem' }}>
            <input
              className="input"
              placeholder="Job ID"
              value={draftFilters.job_id || ''}
              onChange={(e) => setDraftFilters((f) => ({ ...f, job_id: e.target.value || undefined }))}
            />
            <input
              className="input"
              placeholder="Team ID"
              value={draftFilters.team_id || ''}
              onChange={(e) => setDraftFilters((f) => ({ ...f, team_id: e.target.value || undefined }))}
            />
            <input
              className="input"
              placeholder="Actor (username)"
              value={draftFilters.actor || ''}
              onChange={(e) => setDraftFilters((f) => ({ ...f, actor: e.target.value || undefined }))}
            />
            <select
              className="input"
              value={draftFilters.event_type || ''}
              onChange={(e) => setDraftFilters((f) => ({ ...f, event_type: e.target.value || undefined }))}
            >
              <option value="">All event types</option>
              {EVENT_TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
            <input
              className="input"
              type="datetime-local"
              value={draftFilters.start_time || ''}
              onChange={(e) => setDraftFilters((f) => ({ ...f, start_time: e.target.value || undefined }))}
            />
            <input
              className="input"
              type="datetime-local"
              value={draftFilters.end_time || ''}
              onChange={(e) => setDraftFilters((f) => ({ ...f, end_time: e.target.value || undefined }))}
            />
          </div>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button className="btn btn-primary btn-sm" onClick={handleApplyFilters}>Apply</button>
            <button className="btn btn-secondary btn-sm" onClick={handleClearFilters}>
              <X size={13} /> Clear
            </button>
          </div>
        </GlassCard>
      )}

      {loadError && (
        <div
          style={{
            background: 'rgba(239, 68, 68, 0.1)',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            borderRadius: 'var(--radius-sm)',
            padding: '0.85rem 1.25rem',
            color: '#ef4444',
            fontSize: '0.85rem',
            fontWeight: 600,
          }}
        >
          ⚠ {loadError}
        </div>
      )}

      {/* Verification Status Banner */}
      {verificationResult && (
        <div
          style={{
            background: verificationResult.status === 'VALID' ? 'rgba(16, 185, 129, 0.12)' : 'rgba(239, 68, 68, 0.15)',
            border: `1px solid ${verificationResult.status === 'VALID' ? '#10b981' : '#ef4444'}`,
            borderRadius: 'var(--radius-md)',
            padding: '1.25rem 1.5rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '1rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
            <div
              style={{
                width: '40px',
                height: '40px',
                borderRadius: 'var(--radius-full)',
                background: verificationResult.status === 'VALID' ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: verificationResult.status === 'VALID' ? '#10b981' : '#ef4444',
              }}
            >
              {verificationResult.status === 'VALID' ? <CheckCircle2 size={22} /> : <AlertTriangle size={22} />}
            </div>
            <div>
              <div
                style={{
                  fontSize: '0.75rem',
                  fontWeight: 700,
                  letterSpacing: '0.05em',
                  color: verificationResult.status === 'VALID' ? '#10b981' : '#ef4444',
                  textTransform: 'uppercase',
                }}
              >
                {verificationResult.status === 'VALID' ? 'IMMUTABLE PROOF VERIFIED' : 'TAMPERING DETECTED'}
              </div>
              <div style={{ fontSize: '1rem', fontWeight: 600, color: '#ffffff', marginTop: '0.15rem' }}>
                {verificationResult.message}
              </div>
              {verificationResult.failedCheck && (
                <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '0.25rem', fontFamily: 'var(--font-mono)' }}>
                  failed_check: {verificationResult.failedCheck}
                  {verificationResult.failedSequence != null && ` · sequence: ${verificationResult.failedSequence}`}
                </div>
              )}
              {lastVerifiedAt && (
                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                  Last verified: {formatRegionalDateTime(lastVerifiedAt, 'UTC')}
                </div>
              )}
            </div>
          </div>

          <div style={{ textAlign: 'right', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            Verified Blocks: <strong style={{ color: '#ffffff', fontFamily: 'var(--font-mono)' }}>{verificationResult.eventCount}</strong>
          </div>
        </div>
      )}

      {/* Trust Anchor Status Card */}
      {anchorStatus && (
        <GlassCard title="External Anchor & Checkpoint State">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem', fontSize: '0.8rem' }}>
            <div style={{ background: 'var(--bg-surface-elevated)', padding: '0.75rem 1rem', borderRadius: 'var(--radius-sm)' }}>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>Anchor Verification Status</div>
              <div style={{ fontWeight: 700, color: anchorStatus.verified ? '#10b981' : '#f59e0b', marginTop: '0.2rem' }}>
                {anchorStatus.verified ? 'VALIDATED ANCHOR' : anchorStatus.message || 'NO ANCHOR CREATED YET'}
              </div>
            </div>
            <div style={{ background: 'var(--bg-surface-elevated)', padding: '0.75rem 1rem', borderRadius: 'var(--radius-sm)' }}>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>Anchored Sequence</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#38bdf8', marginTop: '0.2rem' }}>
                {anchorStatus.anchor?.sequence !== undefined ? `#${anchorStatus.anchor.sequence}` : 'N/A'}
              </div>
            </div>
            <div style={{ background: 'var(--bg-surface-elevated)', padding: '0.75rem 1rem', borderRadius: 'var(--radius-sm)' }}>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>Anchored Block Root Hash</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: '#10b981', marginTop: '0.2rem', wordBreak: 'break-all' }}>
                {anchorStatus.anchor?.root_hash || 'N/A'}
              </div>
            </div>
          </div>
        </GlassCard>
      )}

      {/* Historical anchors — Platform Admin only */}
      {isPlatformAdmin && anchors.length > 0 && (
        <GlassCard title={`Historical Anchors (${anchors.length})`} subtitle="Server-derived checkpoints; sequence/hash can never be supplied by a client">
          <div className="data-table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Sequence</th>
                  <th>Root Hash</th>
                  <th>Created</th>
                  <th>Created By</th>
                  <th>Verify</th>
                </tr>
              </thead>
              <tbody>
                {anchors.map((a) => {
                  const result = anchorVerifyResult[a.id];
                  return (
                    <tr key={a.id}>
                      <td>{a.id}</td>
                      <td style={{ fontFamily: 'var(--font-mono)' }}>#{a.sequence}</td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem' }}>{a.root_hash.substring(0, 20)}...</td>
                      <td style={{ fontSize: '0.75rem' }}>{formatRegionalDateTime(a.created_at, 'UTC')}</td>
                      <td style={{ fontSize: '0.75rem' }}>{a.created_by_user_id || 'N/A'}</td>
                      <td>
                        <button className="btn btn-secondary btn-sm" onClick={() => handleVerifySpecificAnchor(a.id)}>
                          Verify
                        </button>
                        {result && (
                          <span style={{ marginLeft: '0.5rem', fontSize: '0.72rem', color: result.verified ? '#10b981' : '#ef4444', fontWeight: 700 }}>
                            {result.verified ? 'VALID' : result.message}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </GlassCard>
      )}

      {/* Ledger Block Explorer / Workload Audit Timeline */}
      <GlassCard
        title={filters.job_id ? `Workload Audit Timeline — ${filters.job_id} (${events.length})` : `Audit Ledger Blocks (${events.length})`}
        subtitle="Chronological sequence of SHA-256 chained system, scheduling, and approval events"
        actions={
          <div style={{ position: 'relative', width: '220px' }}>
            <Search size={14} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
            <input
              type="text"
              placeholder="Search by job ID, type..."
              className="input input-sm"
              style={{ paddingLeft: '2rem' }}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
        }
      >
        {isLoading ? (
          <LoadingSkeleton rows={6} height={40} />
        ) : events.length === 0 ? (
          <EmptyState
            title="Audit Ledger is Empty"
            description="No audit events recorded yet. Lifecycle events are cryptographically chained as workloads are ingested, scheduled, approved, and dispatched."
            icon={Database}
          />
        ) : (
          <div className="data-table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Seq</th>
                  <th>Event Type</th>
                  <th>Target Job ID</th>
                  <th>Actor</th>
                  <th>Role</th>
                  <th>Source</th>
                  <th>Request ID</th>
                  <th>Timestamp (UTC)</th>
                  <th>Previous Block Hash</th>
                  <th>Current SHA-256 Hash</th>
                </tr>
              </thead>
              <tbody>
                {filteredEvents.map((evt, idx) => (
                  <tr key={evt.event_id || idx}>
                    <td>
                      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--text-muted)' }}>
                        #{evt.sequence ?? idx + 1}
                      </span>
                    </td>
                    <td>
                      <span style={{ fontWeight: 600, color: '#ffffff' }}>{evt.event_type}</span>
                      {evt.reason && (
                        <div style={{ fontSize: '0.68rem', color: '#f59e0b', marginTop: '0.15rem', maxWidth: '260px' }}>
                          {evt.reason}
                        </div>
                      )}
                    </td>
                    <td>
                      <span style={{ fontFamily: 'var(--font-mono)', color: '#38bdf8' }}>
                        {evt.job_id || 'N/A'}
                      </span>
                    </td>
                    <td style={{ fontSize: '0.75rem' }}>{evt.actor_username || (evt.actor_type === 'SYSTEM' ? 'SYSTEM' : 'N/A')}</td>
                    <td style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{evt.actor_role || '—'}</td>
                    <td style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{evt.source_service || '—'}</td>
                    <td style={{ fontSize: '0.68rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                      {evt.request_id ? `${evt.request_id.substring(0, 8)}...` : '—'}
                    </td>
                    <td>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        {formatRegionalDateTime(evt.timestamp, 'UTC')}
                      </span>
                    </td>
                    <td>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                        {evt.previous_hash ? `${evt.previous_hash.substring(0, 16)}...` : 'GENESIS'}
                      </span>
                    </td>
                    <td>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: '#10b981', fontWeight: 600 }}>
                        {evt.current_hash ? `${evt.current_hash.substring(0, 18)}...` : 'N/A'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
    </div>
  );
};
