/**
 * Normalize a score that may arrive as a ratio (0-1) or an already-scaled
 * percentage (0-100) into a 0-100 percentage. Backend endpoints are not
 * consistent about the scale, so render through this everywhere.
 */
export function toPct(value: number | null | undefined): number | null {
  if (value == null || Number.isNaN(value)) return null;
  return value > 1 ? value : value * 100;
}
