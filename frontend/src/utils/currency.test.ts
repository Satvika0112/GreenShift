import { describe, it, expect } from 'vitest';
import { formatCurrency, getCurrencySymbol, formatRate, currencyRateUnitLabel, isValidCurrencyCode } from './currency';

describe('currency utility', () => {
  describe('formatCurrency', () => {
    it('formats INR correctly', () => {
      expect(formatCurrency(38.4, 'INR')).toBe('₹38.40');
    });

    it('formats USD correctly', () => {
      expect(formatCurrency(0.14, 'USD')).toBe('$0.14');
    });

    it('formats AUD correctly, never collapsing to a bare $', () => {
      const result = formatCurrency(0.28, 'AUD');
      expect(result).toBe('A$0.28');
      expect(result).not.toBe('$0.28');
    });

    it('supports a future ISO currency with no code changes required', () => {
      // JPY is not special-cased anywhere in the utility — this proves the
      // implementation is generic, not a country-specific switch.
      expect(() => formatCurrency(100, 'JPY')).not.toThrow();
      expect(formatCurrency(100, 'JPY')).toMatch(/¥|JPY/);
    });

    it('does not crash on a missing currency code, and never fabricates a value', () => {
      expect(formatCurrency(10, undefined)).toBe('—');
      expect(formatCurrency(10, null)).toBe('—');
      expect(formatCurrency(10, '')).toBe('—');
    });

    it('does not crash on an invalid/unrecognized currency code', () => {
      expect(formatCurrency(10, 'NOT_A_CURRENCY')).toBe('—');
    });

    it('never turns a missing tariff value into zero', () => {
      expect(formatCurrency(undefined, 'INR')).toBe('—');
      expect(formatCurrency(null, 'USD')).toBe('—');
      expect(formatCurrency(Number.NaN, 'AUD')).toBe('—');
    });

    it('preserves precision appropriate for sub-unit electricity rates', () => {
      expect(formatCurrency(0.1148, 'USD')).toBe('$0.1148');
      expect(formatCurrency(0.061196, 'USD')).not.toBe('$0.06'); // real ToD tiers must stay distinguishable
    });
  });

  describe('getCurrencySymbol', () => {
    it('derives ₹ for INR, $ for USD, A$ for AUD — from Intl, not a switch statement', () => {
      expect(getCurrencySymbol('INR')).toBe('₹');
      expect(getCurrencySymbol('USD')).toBe('$');
      expect(getCurrencySymbol('AUD')).toBe('A$');
    });

    it('handles a missing/invalid code without crashing', () => {
      expect(() => getCurrencySymbol(undefined)).not.toThrow();
      expect(() => getCurrencySymbol(null)).not.toThrow();
    });
  });

  describe('formatRate', () => {
    it('renders the full "value + symbol + ISO code + unit" form', () => {
      expect(formatRate(38.4, 'INR')).toBe('₹38.40 INR/kWh');
      expect(formatRate(0.14, 'USD')).toBe('$0.14 USD/kWh');
      expect(formatRate(0.28, 'AUD')).toBe('A$0.28 AUD/kWh');
    });

    it('never renders a fabricated zero rate when the value is missing', () => {
      expect(formatRate(undefined, 'AUD')).toBe('—');
      expect(formatRate(null, 'INR')).toBe('—');
    });

    it('returns — when the currency is missing, even if a value is present', () => {
      expect(formatRate(38.4, undefined)).toBe('—');
    });
  });

  describe('currencyRateUnitLabel', () => {
    it('renders the compact symbol+unit form for chart axes/legends', () => {
      expect(currencyRateUnitLabel('INR')).toBe('₹/kWh');
      expect(currencyRateUnitLabel('USD')).toBe('$/kWh');
      expect(currencyRateUnitLabel('AUD')).toBe('A$/kWh');
    });
  });

  describe('isValidCurrencyCode', () => {
    it('accepts real ISO codes and rejects invalid ones', () => {
      expect(isValidCurrencyCode('INR')).toBe(true);
      expect(isValidCurrencyCode('AUD')).toBe(true);
      expect(isValidCurrencyCode('NOT_REAL')).toBe(false);
      expect(isValidCurrencyCode(undefined)).toBe(false);
      expect(isValidCurrencyCode(null)).toBe(false);
    });
  });
});
