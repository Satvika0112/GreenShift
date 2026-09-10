import { AuditEvent, AuditVerifyResponse, AnchorStatus } from '../../types/api';

// Matches app.shared.models.AuditEvent exactly (GET /api/v1/trust/events).
export const auditEvent: AuditEvent = {
  event_id: 'evt-001',
  sequence: 1,
  event_type: 'JOB_SCHEDULED',
  job_id: 'job-9001',
  timestamp: '2026-09-10T08:55:00Z',
  payload_hash: 'a1b2c3d4e5f6',
  previous_hash: '',
  current_hash: 'f6e5d4c3b2a1',
};

export const auditEvent2: AuditEvent = {
  event_id: 'evt-002',
  sequence: 2,
  event_type: 'APPROVAL_GRANTED',
  job_id: 'job-9001',
  timestamp: '2026-09-10T09:00:00Z',
  payload_hash: 'b2c3d4e5f6a1',
  previous_hash: 'f6e5d4c3b2a1',
  current_hash: '112233445566',
};

// Matches GET /api/v1/trust/verify's exact 3-field response shape.
export const validVerifyResponse: AuditVerifyResponse = {
  valid: true,
  event_count: 2,
  message: 'Hash chain verified: 2 events, no tampering detected.',
};

export const invalidVerifyResponse: AuditVerifyResponse = {
  valid: false,
  event_count: 2,
  message: 'Chain integrity violation detected at sequence 2.',
};

// Matches app.trust.anchor's dict-based verify_anchor() response.
export const verifiedAnchorStatus: AnchorStatus = {
  status: 'verified',
  verified: true,
  message: 'Anchor verified against ledger state.',
  anchor: {
    timestamp: '2026-09-10T08:00:00Z',
    sequence: 2,
    root_hash: 'root-hash-abcdef123456',
    event_count: 2,
    latest_event_id: 'evt-002',
    latest_event_type: 'APPROVAL_GRANTED',
  },
  total_anchors: 1,
};

export const noAnchorStatus: AnchorStatus = {
  status: 'no_anchor_file',
  verified: false,
  message: 'No anchor file has been created yet.',
};
