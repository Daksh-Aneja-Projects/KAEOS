import { describe, it, expect } from 'vitest';
import {
  DEPARTMENTS, DEPARTMENT_LABELS, DEPARTMENT_COLORS, canSeeDepartment,
} from './departments';

describe('canSeeDepartment', () => {
  it('org-wide users (null/undefined scope) see every department', () => {
    for (const d of DEPARTMENTS) {
      expect(canSeeDepartment(null, d)).toBe(true);
      expect(canSeeDepartment(undefined, d)).toBe(true);
    }
  });

  it('scoped users see only their own department', () => {
    expect(canSeeDepartment('hr', 'hr')).toBe(true);
    expect(canSeeDepartment('hr', 'finance')).toBe(false);
    expect(canSeeDepartment('engineering', 'engineering')).toBe(true);
    expect(canSeeDepartment('engineering', 'sales')).toBe(false);
  });

  it('surfaces without a department slug are visible to everyone', () => {
    expect(canSeeDepartment('hr', null)).toBe(true);
    expect(canSeeDepartment('hr', undefined)).toBe(true);
    expect(canSeeDepartment(null, null)).toBe(true);
  });
});

describe('department metadata', () => {
  it('covers all backend-valid departments', () => {
    expect([...DEPARTMENTS].sort()).toEqual(
      ['engineering', 'finance', 'healthcare', 'hr', 'legal', 'lending',
       'operations', 'procurement', 'sales', 'support'],
    );
  });

  it('has a label and a color for every department', () => {
    for (const d of DEPARTMENTS) {
      expect(DEPARTMENT_LABELS[d]).toBeTruthy();
      expect(DEPARTMENT_COLORS[d]).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });
});
