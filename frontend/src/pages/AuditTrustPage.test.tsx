import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AuditTrustPage } from './AuditTrustPage';
import { auditApi } from '../api/endpoints';
import {
  auditEvent,
  auditEvent2,
  validVerifyResponse,
  invalidVerifyResponse,
  verifiedAnchorStatus,
  noAnchorStatus,
} from '../test/fixtures/audit';

vi.mock('../api/endpoints', () => ({
  auditApi: {
    getAuditEvents: vi.fn(),
    verifyTrustChain: vi.fn(),
    verifyAnchor: vi.fn(),
    createAnchor: vi.fn(),
  },
}));

function renderPage() {
  return render(<AuditTrustPage />);
}

describe('AuditTrustPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (auditApi.verifyAnchor as any).mockResolvedValue(noAnchorStatus);
  });

  it('renders real ledger events from the backend', async () => {
    (auditApi.getAuditEvents as any).mockResolvedValue({ events: [auditEvent, auditEvent2] });
    renderPage();

    await waitFor(() => {
      expect(screen.getByText('JOB_SCHEDULED')).toBeInTheDocument();
    });
    expect(screen.getByText('APPROVAL_GRANTED')).toBeInTheDocument();
    expect(screen.getByText('Audit Ledger Blocks (2)')).toBeInTheDocument();
  });

  it('renders an empty state when the ledger has zero events, not fabricated blocks', async () => {
    (auditApi.getAuditEvents as any).mockResolvedValue({ events: [] });
    renderPage();

    await waitFor(() => {
      expect(screen.getByText('Audit Ledger is Empty')).toBeInTheDocument();
    });
  });

  it('displays the exact backend message and event_count on a valid chain verification', async () => {
    const user = userEvent.setup();
    (auditApi.getAuditEvents as any).mockResolvedValue({ events: [auditEvent, auditEvent2] });
    (auditApi.verifyTrustChain as any).mockResolvedValue(validVerifyResponse);
    renderPage();

    await waitFor(() => expect(screen.getByText('JOB_SCHEDULED')).toBeInTheDocument());
    await user.click(screen.getByText('Verify Cryptographic Chain'));

    await waitFor(() => {
      expect(screen.getByText('IMMUTABLE PROOF VERIFIED')).toBeInTheDocument();
    });
    expect(screen.getByText(validVerifyResponse.message)).toBeInTheDocument();
    expect(screen.getByText(String(validVerifyResponse.event_count))).toBeInTheDocument();
  });

  it('displays tampering-detected state on an invalid chain, using the real backend message', async () => {
    const user = userEvent.setup();
    (auditApi.getAuditEvents as any).mockResolvedValue({ events: [auditEvent, auditEvent2] });
    (auditApi.verifyTrustChain as any).mockResolvedValue(invalidVerifyResponse);
    renderPage();

    await waitFor(() => expect(screen.getByText('JOB_SCHEDULED')).toBeInTheDocument());
    await user.click(screen.getByText('Verify Cryptographic Chain'));

    await waitFor(() => {
      expect(screen.getByText('TAMPERING DETECTED')).toBeInTheDocument();
    });
    expect(screen.getByText(invalidVerifyResponse.message)).toBeInTheDocument();
  });

  it('shows an error-derived verification result on backend failure, not a fabricated pass', async () => {
    const user = userEvent.setup();
    (auditApi.getAuditEvents as any).mockResolvedValue({ events: [] });
    (auditApi.verifyTrustChain as any).mockRejectedValue({
      response: { data: { detail: 'Ledger service unavailable.' } },
    });
    renderPage();

    await waitFor(() => expect(screen.getByText('Audit Ledger is Empty')).toBeInTheDocument());
    await user.click(screen.getByText('Verify Cryptographic Chain'));

    await waitFor(() => {
      expect(screen.getByText('TAMPERING DETECTED')).toBeInTheDocument();
    });
    expect(screen.getByText('Ledger service unavailable.')).toBeInTheDocument();
  });

  it('renders the real anchor root hash and sequence using correct field names', async () => {
    (auditApi.getAuditEvents as any).mockResolvedValue({ events: [] });
    (auditApi.verifyAnchor as any).mockResolvedValue(verifiedAnchorStatus);
    renderPage();

    await waitFor(() => {
      expect(screen.getByText('VALIDATED ANCHOR')).toBeInTheDocument();
    });
    expect(screen.getByText(`#${verifiedAnchorStatus.anchor!.sequence}`)).toBeInTheDocument();
    expect(screen.getByText(verifiedAnchorStatus.anchor!.root_hash)).toBeInTheDocument();
  });

  it('shows the backend message when no anchor has been created, never a fake N/A hash', async () => {
    (auditApi.getAuditEvents as any).mockResolvedValue({ events: [] });
    (auditApi.verifyAnchor as any).mockResolvedValue(noAnchorStatus);
    renderPage();

    await waitFor(() => {
      expect(screen.getByText(noAnchorStatus.message)).toBeInTheDocument();
    });
  });

  it('invokes createAnchor then re-fetches verifyAnchor through the real API layer', async () => {
    const user = userEvent.setup();
    (auditApi.getAuditEvents as any).mockResolvedValue({ events: [] });
    (auditApi.createAnchor as any).mockResolvedValue({ status: 'created' });
    (auditApi.verifyAnchor as any)
      .mockResolvedValueOnce(noAnchorStatus)
      .mockResolvedValueOnce(verifiedAnchorStatus);

    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    renderPage();

    await waitFor(() => expect(screen.getByText(noAnchorStatus.message)).toBeInTheDocument());
    await user.click(screen.getByText('Create Anchor'));

    await waitFor(() => {
      expect(auditApi.createAnchor).toHaveBeenCalledTimes(1);
      expect(auditApi.verifyAnchor).toHaveBeenCalledTimes(2);
    });
    await waitFor(() => expect(screen.getByText('VALIDATED ANCHOR')).toBeInTheDocument());
    alertSpy.mockRestore();
  });

  it('filters ledger events by search term against job ID, event type, and hash', async () => {
    const user = userEvent.setup();
    (auditApi.getAuditEvents as any).mockResolvedValue({ events: [auditEvent, auditEvent2] });
    renderPage();

    await waitFor(() => expect(screen.getByText('JOB_SCHEDULED')).toBeInTheDocument());
    await user.type(screen.getByPlaceholderText(/Search by job ID/i), 'APPROVAL_GRANTED');

    expect(screen.queryByText('JOB_SCHEDULED')).not.toBeInTheDocument();
    expect(screen.getByText('APPROVAL_GRANTED')).toBeInTheDocument();
  });
});
