import React, { useState, useEffect } from 'react';
import {
  ShieldCheck,
  CheckCircle2,
  Lock,
  RefreshCw,
  Search,
  Key,
  Database,
  Hash,
  AlertTriangle,
  Anchor,
  FileCheck,
} from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassCard } from '../components/common/GlassCard';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { EmptyState } from '../components/common/EmptyState';
import { auditApi } from '../api/endpoints';
import { AuditEvent, AnchorStatus } from '../types/api';

export const AuditTrustPage: React.FC = () => {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [isVerifying, setIsVerifying] = useState(false);
  const [isCreatingAnchor, setIsCreatingAnchor] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [anchorStatus, setAnchorStatus] = useState<AnchorStatus | null>(null);
  const [verificationResult, setVerificationResult] = useState<{
    status: 'VALID' | 'INVALID';
    eventCount: number;
    message: string;
  } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const fetchLedger = async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const [eventsRes, anchorRes] = await Promise.allSettled([
        auditApi.getAuditEvents(100),
        auditApi.verifyAnchor(),
      ]);

      if (eventsRes.status === 'fulfilled' && eventsRes.value?.events) {
        setEvents(eventsRes.value.events);
      } else if (eventsRes.status === 'rejected') {
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
    fetchLedger();
  }, []);

  const handleVerifyChain = async () => {
    setIsVerifying(true);
    try {
      // AuditVerifyResponse has exactly these 3 fields — the backend's own
      // `message` is displayed verbatim rather than constructing one here.
      const res = await auditApi.verifyTrustChain();
      setVerificationResult({
        status: res.valid ? 'VALID' : 'INVALID',
        eventCount: res.event_count,
        message: res.message,
      });
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
      alert('External cryptographic anchor successfully checkpointed.');
    } catch (err: any) {
      alert('Anchor creation failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setIsCreatingAnchor(false);
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      <PageHeader
        title="Cryptographic Audit & Trust Ledger"
        subtitle="Immutable SHA-256 hash-chained event provenance protecting against tampering, unauthorized overrides, and dispatch discrepancies"
        actions={
          <div style={{ display: 'flex', gap: '0.6rem' }}>
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
          </div>
        }
      />

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

      {/* Ledger Block Explorer */}
      <GlassCard
        title={`Audit Ledger Blocks (${events.length})`}
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
                    </td>
                    <td>
                      <span style={{ fontFamily: 'var(--font-mono)', color: '#38bdf8' }}>
                        {evt.job_id || 'N/A'}
                      </span>
                    </td>
                    <td>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        {new Date(evt.timestamp).toLocaleString()}
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
