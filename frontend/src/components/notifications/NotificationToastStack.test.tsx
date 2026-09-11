import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { NotificationToastStack } from './NotificationToastStack';
import { NotificationToast } from '../../context/RealtimeNotificationContext';
import { NotificationItem } from '../../types/api';

const navigateMock = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => navigateMock };
});

let mockToasts: NotificationToast[];
const dismissToastMock = vi.fn((id: string) => {
  mockToasts = mockToasts.filter((t) => t.toastId !== id);
});

vi.mock('../../context/RealtimeNotificationContext', () => ({
  useRealtimeNotifications: () => ({ toasts: mockToasts, dismissToast: dismissToastMock }),
}));

function notif(overrides: Partial<NotificationItem> = {}): NotificationItem {
  return {
    id: 1,
    job_id: 'JOB-1',
    event_type: 'K8S_JOB_FAILED',
    category: 'EXECUTION',
    severity: 'CRITICAL',
    title: 'Workload JOB-1 failed',
    message: 'Execution failed.',
    action_url: '/workloads/JOB-1',
    created_at: new Date().toISOString(),
    read_at: null,
    is_read: false,
    ...overrides,
  };
}

function renderStack() {
  return render(
    <MemoryRouter>
      <NotificationToastStack />
    </MemoryRouter>
  );
}

describe('NotificationToastStack', () => {
  beforeEach(() => {
    mockToasts = [];
    navigateMock.mockClear();
    dismissToastMock.mockClear();
  });

  it('renders nothing when there are no toasts', () => {
    const { container } = renderStack();
    expect(container.firstChild).toBeNull();
  });

  it('renders a toast with title and message', () => {
    mockToasts = [{ toastId: 't1', notification: notif(), urgent: true, persistent: true }];
    renderStack();
    expect(screen.getByText('Workload JOB-1 failed')).toBeInTheDocument();
    expect(screen.getByText('Execution failed.')).toBeInTheDocument();
  });

  it('clicking the toast body navigates to its action_url and dismisses it', async () => {
    const user = userEvent.setup();
    mockToasts = [{ toastId: 't1', notification: notif(), urgent: true, persistent: true }];
    renderStack();

    await user.click(screen.getByText('Workload JOB-1 failed'));
    expect(navigateMock).toHaveBeenCalledWith('/workloads/JOB-1');
    expect(dismissToastMock).toHaveBeenCalledWith('t1');
  });

  it('clicking the close button dismisses without navigating', async () => {
    const user = userEvent.setup();
    mockToasts = [{ toastId: 't1', notification: notif(), urgent: true, persistent: true }];
    renderStack();

    await user.click(screen.getByLabelText('Dismiss notification'));
    expect(dismissToastMock).toHaveBeenCalledWith('t1');
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it('does not navigate when the notification has no action_url', async () => {
    const user = userEvent.setup();
    mockToasts = [{ toastId: 't1', notification: notif({ action_url: null }), urgent: false, persistent: false }];
    renderStack();

    await user.click(screen.getByText('Workload JOB-1 failed'));
    expect(navigateMock).not.toHaveBeenCalled();
    expect(dismissToastMock).toHaveBeenCalledWith('t1');
  });

  it('renders multiple toasts stacked', () => {
    mockToasts = [
      { toastId: 't1', notification: notif({ id: 1 }), urgent: true, persistent: true },
      { toastId: 't2', notification: notif({ id: 2, title: 'Second event' }), urgent: false, persistent: false },
    ];
    renderStack();
    expect(screen.getByText('Workload JOB-1 failed')).toBeInTheDocument();
    expect(screen.getByText('Second event')).toBeInTheDocument();
  });
});
