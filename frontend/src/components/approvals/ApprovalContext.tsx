import React from 'react';
import { approvalContextText } from '../../utils/approvalDisplay';

interface ApprovalContextProps {
  reason?: string | null;
}

// "Why approval is required" — the backend's own policy reason when it
// provides one, otherwise the one honest, universally-true fallback (every
// PENDING_APPROVAL job requires human authorization before execution).
export const ApprovalContext: React.FC<ApprovalContextProps> = ({ reason }) => (
  <div
    style={{
      fontSize: '0.8rem',
      background: 'rgba(245, 158, 11, 0.1)',
      border: '1px solid rgba(245, 158, 11, 0.3)',
      padding: '0.5rem 0.75rem',
      borderRadius: 'var(--radius-sm)',
      color: '#f59e0b',
    }}
  >
    <strong>Approval Context: </strong>
    {approvalContextText(reason)}
  </div>
);
