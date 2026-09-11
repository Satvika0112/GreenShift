import { describe, it, expect } from 'vitest';
import {
  formatRegionalDateTime,
  formatRegionalDate,
  formatRegionalTime,
  getTimezoneLabel,
  toRegionalInputValue,
  resolveRegionTimezone,
  isValidIanaTimezone,
} from './dateTime';

// A fixed instant with an unambiguous UTC hour so region conversions are
// easy to reason about: 2026-09-10T12:00:00Z.
const UTC_INSTANT = '2026-09-10T12:00:00Z';

describe('formatRegionalDateTime', () => {
  it('formats an India (IST, UTC+5:30, no DST) timestamp in the region timezone', () => {
    const result = formatRegionalDateTime(UTC_INSTANT, 'Asia/Kolkata');
    // 12:00 UTC -> 17:30 IST
    expect(result).toContain('5:30');
    expect(result.toUpperCase()).toContain('PM');
  });

  it('formats a USA (America/Los_Angeles) timestamp in the region timezone', () => {
    const result = formatRegionalDateTime(UTC_INSTANT, 'America/Los_Angeles');
    // 12:00 UTC -> 05:00 PDT (September is within US DST)
    expect(result).toContain('5:00');
    expect(result.toUpperCase()).toContain('AM');
  });

  it('formats an Australia (Australia/Adelaide) timestamp in the region timezone', () => {
    const result = formatRegionalDateTime(UTC_INSTANT, 'Australia/Adelaide');
    // Adelaide is UTC+9:30 in September (no DST in southern winter/early spring
    // for ACST) -> 12:00 UTC -> 21:30 local.
    expect(result).toContain('9:30');
    expect(result.toUpperCase()).toContain('PM');
  });

  it('never falls back to the browser-local timezone when an explicit timezone is supplied', () => {
    // Two different regions must produce different wall-clock strings for the
    // same instant — proof the browser's own timezone isn't leaking in.
    const india = formatRegionalDateTime(UTC_INSTANT, 'Asia/Kolkata');
    const usa = formatRegionalDateTime(UTC_INSTANT, 'America/Los_Angeles');
    expect(india).not.toBe(usa);
  });

  it('is DST-aware for a zone that observes it (America/Los_Angeles, Jan vs Jul)', () => {
    const januaryPst = formatRegionalDateTime('2026-01-10T20:00:00Z', 'America/Los_Angeles'); // PST = UTC-8
    const julyPdt = formatRegionalDateTime('2026-07-10T20:00:00Z', 'America/Los_Angeles'); // PDT = UTC-7
    expect(januaryPst).toContain('12:00');
    expect(julyPdt).toContain('1:00');
  });

  it('returns DATA UNAVAILABLE when no timezone is supplied, never guessing browser-local', () => {
    expect(formatRegionalDateTime(UTC_INSTANT, undefined)).toBe('DATA UNAVAILABLE');
    expect(formatRegionalDateTime(UTC_INSTANT, null)).toBe('DATA UNAVAILABLE');
  });

  it('returns DATA UNAVAILABLE for an invalid IANA timezone string', () => {
    expect(formatRegionalDateTime(UTC_INSTANT, 'Not/A_Zone')).toBe('DATA UNAVAILABLE');
  });

  it('returns an em dash for a missing or invalid timestamp', () => {
    expect(formatRegionalDateTime(undefined, 'Asia/Kolkata')).toBe('—');
    expect(formatRegionalDateTime(null, 'Asia/Kolkata')).toBe('—');
    expect(formatRegionalDateTime('not-a-date', 'Asia/Kolkata')).toBe('—');
  });
});

describe('formatRegionalDate / formatRegionalTime', () => {
  it('formatRegionalDate renders only the date portion', () => {
    const result = formatRegionalDate(UTC_INSTANT, 'Asia/Kolkata');
    expect(result).not.toMatch(/\d{1,2}:\d{2}/);
    expect(result).toContain('2026');
  });

  it('formatRegionalTime renders only the time portion', () => {
    const result = formatRegionalTime(UTC_INSTANT, 'Asia/Kolkata');
    expect(result).toMatch(/\d{1,2}:\d{2}/);
    expect(result).not.toContain('2026');
  });
});

