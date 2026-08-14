import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { timeAgo, fullTime, formatDuration } from './time';

// Pin "now" so relative output is deterministic.
const NOW = new Date('2026-07-25T12:00:00.000Z');

describe('timeAgo', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns the placeholder for empty or invalid input', () => {
    expect(timeAgo(null)).toBe('--');
    expect(timeAgo(undefined)).toBe('--');
    expect(timeAgo('')).toBe('--');
    expect(timeAgo('not a date')).toBe('--');
  });

  it('renders very recent past as "just now" (under 45s)', () => {
    expect(timeAgo(new Date(NOW.getTime() - 10_000))).toBe('just now');
    expect(timeAgo(new Date(NOW.getTime() - 44_000))).toBe('just now');
  });

  it('renders minutes for the past hour', () => {
    expect(timeAgo(new Date(NOW.getTime() - 5 * 60_000))).toBe('5m ago');
    expect(timeAgo(new Date(NOW.getTime() - 59 * 60_000))).toBe('59m ago');
  });

  it('renders hours for the past day', () => {
    expect(timeAgo(new Date(NOW.getTime() - 3 * 3_600_000))).toBe('3h ago');
  });

  it('renders days for the past month', () => {
    expect(timeAgo(new Date(NOW.getTime() - 4 * 86_400_000))).toBe('4d ago');
  });

  it('falls back to a locale date beyond 30 days', () => {
    const old = new Date(NOW.getTime() - 60 * 86_400_000);
    expect(timeAgo(old)).toBe(
      old.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }),
    );
  });

  it('renders future timestamps with the "in" prefix', () => {
    expect(timeAgo(new Date(NOW.getTime() + 30_000))).toBe('in moments');
    expect(timeAgo(new Date(NOW.getTime() + 10 * 60_000))).toBe('in 10m');
    expect(timeAgo(new Date(NOW.getTime() + 5 * 3_600_000))).toBe('in 5h');
    expect(timeAgo(new Date(NOW.getTime() + 3 * 86_400_000))).toBe('in 3d');
  });

  it('accepts epoch millis and ISO strings, not only Date objects', () => {
    expect(timeAgo(NOW.getTime() - 5 * 60_000)).toBe('5m ago');
    expect(timeAgo(new Date(NOW.getTime() - 2 * 3_600_000).toISOString())).toBe('2h ago');
  });
});

describe('fullTime', () => {
  it('returns an empty string for empty or invalid input', () => {
    expect(fullTime(null)).toBe('');
    expect(fullTime(undefined)).toBe('');
    expect(fullTime('garbage')).toBe('');
  });

  it('formats a valid timestamp with date and minutes, no seconds', () => {
    const d = new Date('2026-07-16T16:48:21.234Z');
    expect(fullTime(d)).toBe(
      d.toLocaleString(undefined, {
        year: 'numeric', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit',
      }),
    );
    // The whole point: no raw microseconds leak through.
    expect(fullTime(d)).not.toContain('234');
  });
});

describe('formatDuration', () => {
  it('collapses missing/negative/NaN to 0s', () => {
    expect(formatDuration(null)).toBe('0s');
    expect(formatDuration(undefined)).toBe('0s');
    expect(formatDuration(-5)).toBe('0s');
    expect(formatDuration(NaN)).toBe('0s');
  });

  it('shows the two most-significant units', () => {
    expect(formatDuration(45)).toBe('45s');
    expect(formatDuration(95)).toBe('1m 35s');
    expect(formatDuration(3661)).toBe('1h 1m');
    expect(formatDuration(172800)).toBe('2d 0h');
  });
});
