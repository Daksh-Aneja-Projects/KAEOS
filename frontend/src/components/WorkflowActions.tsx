import React, { useState } from 'react';
import { ChevronRight, History, Loader2, MessageSquare, UserPlus } from 'lucide-react';
import { api } from '../api/client';
import type { EntityComment, WorkflowEvent } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { timeAgo } from '../lib/time';

/**
 * Per-row workflow controls: allowed next-state buttons (from the domain's
 * declared spec), plus on-demand panels for the transition history, ownership
 * assignment, and the comment thread - all keyed off the same entity. Every
 * mutation flows through the guarded backend engine (transition map, role
 * floors, guards, audit).
 */

const STATE_COLORS: Record<string, string> = {
  APPROVED: '#22c55e', RESOLVED: '#22c55e', CLOSED_WON: '#22c55e', PAID: '#22c55e',
  ACTIVE: '#22c55e', SIGNED: '#22c55e', RECEIVED: '#22c55e', SUCCEEDED: '#22c55e', HIRED: '#22c55e',
  REJECTED: '#ef4444', DENIED: '#ef4444', CLOSED_LOST: '#ef4444', VOIDED: '#ef4444',
  CANCELLED: '#ef4444', TERMINATED: '#ef4444', FAILED: '#ef4444', DISPUTED: '#ef4444',
  CLOSED: '#64748b', EXPIRED: '#64748b', ROLLED_BACK: '#f59e0b',
};

// URL path segment -> workflow entity_type used by the collaboration endpoints.
const PATH_TO_ENTITY: Record<string, string> = {
  tickets: 'ticket', opportunities: 'opportunity', contracts: 'contract',
  'purchase-requests': 'purchase_request', 'purchase-orders': 'purchase_order',
  invoices: 'invoice', 'expense-reports': 'expense_report',
  incidents: 'incident', deployments: 'deployment',
  'time-off-requests': 'time_off_request', requisitions: 'job_requisition',
};

interface Props {
  domain: string;
  entityPath: string;      // e.g. "tickets"
  entityId: string;
  currentState: string;
  transitions: Record<string, string[]> | undefined;
  onDone: (msg: string) => void;
  onError?: (msg: string) => void;
}

