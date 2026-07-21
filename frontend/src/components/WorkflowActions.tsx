import React, { useState } from 'react';
import { ChevronRight, History, Loader2 } from 'lucide-react';
import { api } from '../api/client';
import type { WorkflowEvent } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { timeAgo } from '../lib/time';

/**
 * Renders the allowed next-state buttons for one entity row, driven by the
 * domain's declared workflow spec (GET /{domain}/workflows), plus a history
 * toggle that loads the entity's transition audit trail on demand. Clicking a
 * state POSTs to /{domain}/{entityPath}/{id}/transition — the backend engine
 * validates the move (map, role floor, business guards), stamps side-effects
 * and writes the audit trail.
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
  const [history, setHistory] = useState<WorkflowEvent[] | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);

  const allowed = transitions?.[(currentState || '').toUpperCase()] || [];

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

  const toggleHistory = async () => {
    if (showHistory) { setShowHistory(false); return; }
    setShowHistory(true);
    if (history === null) {
      setLoadingHistory(true);
      try {
        setHistory(await api.getWorkflowEvents(domain, { entity_id: entityId }));
      } catch {
        setHistory([]);
      } finally {
        setLoadingHistory(false);
      }
    }
  };

  return (
    <div>
      <div className="flex gap-1 flex-wrap items-center">
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
        <button onClick={toggleHistory} title="Transition history"
          className="p-1 rounded-md"
          style={{ color: showHistory ? colors.primary : colors.inkTertiary }}>
          <History className="w-3 h-3" />
        </button>
      </div>

      {showHistory && (
        <div className="mt-1.5 rounded-lg p-2 space-y-1 min-w-[210px]"
          style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
          {loadingHistory && <Loader2 className="w-3 h-3 animate-spin" style={{ color: colors.inkSubtle }} />}
          {!loadingHistory && (history || []).length === 0 && (
            <p className="text-[10px]" style={{ color: colors.inkTertiary }}>No transitions recorded yet.</p>
          )}
          {(history || []).map(e => (
            <div key={e.id} className="flex items-center gap-1.5 text-[10px]">
              <span className="font-mono whitespace-nowrap" style={{ color: colors.inkSubtle }}>
                {e.from_state} → <span style={{ color: STATE_COLORS[e.to_state] || colors.ink }}>{e.to_state}</span>
              </span>
              <span className="ml-auto whitespace-nowrap" style={{ color: colors.inkTertiary }}>
                {e.actor ? `${e.actor} · ` : ''}{timeAgo(e.at)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default WorkflowActions;
