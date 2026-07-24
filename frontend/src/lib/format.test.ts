import { describe, it, expect } from 'vitest';
import { toPct } from './format';

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