const WorkflowActions: React.FC<Props> = ({ domain, entityPath, entityId, currentState, transitions, onDone, onError }) => {
  const { colors } = useTheme();
  const entityType = PATH_TO_ENTITY[entityPath] || entityPath;

  const [busy, setBusy] = useState<string | null>(null);
  const [panel, setPanel] = useState<'history' | 'assign' | 'comments' | null>(null);

  const [history, setHistory] = useState<WorkflowEvent[] | null>(null);
  const [assignee, setAssignee] = useState('');
  const [assignBusy, setAssignBusy] = useState(false);
  const [comments, setComments] = useState<EntityComment[] | null>(null);
  const [newComment, setNewComment] = useState('');
  const [commentBusy, setCommentBusy] = useState(false);

  const allowed = transitions?.[(currentState || '').toUpperCase()] || [];

  const go = async (to: string) => {
    setBusy(to);
    try {
      const res = await api.transitionEntity(domain, entityPath, entityId, to);
      onDone(`${res.entity_type.replace(/_/g, ' ')} moved ${res.from_state} → ${res.to_state}`);
    } catch (e: any) {
      (onError || onDone)(`Transition failed: ${e?.message || e}`);
    } finally { setBusy(null); }
  };

  const openPanel = async (p: 'history' | 'assign' | 'comments') => {
    if (panel === p) { setPanel(null); return; }
    setPanel(p);
    if (p === 'history' && history === null) {
      try { setHistory(await api.getWorkflowEvents(domain, { entity_id: entityId })); }
      catch { setHistory([]); }
    }
    if (p === 'comments' && comments === null) {
      try { setComments(await api.getComments(entityType, entityId)); }
      catch { setComments([]); }
    }
  };

  const saveAssignee = async () => {
    if (!assignee.trim()) return;
    setAssignBusy(true);
    try {
      await api.assignEntity(entityType, entityId, assignee.trim());
      onDone(`Assigned to ${assignee.trim()}`);
      setPanel(null); setAssignee('');
    } catch (e: any) { (onError || onDone)(`Assign failed: ${e?.message || e}`); }
    finally { setAssignBusy(false); }
  };

  const postComment = async () => {
    if (!newComment.trim()) return;
    setCommentBusy(true);
    try {
      const c = await api.addComment(entityType, entityId, newComment.trim());
      setComments(prev => [...(prev || []), c]);
      setNewComment('');
    } catch (e: any) { (onError || onDone)(`Comment failed: ${e?.message || e}`); }
    finally { setCommentBusy(false); }
  };

  const iconBtn = (active: boolean) =>
    ({ color: active ? colors.primary : colors.inkTertiary } as React.CSSProperties);

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
        <button onClick={() => openPanel('history')} title="Transition history" className="p-1 rounded-md" style={iconBtn(panel === 'history')}>
          <History className="w-3 h-3" />
        </button>
        <button onClick={() => openPanel('assign')} title="Assign" className="p-1 rounded-md" style={iconBtn(panel === 'assign')}>
          <UserPlus className="w-3 h-3" />
        </button>
        <button onClick={() => openPanel('comments')} title="Comments" className="p-1 rounded-md" style={iconBtn(panel === 'comments')}>
          <MessageSquare className="w-3 h-3" />
        </button>
      </div>

      {panel === 'history' && (
        <div className="mt-1.5 rounded-lg p-2 space-y-1 min-w-[210px]"
          style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
          {history === null && <Loader2 className="w-3 h-3 animate-spin" style={{ color: colors.inkSubtle }} />}
          {history !== null && history.length === 0 && (
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

      {panel === 'assign' && (
        <div className="mt-1.5 rounded-lg p-2 flex items-center gap-1.5 min-w-[220px]"
          style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
          <input value={assignee} onChange={e => setAssignee(e.target.value)}
            placeholder="assignee (email or name)" onKeyDown={e => e.key === 'Enter' && saveAssignee()}
            className="flex-1 px-2 py-1 rounded text-[11px] focus:outline-none"
            style={{ background: colors.surface1, border: `1px solid ${colors.hairline}`, color: colors.ink }} />
          <button onClick={saveAssignee} disabled={assignBusy}
            className="px-2 py-1 rounded text-[10px] font-semibold text-white disabled:opacity-50"
            style={{ background: colors.primary }}>
            {assignBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Assign'}
          </button>
        </div>
      )}

      {panel === 'comments' && (
        <div className="mt-1.5 rounded-lg p-2 space-y-1.5 min-w-[240px]"
          style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
          {comments === null && <Loader2 className="w-3 h-3 animate-spin" style={{ color: colors.inkSubtle }} />}
          {comments !== null && comments.length === 0 && (
            <p className="text-[10px]" style={{ color: colors.inkTertiary }}>No comments yet.</p>
          )}
          {(comments || []).map(c => (
            <div key={c.id} className="text-[10px]">
              <span className="font-semibold" style={{ color: colors.ink }}>{c.author}</span>
              <span className="ml-1" style={{ color: colors.inkTertiary }}>{timeAgo(c.at)}</span>
              <p style={{ color: colors.inkSubtle }}>{c.body}</p>
            </div>
          ))}
          <div className="flex items-center gap-1.5 pt-1">
            <input value={newComment} onChange={e => setNewComment(e.target.value)}
              placeholder="add a note… @mention supported" onKeyDown={e => e.key === 'Enter' && postComment()}
              className="flex-1 px-2 py-1 rounded text-[11px] focus:outline-none"
              style={{ background: colors.surface1, border: `1px solid ${colors.hairline}`, color: colors.ink }} />
            <button onClick={postComment} disabled={commentBusy}
              className="px-2 py-1 rounded text-[10px] font-semibold text-white disabled:opacity-50"
              style={{ background: colors.primary }}>
              {commentBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Post'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default WorkflowActions;
