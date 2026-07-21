import React, { useState } from 'react';
import { ChevronRight, Loader2 } from 'lucide-react';
import { api } from '../api/client';
import { useTheme } from '../context/ThemeContext';

/**
 * Renders the allowed next-state buttons for one entity row, driven by the
 * domain's declared workflow spec (GET /{domain}/workflows). Clicking a state
 * POSTs to /{domain}/{entityPath}/{id}/transition — the backend engine
 * validates the move, stamps side-effects and writes the audit trail.
 */

const STATE_COLORS: Record<string, string> = {
  APPROVED: '#22c55e', RESOLVED: '#22c55e', CLOSED_WON: '#22c55e', PAID: '#22c55e',
  ACTIVE: '#22c55e', SIGNED: '#22c55e', RECEIVED: '#22c55e', SUCCEEDED: '#22c55e', HIRED: '#22c55e',
  REJECTED: '#ef4444', DENIED: '#ef4444', CLOSED_LOST: '#ef4444', VOIDED: '#ef4444',
  CANCELLED: '#ef4444', TERMINATED: '#ef4444', FAILED: '#ef4444', DISPUTED: '#ef4444',
  CLOSED: '#64748b', EXPIRED: '#64748b', ROLLED_BACK: '#f59e0b',
};

interface Props {
  domain: string;          // e.g. "support"
  entityPath: string;      // e.g. "tickets"
  entityId: string;
  currentState: string;
  transitions: Record<string, string[]> | undefined; // spec.transitions
  onDone: (msg: string) => void;   // refresh callback with a status message
  onError?: (msg: string) => void;
}

const WorkflowActions: React.FC<Props> = ({ domain, entityPath, entityId, currentState, transitions, onDone, onError }) => {
  const { colors } = useTheme();
  const [busy, setBusy] = useState<string | null>(null);

  const allowed = transitions?.[(currentState || '').toUpperCase()] || [];
  if (!allowed.length) return null;

  const go = async (to: string) => {
    setBusy(to);
    try {
      const res = await api.transitionEntity(domain, entityPath, entityId, to);
      onDone(`${res.entity_type.replace(/_/g, ' ')} moved ${res.from_state} → ${res.to_state}`);
    } catch (e: any) {
      (onError || onDone)(`Transition failed: ${e?.message || e}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex gap-1 flex-wrap">
      {allowed.map(state => {
        const color = STATE_COLORS[state] || '#6366f1';
        return (
          <button key={state} onClick={() => go(state)} disabled={!!busy}
            title={`Move to ${state}`}
            className="flex items-center gap-0.5 px-2 py-1 rounded-md text-[10px] font-semibold disabled:opacity-50 whitespace-nowrap"
            style={{ background: `${color}15`, color }}>
            {busy === state ? <Loader2 className="w-3 h-3 animate-spin" /> : <ChevronRight className="w-3 h-3" />}
            {state.replace(/_/g, ' ')}
          </button>
        );
      })}
    </div>
  );
};

export default WorkflowActions;
