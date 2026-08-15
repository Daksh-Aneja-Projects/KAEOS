import { describe, it, expect } from 'vitest';
import {
  DEPT_PALETTE, fitDeptLabel, DEPT_LABEL_BASE_FONT, DEPT_LABEL_MIN_FONT,
  DEPT_LABEL_LETTER_SPACING, DEPT_LABEL_CHAR_WIDTH,
} from './TwinGraph.layout';
import { DEPARTMENT_LABELS } from '../lib/departments';

// Same width formula fitDeptLabel fits against - used here only to verify
// its output, never to duplicate its logic.
const renderedHalfWidth = (len: number, fontSize: number) =>
  (len * DEPT_LABEL_CHAR_WIDTH * fontSize + Math.max(0, len - 1) * DEPT_LABEL_LETTER_SPACING) / 2;

describe('DEPT_PALETTE', () => {
  it('has at least 10 distinct hues, one per shipped department', () => {
    expect(DEPT_PALETTE.length).toBeGreaterThanOrEqual(10);
    expect(new Set(DEPT_PALETTE).size).toBe(DEPT_PALETTE.length);
  });
});

describe('fitDeptLabel', () => {
  it('keeps the base font when the budget is generous', () => {
    const { fontSize, maxChars } = fitDeptLabel('Finance', 200);
    expect(fontSize).toBe(DEPT_LABEL_BASE_FONT);
    expect(maxChars).toBe(Infinity);
  });

  it('shrinks the font before truncating when a name almost fits', () => {
    // 'Procurement' (11 chars) overflows a 36-unit half-width budget at base
    // font but still fits by shrinking alone.
    const { fontSize, maxChars } = fitDeptLabel('Procurement', 36);
    expect(fontSize).toBeLessThan(DEPT_LABEL_BASE_FONT);
    expect(fontSize).toBeGreaterThanOrEqual(DEPT_LABEL_MIN_FONT);
    expect(maxChars).toBe(Infinity);
  });

  it('truncates with an ellipsis only once the floor font still overflows', () => {
    // 'Engineering & IT Ops' (20 chars) - the confirmed worst case at 10
    // departments in the Neural Map's fixed-width horizontal band.
    const { fontSize, maxChars } = fitDeptLabel('Engineering & IT Ops', 36);
    expect(fontSize).toBe(DEPT_LABEL_MIN_FONT);
    expect(maxChars).toBeLessThan('Engineering & IT Ops'.length);
    expect(maxChars).toBeGreaterThanOrEqual(3);
  });

  it('never returns a size below the legibility floor', () => {
    const { fontSize } = fitDeptLabel('A Very Long Department Name Indeed', 10);
    expect(fontSize).toBeGreaterThanOrEqual(DEPT_LABEL_MIN_FONT);
  });

  it('proves every real 10-department name fits its slot with zero overlap '
    + 'at the Neural Map worst-case (TWIN_W=960, margin=60, 10 departments)', () => {
    const TWIN_W = 960, margin = 60, n = 10;
    const slot = (TWIN_W - margin * 2) / n; // 84
    const budget = Math.max(20, slot / 2 - 6); // 36, mirrors TwinGraph.tsx's gutter

    for (const name of Object.values(DEPARTMENT_LABELS)) {
      const { fontSize, maxChars } = fitDeptLabel(name.toUpperCase(), budget);
      const shown = Math.min(name.length, maxChars);
      const half = renderedHalfWidth(shown, fontSize);
      expect(fontSize).toBeGreaterThanOrEqual(DEPT_LABEL_MIN_FONT);
      // Half-width must stay inside the budget - i.e. inside its own slot -
      // so it can never reach a neighboring department's label.
      expect(half).toBeLessThanOrEqual(budget + 0.1);
    }
  });
});
