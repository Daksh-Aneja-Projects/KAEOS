import { describe, it, expect } from 'vitest';
import {
  toPct, humanize, measured, NOT_MEASURED,
  formatCurrency, formatNumber, formatCompact, formatPercent, formatDate, formatDateTime,
} from './format';

describe('formatCurrency', () => {
  it('formats numbers and numeric strings as currency', () => {
    // Node/jsdom default locale is en-US; assert the stable parts.
    expect(formatCurrency(1500.5)).toBe('$1,500.50');
    expect(formatCurrency('1200000')).toBe('$1,200,000.00');
  });
  it('honours a non-USD currency', () => {
    const eur = formatCurrency(10, 'EUR');
    expect(eur).toContain('10');
    expect(eur).toMatch(/€|EUR/);
  });
  it('returns Not measured for absent values, formats a real zero', () => {
    expect(formatCurrency(null)).toBe(NOT_MEASURED);
    expect(formatCurrency(undefined)).toBe(NOT_MEASURED);
    expect(formatCurrency('')).toBe(NOT_MEASURED);
    expect(formatCurrency('not-a-number')).toBe(NOT_MEASURED);
    expect(formatCurrency(0)).toBe('$0.00');
  });
});

describe('formatNumber / formatCompact', () => {
  it('groups integers and respects digit count', () => {
    expect(formatNumber(12345)).toBe('12,345');
    expect(formatNumber(3.14159, 2)).toBe('3.14');
  });
  it('compacts large numbers', () => {
    expect(formatCompact(1200000)).toBe('1.2M');
  });
  it('returns Not measured for null', () => {
    expect(formatNumber(null)).toBe(NOT_MEASURED);
    expect(formatCompact(undefined)).toBe(NOT_MEASURED);
  });
});

describe('formatPercent', () => {
  it('formats a 0-100 value with a percent sign', () => {
    expect(formatPercent(87.5)).toBe('88%');
    expect(formatPercent(87.5, 1)).toBe('87.5%');
  });
  it('returns Not measured for null', () => {
    expect(formatPercent(null)).toBe(NOT_MEASURED);
  });
});

describe('formatDate / formatDateTime', () => {
  it('formats an ISO date', () => {
    expect(formatDate('2026-08-14T12:00:00Z')).toBe('Aug 14, 2026');
  });
  it('includes time in formatDateTime', () => {
    expect(formatDateTime('2026-08-14T12:00:00Z')).toMatch(/Aug 14, 2026/);
  });
  it('returns empty string for absent or invalid input', () => {
    expect(formatDate(null)).toBe('');
    expect(formatDate('')).toBe('');
    expect(formatDate('garbage')).toBe('');
  });
});

describe('measured', () => {
  it('formats a present value', () => {
    expect(measured(120, v => `${v}h`)).toBe('120h');
    expect(measured(1500, v => `$${v.toLocaleString()}`)).toBe('$1,500');
  });

  it('distinguishes a measured zero from an absent value', () => {
    // 0 is a real measurement and must render as such...
    expect(measured(0, v => `${v}h`)).toBe('0h');
    // ...while null means "no basis to measure", never "saved nothing".
    expect(measured(null, v => `${v}h`)).toBe(NOT_MEASURED);
    expect(measured(undefined, v => `${v}h`)).toBe(NOT_MEASURED);
  });
});

describe('toPct', () => {
  it('scales a 0-1 ratio to a percentage', () => {
    expect(toPct(0.5)).toBe(50);
    expect(toPct(0.607)).toBeCloseTo(60.7);
  });

  it('passes an already-scaled percentage (>1) through unchanged', () => {
    expect(toPct(87)).toBe(87);
    expect(toPct(100)).toBe(100);
  });

  it('returns null for null, undefined, or NaN', () => {
    expect(toPct(null)).toBeNull();
    expect(toPct(undefined)).toBeNull();
    expect(toPct(NaN)).toBeNull();
  });

  it('treats exactly 1 as a ratio (edge)', () => {
    expect(toPct(1)).toBe(100);
  });
});

describe('humanize', () => {
  it('title-cases snake_case tokens', () => {
    expect(humanize('safe_autonomy_rate')).toBe('Safe Autonomy Rate');
  });

  it('keeps known acronyms uppercase', () => {
    expect(humanize('HITL_PENDING')).toBe('HITL Pending');
    expect(humanize('ooda_loop')).toBe('OODA Loop');
  });

  it('splits camelCase and kebab-case and dotted tokens', () => {
    expect(humanize('routeType')).toBe('Route Type');
    expect(humanize('gate.pre_approved')).toBe('Gate Pre Approved');
    expect(humanize('kebab-case')).toBe('Kebab Case');
  });

  it('returns empty string for null, undefined, or blank', () => {
    expect(humanize(null)).toBe('');
    expect(humanize(undefined)).toBe('');
    expect(humanize('   ')).toBe('');
  });
});
