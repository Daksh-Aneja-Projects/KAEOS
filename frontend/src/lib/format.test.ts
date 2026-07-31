import { describe, it, expect } from 'vitest';
import { toPct, humanize } from './format';

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
