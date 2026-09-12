import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AuditTrustPage } from './AuditTrustPage';
import { auditApi } from '../api/endpoints';
import { User } from '../types/api';
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
    getJobAuditTrail: vi.fn(),
    verifyTrustChain: vi.fn(),
    verifyAnchor: vi.fn(),
    createAnchor: vi.fn(),
    listAnchors: vi.fn(),
    verifyAnchorById: vi.fn(),
    exportEvents: vi.fn(),
  },
}));

// Existing tests exercise Platform-Admin-only controls (Verify Chain,
// Create Anchor) directly, so the default mocked identity is a Platform
// Admin — tests specifically covering role-gated visibility override this.
let mockUser: Partial<User> = { username: 'plat_admin', role: 'PLATFORM_ADMIN' as any, team_id: 'platform' };
let mockIsPlatformAdmin = true;
let mockIsCompanyAdmin = true;

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: mockUser, isPlatformAdmin: mockIsPlatformAdmin, isCompanyAdmin: mockIsCompanyAdmin }),
}));

function renderPage() {
  return render(<AuditTrustPage />);
}

describe('AuditTrustPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUser = { username: 'plat_admin', role: 'PLATFORM_ADMIN' as any, team_id: 'platform' };
    mockIsPlatformAdmin = true;
    mockIsCompanyAdmin = true;
    (auditApi.verifyAnchor as any).mockResolvedValue(noAnchorStatus);
    (auditApi.listAnchors as any).mockResolvedValue({ anchors: [] });
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

  describe('role-gated visibility', () => {
    it('hides Verify Chain and Create Anchor for a Company Admin', async () => {
      mockIsPlatformAdmin = false;
      mockUser = { username: 'co_admin', role: 'COMPANY_ADMIN' as any, team_id: 'team-a', tenant_id: 'tenant-a' };
      (auditApi.getAuditEvents as any).mockResolvedValue({ events: [auditEvent] });
      renderPage();

      await waitFor(() => expect(screen.getByText('JOB_SCHEDULED')).toBeInTheDocument());
      expect(screen.queryByText('Verify Cryptographic Chain')).not.toBeInTheDocument();
      expect(screen.queryByText('Create Anchor')).not.toBeInTheDocument();
      expect(screen.getByText(/Company-wide/)).toBeInTheDocument();
    });

    it('hides Verify Chain and Create Anchor for a Company User and shows team-scoped label', async () => {
      mockIsPlatformAdmin = false;
      mockIsCompanyAdmin = false;
      mockUser = { username: 'co_user', role: 'COMPANY_USER' as any, team_id: 'team-a', tenant_id: 'tenant-a' };
      (auditApi.getAuditEvents as any).mockResolvedValue({ events: [auditEvent] });
      renderPage();

      await waitFor(() => expect(screen.getByText('JOB_SCHEDULED')).toBeInTheDocument());
      expect(screen.queryByText('Verify Cryptographic Chain')).not.toBeInTheDocument();
      expect(screen.queryByText('Create Anchor')).not.toBeInTheDocument();
      expect(screen.getByText(/Your team/)).toBeInTheDocument();
    });

    it('shows Verify Chain and Create Anchor for a Platform Admin', async () => {
      (auditApi.getAuditEvents as any).mockResolvedValue({ events: [auditEvent] });
      renderPage();

      await waitFor(() => expect(screen.getByText('JOB_SCHEDULED')).toBeInTheDocument());
      expect(screen.getByText('Verify Cryptographic Chain')).toBeInTheDocument();
      expect(screen.getByText('Create Anchor')).toBeInTheDocument();
    });
  });

  describe('filters and export', () => {
    it('applies job/team/actor/event-type filters to the events query', async () => {
      const user = userEvent.setup();
      (auditApi.getAuditEvents as any).mockResolvedValue({ events: [] });
      renderPage();

      await waitFor(() => expect(screen.getByText('Audit Ledger is Empty')).toBeInTheDocument());
      await user.click(screen.getByText(/^Filters/));
      await user.type(screen.getByPlaceholderText('Team ID'), 'team-a');
      await user.type(screen.getByPlaceholderText('Actor (username)'), 'alice');
      await user.click(screen.getByText('Apply'));

      await waitFor(() => {
        expect(auditApi.getAuditEvents).toHaveBeenCalledWith(
          expect.objectContaining({ team_id: 'team-a', actor: 'alice' }),
        );
      });
    });

    it('exports the current filtered view as a CSV download', async () => {
      const user = userEvent.setup();
      (auditApi.getAuditEvents as any).mockResolvedValue({ events: [auditEvent] });
      (auditApi.exportEvents as any).mockResolvedValue(new Blob(['seq,event'], { type: 'text/csv' }));
      const createObjectURL = vi.fn().mockReturnValue('blob:mock-url');
      const revokeObjectURL = vi.fn();
      (window.URL as any).createObjectURL = createObjectURL;
      (window.URL as any).revokeObjectURL = revokeObjectURL;

      renderPage();
      await waitFor(() => expect(screen.getByText('JOB_SCHEDULED')).toBeInTheDocument());
      await user.click(screen.getByText('Export CSV'));

      await waitFor(() => {
        expect(auditApi.exportEvents).toHaveBeenCalledWith(expect.any(Object), 'csv');
        expect(createObjectURL).toHaveBeenCalled();
      });
    });
  });
});