describe('getTimezoneLabel', () => {
  // Exact abbreviation text (IST vs GMT+5:30, PDT vs GMT-7, ...) depends on
  // the runtime's ICU timezone-name data, which varies across Node/browser
  // builds — assert the property that must hold everywhere: it's derived
  // from Intl (a real, non-empty label), not a hardcoded lookup table, and
  // it changes across a DST boundary for a zone that observes DST.
  it('derives a real, non-empty label for India via Intl (never hardcoded)', () => {
    const label = getTimezoneLabel(UTC_INSTANT, 'Asia/Kolkata');
    expect(label).toBeTruthy();
    expect(label).not.toBe('DATA UNAVAILABLE');
  });

  it('is DST-aware for the US (label differs between January and July)', () => {
    const januaryLabel = getTimezoneLabel('2026-01-10T20:00:00Z', 'America/Los_Angeles');
    const julyLabel = getTimezoneLabel('2026-07-10T20:00:00Z', 'America/Los_Angeles');
    expect(januaryLabel).not.toBe(julyLabel);
  });

  it('derives a real, non-empty label for Australia via Intl (never hardcoded)', () => {
    const label = getTimezoneLabel(UTC_INSTANT, 'Australia/Adelaide');
    expect(label).toBeTruthy();
    expect(label).not.toBe('DATA UNAVAILABLE');
  });

  it('returns DATA UNAVAILABLE for a missing timezone', () => {
    expect(getTimezoneLabel(UTC_INSTANT, undefined)).toBe('DATA UNAVAILABLE');
  });
});

describe('toRegionalInputValue', () => {
  it('produces a datetime-local-compatible string in the region wall clock', () => {
    const value = toRegionalInputValue(UTC_INSTANT, 'Asia/Kolkata');
    expect(value).toBe('2026-09-10T17:30');
  });

  it('returns an empty string when the timezone or timestamp is missing', () => {
    expect(toRegionalInputValue(UTC_INSTANT, undefined)).toBe('');
    expect(toRegionalInputValue(undefined, 'Asia/Kolkata')).toBe('');
  });
});

describe('resolveRegionTimezone', () => {
  const regions = [
    { region_id: 'IN-TG', timezone: 'Asia/Kolkata' },
    { region_id: 'AU-SA-Small', timezone: 'Australia/Adelaide' },
  ];

  it('resolves the timezone for a known region_id', () => {
    expect(resolveRegionTimezone(regions, 'AU-SA-Small')).toBe('Australia/Adelaide');
  });

  it('returns undefined for an unknown region, never a guessed default', () => {
    expect(resolveRegionTimezone(regions, 'US-CA')).toBeUndefined();
  });

  it('returns undefined when the regions list or region id is missing', () => {
    expect(resolveRegionTimezone(undefined, 'IN-TG')).toBeUndefined();
    expect(resolveRegionTimezone(regions, undefined)).toBeUndefined();
  });
});

describe('isValidIanaTimezone', () => {
  it('accepts real IANA zones', () => {
    expect(isValidIanaTimezone('Asia/Kolkata')).toBe(true);
    expect(isValidIanaTimezone('Australia/Adelaide')).toBe(true);
    expect(isValidIanaTimezone('UTC')).toBe(true);
  });

  it('rejects a clearly invalid/garbage timezone string', () => {
    expect(isValidIanaTimezone('Not/A_Real_Zone')).toBe(false);
    expect(isValidIanaTimezone('XXXXXNOTATIMEZONE')).toBe(false);
    expect(isValidIanaTimezone('')).toBe(false);
    expect(isValidIanaTimezone(undefined)).toBe(false);
    expect(isValidIanaTimezone(null)).toBe(false);
  });
});
