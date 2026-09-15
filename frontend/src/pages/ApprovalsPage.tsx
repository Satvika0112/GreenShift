import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { RefreshCw, CheckCircle2 } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { EmptyState } from '../components/common/EmptyState';
import { InlineBanner } from '../components/common/InlineBanner';
import { approvalsApi } from '../api/endpoints';
import { PendingApprovalItem } from '../types/api';
import { useAuth } from '../context/AuthContext';
import { useRegions } from '../hooks/useDashboard';
import { usePendingApprovals, useApprovalHistory } from '../hooks/useApprovals';
import { PendingApprovalCard } from '../components/approvals/PendingApprovalCard';
import { ApprovalReviewModal } from '../components/approvals/ApprovalReviewModal';
import { ApprovalHistory } from '../components/approvals/ApprovalHistory';

type ApprovalsTab = 'pending' | 'history';

export const ApprovalsPage: React.FC = () => {
  const navigate = useNavigate();
  const { user, isAdmin } = useAuth();
  const canAuthorize = isAdmin;

  const [activeTab, setActiveTab] = useState<ApprovalsTab>('pending');
  const [selectedItem, setSelectedItem] = useState<PendingApprovalItem | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // The team_id filter is only meaningful for non-admins; admins get the
  // backend's unfiltered (tenant/platform-scoped) result regardless of what
  // is sent, matching the existing Workloads/Dashboard pattern.
  const teamFilter = isAdmin ? undefined : user?.team_id;
  const pendingQ = usePendingApprovals(teamFilter);
  const historyQ = useApprovalHistory(teamFilter);
  const regionsQ = useRegions();
  const regions = regionsQ.data || [];

  const pendingItems = pendingQ.data || [];
  const historyItems = historyQ.data || [];

  const handleRefresh = () => {
    pendingQ.refetch();
    historyQ.refetch();
  };

  const handleApprove = async (item: PendingApprovalItem, note: string) => {
    setIsProcessing(true);
    setErrorMessage(null);
    try {
      await approvalsApi.approveJob(item.job_id, item.schedule_id, note.trim() || undefined);
      setSuccessMessage('Schedule approved — ready for execution');
      setSelectedItem(null);
      await Promise.all([pendingQ.refetch(), historyQ.refetch()]);
      setTimeout(() => setSuccessMessage(null), 4000);
    } catch (err: any) {
      setErrorMessage(err.response?.data?.detail || "Couldn't approve this schedule. Please try again.");
    } finally {
      setIsProcessing(false);
    }
  };

  const handleDecline = async (item: PendingApprovalItem, note: string) => {
    if (!note.trim()) {
      setErrorMessage('Please provide a reason before declining this schedule.');
      return;
    }
    setIsProcessing(true);
    setErrorMessage(null);
    try {
      await approvalsApi.declineJob(item.job_id, item.schedule_id, note.trim());
      setSuccessMessage('Schedule declined');
      setSelectedItem(null);
      await Promise.all([pendingQ.refetch(), historyQ.refetch()]);
      setTimeout(() => setSuccessMessage(null), 4000);
    } catch (err: any) {
      setErrorMessage(err.response?.data?.detail || "Couldn't decline this schedule. Please try again.");
    } finally {
      setIsProcessing(false);
    }
  };

  const pendingCountLabel = pendingQ.isLoading ? '—' : pendingQ.isError ? 'Data unavailable' : `${pendingItems.length} Pending`;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      <PageHeader
        title="Review"
        subtitle="Review and authorize recommended workload schedules before execution."
        badge={<span className="badge badge-warning">{pendingCountLabel}</span>}
        actions={
          <button className="btn btn-secondary" onClick={handleRefresh} disabled={pendingQ.isFetching || historyQ.isFetching}>
            <RefreshCw size={14} className={pendingQ.isFetching || historyQ.isFetching ? 'animate-spin' : ''} />
            <span>Refresh</span>
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

      <div style={{ display: 'flex', gap: '0.5rem', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '0.5rem' }} role="tablist" aria-label="Review">
        <button
          role="tab"
          aria-selected={activeTab === 'pending'}
          className={`btn btn-sm ${activeTab === 'pending' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setActiveTab('pending')}
        >
          <span>Pending ({pendingQ.isLoading ? '—' : pendingItems.length})</span>
        </button>
        <button
          role="tab"
          aria-selected={activeTab === 'history'}
          className={`btn btn-sm ${activeTab === 'history' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setActiveTab('history')}
        >
          <span>History ({historyQ.isLoading ? '—' : historyItems.length})</span>
        </button>
      </div>

      {activeTab === 'pending' ? (
        pendingQ.isError ? (
          <InlineBanner
            variant="error"
            action={
              <button className="btn btn-secondary btn-sm" onClick={() => pendingQ.refetch()}>
                <span>Retry</span>
              </button>
            }
          >
            Couldn't load approvals. Please try again.
          </InlineBanner>
        ) : pendingQ.isLoading ? (
          <LoadingSkeleton rows={4} height={140} />
        ) : pendingItems.length === 0 ? (
          <EmptyState
            title="No pending approvals"
            description="There are no workload schedules waiting for your decision."
            icon={CheckCircle2}
          />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {pendingItems.map((item) => (
              <PendingApprovalCard key={`${item.job_id}-${item.schedule_id}`} item={item} onReview={() => setSelectedItem(item)} />
            ))}
          </div>
        )
      ) : (
        <ApprovalHistory items={historyItems} regions={regions} isLoading={historyQ.isLoading} isError={historyQ.isError} onRetry={() => historyQ.refetch()} />
      )}

      {selectedItem && (
        <ApprovalReviewModal
          item={selectedItem}
          canAuthorize={canAuthorize}
          isProcessing={isProcessing}
          onClose={() => setSelectedItem(null)}
          onApprove={(note) => handleApprove(selectedItem, note)}
          onDecline={(note) => handleDecline(selectedItem, note)}
          onViewScheduling={() => navigate(`/scheduling?jobId=${selectedItem.job_id}`)}
          onViewWorkload={() => navigate(`/workloads/${selectedItem.job_id}`)}
        />
      )}
    </div>
  );
};
