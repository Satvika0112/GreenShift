import React from 'react';
import { JobStatus } from '../../types/api';

interface StatusBadgeProps {
  status: JobStatus | string;
  size?: 'sm' | 'md';
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, size = 'md' }) => {
  const normalized = status.toUpperCase();

  let badgeClass = 'badge-neutral';
  let hasPulse = false;

  switch (normalized) {
    case 'COMPLETED':
    case 'APPROVED':
    case 'HEALTHY':
    case 'CONNECTED':
    case 'SUCCEEDED':
      badgeClass = 'badge-success';
      break;
    case 'RUNNING':
    case 'DISPATCHING':
      badgeClass = 'badge-info';
      hasPulse = true;
      break;
    case 'SCHEDULED':
      badgeClass = 'badge-info';
      break;
    case 'PENDING':
    case 'QUEUED':
    case 'AWAITING_APPROVAL':
    case 'DEGRADED':
      badgeClass = 'badge-warning';
      hasPulse = true;
      break;
    case 'FAILED':
    case 'DECLINED':
    case 'CANCELLED':
    case 'DISCONNECTED':
    case 'DOWN':
      badgeClass = 'badge-danger';
      break;
    default:
      badgeClass = 'badge-neutral';
  }

  return (
    <span
      className={`badge ${badgeClass} ${size === 'sm' ? 'text-xs py-0.5 px-2' : ''}`}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '0.4rem',
        fontSize: size === 'sm' ? '0.7rem' : '0.75rem',
      }}
    >
      {hasPulse && <span className="pulse-dot" />}
      {normalized.replace('_', ' ')}
    </span>
  );
};
