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
