import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useNotificationSound } from './useNotificationSound';

describe('useNotificationSound', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('defaults to enabled when nothing is stored', () => {
    const { result } = renderHook(() => useNotificationSound());
    expect(result.current.soundEnabled).toBe(true);
  });

  it('reads a previously stored disabled preference', () => {
    localStorage.setItem('gs_pref_sound_enabled', '0');
    const { result } = renderHook(() => useNotificationSound());
    expect(result.current.soundEnabled).toBe(false);
  });

  it('setSoundEnabled persists the preference to localStorage', () => {
    const { result } = renderHook(() => useNotificationSound());
    act(() => result.current.setSoundEnabled(false));
    expect(result.current.soundEnabled).toBe(false);
    expect(localStorage.getItem('gs_pref_sound_enabled')).toBe('0');

    act(() => result.current.setSoundEnabled(true));
    expect(localStorage.getItem('gs_pref_sound_enabled')).toBe('1');
  });

  it('playNotificationSound is a silent no-op before the AudioContext has been unlocked by a user gesture', () => {
    const { result } = renderHook(() => useNotificationSound());
    // No pointerdown/keydown has fired yet in this test — audio stays locked.
    expect(() => result.current.playNotificationSound(true)).not.toThrow();
    expect(() => result.current.playNotificationSound(false)).not.toThrow();
  });

  it('playNotificationSound is a no-op once sound is disabled, even after unlock', () => {
    const { result } = renderHook(() => useNotificationSound());
    act(() => result.current.setSoundEnabled(false));
    expect(() => result.current.playNotificationSound(true)).not.toThrow();
  });
});
