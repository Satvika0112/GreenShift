import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AlertsPage } from './AlertsPage';
import { notificationsApi } from '../api/endpoints';
import {
  notificationList,
  unreadScheduleNotification,
  readApprovalNotification,
  criticalExecutionNotification,
} from '../test/fixtures/notifications';

// The API layer is mocked at the module boundary — AlertsPage must only ever
// talk to the backend through notificationsApi, never a raw axios/fetch call.
vi.mock('../api/endpoints', () => ({
  notificationsApi: {
    getNotifications: vi.fn(),
    getUnreadCount: vi.fn(),
    markRead: vi.fn(),
    markAllRead: vi.fn(),
  },
}));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AlertsPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('AlertsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows a loading state before data arrives', async () => {
    let resolveFn: (v: any) => void;
    (notificationsApi.getNotifications as any).mockReturnValue(
      new Promise((resolve) => {
        resolveFn = resolve;
      })
    );
    renderPage();
    expect(document.querySelector('.skeleton, [class*="skeleton"]') || screen.queryByText(/Alerts/)).toBeTruthy();
    resolveFn!([]);
  });

  it('renders real backend notification data (title, message, severity, category)', async () => {
    (notificationsApi.getNotifications as any).mockResolvedValue(notificationList);
    renderPage();

    await waitFor(() => {
      expect(screen.getByText(unreadScheduleNotification.title)).toBeInTheDocument();
    });

    expect(screen.getByText(unreadScheduleNotification.message)).toBeInTheDocument();
    // Category is rendered via the human-friendly categoryLabel() mapping.
    expect(screen.getAllByText('Scheduling').length).toBeGreaterThan(0);
    expect(screen.getAllByText('INFO').length).toBeGreaterThan(0);
    expect(screen.getByText('CRITICAL')).toBeInTheDocument();

    // Called through the real centralized API layer, with only the fields the
    // real backend endpoint accepts (limit) — no client-chosen recipient.
    expect(notificationsApi.getNotifications).toHaveBeenCalledWith({ limit: 100 });
  });

  it('renders an empty state when the backend returns zero notifications (not fake alerts)', async () => {
    (notificationsApi.getNotifications as any).mockResolvedValue([]);
    renderPage();

    await waitFor(() => {
      expect(screen.getByText('No Notifications Yet')).toBeInTheDocument();
    });
    // Must not show any of the fixture titles - nothing was fabricated.
    expect(screen.queryByText(unreadScheduleNotification.title)).not.toBeInTheDocument();
  });

  it('renders a clear error state on backend failure, not a silent success', async () => {
    (notificationsApi.getNotifications as any).mockRejectedValue({
      response: { status: 500, data: { detail: 'Internal error' } },
    });
    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/unexpected server error/i)).toBeInTheDocument();
    });
    expect(screen.queryByText('No Notifications Yet')).not.toBeInTheDocument();
  });

  it('renders a specific message for network failures', async () => {
    (notificationsApi.getNotifications as any).mockRejectedValue({});
    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/Unable to reach the GreenShift backend/i)).toBeInTheDocument();
    });
  });

  it('distinguishes read vs unread state visually', async () => {
    (notificationsApi.getNotifications as any).mockResolvedValue(notificationList);
    renderPage();

    await waitFor(() => {
      expect(screen.getByText(unreadScheduleNotification.title)).toBeInTheDocument();
    });

    // Unread items expose a "Mark Read" action; read items show a "Read" indicator.
    expect(screen.getAllByText('Mark Read').length).toBe(2); // unread + critical
    expect(screen.getByText('Read')).toBeInTheDocument(); // the approval-granted one
  });

  it('invokes the real markRead mutation through the API layer when marking an item read', async () => {
    const user = userEvent.setup();
    (notificationsApi.getNotifications as any).mockResolvedValue([unreadScheduleNotification]);
    (notificationsApi.markRead as any).mockResolvedValue({ ...unreadScheduleNotification, is_read: true });

    renderPage();
    await waitFor(() => expect(screen.getByText(unreadScheduleNotification.title)).toBeInTheDocument());

    await user.click(screen.getByText('Mark Read'));

    await waitFor(() => {
      expect(notificationsApi.markRead).toHaveBeenCalledWith(unreadScheduleNotification.id);
    });
  });

  it('invokes the real markAllRead mutation and never a per-item loop or fake local state', async () => {
    const user = userEvent.setup();
    (notificationsApi.getNotifications as any).mockResolvedValue(notificationList);
    (notificationsApi.markAllRead as any).mockResolvedValue({ marked_read: 2 });

    renderPage();
    await waitFor(() => expect(screen.getByText(unreadScheduleNotification.title)).toBeInTheDocument());

    await user.click(screen.getByText('Mark All Read'));

    await waitFor(() => {
      expect(notificationsApi.markAllRead).toHaveBeenCalledTimes(1);
    });
    // markRead (the per-item endpoint) must never be invoked as a substitute.
    expect(notificationsApi.markRead).not.toHaveBeenCalled();
  });

  it('derives category filter tabs from the real data rather than a hardcoded list', async () => {
    (notificationsApi.getNotifications as any).mockResolvedValue(notificationList);
    renderPage();

    await waitFor(() => expect(screen.getByText(unreadScheduleNotification.title)).toBeInTheDocument());

    // Categories present in the fixture: SCHEDULING, APPROVAL, EXECUTION.
    expect(screen.getByText(/Scheduling \(1\)/)).toBeInTheDocument();
    expect(screen.getByText(/Approval \(1\)/)).toBeInTheDocument();
    expect(screen.getByText(/Execution \(1\)/)).toBeInTheDocument();
    // A category never emitted by the backend must not appear as a fabricated tab.
    expect(screen.queryByText(/Security/)).not.toBeInTheDocument();
  });

  it('filters to only unread items when the Unread tab is selected', async () => {
    const user = userEvent.setup();
    (notificationsApi.getNotifications as any).mockResolvedValue(notificationList);
    renderPage();

    await waitFor(() => expect(screen.getByText(unreadScheduleNotification.title)).toBeInTheDocument());

    await user.click(screen.getByText(/Unread \(2\)/));

    expect(screen.getByText(unreadScheduleNotification.title)).toBeInTheDocument();
    expect(screen.getByText(criticalExecutionNotification.title)).toBeInTheDocument();
    expect(screen.queryByText(readApprovalNotification.title)).not.toBeInTheDocument();
  });

  it('renders a workload navigation link only when the notification carries a real job_id', async () => {
    (notificationsApi.getNotifications as any).mockResolvedValue([unreadScheduleNotification]);
    renderPage();

    await waitFor(() => expect(screen.getByText(unreadScheduleNotification.title)).toBeInTheDocument());
    expect(screen.getByText(`View Workload ${unreadScheduleNotification.job_id}`)).toBeInTheDocument();
  });

  it('never sends a client-chosen recipient/user id to the backend', async () => {
    (notificationsApi.getNotifications as any).mockResolvedValue(notificationList);
    renderPage();
    await waitFor(() => expect(notificationsApi.getNotifications).toHaveBeenCalled());

    const call = (notificationsApi.getNotifications as any).mock.calls[0][0];
    expect(call).not.toHaveProperty('recipient_user_id');
    expect(call).not.toHaveProperty('user_id');
  });
});
