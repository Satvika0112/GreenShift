import React, { useState, useEffect } from 'react';
import {
  CheckCircle2,
  XCircle,
  Clock,
  ShieldAlert,
  Leaf,
  DollarSign,
  UserCheck,
  RefreshCw,
} from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassCard } from '../components/common/GlassCard';
import { StatusBadge } from '../components/common/StatusBadge';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { EmptyState } from '../components/common/EmptyState';
import { InlineBanner } from '../components/common/InlineBanner';
import { approvalsApi } from '../api/endpoints';
import { PendingApprovalItem } from '../types/api';
import { useAuth } from '../context/AuthContext';

export const ApprovalsPage: React.FC = () => {
  const { user, isAdmin } = useAuth();

  const [pendingItems, setPendingItems] = useState<PendingApprovalItem[]>([]);
  const [declinedItems, setDeclinedItems] = useState<any[]>([]);
  const [activeTab, setActiveTab] = useState<'pending' | 'history'>('pending');
  const [selectedItem, setSelectedItem] = useState<PendingApprovalItem | null>(null);
  const [approvalNote, setApprovalNote] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const canAuthorize = isAdmin;

  const fetchApprovals = async () => {
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const [pendingRes, declinedRes] = await Promise.allSettled([
        approvalsApi.getPendingApprovals(isAdmin ? undefined : user?.team_id),
        approvalsApi.getDeclinedApprovals(isAdmin ? undefined : user?.team_id),
      ]);

      if (pendingRes.status === 'fulfilled' && Array.isArray(pendingRes.value)) {
        setPendingItems(pendingRes.value);
      } else if (pendingRes.status === 'rejected') {
        setErrorMessage('Failed to load pending approval queues from backend.');
      }
      if (declinedRes.status === 'fulfilled' && Array.isArray(declinedRes.value)) {
        setDeclinedItems(declinedRes.value);
      }
    } catch (err: any) {
      setErrorMessage('Failed to load approval queues from backend.');
    } finally {
      setIsLoading(false);
    }
  };

  // Close modal on Escape key
  useEffect(() => {
    if (!selectedItem) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isProcessing) {
        setSelectedItem(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedItem, isProcessing]);

  useEffect(() => {
    fetchApprovals();
  }, [user]);

  const handleApprove = async (item: PendingApprovalItem) => {
    if (!canAuthorize) {
      alert('Only a Company Admin or Platform Admin can approve workloads.');
      return;
    }
    setIsProcessing(true);
    setErrorMessage(null);
    try {
      await approvalsApi.approveJob(
        item.job_id,
        item.schedule_id,
        approvalNote || 'Approved via GreenShift Control Plane'
      );
      setSuccessMessage(`Workload ${item.job_id} approved for dispatch.`);
      setSelectedItem(null);
      setApprovalNote('');
      await fetchApprovals();
      setTimeout(() => setSuccessMessage(null), 4000);
    } catch (err: any) {
      setErrorMessage(err.response?.data?.detail || 'Approval submission failed.');
    } finally {
      setIsProcessing(false);
    }
  };

  const handleDecline = async (item: PendingApprovalItem) => {
    if (!canAuthorize) {
      alert('Only a Company Admin or Platform Admin can decline workloads.');
      return;
    }
    if (!approvalNote.trim()) {
      alert('A reason is mandatory when declining a workload.');
      return;
    }

    setIsProcessing(true);
    setErrorMessage(null);
    try {
      await approvalsApi.declineJob(item.job_id, item.schedule_id, approvalNote);
      setSuccessMessage(`Workload ${item.job_id} declined.`);
      setSelectedItem(null);
      setApprovalNote('');
      await fetchApprovals();
      setTimeout(() => setSuccessMessage(null), 4000);
    } catch (err: any) {
      setErrorMessage(err.response?.data?.detail || 'Decline submission failed.');
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      <PageHeader
        title="Human-in-the-Loop Governance"
        subtitle={`Review and authorize workloads exceeding carbon caps or budget thresholds. Active user: ${user?.username} (${user?.role})`}
        badge={
          <span className="badge badge-warning">
            {pendingItems.length} PENDING REVIEW
          </span>
        }
        actions={
          <button className="btn btn-secondary" onClick={fetchApprovals} disabled={isLoading}>
            <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
            <span>Sync Approvals</span>
          </button>
        }
      />

      {successMessage && <InlineBanner variant="success">{successMessage}</InlineBanner>}

      {errorMessage && <InlineBanner variant="error">{errorMessage}</InlineBanner>}

      {!canAuthorize && (
        <InlineBanner variant="info">
          Role '{user?.role}' has read-only observation permissions. Only a Company Admin or Platform Admin may authorize or decline workloads.
        </InlineBanner>
      )}

      {/* Navigation Tabs */}
      <div style={{ display: 'flex', gap: '0.5rem', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '0.5rem' }}>
        <button
          className={`btn btn-sm ${activeTab === 'pending' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setActiveTab('pending')}
        >
          <span>Pending Approvals ({pendingItems.length})</span>
        </button>
        <button
          className={`btn btn-sm ${activeTab === 'history' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setActiveTab('history')}
        >
          <span>Declined Workloads ({declinedItems.length})</span>
        </button>
      </div>

      {isLoading ? (
        <LoadingSkeleton rows={5} height={60} />
      ) : activeTab === 'pending' ? (
        pendingItems.length === 0 ? (
          <EmptyState
            title="No Pending Workload Approvals"
            description="All scheduled workloads are within standard automated operational policy thresholds. New workloads that trigger carbon caps will appear here."
            icon={CheckCircle2}
          />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {pendingItems.map((item) => (
              <GlassCard key={`${item.job_id}-${item.schedule_id}`}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                      <h3 style={{ fontSize: '1.05rem', margin: 0 }}>
                        {item.workload_name || item.job_id}
                      </h3>
                      <StatusBadge status="AWAITING_APPROVAL" size="sm" />
                    </div>

                    <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '0.35rem', display: 'flex', gap: '1rem' }}>
                      <span>Team: <strong style={{ color: '#ffffff' }}>{item.team_id}</strong></span>
                      <span>Region: <strong style={{ color: '#38bdf8' }}>{item.region}</strong></span>
                      <span>Runtime: <strong>{item.runtime_minutes}m</strong></span>
                      <span>Power: <strong>{item.power_kw} kW</strong></span>
                    </div>

                    {item.reason && (
                      <div
                        style={{
                          marginTop: '0.6rem',
                          fontSize: '0.8rem',
                          background: 'rgba(245, 158, 11, 0.1)',
                          border: '1px solid rgba(245, 158, 11, 0.3)',
                          padding: '0.4rem 0.75rem',
                          borderRadius: 'var(--radius-sm)',
                          color: '#f59e0b',
                        }}
                      >
                        Policy Trigger: {item.reason}
                      </div>
                    )}
                  </div>

                  {/* Proposed Window & Actions */}
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.75rem' }}>
                    <div style={{ textAlign: 'right', fontSize: '0.78rem' }}>
                      <div style={{ color: 'var(--text-muted)' }}>Proposed Window Start:</div>
                      <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#10b981' }}>
                        {item.selected_start_utc ? new Date(item.selected_start_utc).toLocaleString() : 'Immediate'}
                      </div>
                    </div>

                    {canAuthorize && (
                      <div style={{ display: 'flex', gap: '0.5rem' }}>
                        <button
                          className="btn btn-secondary btn-sm"
                          onClick={() => setSelectedItem(item)}
                          disabled={isProcessing}
                        >
                          <XCircle size={14} />
                          <span>Review / Decline</span>
                        </button>
                        <button
                          className="btn btn-primary btn-sm"
                          onClick={() => handleApprove(item)}
                          disabled={isProcessing}
                        >
                          <CheckCircle2 size={14} />
                          <span>Approve Dispatch</span>
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </GlassCard>
            ))}
          </div>
        )
      ) : (
        /* History Tab: Declined items */
        declinedItems.length === 0 ? (
          <EmptyState
            title="No Declined Workloads"
            description="Zero workloads have been declined in the current governance history."
            icon={ShieldAlert}
          />
        ) : (
          <div className="data-table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Job ID</th>
                  <th>Team</th>
                  <th>Declined By</th>
                  <th>Declined At</th>
                  <th>Justification / Reason</th>
                </tr>
              </thead>
              <tbody>
                {declinedItems.map((d, i) => (
                  <tr key={d.job_id || i}>
                    <td>
                      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{d.job_id}</span>
                    </td>
                    <td>{d.team_id}</td>
                    <td>
                      <span style={{ color: '#38bdf8' }}>{d.declined_by}</span>
                    </td>
                    <td style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      {d.declined_at ? new Date(d.declined_at).toLocaleString() : 'N/A'}
                    </td>
                    <td style={{ fontSize: '0.8rem', color: '#ef4444' }}>{d.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      {/* Modal for Decline / Rationale */}
      {selectedItem && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="governance-decision-title"
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.75)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 100,
            backdropFilter: 'blur(4px)',
          }}
        >
          <div
            style={{
              background: '#0e1422',
              border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-md)',
              width: '100%',
              maxWidth: '520px',
              padding: '1.75rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '1.25rem',
            }}
          >
            <div>
              <h3 id="governance-decision-title" style={{ fontSize: '1.2rem', marginBottom: '0.25rem' }}>
                Governance Decision — {selectedItem.job_id}
              </h3>
              <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                Provide justification or audit reason for approving or declining this workload.
              </p>
            </div>

            <div className="form-group">
              <label className="form-label">Approval / Decline Note (Required for decline)</label>
              <textarea
                className="input"
                rows={3}
                placeholder="E.g. Carbon budget exceeded and requires re-batching off-peak..."
                value={approvalNote}
                onChange={(e) => setApprovalNote(e.target.value)}
              />
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
              <button
                className="btn btn-secondary"
                onClick={() => setSelectedItem(null)}
                disabled={isProcessing}
              >
                Cancel
              </button>
              <button
                className="btn btn-danger"
                onClick={() => handleDecline(selectedItem)}
                disabled={isProcessing || !approvalNote.trim()}
              >
                Decline Workload
              </button>
              <button
                className="btn btn-primary"
                onClick={() => handleApprove(selectedItem)}
                disabled={isProcessing}
              >
                Approve Workload
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
