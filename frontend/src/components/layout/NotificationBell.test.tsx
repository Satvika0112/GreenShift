import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { NotificationBell } from './NotificationBell';
import { notificationsApi } from '../../api/endpoints';
import { NotificationItem } from '../../types/api';

const navigateMock = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => navigateMock };
});

vi.mock('../../api/endpoints', () => ({
  notificationsApi: {
    getUnreadCount: vi.fn(),
    getNotifications: vi.fn(),
    markRead: vi.fn(),
    markAllRead: vi.fn(),
  },
}));

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: true }),
}));

let mockConnectionStatus: string;
vi.mock('../../context/RealtimeNotificationContext', () => ({
  useRealtimeNotifications: () => ({ connectionStatus: mockConnectionStatus }),
}));

function notif(overrides: Partial<NotificationItem> = {}): NotificationItem {
  return {
    id: 1,
    job_id: 'JOB-1',
    event_type: 'SCHEDULE_PROPOSED',
    category: 'APPROVAL',
    severity: 'INFO',
    title: 'Approval required — JOB-1',
    message: 'Awaiting your approval.',
    action_url: '/approvals',
    created_at: new Date().toISOString(),
    read_at: null,
    is_read: false,
    ...overrides,
  };
}

function renderBell() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('NotificationBell', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConnectionStatus = 'connected';
    (notificationsApi.getUnreadCount as any).mockResolvedValue({ unread_count: 1 });
    (notificationsApi.getNotifications as any).mockResolvedValue([notif()]);
    (notificationsApi.markRead as any).mockResolvedValue(notif({ is_read: true }));
  });

  it('shows the unread badge from real backend data', async () => {
    renderBell();
    await waitFor(() => expect(screen.getByText('1')).toBeInTheDocument());
  });

  it('shows the live connection indicator when the panel is open', async () => {
    const user = userEvent.setup();
    renderBell();
    await user.click(screen.getByLabelText('Notifications'));
    await waitFor(() => expect(screen.getByText('Live')).toBeInTheDocument());
  });

  it('clicking a notification with an action_url marks it read and navigates there', async () => {
    const user = userEvent.setup();
    renderBell();
    await user.click(screen.getByLabelText('Notifications'));

    const item = await screen.findByText('Approval required — JOB-1');
    await user.click(item);

    await waitFor(() => expect(notificationsApi.markRead).toHaveBeenCalledWith(1));
    expect(navigateMock).toHaveBeenCalledWith('/approvals');
  });
});
