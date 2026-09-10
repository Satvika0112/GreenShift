// A fixed base locale — deliberately NOT the viewer's own locale — is used
// for all currency symbol/value formatting. This is what makes the output
// deterministic regardless of who's looking at it: in an 'en-AU' locale,
// Intl renders AUD with its bare local symbol ("$"), indistinguishable from
// USD; 'en-US' renders foreign currencies with their disambiguating prefix
// (AUD -> "A$", CAD -> "CA$", INR -> "₹"), which is exactly the "A$28.40
// AUD/kWh" style GreenShift always wants, everywhere, for every viewer.
const BASE_LOCALE = 'en-US';

export function isValidCurrencyCode(code?: string | null): code is string {
  if (!code) return false;
  try {
    new Intl.NumberFormat(BASE_LOCALE, { style: 'currency', currency: code }).format(0);
    return true;
  } catch {
    return false;
  }
}

// Symbol+value only (e.g. "₹38.40", "A$0.28"). Never fabricates a value —
// returns "—" when the amount or currency code is missing/invalid.
export function formatCurrency(
  value: number | null | undefined,
  currencyCode: string | null | undefined,
  options?: Intl.NumberFormatOptions
): string {
  if (value === null || value === undefined || Number.isNaN(value) || !isValidCurrencyCode(currencyCode)) {
    return '—';
  }
  return new Intl.NumberFormat(BASE_LOCALE, {
    style: 'currency',
    currency: currencyCode,
    // Electricity per-kWh rates are frequently sub-dollar/sub-rupee with
    // meaningful precision past 2 decimals (e.g. $0.1148/kWh) — cap at 4
    // rather than rounding distinct tariff tiers into the same display.
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
    ...options,
  }).format(value);
}

// Derives the real display symbol from Intl rather than a country-specific
// switch statement — "₹" for INR, "$" for USD, "A$" for AUD, and so on for
// any ISO code the backend ever returns, with no code changes required.
export function getCurrencySymbol(currencyCode?: string | null): string {
  if (!isValidCurrencyCode(currencyCode)) return currencyCode || '';
  const parts = new Intl.NumberFormat(BASE_LOCALE, { style: 'currency', currency: currencyCode }).formatToParts(0);
  const symbol = parts.filter((p) => p.type === 'currency').map((p) => p.value).join('');
  return symbol || currencyCode;
}

// The full, unambiguous "value + symbol + ISO code + unit" form used
// throughout Regions/Carbon & Tariffs: "₹38.40 INR/kWh", "$0.14 USD/kWh",
// "A$0.28 AUD/kWh". Returns "—" (never "$0.00" or similar) when unavailable.
export function formatRate(
  value: number | null | undefined,
  currencyCode: string | null | undefined,
  unit = '/kWh'
): string {
  const formatted = formatCurrency(value, currencyCode);
  if (formatted === '—' || !currencyCode) return '—';
  return `${formatted} ${currencyCode}${unit}`;
}

// The compact "symbol + unit" form for chart axes/legends/series names,
// e.g. "₹/kWh", "$/kWh", "A$/kWh" — never a hardcoded "$".
export function currencyRateUnitLabel(currencyCode: string | null | undefined, unit = '/kWh'): string {
  const symbol = currencyCode ? getCurrencySymbol(currencyCode) : null;
  return `${symbol || currencyCode || ''}${unit}`;
}
