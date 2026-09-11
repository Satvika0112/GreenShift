import { useCallback, useEffect, useRef, useState } from 'react';

const STORAGE_KEY = 'gs_pref_sound_enabled';

/**
 * Real, synthesized notification sound via the Web Audio API — no audio
 * asset file to source/embed. A short two-tone chime for CRITICAL/WARNING
 * events, a single soft tone for INFO events, matching the "important
 * events get sound, informational events get a softer/no sound" spec.
 *
 * Browsers block audio until a user gesture unlocks the AudioContext, so
 * the context is created lazily and resumed on the first click/keydown
 * anywhere in the app (see the `unlock` effect below) rather than at
 * import time. Until unlocked, play() is a silent no-op — it never throws
 * and never queues sounds to "catch up" later, so a page opened in the
 * background can't suddenly play a backlog of tones once focused.
 */
export function useNotificationSound() {
  const [enabled, setEnabledState] = useState<boolean>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      return stored === null ? true : stored === '1';
    } catch {
      return true;
    }
  });
  const audioCtxRef = useRef<AudioContext | null>(null);
  const unlockedRef = useRef(false);

  useEffect(() => {
    const unlock = () => {
      if (unlockedRef.current) return;
      try {
        const Ctx = window.AudioContext || (window as any).webkitAudioContext;
        if (!Ctx) return;
        if (!audioCtxRef.current) {
          audioCtxRef.current = new Ctx();
        }
        if (audioCtxRef.current.state === 'suspended') {
          audioCtxRef.current.resume().catch(() => {});
        }
        unlockedRef.current = true;
      } catch {
        // Web Audio unavailable in this environment — sound stays a no-op.
      }
    };
    window.addEventListener('pointerdown', unlock, { once: true });
    window.addEventListener('keydown', unlock, { once: true });
    return () => {
      window.removeEventListener('pointerdown', unlock);
      window.removeEventListener('keydown', unlock);
    };
  }, []);

  const setEnabled = useCallback((value: boolean) => {
    setEnabledState(value);
    try {
      localStorage.setItem(STORAGE_KEY, value ? '1' : '0');
    } catch {
      // localStorage unavailable (private mode, quota) — preference just
      // won't persist across reloads; the in-memory value still applies.
    }
  }, []);

  const playTone = useCallback((frequency: number, startAt: number, durationSec: number, ctx: AudioContext, peakGain: number) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = frequency;
    gain.gain.setValueAtTime(0, startAt);
    gain.gain.linearRampToValueAtTime(peakGain, startAt + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, startAt + durationSec);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(startAt);
    osc.stop(startAt + durationSec + 0.02);
  }, []);

  /** Plays once for this call only — never loops, never replays a backlog. */
  const play = useCallback((urgent: boolean) => {
    if (!enabled) return;
    const ctx = audioCtxRef.current;
    if (!ctx || ctx.state !== 'running') return; // not unlocked yet — silent no-op
    const now = ctx.currentTime;
    if (urgent) {
      playTone(880, now, 0.14, ctx, 0.18);
      playTone(1108, now + 0.12, 0.16, ctx, 0.18);
    } else {
      playTone(660, now, 0.12, ctx, 0.1);
    }
  }, [enabled, playTone]);

  return { soundEnabled: enabled, setSoundEnabled: setEnabled, playNotificationSound: play };
}
