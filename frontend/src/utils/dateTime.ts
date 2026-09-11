import { RegionInfo } from '../types/api';

// Single source of truth for converting a UTC timestamp into a region's
// local wall-clock display. Every page renders business timestamps through
// these functions — never `new Date(x).toLocaleString()` directly — so
// there is exactly one place that does timezone conversion.

function parseDate(iso?: string | null): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function isValidIanaTimezone(timezoneName?: string | null): timezoneName is string {
  if (!timezoneName) return false;
  try {
    new Intl.DateTimeFormat(undefined, { timeZone: timezoneName }).format(0);
    return true;
  } catch {
    return false;
  }
}

// Resolves an IANA timezone from a region_id against the already-fetched
// regions list (RegionInfo[]) — the one lookup every page shares instead of
// each re-implementing `regions.find(r => r.region_id === regionId)`.
export function resolveRegionTimezone(
  regions: Pick<RegionInfo, 'region_id' | 'timezone'>[] | undefined | null,
  regionId?: string | null
): string | undefined {
  if (!regions || !regionId) return undefined;
  return regions.find((r) => r.region_id === regionId)?.timezone;
}

export function formatRegionalDateTime(
  iso?: string | null,
  timezoneName?: string | null,
  options?: Intl.DateTimeFormatOptions
): string {
  const d = parseDate(iso);
  if (!d) return '—';
  if (!isValidIanaTimezone(timezoneName)) return 'DATA UNAVAILABLE';
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: timezoneName,
    ...options,
  }).format(d);
}

export function formatRegionalDate(iso?: string | null, timezoneName?: string | null): string {
  const d = parseDate(iso);
  if (!d) return '—';
  if (!isValidIanaTimezone(timezoneName)) return 'DATA UNAVAILABLE';
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeZone: timezoneName }).format(d);
}

export function formatRegionalTime(iso?: string | null, timezoneName?: string | null): string {
  const d = parseDate(iso);
  if (!d) return '—';
  if (!isValidIanaTimezone(timezoneName)) return 'DATA UNAVAILABLE';
  return new Intl.DateTimeFormat(undefined, { timeStyle: 'short', timeZone: timezoneName }).format(d);
}

// Short zone abbreviation for a specific instant (e.g. "IST", "PDT", "AEST")
// — computed via Intl rather than a hardcoded map, so it's correct across
// DST boundaries for zones that observe it.
export function getTimezoneLabel(iso?: string | null, timezoneName?: string | null): string {
  const d = parseDate(iso) || new Date();
  if (!isValidIanaTimezone(timezoneName)) return 'DATA UNAVAILABLE';
  const parts = new Intl.DateTimeFormat(undefined, { timeZoneName: 'short', timeZone: timezoneName }).formatToParts(d);
  return parts.find((p) => p.type === 'timeZoneName')?.value || timezoneName;
}

// Formats a UTC instant as the region-local `YYYY-MM-DDTHH:mm` string
// `<input type="datetime-local">` requires, for pre-filling an editable
// field with a dataset value the user is about to override.
export function toRegionalInputValue(iso?: string | null, timezoneName?: string | null): string {
  const d = parseDate(iso);
  if (!d || !isValidIanaTimezone(timezoneName)) return '';
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: timezoneName,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(d);
  const get = (type: string) => parts.find((p) => p.type === type)?.value || '';
  return `${get('year')}-${get('month')}-${get('day')}T${get('hour')}:${get('minute')}`;
}
