import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { API_BASE_URL } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { useNotificationSound } from '../hooks/useNotificationSound';
import { NotificationItem, UnreadCountResponse } from '../types/api';

export type RealtimeConnectionStatus =
  | 'idle'
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'disconnected'
  | 'unavailable';

export interface NotificationToast {
  toastId: string;
  notification: NotificationItem;
  urgent: boolean;
  persistent: boolean;
}

interface RealtimeNotificationContextType {
  connectionStatus: RealtimeConnectionStatus;
  toasts: NotificationToast[];
  dismissToast: (toastId: string) => void;
  soundEnabled: boolean;
  setSoundEnabled: (enabled: boolean) => void;
}

const RealtimeNotificationContext = createContext<RealtimeNotificationContextType | undefined>(undefined);

const MAX_SEEN_IDS = 300;
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;
const AUTO_DISMISS_MS = 8000;

function isUrgent(n: NotificationItem): boolean {
  return n.severity === 'CRITICAL' || n.severity === 'WARNING';
}

function isPersistent(n: NotificationItem): boolean {
  return n.severity === 'CRITICAL';
}

export const RealtimeNotificationProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated } = useAuth();
  const queryClient = useQueryClient();
  const { soundEnabled, setSoundEnabled, playNotificationSound } = useNotificationSound();

  const [connectionStatus, setConnectionStatus] = useState<RealtimeConnectionStatus>('idle');
  const [toasts, setToasts] = useState<NotificationToast[]>([]);

  const abortRef = useRef<AbortController | null>(null);
  const seenIdsRef = useRef<Set<number>>(new Set());
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stoppedRef = useRef(false);

  const dismissToast = useCallback((toastId: string) => {
    setToasts((prev) => prev.filter((t) => t.toastId !== toastId));
  }, []);

  const handleIncomingNotification = useCallback((notif: NotificationItem) => {
    // Idempotency guard: a reconnect never replays history over Pub/Sub, but
    // this defends against any rare duplicate delivery so the same
    // notification is never toasted/sounded/counted twice.
    if (seenIdsRef.current.has(notif.id)) return;
    seenIdsRef.current.add(notif.id);
    if (seenIdsRef.current.size > MAX_SEEN_IDS) {
      const first = seenIdsRef.current.values().next().value;
      if (first !== undefined) seenIdsRef.current.delete(first);
    }

    // Instant unread-count bump (don't wait for the next 30s poll).
    queryClient.setQueryData<UnreadCountResponse | undefined>(['notificationsUnreadCount'], (prev) => ({
      unread_count: (prev?.unread_count ?? 0) + (notif.is_read ? 0 : 1),
    }));
    // If the notification list/panel is mounted, let it pick up the new row.
    queryClient.invalidateQueries({ queryKey: ['notifications'] });

    const urgent = isUrgent(notif);
    setToasts((prev) => [
      ...prev,
      { toastId: `${notif.id}-${Date.now()}`, notification: notif, urgent, persistent: isPersistent(notif) },
    ]);
    playNotificationSound(urgent);
  }, [queryClient, playNotificationSound]);

  useEffect(() => {
    if (!isAuthenticated) {
      stoppedRef.current = true;
      abortRef.current?.abort();
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      setConnectionStatus('idle');
      seenIdsRef.current.clear();
      return;
    }

    stoppedRef.current = false;

    const connect = async () => {
      if (stoppedRef.current) return;
      const token = sessionStorage.getItem('greenshift_token');
      if (!token) return;

      const controller = new AbortController();
      abortRef.current = controller;
      setConnectionStatus(reconnectAttemptRef.current > 0 ? 'reconnecting' : 'connecting');

      try {
        const res = await fetch(`${API_BASE_URL}/api/v1/notifications/stream`, {
          headers: { Authorization: `Bearer ${token}`, Accept: 'text/event-stream' },
          signal: controller.signal,
        });
        if (!res.ok || !res.body) {
          throw new Error(`Notification stream responded ${res.status}`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (!stoppedRef.current) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          let sepIndex: number;
          while ((sepIndex = buffer.indexOf('\n\n')) !== -1) {
            const frame = buffer.slice(0, sepIndex);
            buffer = buffer.slice(sepIndex + 2);
            if (!frame || frame.startsWith(':')) continue; // heartbeat comment

            let eventName = 'message';
            let dataLine = '';
            for (const line of frame.split('\n')) {
              if (line.startsWith('event:')) eventName = line.slice(6).trim();
              else if (line.startsWith('data:')) dataLine += line.slice(5).trim();
            }
            if (!dataLine) continue;

            if (eventName === 'connected') {
              reconnectAttemptRef.current = 0;
              try {
                const parsed = JSON.parse(dataLine);
                setConnectionStatus(parsed.realtime ? 'connected' : 'unavailable');
              } catch {
                setConnectionStatus('connected');
              }
            } else if (eventName === 'notification') {
              try {
                const notif: NotificationItem = JSON.parse(dataLine);
                handleIncomingNotification(notif);
              } catch {
                // Malformed frame — ignore this one, stream continues.
              }
            }
          }
        }
      } catch (err) {
        if (controller.signal.aborted) return;
      }

      if (stoppedRef.current) return;

      // Stream ended (server closed it, network blip, etc.) — reconnect
      // with capped exponential backoff rather than hammering the server.
      setConnectionStatus('reconnecting');
      reconnectAttemptRef.current += 1;
      const delay = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** (reconnectAttemptRef.current - 1));
      reconnectTimerRef.current = setTimeout(connect, delay);
    };

    connect();

    return () => {
      stoppedRef.current = true;
      abortRef.current?.abort();
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated]);

  // Auto-dismiss non-persistent toasts.
  useEffect(() => {
    if (toasts.length === 0) return;
    const timers = toasts
      .filter((t) => !t.persistent)
      .map((t) => setTimeout(() => dismissToast(t.toastId), AUTO_DISMISS_MS));
    return () => timers.forEach(clearTimeout);
  }, [toasts, dismissToast]);

  return (
    <RealtimeNotificationContext.Provider
      value={{ connectionStatus, toasts, dismissToast, soundEnabled, setSoundEnabled }}
    >
      {children}
    </RealtimeNotificationContext.Provider>
  );
};

export const useRealtimeNotifications = () => {
  const ctx = useContext(RealtimeNotificationContext);
  if (!ctx) {
    throw new Error('useRealtimeNotifications must be used within a RealtimeNotificationProvider');
  }
  return ctx;
};
