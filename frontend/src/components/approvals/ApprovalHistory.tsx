import React from 'react';
import { RotateCcw } from 'lucide-react';
import { GlassCard } from '../common/GlassCard';
import { LoadingSkeleton } from '../common/LoadingSkeleton';
import { EmptyState } from '../common/EmptyState';
import { InlineBanner } from '../common/InlineBanner';
import { ApprovalHistoryItem, RegionInfo } from '../../types/api';
import { resolveRegionTimezone } from '../../utils/dateTime';
import { ApprovalHistoryRow } from './ApprovalHistoryRow';

interface ApprovalHistoryProps {
  items: ApprovalHistoryItem[];
  regions: RegionInfo[];
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
}

export const ApprovalHistory: React.FC<ApprovalHistoryProps> = ({ items, regions, isLoading, isError, onRetry }) => {
  if (isError) {
    return (
      <GlassCard>
        <InlineBanner
          variant="error"
          action={
            <button className="btn btn-secondary btn-sm" onClick={onRetry}>
              <RotateCcw size={13} />
              <span>Retry</span>
            </button>
          }
        >
          Couldn't load approvals. Please try again.
        </InlineBanner>
      </GlassCard>
    );
  }

  if (isLoading) {
    return (
      <GlassCard>
        <LoadingSkeleton rows={5} height={44} />
      </GlassCard>
    );
  }

  if (items.length === 0) {
    return (
      <EmptyState
        title="No approval history"
        description="There are no recorded approval decisions yet."
      />
    );
  }

  return (
    <GlassCard title={`History (${items.length})`}>
      <div className="data-table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th>Workload</th>
              <th>Decision</th>
              <th>Region</th>
              <th>Scheduled Start</th>
              <th>Decided By</th>
              <th>Decided At</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, i) => (
              <ApprovalHistoryRow
                key={`${item.job_id}-${item.decided_at}-${i}`}
                item={item}
                timezoneName={resolveRegionTimezone(regions, item.region)}
              />
            ))}
          </tbody>
        </table>
      </div>
    </GlassCard>
  );
};
