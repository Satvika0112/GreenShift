import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RealtimeNotificationProvider, useRealtimeNotifications } from './RealtimeNotificationContext';
import { NotificationItem } from '../types/api';

let mockIsAuthenticated: boolean;
vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: mockIsAuthenticated }),
}));

function sseFrame(event: string, data: unknown): Uint8Array {
  return new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
}

/** A ReadableStream whose chunks we can push on demand, then close. */
function makeControllableStream() {
  let controllerRef: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controllerRef = controller;
    },
  });
  return {
    stream,
    push: (chunk: Uint8Array) => controllerRef.enqueue(chunk),
    close: () => controllerRef.close(),
  };
}

function baseNotification(overrides: Partial<NotificationItem> = {}): NotificationItem {
  return {
    id: 1,
    job_id: 'JOB-1',
    event_type: 'K8S_JOB_COMPLETED',
    category: 'EXECUTION',
    severity: 'INFO',
    title: 'Workload JOB-1 completed',
    message: 'Workload completed successfully.',
    action_url: '/workloads/JOB-1',
    created_at: new Date().toISOString(),
    read_at: null,
    is_read: false,
    ...overrides,
  };
}

function Probe() {
  const { connectionStatus, toasts, dismissToast } = useRealtimeNotifications();
  return (
    <div>
      <span data-testid="status">{connectionStatus}</span>
      <span data-testid="toast-count">{toasts.length}</span>
      {toasts.map((t) => (
        <div key={t.toastId} data-testid={`toast-${t.notification.id}`}>
          <span>{t.notification.title}</span>
          <button onClick={() => dismissToast(t.toastId)}>dismiss-{t.notification.id}</button>
        </div>
      ))}
    </div>
  );
}

function renderProbe() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <RealtimeNotificationProvider>
          <Probe />
        </RealtimeNotificationProvider>
      </QueryClientProvider>
    ),
  };
}

describe('RealtimeNotificationContext', () => {
  beforeEach(() => {
    mockIsAuthenticated = true;
    sessionStorage.setItem('greenshift_token', 'test-token');
  });

  afterEach(() => {
    vi.restoreAllMocks();
    sessionStorage.clear();
  });

  it('does not open a stream connection when not authenticated', async () => {
    mockIsAuthenticated = false;
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    renderProbe();
    await new Promise((r) => setTimeout(r, 0));
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('reflects realtime:true as connected', async () => {
    const { stream, push } = makeControllableStream();
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, body: stream } as any);

    renderProbe();
    act(() => push(sseFrame('connected', { realtime: true })));

    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('connected'));
  });

  it('reflects realtime:false as unavailable (graceful degradation)', async () => {
    const { stream, push } = makeControllableStream();
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, body: stream } as any);

    renderProbe();
    act(() => push(sseFrame('connected', { realtime: false })));

    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('unavailable'));
  });

  it('renders a toast and bumps the unread-count cache when a notification event arrives', async () => {
    const { stream, push } = makeControllableStream();
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, body: stream } as any);

    const { queryClient } = renderProbe();
    queryClient.setQueryData(['notificationsUnreadCount'], { unread_count: 2 });

    act(() => push(sseFrame('connected', { realtime: true })));
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('connected'));

    act(() => push(sseFrame('notification', baseNotification({ id: 42 }))));

    await waitFor(() => expect(screen.getByTestId('toast-count').textContent).toBe('1'));
    expect(screen.getByText('Workload JOB-1 completed')).toBeInTheDocument();
    expect(queryClient.getQueryData(['notificationsUnreadCount'])).toEqual({ unread_count: 3 });
  });

  it('does not duplicate a toast for the same notification id delivered twice', async () => {
    const { stream, push } = makeControllableStream();
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, body: stream } as any);

    renderProbe();
    act(() => push(sseFrame('connected', { realtime: true })));
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('connected'));

    const notif = baseNotification({ id: 99 });
    act(() => push(sseFrame('notification', notif)));
    await waitFor(() => expect(screen.getByTestId('toast-count').textContent).toBe('1'));

    act(() => push(sseFrame('notification', notif)));
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.getByTestId('toast-count').textContent).toBe('1');
  });

  it('lets the user dismiss a toast manually', async () => {
    const user = userEvent.setup();
    const { stream, push } = makeControllableStream();
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, body: stream } as any);

    renderProbe();
    act(() => push(sseFrame('connected', { realtime: true })));
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('connected'));

    act(() => push(sseFrame('notification', baseNotification({ id: 7 }))));
    await waitFor(() => expect(screen.getByTestId('toast-count').textContent).toBe('1'));

    await user.click(screen.getByText('dismiss-7'));
    await waitFor(() => expect(screen.getByTestId('toast-count').textContent).toBe('0'));
  });

  it('a CRITICAL notification does not auto-dismiss on its own within a short window', async () => {
    const { stream, push } = makeControllableStream();
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, body: stream } as any);

    renderProbe();
    act(() => push(sseFrame('connected', { realtime: true })));
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('connected'));

    act(() => push(sseFrame('notification', baseNotification({ id: 8, severity: 'CRITICAL' }))));
    await waitFor(() => expect(screen.getByTestId('toast-count').textContent).toBe('1'));

    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByTestId('toast-count').textContent).toBe('1');
  });
});
