import { useMemo, useState } from 'react';
import type { WorkflowSpec } from '../api/client';

/**
 * Shared multi-select + bulk-transition state for the domain views.
 *
 * Given the rows on screen and the workflow spec, it exposes selection
 * helpers and — critically — `bulkAllowed`: the set of target states that are
 * legal for EVERY selected row (the intersection of each row's allowed
 * transitions). Offering a state that only some rows can reach would half-fail
 * a bulk action, so the bar only shows moves that apply to all of them.
 *
 * `statusOf` lets callers point at whichever field holds the state
 * (status vs. stage) without the hook knowing the row shape.
 */
export function useBulkSelect<T extends { id: string }>(
  rows: T[],
  spec: WorkflowSpec | undefined,
  statusOf: (row: T) => string,
) {
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const toggle = (id: string) =>
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });

  const clear = () => setSelected(new Set());

  const allSelected = rows.length > 0 && selected.size === rows.length;
  const setAll = (on: boolean) => setSelected(on ? new Set(rows.map(r => r.id)) : new Set());

  const bulkAllowed = useMemo(() => {
    const map = spec?.transitions;
    if (!map || selected.size === 0) return [] as string[];
    const picked = rows.filter(r => selected.has(r.id));
    let common: string[] | null = null;
    for (const r of picked) {
      const allowed = map[(statusOf(r) || '').toUpperCase()] || [];
      common = common === null ? allowed : common.filter(s => allowed.includes(s));
    }
    return common || [];
  }, [rows, spec, selected, statusOf]);

  return {
    selected, ids: Array.from(selected), size: selected.size,
    toggle, clear, allSelected, setAll, bulkAllowed,
    isSelected: (id: string) => selected.has(id),
  };
}
