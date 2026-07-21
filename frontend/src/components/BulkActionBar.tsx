import React, { useState } from 'react';
import { Loader2 } from 'lucide-react';
import { api } from '../api/client';
import { useTheme } from '../context/ThemeContext';

/**
 * The floating bar that appears when rows are multi-selected in a domain view.
 * Renders one button per state that is legal for EVERY selected row (computed
 * by useBulkSelect) and fires the bulk-transition endpoint, then reports a
 * per-outcome summary. Shared across all 7 domain views.
 */

interface Props {
  domain: string;
  entityType: string;      // workflow key, e.g. "ticket", "opportunity"
  ids: string[];
  count: number;
  bulkAllowed: string[];
  onDone: (msg: string) => void;   // refresh callback
  onClear: () => void;
  noun?: string;           // "ticket", "deal" — for the empty-intersection hint
}

const BulkActionBar: React.FC<Props> = ({ domain, entityType, ids, count, bulkAllowed, onDone, onClear, noun = 'row' }) => {
  const { colors } = useTheme();
  const [busy, setBusy] = useState<string | null>(null);

  if (count === 0) return null;

  const run = async (state: string) => {
    setBusy(state);
    try {
      const res = await api.bulkTransition(domain, entityType, ids, state);
      onDone(`Bulk ${state.replace(/_/g, ' ')}: ${res.succeeded} succeeded${res.failed ? `, ${res.failed} failed` : ''}`);
      onClear();
    } catch (e: any) {
      onDone(`Bulk transition failed: ${e?.message || e}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex items-center gap-2 px-4 py-2.5 rounded-lg flex-wrap"
      style={{ background: `${colors.primary}12`, border: `1px solid ${colors.primary}30` }}>
      <span className="text-[12px] font-semibold" style={{ color: colors.ink }}>{count} selected</span>
      {bulkAllowed.map(state => (
        <button key={state} onClick={() => run(state)} disabled={!!busy}
          className="flex items-center gap-1 px-2.5 py-1.5 rounded-md text-[11px] font-semibold disabled:opacity-50"
          style={{ background: `${colors.primary}18`, color: colors.primary }}>
          {busy === state ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
          Move all to {state.replace(/_/g, ' ')}
        </button>
      ))}
      {bulkAllowed.length === 0 && (
        <span className="text-[11px]" style={{ color: colors.inkSubtle }}>
          No transition is legal for every selected {noun} — narrow the selection.
        </span>
      )}
      <button onClick={onClear} className="ml-auto text-[11px] font-medium" style={{ color: colors.inkSubtle }}>
        Clear
      </button>
    </div>
  );
};

export default BulkActionBar;
