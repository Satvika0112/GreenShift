import React, { useEffect, useRef, useState } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { PendingApprovalItem } from '../../types/api';
import { whyThisScheduleText } from '../../utils/approvalDisplay';
import { ApprovalSummary } from './ApprovalSummary';
import { ScheduleComparison } from './ScheduleComparison';

interface ApprovalReviewModalProps {
  item: PendingApprovalItem;
  canAuthorize: boolean;
  isProcessing: boolean;
  onClose: () => void;
  onApprove: (note: string) => void;
  onDecline: (note: string) => void;
  onViewScheduling: () => void;
  onViewWorkload: () => void;
}

export const ApprovalReviewModal: React.FC<ApprovalReviewModalProps> = ({
  item,
  canAuthorize,
  isProcessing,
  onClose,
  onApprove,
  onDecline,
  onViewScheduling,
  onViewWorkload,
}) => {
  const [note, setNote] = useState('');
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeButtonRef.current?.focus();
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isProcessing) onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isProcessing, onClose]);

  const canDecline = note.trim().length > 0;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="review-schedule-title"
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0, 0, 0, 0.75)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 100,
        backdropFilter: 'blur(4px)',
        padding: '1rem',
      }}
    >
      <div
        style={{
          background: '#0e1422',
          border: '1px solid var(--border-default)',
          borderRadius: 'var(--radius-md)',
          width: '100%',
          maxWidth: '640px',
          maxHeight: '90vh',
          overflowY: 'auto',
          padding: '1.75rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '1.5rem',
        }}
      >
        <div>
          <h3 id="review-schedule-title" style={{ fontSize: '1.2rem', marginBottom: '0.25rem' }}>
            Review Schedule
          </h3>
          <p style={{ fontSize: '0.9rem', fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>
            {item.workload_name || item.job_id}
          </p>
          <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', margin: 0 }}>
            {item.job_id}
          </p>
        </div>

        <ApprovalSummary item={item} />

        <div>
          <h4 style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text-muted)', marginBottom: '0.5rem' }}>
            Why this schedule?
          </h4>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', margin: 0 }}>
            {item.reason || whyThisScheduleText()}
          </p>
          <div style={{ display: 'flex', gap: '1rem', marginTop: '0.6rem', flexWrap: 'wrap' }}>
            <button type="button" className="btn btn-secondary btn-sm" onClick={onViewScheduling}>
              <span>View Scheduling Analysis</span>
              <ArrowUpRight size={13} />
            </button>
            <button type="button" className="btn btn-secondary btn-sm" onClick={onViewWorkload}>
              <span>View Workload</span>
              <ArrowUpRight size={13} />
            </button>
          </div>
        </div>

        <ScheduleComparison item={item} />

        {canAuthorize ? (
          <>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label" htmlFor="decision-note">Decision note</label>
              <textarea
                id="decision-note"
                className="input"
                rows={3}
                placeholder="E.g. Carbon budget exceeded and requires re-batching off-peak..."
                value={note}
                onChange={(e) => setNote(e.target.value)}
                disabled={isProcessing}
                aria-describedby="decision-note-helper"
              />
              <p id="decision-note-helper" style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.35rem', marginBottom: 0 }}>
                Optional for approval, required for decline.
              </p>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', flexWrap: 'wrap' }}>
              <button ref={closeButtonRef} type="button" className="btn btn-secondary" onClick={onClose} disabled={isProcessing}>
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-danger"
                onClick={() => onDecline(note)}
                disabled={isProcessing || !canDecline}
              >
                Decline Schedule
              </button>
              <button type="button" className="btn btn-primary" onClick={() => onApprove(note)} disabled={isProcessing}>
                Approve Schedule
              </button>
            </div>
          </>
        ) : (
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button ref={closeButtonRef} type="button" className="btn btn-secondary" onClick={onClose}>
              Close
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
