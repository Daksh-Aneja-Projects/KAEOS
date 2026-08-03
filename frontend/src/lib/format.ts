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
