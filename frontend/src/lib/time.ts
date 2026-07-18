/**
 * Human time.
 *
 * Tables were rendering raw DB timestamps - `2026-07-16 16:48:21.234799+00:00`
 * - truncated mid-string in a narrow column. Nobody reads microseconds.
 */

export function timeAgo(value?: string | number | Date | null): string {
  if (!value) return '--';
  const d = value instanceof Date ? value : new Date(value);
  if (isNaN(d.getTime())) return '--';

  const secs = (Date.now() - d.getTime()) / 1000;
  if (secs < 0) {
    const ahead = Math.abs(secs);
    if (ahead < 60) return 'in moments';
    if (ahead < 3600) return `in ${Math.round(ahead / 60)}m`;
    if (ahead < 86400) return `in ${Math.round(ahead / 3600)}h`;
    return `in ${Math.round(ahead / 86400)}d`;
  }
  if (secs < 45) return 'just now';
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
  if (secs < 2592000) return `${Math.round(secs / 86400)}d ago`;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

/** Full timestamp for a tooltip - precise on demand, never in the cell. */
export function fullTime(value?: string | number | Date | null): string {
  if (!value) return '';
  const d = value instanceof Date ? value : new Date(value);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}
