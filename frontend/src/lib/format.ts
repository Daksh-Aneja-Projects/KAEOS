/**
 * Normalize a score that may arrive as a ratio (0-1) or an already-scaled
 * percentage (0-100) into a 0-100 percentage. Backend endpoints are not
 * consistent about the scale, so render through this everywhere.
 */
export function toPct(value: number | null | undefined): number | null {
  if (value == null || Number.isNaN(value)) return null;
  return value > 1 ? value : value * 100;
}

/**
 * Copy shown wherever the backend returns null because a figure cannot be
 * measured (rather than because it measured out at zero). Rendering `|| 0` in
 * those slots is the bug this exists to prevent: "0h" reads as "we measured it
 * and it saved nothing", which is a claim the platform has not earned.
 */
export const NOT_MEASURED = 'Not measured';

/**
 * Format a possibly-null measured value for display.
 *
 * Returns `NOT_MEASURED` when the value is absent, and the formatted value
 * otherwise. Use for any field the backend may null out on purpose
 * (hours saved, cost saved, and anything else needing a tenant baseline).
 *
 *   measured(120, v => `${v}h`)   -> "120h"
 *   measured(0,   v => `${v}h`)   -> "0h"       (a real, measured zero)
 *   measured(null, v => `${v}h`)  -> "Not measured"
 */
export function measured<T>(
  value: T | null | undefined,
  format: (v: T) => string,
): string {
  if (value == null) return NOT_MEASURED;
  return format(value);
}

/* ═══════════════════════════════════════════════════════════════
   Intl formatting. One place to format money, numbers, percents and
   dates so we never surface `toFixed`/`toLocaleString` drift (grouping,
   currency symbol, locale) inconsistently across the app. Uses the
   viewer's locale by default; money defaults to USD (the platform's
   settlement currency) and is overridable per call.
   ═══════════════════════════════════════════════════════════════ */

const _currencyFmt = new Map<string, Intl.NumberFormat>();
const _num0 = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });
const _compact = new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 });

function _num(v: unknown): number | null {
  if (v == null || v === '') return null;
  const n = typeof v === 'number' ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n : null;
}

/**
 * Money via Intl currency formatting. Accepts number | numeric string
 * (backend sends Decimal money as a string). Returns NOT_MEASURED when the
 * value is genuinely absent, so this respects the honesty contract.
 *
 *   formatCurrency(1500.5)          -> "$1,500.50"
 *   formatCurrency("1200000", 'EUR')-> "€1,200,000.00"
 *   formatCurrency(null)            -> "Not measured"
 */
export function formatCurrency(
  value: unknown,
  currency = 'USD',
  opts?: Intl.NumberFormatOptions,
): string {
  const n = _num(value);
  if (n == null) return NOT_MEASURED;
  const key = currency + JSON.stringify(opts ?? {});
  let fmt = _currencyFmt.get(key);
  if (!fmt) {
    fmt = new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency,
      minimumFractionDigits: 2,
      ...opts,
    });
    _currencyFmt.set(key, fmt);
  }
  return fmt.format(n);
}

/**
 * Grouped number. `digits` sets the fraction length (default: integer).
 *   formatNumber(12345)      -> "12,345"
 *   formatNumber(3.14159, 2) -> "3.14"
 */
export function formatNumber(value: unknown, digits?: number): string {
  const n = _num(value);
  if (n == null) return NOT_MEASURED;
  if (digits == null) return _num0.format(n);
  return new Intl.NumberFormat(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(n);
}

/** Compact number for tight cells: 1_200_000 -> "1.2M". */
export function formatCompact(value: unknown): string {
  const n = _num(value);
  if (n == null) return NOT_MEASURED;
  return _compact.format(n);
}

/**
 * Percent from a 0-100 scale (this app's convention; run values through
 * `toPct` first if they may be 0-1 ratios).
 *   formatPercent(87.5)    -> "88%"
 *   formatPercent(87.5, 1) -> "87.5%"
 */
export function formatPercent(value: unknown, digits = 0): string {
  const n = _num(value);
  if (n == null) return NOT_MEASURED;
  return new Intl.NumberFormat(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(n) + '%';
}

/** Locale date, no time. `2026-08-14` -> "Aug 14, 2026". */
export function formatDate(
  value?: string | number | Date | null,
  opts: Intl.DateTimeFormatOptions = { year: 'numeric', month: 'short', day: 'numeric' },
): string {
  if (value == null || value === '') return '';
  const d = value instanceof Date ? value : new Date(value);
  if (isNaN(d.getTime())) return '';
  return new Intl.DateTimeFormat(undefined, opts).format(d);
}

/** Locale date + time. */
export function formatDateTime(value?: string | number | Date | null): string {
  return formatDate(value, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

/**
 * Turn a raw enum / code token into human copy. Backend statuses, types, and
 * routes arrive as SNAKE_CASE / kebab-case / camelCase / dotted tokens; never
 * surface those to a person. "HITL_PENDING" -> "HITL Pending",
 * "safe_autonomy_rate" -> "Safe Autonomy Rate", null -> "".
 *
 * Known acronyms stay uppercase so we don't render "Hitl" or "Ooda".
 */
const ACRONYMS = new Set([
  'HITL', 'OODA', 'KAEOS', 'AEOS', 'API', 'ID', 'URL', 'SSO', 'SAML', 'CRM',
  'PII', 'RBAC', 'RLS', 'MCP', 'LLM', 'ROI', 'KPI', 'SLA', 'IT', 'HR', 'AI',
  'UI', 'UX', 'PDF', 'CSV', 'JSON', 'SQL', 'CEO', 'CFO', 'CTO', 'COO', 'B2B',
  'NDA', 'GDPR', 'SOC', 'SOX', 'HIPAA', 'ML', 'SRE', 'VP',
]);

export function humanize(s: string | null | undefined): string {
  if (s == null) return '';
  const str = String(s).trim();
  if (!str) return '';
  return str
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2') // split camelCase / PascalCase
    .replace(/[_\-.]+/g, ' ')               // separators -> spaces
    .split(/\s+/)
    .filter(Boolean)
    .map(w => {
      const up = w.toUpperCase();
      if (ACRONYMS.has(up)) return up;
      return up.charAt(0) + w.slice(1).toLowerCase();
    })
    .join(' ');
}
