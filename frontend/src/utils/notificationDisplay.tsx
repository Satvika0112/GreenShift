import React from 'react';
import { AlertTriangle, AlertCircle, Info } from 'lucide-react';

/** Backend severity values are constrained to INFO/WARNING/CRITICAL (ck_notifications_severity_valid). */
export function severityIcon(severity: string, size = 15): React.ReactNode {
  const s = (severity || '').toUpperCase();
  if (s === 'CRITICAL') return <AlertTriangle size={size} color="#ef4444" />;
  if (s === 'WARNING') return <AlertCircle size={size} color="#f59e0b" />;
  return <Info size={size} color="#38bdf8" />;
}

export function severityColor(severity: string): string {
  const s = (severity || '').toUpperCase();
  if (s === 'CRITICAL') return '#ef4444';
  if (s === 'WARNING') return '#f59e0b';
  return '#38bdf8';
}

export function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

/**
 * Human-friendly label for a notification `category`. Categories are a
 * free-form backend string (no fixed enum) — known values observed in
 * app/notify/service.py call sites are ACCOUNT/APPROVAL/EXECUTION/SCHEDULING,
 * but any string must render safely via the title-case fallback.
 */
export function categoryLabel(category: string): string {
  const known: Record<string, string> = {
    ACCOUNT: 'Account',
    APPROVAL: 'Approval',
    EXECUTION: 'Execution',
    SCHEDULING: 'Scheduling',
    SECURITY: 'Security',
    INFRASTRUCTURE: 'Infrastructure',
  };
  if (known[category]) return known[category];
  return category
    .toLowerCase()
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}
