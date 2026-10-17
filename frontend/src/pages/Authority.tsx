import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  PenLine, Loader2, Lock, Unlock, ChevronDown, ChevronUp, Check, X, ArrowRight, Share2, Ban, Sparkles,
  PauseCircle, PlayCircle, KeyRound, History, Undo2, Users, Download, Plus,
} from 'lucide-react';
import { Link } from 'react-router';
import { api } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { useAuth } from '../context/AuthContext';
import { BrainLoading, BrainError, BrainEmpty, RefreshFailed } from '../components/BrainStates';
import { EnterpriseNotice } from '../components/EnterpriseNotice';
import { useEnterprisePanel as usePanel } from '../hooks/useEnterprisePanel';
import { humanize } from '../lib/format';
import { timeAgo } from '../lib/time';
import { PAGE_PAD } from '../lib/layout';
import { DEPARTMENTS, DEPARTMENT_LABELS, type DepartmentSlug } from '../lib/departments';
import AuthorityBalance from './AuthorityBalance';

/**
 * Authority: what runs under your name, and on whose signature.
 *
 * A person lends their own signature to the machine, scoped and limited, and
 * every sealed proof names the basis it ran on. Honesty contract: every number
 * on this page comes from the Authority routes. A value the record does not
 * hold reads "Not measured"; on open core the routes answer 402 with a plain
 * sentence and the page shows that sentence.
 */

// ── Plain-English translations ────────────────────────────────────────────────

const TIER_LABEL: Record<string, string> = {
  observe: 'Observe', advise: 'Advise', act_with_approval: 'Act with approval', autonomous: 'Autonomous',
};

const WINDOW_WORD: Record<string, string> = { day: 'a day', week: 'a week', month: 'a month' };

const USE_STATUS: Record<string, { label: string; tone: Tone }> = {
  reserved: { label: 'In flight', tone: 'primary' },
  used: { label: 'Used', tone: 'ok' },
  released: { label: 'Released (nothing happened)', tone: 'muted' },
  stale: { label: 'Refused at the write (authority revoked)', tone: 'bad' },
  unlent: { label: "Nobody's authority", tone: 'warn' },
};

const GRANT_STATE: Record<string, { label: string; tone: Tone }> = {
  active: { label: 'Active', tone: 'ok' },
  expired: { label: 'Expired', tone: 'muted' },
  revoked: { label: 'Revoked', tone: 'bad' },
  pending: { label: 'Waiting for acceptance', tone: 'warn' },
  suspended: { label: 'Suspended', tone: 'warn' },
  declined: { label: 'Declined', tone: 'muted' },
};

type Tone = 'ok' | 'warn' | 'bad' | 'muted' | 'primary';

const NOT_MEASURED = 'Not measured';

function moneyText(n: number | null | undefined, currency: string): string {
  if (n == null || !Number.isFinite(Number(n))) return NOT_MEASURED;
  return `${currency} ${Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function numText(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(Number(n))) return NOT_MEASURED;
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function deptLabel(slug: string | null | undefined): string {
  if (!slug) return '';
  return DEPARTMENT_LABELS[slug as DepartmentSlug] || humanize(slug);
}

function scopeWords(g: any): string {
  const s = g?.scope || {};
  const dept = deptLabel(s.department);
  const skills = Array.isArray(s.skills) && s.skills.length ? s.skills.map((x: string) => humanize(x)).join(', ') : '';
  const base = dept && skills ? `${dept}, ${skills}` : dept || skills || '';
  if (s.external_principal) {
    return base ? `${base}, for external agent ${s.external_principal}` : `For external agent ${s.external_principal}`;
  }
  return base || 'Any department';
}

function limitWords(g: any): string {
  const l = g?.limits || {};
  const cur = l.currency || '';
  const per = l.per_action, wa = l.window_amount, wc = l.window_actions;
  const win = WINDOW_WORD[l.window] || '';
  if (per == null && wa == null && wc == null) return 'No limits set';
  const items: string[] = [];
  if (wa != null) items.push(moneyText(wa, cur));
  if (wc != null) items.push(`${wc} action${Number(wc) === 1 ? '' : 's'}`);
  const winClause = items.length ? `${items.join(' and ')} ${win}`.trim() : null;
  const out: string[] = [];
  if (per != null) out.push(`Up to ${moneyText(per, cur)} per action`);
  else if (wa == null) out.push('No money limit');
  if (winClause) out.push(per == null && wa != null ? `Up to ${winClause}` : winClause);
  else out.push(`no limit ${win}`.trim());
  return out.join(', ');
}

/** The tripwire in plain words; empty when the server did not send the field at all. */
function tripwireWords(g: any): string {
  const n = g?.tripwire_adverse_runs;
  if (n === undefined) return '';
  if (n == null) return 'no tripwire';
  const win = WINDOW_WORD[g?.limits?.window] || WINDOW_WORD.day;
  return `trips after ${n} adverse run${Number(n) === 1 ? '' : 's'} ${win}`;
}

/** A calendar day from the record ("2026-10-03") as "Oct 3". */
function dayWord(day: string | null | undefined): string {
  if (!day) return '';
  const d = new Date(`${String(day).slice(0, 10)}T00:00:00Z`);
  if (!Number.isFinite(d.getTime())) return String(day);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' });
}

function secondsText(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(Number(n))) return NOT_MEASURED;
  const v = Number(n);
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} s`;
}

function pctText(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(Number(n))) return NOT_MEASURED;
  return `${Number(n).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
}

function relFuture(iso: string | null | undefined): string {
  if (!iso) return '';
  const ms = new Date(iso).getTime() - Date.now();
  if (!Number.isFinite(ms)) return '';
  if (ms <= 0) return 'now';
  const m = Math.round(ms / 60000);
  if (m < 60) return `in ${Math.max(m, 1)}m`;
  const h = Math.round(ms / 3600000);
  if (h < 24) return `in ${h}h`;
  const d = Math.round(ms / 86400000);
  return `in ${d} day${d === 1 ? '' : 's'}`;
}

function resetsText(iso: string | null | undefined): string {
  const r = relFuture(iso);
  return r ? (r === 'now' ? 'resets now' : `resets ${r}`) : '';
}

function expiryText(iso: string | null | undefined): string {
  if (!iso) return 'No expiry';
  const r = relFuture(iso);
  if (!r) return 'No expiry';
  return r === 'now' ? 'Expired' : `Expires ${r}`;
}

/** A moment from the record as a short local date and time. */
function whenText(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isFinite(d.getTime()) ? d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : String(iso);
}

/** How long a run's write can be undone, in words; empty when the server did not send the field. */
function undoWords(g: any): string[] {
  const out: string[] = [];
  if (g?.undo_window_hours === null) out.push('no undo');
  else if (g?.undo_window_hours !== undefined) out.push(`undo within ${numText(g.undo_window_hours)} h`);
  if (g?.reversible_only) out.push('reversible writes only');
  return out;
}

/** The undo assessment in plain English. */
function undoSentence(a: any): { text: string; tone: Tone } {
  const by = a?.reversed_by ? ` by ${a.reversed_by}` : '';
  switch (a?.state) {
    case 'available':
      return { text: a.deadline ? `Can be undone until ${whenText(a.deadline)}.` : 'Can be undone.', tone: 'ok' };
    case 'reversed':
      return { text: `Already undone${by}${a.reversed_at ? ` ${timeAgo(a.reversed_at)}` : ''}.`, tone: 'muted' };
    case 'expired':
      return { text: a.deadline ? `The undo window closed at ${whenText(a.deadline)}.` : 'The undo window has closed.', tone: 'muted' };
    case 'drifted':
      return { text: 'The record has changed since the write, so undoing would overwrite a change nobody reviewed.', tone: 'warn' };
    case 'not_reversible':
      return { text: 'This write cannot be undone.', tone: 'muted' };
    case 'no_write':
      return { text: 'This run performed no governed write.', tone: 'muted' };
    case 'no_undo_window':
      return { text: 'The grant behind this run had no undo window, so it cannot be undone.', tone: 'muted' };
    default:
      return { text: a?.state ? humanize(a.state) : NOT_MEASURED, tone: 'muted' };
  }
}

/** A list the server may send bare or wrapped under a key. */
function asList(d: any, key: string): any[] {
  if (Array.isArray(d)) return d;
  if (d && Array.isArray(d[key])) return d[key];
  return [];
}

/** One claim of a declared record: its value in words, or "Not measured" when it holds none. */
function claimValueText(c: any): string {
  const v = c && typeof c === 'object' && 'value' in c ? c.value : null;
  if (v == null) return NOT_MEASURED;
  if (typeof v === 'number') return numText(v);
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  if (typeof v === 'string') return v;
  try { return JSON.stringify(v); } catch { return NOT_MEASURED; }
}

function claimTitle(c: any): string | undefined {
  if (!c || typeof c !== 'object') return undefined;
  const why = c.reason ?? c.evidence;
  const text = why == null ? '' : typeof why === 'string' ? why : (() => { try { return JSON.stringify(why); } catch { return ''; } })();
  return [c.status ? humanize(c.status) : '', text].filter(Boolean).join(': ') || undefined;
}

function prefersReducedMotion(): boolean {
  try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch { return false; }
}

// ── Small shared pieces (this page owns its own, GovernedExecution exports none) ─

function Pill({ text, tone }: { text: string; tone: Tone }) {
  const { colors } = useTheme();
  const c = tone === 'ok' ? colors.success : tone === 'warn' ? colors.warning : tone === 'bad' ? colors.error
    : tone === 'primary' ? colors.primary : colors.inkSubtle;
  return (
    <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold whitespace-nowrap"
      style={{ background: c + '18', color: c, border: `1px solid ${c}30` }}>{text}</span>
  );
}

function Stat({ label, value, note }: { label: string; value: React.ReactNode; note?: string }) {
  const { colors } = useTheme();
  return (
    <div className="rounded-xl px-3.5 py-3 min-w-0" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      <div className="text-[11px] font-medium truncate" style={{ color: colors.inkSubtle }}>{label}</div>
      <div className="text-[22px] font-semibold mt-0.5 tabular-nums truncate" style={{ color: colors.ink }}>{value}</div>
      {note && <div className="text-[11px] mt-0.5 truncate" style={{ color: colors.inkTertiary }} title={note}>{note}</div>}
    </div>
  );
}

function SectionHead({ title, right }: { title: string; right?: React.ReactNode }) {
  const { colors } = useTheme();
  return (
    <div className="px-4 py-2.5 text-[11.5px] font-medium flex items-center justify-between gap-3"
      style={{ background: colors.surface2, color: colors.inkSubtle }}>
      <span>{title}</span>{right}
    </div>
  );
}

function GrantId({ id }: { id: string }) {
  const { colors } = useTheme();
  return <span className="font-mono text-[11px]" style={{ color: colors.inkTertiary }}>{String(id).slice(0, 8)}</span>;
}

/** Eased count-up toward `target`, driven by rAF; jumps straight there under reduced motion. */
function useAnimatedValue(target: number): number {
  const [value, setValue] = useState(0);
  const current = useRef(0);
  useEffect(() => {
    if (prefersReducedMotion()) { current.current = target; setValue(target); return; }
    const from = current.current;
    const t0 = performance.now();
    let raf = 0;
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / 700);
      const eased = 1 - Math.pow(1 - p, 3);
      const v = from + (target - from) * eased;
      current.current = v;
      setValue(v);
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target]);
  return value;
}

/** The signature element: how much of the authority lent out is reserved today. */
function ExposureRing({ fraction, caption }: { fraction: number; caption: string }) {
  const { colors } = useTheme();
  const shown = useAnimatedValue(Math.max(0, Math.min(1, fraction)));
  const size = 64, stroke = 5, r = (size - stroke) / 2, circ = 2 * Math.PI * r;
  return (
    <div className="flex items-center gap-3" role="img" aria-label={`Exposure today: ${Math.round(fraction * 100)} percent. ${caption}`}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={colors.hairline} strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={colors.primary} strokeWidth={stroke}
          strokeLinecap="round" strokeDasharray={circ} strokeDashoffset={circ * (1 - shown)}
          transform={`rotate(-90 ${size / 2} ${size / 2})`} />
        <text x="50%" y="50%" textAnchor="middle" dominantBaseline="central" fontSize="14" fontWeight="600"
          fill={colors.ink} style={{ fontVariantNumeric: 'tabular-nums' }}>{Math.round(shown * 100)}%</text>
      </svg>
      <div className="min-w-0 hidden sm:block">
        <div className="text-[11px] font-medium" style={{ color: colors.inkSubtle }}>Exposure today</div>
        <div className="text-[12px] max-w-[190px]" style={{ color: colors.inkMuted }}>{caption}</div>
      </div>
    </div>
  );
}

function Bar({ label, used, limit, left }: { label: string; used: number; limit: number; left: string }) {
  const { colors } = useTheme();
  const pct = limit > 0 ? Math.max(0, Math.min(100, (used / limit) * 100)) : 0;
  const hot = pct >= 90;
  return (
    <div className="min-w-0">
      <div className="flex items-center justify-between gap-2 text-[11px]" style={{ color: colors.inkSubtle }}>
        <span className="truncate">{label}</span><span className="tabular-nums whitespace-nowrap">{left}</span>
      </div>
      <div className="h-1 rounded-full mt-1 overflow-hidden" style={{ background: colors.hairline }}>
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: hot ? colors.warning : colors.primary, transition: 'width 600ms ease-out' }} />
      </div>
    </div>
  );
}

const inputCls = 'w-full px-2.5 py-1.5 rounded-lg text-[12.5px] focus:outline-none';

function useInputStyle(): React.CSSProperties {
  const { colors } = useTheme();
  return { background: colors.inputBg, color: colors.ink, border: `1px solid ${colors.hairline}` };
}

function Field({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  const { colors } = useTheme();
  return (
    <label className={`block min-w-0 ${className || ''}`}>
      <span className="block text-[11px] mb-1" style={{ color: colors.inkSubtle }}>{label}</span>
      {children}
    </label>
  );
}

// ── One grant ─────────────────────────────────────────────────────────────────

function GrantCard({ g, me, onChanged }: { g: any; me: string | null; onChanged: () => void }) {
  const { colors } = useTheme();
  const inputStyle = useInputStyle();
  const [panel, setPanel] = useState<null | 'revoke' | 'delegate'>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const [d, setD] = useState({ to_identity: '', per_action: '', window_actions: '', note: '' });

  const state = GRANT_STATE[g.state] || { label: humanize(g.state), tone: 'muted' as Tone };
  const l = g.limits || {};
  const h = g.headroom || {};
  const cur = l.currency || '';
  const mine = !me || g.holder === me;

  const run = async (key: string, fn: () => Promise<unknown>, after?: () => void) => {
    setBusy(key); setError(null);
    try { await fn(); after?.(); onChanged(); }
    catch (e: any) { setError(e?.message || 'That change was refused.'); }
    finally { setBusy(null); }
  };

  const delegate = () => {
    const to = d.to_identity.trim();
    if (!to) { setError('Name the person you are delegating to.'); return; }
    const body: Record<string, unknown> = { to_identity: to, note: d.note.trim() };
    if (d.per_action.trim() !== '') body.per_action = Number(d.per_action);
    if (d.window_actions.trim() !== '') body.window_actions = Number(d.window_actions);
    run('delegate', () => api.delegateAuthorityGrant(g.id, body), () => {
      setPanel(null); setD({ to_identity: '', per_action: '', window_actions: '', note: '' });
    });
  };

  const btn = 'px-2.5 py-1 rounded-md text-[11.5px] font-semibold flex items-center gap-1.5 disabled:opacity-50';
  const quiet: React.CSSProperties = { background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` };

  return (
    <div className="px-4 py-3 space-y-2" style={{ borderTop: `1px solid ${colors.hairline}` }}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[13px] font-medium min-w-0" style={{ color: colors.ink }}>{scopeWords(g)}</span>
        <Pill text={state.label} tone={state.tone} />
        {g.delegable && <Pill text="May delegate" tone="muted" />}
        <span className="ml-auto flex items-center gap-2">
          {(g.state === 'active' || g.state === 'suspended' || g.state === 'expired' || g.state === 'revoked') && (
            g.proof_id ? <Pill text="Lending sealed" tone="ok" /> : <Pill text="Seal missing" tone="bad" />
          )}
          {g.state === 'revoked' && (g.revoke_proof_id ? <Pill text="Revocation sealed" tone="ok" /> : <Pill text="Revocation seal missing" tone="bad" />)}
          <GrantId id={g.id} />
        </span>
      </div>
      <div className="text-[12px]" style={{ color: colors.inkMuted }}>
        {limitWords(g)}
        {tripwireWords(g) && <span style={{ color: colors.inkTertiary }}>{`; ${tripwireWords(g)}`}</span>}
        {undoWords(g).length > 0 && <span style={{ color: colors.inkTertiary }}>{`; ${undoWords(g).join('; ')}`}</span>}
      </div>

      {g.state === 'suspended' && (
        <div className="flex items-center gap-2 flex-wrap rounded-lg px-3 py-2" style={{ background: colors.warning + '10', border: `1px solid ${colors.warning}30` }}>
          <span className="text-[12px] flex-1 min-w-[160px]" style={{ color: colors.warning }}>
            {g.suspend_reason || 'This grant is suspended.'}
            {g.suspended_at && <span className="text-[11px]" style={{ color: colors.inkTertiary }}>{` Suspended ${timeAgo(g.suspended_at)}.`}</span>}
          </span>
          <button onClick={() => run('resume', () => api.resumeAuthorityGrant(g.id))} disabled={busy !== null}
            className={btn} style={{ background: colors.primary + '18', color: colors.primary }}>
            {busy === 'resume' ? <Loader2 className="w-3 h-3 animate-spin" /> : <PlayCircle className="w-3 h-3" />} Resume
          </button>
        </div>
      )}

      {(g.state === 'active' || g.state === 'suspended' || g.state === 'expired') && (l.window_amount != null || l.window_actions != null) && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2">
          {l.window_amount != null && (
            <Bar label="Money reserved" used={Number(h.amount_reserved || 0)} limit={Number(l.window_amount)}
              left={h.amount_left == null ? NOT_MEASURED : `${moneyText(h.amount_left, cur)} left`} />
          )}
          {l.window_actions != null && (
            <Bar label="Actions reserved" used={Number(h.actions_reserved || 0)} limit={Number(l.window_actions)}
              left={h.actions_left == null ? NOT_MEASURED : `${numText(h.actions_left)} left`} />
          )}
        </div>
      )}

      <div className="flex items-center gap-x-3 gap-y-1 flex-wrap text-[11px]" style={{ color: colors.inkTertiary }}>
        {(g.state === 'active' || g.state === 'suspended') && h.window_ends_at && <span>{`${resetsText(h.window_ends_at).replace(/^r/, 'R')}`}</span>}
        <span>{g.state === 'revoked' || g.state === 'declined' ? (g.state === 'revoked' && g.revoked_at ? `Revoked ${timeAgo(g.revoked_at)}` : '') : expiryText(g.expires_at)}</span>
        {l.currency && <span>{l.currency}</span>}
        {g.scope?.max_risk_tier && <span>{`Up to ${String(g.scope.max_risk_tier).toLowerCase()} risk`}</span>}
        {g.state === 'revoked' && g.revoke_reason && <span title={g.revoke_reason}>{`Reason: ${g.revoke_reason}`}</span>}
        {g.note && <span className="truncate max-w-[260px]" title={g.note}>{g.note}</span>}
      </div>

      {g.state === 'pending' && (
        <div className="flex items-center gap-2 flex-wrap rounded-lg px-3 py-2" style={{ background: colors.warning + '10', border: `1px solid ${colors.warning}30` }}>
          {mine ? (
            <>
              <span className="text-[12px]" style={{ color: colors.inkMuted }}>
                {`${g.lent_by || 'Someone'} delegated this to you`}
              </span>
              <span className="ml-auto flex items-center gap-2">
                <button onClick={() => run('accept', () => api.respondToAuthorityGrant(g.id, true))} disabled={busy !== null}
                  className={btn} style={{ background: colors.primary + '18', color: colors.primary }}>
                  {busy === 'accept' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />} Accept
                </button>
                <button onClick={() => run('decline', () => api.respondToAuthorityGrant(g.id, false))} disabled={busy !== null}
                  className={btn} style={quiet}>
                  {busy === 'decline' ? <Loader2 className="w-3 h-3 animate-spin" /> : <X className="w-3 h-3" />} Decline
                </button>
              </span>
            </>
          ) : (
            <span className="text-[12px] break-words [overflow-wrap:anywhere]" style={{ color: colors.inkMuted }}>{`Waiting for ${g.holder} to accept`}</span>
          )}
        </div>
      )}

      {(g.state === 'active' || g.state === 'suspended') && mine && (
        <div className="flex items-center gap-2 flex-wrap">
          <button onClick={() => { setPanel(panel === 'revoke' ? null : 'revoke'); setError(null); }} className={btn}
            style={{ background: colors.error + '12', color: colors.error }} aria-expanded={panel === 'revoke'}>
            <Ban className="w-3 h-3" /> Revoke {panel === 'revoke' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>
          {g.delegable && g.state === 'active' && (
            <button onClick={() => { setPanel(panel === 'delegate' ? null : 'delegate'); setError(null); }} className={btn}
              style={quiet} aria-expanded={panel === 'delegate'}>
              <Share2 className="w-3 h-3" /> Delegate {panel === 'delegate' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            </button>
          )}
        </div>
      )}

      {panel === 'revoke' && (
        <div className="flex items-center gap-2 flex-wrap">
          <input value={reason} onChange={e => setReason(e.target.value)} aria-label="Reason for revoking"
            placeholder="Why are you taking this back?" className={`${inputCls} flex-1 min-w-[180px]`} style={inputStyle} />
          <button onClick={() => run('revoke', () => api.revokeAuthorityGrant(g.id, reason.trim()), () => { setPanel(null); setReason(''); })}
            disabled={busy !== null} className={btn} style={{ background: colors.error, color: '#fff' }}>
            {busy === 'revoke' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Ban className="w-3 h-3" />} Revoke now
          </button>
        </div>
      )}

      {panel === 'delegate' && (
        <div className="rounded-lg p-3 space-y-2" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
          <p className="text-[11px]" style={{ color: colors.inkTertiary }}>
            A delegated grant can only be narrower than this one. It stays pending until the person accepts it.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            <Field label="Delegate to" className="sm:col-span-1">
              <input value={d.to_identity} onChange={e => setD({ ...d, to_identity: e.target.value })} className={inputCls} style={inputStyle} placeholder="Their sign-in email" />
            </Field>
            <Field label="Per action">
              <input type="number" min={0} value={d.per_action} onChange={e => setD({ ...d, per_action: e.target.value })} className={inputCls} style={inputStyle} />
            </Field>
            <Field label="Actions per window">
              <input type="number" min={0} value={d.window_actions} onChange={e => setD({ ...d, window_actions: e.target.value })} className={inputCls} style={inputStyle} />
            </Field>
          </div>
          <div className="flex items-end gap-2 flex-wrap">
            <Field label="Note" className="flex-1 min-w-[160px]">
              <input value={d.note} onChange={e => setD({ ...d, note: e.target.value })} className={inputCls} style={inputStyle} />
            </Field>
            <button onClick={delegate} disabled={busy !== null} className={btn} style={{ background: colors.primary + '18', color: colors.primary }}>
              {busy === 'delegate' ? <Loader2 className="w-3 h-3 animate-spin" /> : <ArrowRight className="w-3 h-3" />} Send delegation
            </button>
          </div>
        </div>
      )}

      {error && <div className="text-[12px]" style={{ color: colors.error }} role="alert">{error}</div>}
    </div>
  );
}

// ── Underwriting ──────────────────────────────────────────────────────────────

function Underwriting({ skill, onUse }: { skill: string; onUse: (s: any) => void }) {
  const { colors } = useTheme();
  const [state, setState] = useState<{ loading: boolean; data: any; error: string | null }>({ loading: false, data: null, error: null });

  useEffect(() => {
    const s = skill.trim();
    if (!s) { setState({ loading: false, data: null, error: null }); return; }
    let cancelled = false;
    setState({ loading: true, data: null, error: null });
    const t = setTimeout(async () => {
      try {
        const data = await api.getAuthorityUnderwriting(s, 90);
        if (!cancelled) setState({ loading: false, data, error: null });
      } catch (e: any) {
        if (!cancelled) setState({ loading: false, data: null, error: e?.message || 'The record could not be read.' });
      }
    }, 500);
    return () => { cancelled = true; clearTimeout(t); };
  }, [skill]);

  const box = 'rounded-lg px-3 py-2 min-w-0';
  const boxStyle: React.CSSProperties = { background: colors.surface2, border: `1px solid ${colors.hairline}` };

  if (!skill.trim()) {
    return <p className="text-[12px]" style={{ color: colors.inkTertiary }}>Enter a skill to see what the record says before you lend.</p>;
  }
  if (state.loading && !state.data) return <BrainLoading variant="compact" message="Reading the record for this skill…" />;
  if (state.error) return <p className="text-[12px]" style={{ color: colors.error }} role="alert">{state.error}</p>;
  const u = state.data;
  if (!u) return null;

  const ev = u.evidence || {};
  const am = u.amounts || {};
  const tr = u.trust || {};
  const sg = u.suggestion || {};
  const lo = ev.override_rate_ci_pct?.[0], hi = ev.override_rate_ci_pct?.[1];
  const point = ev.override_rate_pct;
  const hasCi = lo != null && hi != null;
  const suggestionRows: { label: string; value: string; basis?: string }[] = [];
  if (sg.per_action) suggestionRows.push({ label: 'Per action', value: numText(sg.per_action.value), basis: sg.per_action.basis });
  if (sg.window_amount) suggestionRows.push({ label: `Money ${WINDOW_WORD[sg.window_amount.window] || 'per window'}`, value: numText(sg.window_amount.value), basis: sg.window_amount.basis });
  if (sg.window_actions) suggestionRows.push({ label: `Actions ${WINDOW_WORD[sg.window_actions.window] || 'per window'}`, value: numText(sg.window_actions.value), basis: sg.window_actions.basis });
  if (sg.money_limit) suggestionRows.push({ label: 'Money limit', value: sg.money_limit.value == null ? NOT_MEASURED : numText(sg.money_limit.value), basis: sg.money_limit.basis });
  const usable = Boolean(sg.per_action || sg.window_amount || sg.window_actions);
  const examples: any[] = Array.isArray(u.override_examples) ? u.override_examples.slice(0, 3) : [];

  return (
    <div className="space-y-3">
      {u.verdict && <p className="text-[13px] leading-relaxed" style={{ color: colors.ink }}>{u.verdict}</p>}

      <div className="grid grid-cols-2 gap-2">
        <div className={box} style={boxStyle}>
          <div className="text-[11px]" style={{ color: colors.inkSubtle }}>Human-reviewed</div>
          <div className="text-[18px] font-semibold tabular-nums" style={{ color: colors.ink }}>{numText(ev.counted_reviews)}</div>
          {ev.quick_excluded > 0 && <div className="text-[11px]" style={{ color: colors.inkTertiary }}>{`${ev.quick_excluded} quick decisions excluded`}</div>}
        </div>
        <div className={box} style={boxStyle}>
          <div className="text-[11px]" style={{ color: colors.inkSubtle }}>Overridden</div>
          <div className="text-[18px] font-semibold tabular-nums" style={{ color: colors.ink }}>{numText(ev.overrides)}</div>
          <div className="text-[11px]" style={{ color: colors.inkTertiary }}>{point == null ? NOT_MEASURED : `${numText(point)}% of reviews`}</div>
        </div>
      </div>

      <div className={box} style={boxStyle}>
        <div className="text-[11px] mb-1.5" style={{ color: colors.inkSubtle }}>Override rate</div>
        {hasCi ? (
          <>
            <div className="relative h-2 rounded-full" style={{ background: colors.hairline }} role="img"
              aria-label={`95 percent interval ${lo} to ${hi} percent`}>
              <div className="absolute top-0 h-2 rounded-full" style={{ left: `${Math.max(0, Math.min(100, lo))}%`, width: `${Math.max(1, Math.min(100, hi) - Math.max(0, lo))}%`, background: colors.primary + '66' }} />
              {point != null && <div className="absolute -top-0.5 w-0.5 h-3 rounded" style={{ left: `${Math.max(0, Math.min(100, point))}%`, background: colors.primary }} />}
            </div>
            <div className="flex justify-between text-[11px] mt-1" style={{ color: colors.inkTertiary }}>
              <span>0%</span><span>{`95% interval ${numText(lo)}% to ${numText(hi)}%`}</span><span>100%</span>
            </div>
          </>
        ) : <div className="text-[12px]" style={{ color: colors.inkTertiary }}>{NOT_MEASURED}</div>}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className={box} style={boxStyle}>
          <div className="text-[11px]" style={{ color: colors.inkSubtle }}>Amounts seen</div>
          <div className="text-[12.5px] tabular-nums mt-0.5" style={{ color: colors.ink }}>
            {am.p50 == null && am.p90 == null && am.max == null ? NOT_MEASURED
              : `${numText(am.p50)} / ${numText(am.p90)} / ${numText(am.max)}`}
          </div>
          <div className="text-[11px]" style={{ color: colors.inkTertiary }}>
            {am.p50 == null && am.p90 == null && am.max == null ? '' : 'Typical, high, largest. '}
            {am.known != null && ev.runs != null ? `${am.known} of ${ev.runs} runs stated an amount` : ''}
          </div>
        </div>
        <div className={box} style={boxStyle}>
          <div className="text-[11px]" style={{ color: colors.inkSubtle }}>Trust ladder</div>
          <div className="text-[12.5px] font-medium mt-0.5" style={{ color: colors.ink }}>
            {tr.held_tier ? (TIER_LABEL[tr.held_tier] || humanize(tr.held_tier)) : 'No rung yet'}
          </div>
          <div className="text-[11px]" style={{ color: colors.inkTertiary }}>
            {tr.trust_score != null ? `Trust score ${Number(tr.trust_score).toFixed(2)} over ${tr.samples ?? 0} runs` : NOT_MEASURED}
          </div>
        </div>
      </div>

      <div className={box} style={boxStyle}>
        <div className="flex items-center justify-between gap-2 mb-1.5">
          <span className="text-[11.5px] font-medium" style={{ color: colors.inkSubtle }}>Suggested limits</span>
          <button onClick={() => onUse(sg)} disabled={!usable}
            className="px-2.5 py-1 rounded-md text-[11.5px] font-semibold flex items-center gap-1.5 disabled:opacity-40"
            style={{ background: colors.primary + '18', color: colors.primary }}>
            <Sparkles className="w-3 h-3" /> Use suggested limits
          </button>
        </div>
        {suggestionRows.length === 0 ? (
          <div className="text-[12px]" style={{ color: colors.inkTertiary }}>{NOT_MEASURED}</div>
        ) : suggestionRows.map(r => (
          <div key={r.label} className="py-1" style={{ borderTop: `1px solid ${colors.hairline}` }}>
            <div className="flex items-baseline justify-between gap-3 text-[12.5px]">
              <span style={{ color: colors.inkMuted }}>{r.label}</span>
              <span className="tabular-nums font-medium" style={{ color: colors.ink }}>{r.value}</span>
            </div>
            {r.basis && <div className="text-[11px] leading-snug" style={{ color: colors.inkTertiary }}>{r.basis}</div>}
          </div>
        ))}
      </div>

      {examples.length > 0 && (
        <div className={box} style={boxStyle}>
          <div className="text-[11.5px] font-medium mb-1" style={{ color: colors.inkSubtle }}>Recent overrides</div>
          {examples.map((x, i) => (
            <div key={`${x.execution_id}-${i}`} className="py-1 text-[12px] flex items-baseline gap-2 flex-wrap" style={{ borderTop: `1px solid ${colors.hairline}`, color: colors.inkMuted }}>
              <span>{humanize(x.kind)}</span>
              <span className="text-[11px]" style={{ color: colors.inkTertiary }}>{timeAgo(x.at)}</span>
              {x.quick && <Pill text="Quick" tone="warn" />}
              {x.amount != null && <span className="tabular-nums">{numText(x.amount)}</span>}
              {x.reason && <span className="truncate flex-1 min-w-[120px]" title={x.reason}>{x.reason}</span>}
            </div>
          ))}
        </div>
      )}

      {u.method && <p className="text-[11px] leading-snug" style={{ color: colors.inkTertiary }}>{u.method}</p>}
    </div>
  );
}

// ── Replay: what these limits would have done ───────────────────────────────

const REPLAY_DAYS = [30, 90, 180, 365];

function StatBox({ label, value, note }: { label: string; value: React.ReactNode; note?: string }) {
  const { colors } = useTheme();
  return (
    <div className="rounded-lg px-3 py-2 min-w-0" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
      <div className="text-[11px]" style={{ color: colors.inkSubtle }}>{label}</div>
      <div className="text-[18px] font-semibold tabular-nums" style={{ color: colors.ink }}>{value}</div>
      {note && <div className="text-[11px] leading-snug" style={{ color: colors.inkTertiary }}>{note}</div>}
    </div>
  );
}

type ReplayState = { loading: boolean; data: any; error: string | null; currency: string };

function ReplayPanel({ draft, hasDraft, fallbackCurrency }: {
  draft: Record<string, unknown>; hasDraft: boolean; fallbackCurrency: string;
}) {
  const { colors } = useTheme();
  const inputStyle = useInputStyle();
  const [days, setDays] = useState(90);
  const [st, setSt] = useState<ReplayState>({ loading: false, data: null, error: null, currency: '' });
  const seq = useRef(0);

  const run = async () => {
    const id = ++seq.current;
    const currency = hasDraft ? String(draft.currency || '') : fallbackCurrency;
    setSt(prev => ({ ...prev, loading: true, error: null }));
    try {
      const data = await api.replayAuthority({
        days,
        grants: hasDraft ? [{ ...draft, label: 'these limits' }] : null,
      });
      if (id === seq.current) setSt({ loading: false, data, error: null, currency });
    } catch (e: any) {
      if (id === seq.current) setSt({ loading: false, data: null, error: e?.message || 'The replay could not be run.', currency });
    }
  };

  const r = st.data;
  const money = (n: number | null | undefined) => (st.currency ? moneyText(n, st.currency) : numText(n));
  const runs = r ? Number(r.runs || 0) : 0;
  const proceeded = r ? Number(r.proceeded || 0) : 0;
  const paused = r ? Number(r.paused || 0) : 0;
  const reasons: any[] = Array.isArray(r?.paused_by_reason) ? r.paused_by_reason : [];
  const perGrant: any[] = Array.isArray(r?.grants) ? r.grants : [];
  const load = r?.human_load || {};
  const exp = r?.exposure || {};
  const exposureKnown = exp.amount_proceeded != null && Number(exp.runs_with_amount || 0) > 0;
  const days_ = r?.window_days ?? days;

  return (
    <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.hairline}`, background: colors.surface1 }}>
      <SectionHead title="What these limits would have done" />
      <div className="p-4 space-y-3">
        <div className="flex items-center gap-2 flex-wrap">
          <button onClick={run} disabled={st.loading}
            className="px-3 py-1.5 rounded-lg text-[12px] font-semibold flex items-center gap-1.5 disabled:opacity-50"
            style={{ background: colors.primary + '18', color: colors.primary }}>
            {st.loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <History className="w-3.5 h-3.5" />}
            {`Replay the last ${days} days`}
          </button>
          <select value={days} onChange={e => setDays(Number(e.target.value))} aria-label="Days to replay"
            className="px-2 py-1.5 rounded-lg text-[12px] focus:outline-none" style={inputStyle}>
            {REPLAY_DAYS.map(d => <option key={d} value={d}>{`${d} days`}</option>)}
          </select>
          <span className="text-[11px]" style={{ color: colors.inkTertiary }}>
            {hasDraft ? 'Replaying the limits in the form above' : 'Replaying your active grants'}
          </span>
        </div>

        {st.loading && !r && <BrainLoading variant="compact" message="Replaying the record against these limits…" />}
        {st.error && <p className="text-[12px] leading-snug" style={{ color: colors.error }} role="alert">{st.error}</p>}

        {r && (
          <div className="space-y-3" style={{ opacity: st.loading ? 0.55 : 1, transition: 'opacity 150ms' }}>
            {runs === 0 ? (
              <p className="text-[13px] leading-relaxed" style={{ color: colors.ink }}>
                {`There were no runs in the last ${days_} days, so there is nothing to replay yet.`}
              </p>
            ) : (
              <p className="text-[13px] leading-relaxed" style={{ color: colors.ink }}>
                {`Of ${numText(runs)} run${runs === 1 ? '' : 's'} in the last ${days_} days, ${numText(proceeded)} would have run on your authority and ${numText(paused)} would have gone to a person.`}
              </p>
            )}

            {runs > 0 && (
              <>
                <div className="grid grid-cols-2 gap-2">
                  <StatBox label="Would have proceeded" value={numText(proceeded)} />
                  <StatBox label="Would have paused" value={numText(paused)} />
                  <StatBox label="Exposure"
                    value={exposureKnown ? money(exp.amount_proceeded) : NOT_MEASURED}
                    note={exp.worst_day
                      ? `worst day ${money(exp.worst_day.amount)}${exp.worst_day.day ? ` on ${dayWord(exp.worst_day.day)}` : ''}`
                      : `${numText(exp.runs_with_amount || 0)} of ${numText(runs)} runs stated an amount`} />
                  <StatBox label="Human load"
                    value={load.average_per_pause_day != null ? `${numText(load.average_per_pause_day)} a day` : (paused === 0 ? '0' : NOT_MEASURED)}
                    note={load.busiest_day ? `busiest day ${numText(load.busiest_day.runs)} on ${dayWord(load.busiest_day.day)}` : (paused === 0 ? 'nothing would have paused' : undefined)} />
                </div>

                <div className="rounded-lg px-3 py-2" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
                  <div className="text-[11.5px] font-medium mb-1" style={{ color: colors.inkSubtle }}>Why they would have paused</div>
                  {reasons.length === 0 ? (
                    <div className="text-[12px]" style={{ color: colors.inkTertiary }}>Nothing would have paused.</div>
                  ) : reasons.map((x, i) => (
                    <div key={`${x.reason}-${i}`} className="py-1 flex items-baseline justify-between gap-3 text-[12px]"
                      style={{ borderTop: i === 0 ? undefined : `1px solid ${colors.hairline}`, color: colors.inkMuted }}>
                      <span className="min-w-0">{x.label || humanize(x.reason)}</span>
                      <span className="tabular-nums font-medium whitespace-nowrap" style={{ color: colors.ink }}>{numText(x.runs)}</span>
                    </div>
                  ))}
                </div>

                {perGrant.length > 0 && (
                  <div className="rounded-lg px-3 py-2" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
                    <div className="text-[11.5px] font-medium mb-1" style={{ color: colors.inkSubtle }}>How much of each grant would have been used</div>
                    {perGrant.map((x, i) => (
                      <div key={`${x.label}-${i}`} className="py-1 text-[12px] leading-snug"
                        style={{ borderTop: i === 0 ? undefined : `1px solid ${colors.hairline}`, color: colors.inkMuted }}>
                        <span className="font-medium" style={{ color: colors.ink }}>{x.label || 'Grant'}</span>
                        {`: ${numText(x.proceeded)} run${Number(x.proceeded) === 1 ? '' : 's'} would have proceeded. Busiest window ${money(x.busiest_window_amount)}, ${x.busiest_window_actions == null ? NOT_MEASURED.toLowerCase() : `${numText(x.busiest_window_actions)} action${Number(x.busiest_window_actions) === 1 ? '' : 's'}`}.`}
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}

            {r.note && <p className="text-[11px] leading-snug" style={{ color: colors.inkTertiary }}>{r.note}</p>}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Review quality: did the humans in the loop actually look ───────────────────

function ReviewQuality() {
  const { colors } = useTheme();
  const rq = usePanel(() => api.getAuthorityReviewers(90), { poll: false });
  const d: any = rq.data;
  const pctRaw = d?.workspace?.evidence_grade_pct;
  const shown = useAnimatedValue(pctRaw != null && Number.isFinite(Number(pctRaw)) ? Number(pctRaw) : 0);

  // A viewer (403) or an open-core deployment (402) has no reviewer record to read: hide the panel.
  if (rq.notice) return null;

  const reviewers: any[] = Array.isArray(d?.reviewers) ? d.reviewers : [];
  const w = d?.workspace || {};
  const th = 'text-left font-medium py-1.5 pr-3 whitespace-nowrap';
  const num = 'py-1.5 pr-3 tabular-nums whitespace-nowrap';

  return (
    <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.hairline}`, background: colors.surface1 }}>
      <SectionHead title="Review quality" right={<span>Last 90 days</span>} />
      <div className="px-4 pt-3 pb-4 space-y-3">
        <p className="text-[11.5px]" style={{ color: colors.inkTertiary }}>Whether the humans in the loop actually looked</p>
        {rq.loading && !d && <BrainLoading variant="compact" message="Reading who decided what…" />}
        {rq.error && !d && <p className="text-[12px]" style={{ color: colors.error }} role="alert">{rq.error}</p>}
        {d && (Number(w.decisions || 0) === 0 && reviewers.length === 0 ? (
          <div className="py-2 text-[12.5px]" style={{ color: colors.inkTertiary }}>No human decisions in this window yet.</div>
        ) : d && (
          <>
            <div className="flex items-end gap-4 flex-wrap">
              <div>
                <div className="text-[26px] leading-none font-semibold tabular-nums" style={{ color: colors.ink }}>
                  {pctRaw == null ? NOT_MEASURED : `${Math.round(shown)}%`}
                </div>
                <div className="text-[12px] mt-1" style={{ color: colors.inkMuted }}>
                  {pctRaw == null ? 'of decisions were evidence-grade' : `${Math.round(shown)}% of decisions were evidence-grade`}
                </div>
              </div>
              <div className="text-[11.5px] leading-snug space-y-0.5 pb-0.5" style={{ color: colors.inkTertiary }}>
                <div>{`${pctText(w.quick_rate_pct)} decided quickly`}</div>
                <div>{`${numText(w.unattested)} not attested by the reviewer`}</div>
                <div>{`${numText(w.decisions)} decision${Number(w.decisions) === 1 ? '' : 's'} in all`}</div>
              </div>
            </div>
            {pctRaw != null && (
              <div className="h-1 rounded-full overflow-hidden" style={{ background: colors.hairline }} aria-hidden>
                <div className="h-full rounded-full" style={{ width: `${Math.max(0, Math.min(100, shown))}%`, background: colors.primary }} />
              </div>
            )}
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]" style={{ color: colors.inkMuted }}>
                <thead>
                  <tr style={{ color: colors.inkSubtle, borderBottom: `1px solid ${colors.hairline}` }}>
                    <th className={th}>Reviewer</th>
                    <th className={th}>Decisions</th>
                    <th className={th}>Median time on screen</th>
                    <th className={th}>Quick rate</th>
                    <th className={th}>Rejected</th>
                    <th className={th}>Edited</th>
                  </tr>
                </thead>
                <tbody>
                  {reviewers.map((x, i) => (
                    <tr key={`${x.approver}-${i}`} style={{ borderTop: i === 0 ? undefined : `1px solid ${colors.hairline}` }}>
                      <td className="py-1.5 pr-3 max-w-[200px] break-words [overflow-wrap:anywhere]" style={{ color: colors.ink }} title={x.approver || undefined}>{x.approver || NOT_MEASURED}</td>
                      <td className={num}>{numText(x.decisions)}</td>
                      <td className={num}>{secondsText(x.median_seconds)}</td>
                      <td className={num}>{pctText(x.quick_rate_pct)}</td>
                      <td className={num}>{numText(x.rejected)}</td>
                      <td className={num}>{numText(x.edited)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {d.method && <p className="text-[11px] leading-snug" style={{ color: colors.inkTertiary }}>{d.method}</p>}
          </>
        ))}
      </div>
    </div>
  );
}

// ── Lend authority ────────────────────────────────────────────────────────────

const EMPTY_FORM = {
  department: '', skill: '', per_action: '', window_amount: '', window_actions: '', window: 'day',
  currency: 'USD', expires_in_days: '', max_risk_tier: '', delegable: false, note: '', tripwire: '1',
  undo_window_hours: '24', reversible_only: false,
};

function LendPanel({ onLent, sectionRef, fallbackCurrency }: {
  onLent: () => void; sectionRef: React.RefObject<HTMLDivElement | null>; fallbackCurrency: string;
}) {
  const { colors } = useTheme();
  const { isAdmin } = useAuth();
  const inputStyle = useInputStyle();
  const [f, setF] = useState(EMPTY_FORM);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const set = (patch: Partial<typeof EMPTY_FORM>) => { setF(prev => ({ ...prev, ...patch })); setDone(false); };
  const skills = useMemo(() => f.skill.split(/[,\n]+/).map(s => s.trim()).filter(Boolean), [f.skill]);
  const num = (v: string): number | null => (v.trim() === '' ? null : Number(v));

  // What a replay should test: the limits in the form when any are filled, else the grants already lent.
  const hasDraft = skills.length > 0 || f.per_action.trim() !== '' || f.window_amount.trim() !== '' || f.window_actions.trim() !== '';
  const draft: Record<string, unknown> = {
    department: f.department || null,
    skills: skills.length ? skills : null,
    per_action: num(f.per_action),
    window_amount: num(f.window_amount),
    window_actions: num(f.window_actions),
    window: f.window,
    currency: (f.currency.trim() || 'USD').toUpperCase(),
    max_risk_tier: f.max_risk_tier || null,
  };

  const useSuggestion = (sg: any) => {
    const patch: Partial<typeof EMPTY_FORM> = {};
    if (sg?.per_action?.value != null) patch.per_action = String(sg.per_action.value);
    if (sg?.window_amount?.value != null) patch.window_amount = String(sg.window_amount.value);
    if (sg?.window_actions?.value != null) patch.window_actions = String(sg.window_actions.value);
    const w = sg?.window_amount?.window || sg?.window_actions?.window;
    if (w) patch.window = w;
    set(patch);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null); setDone(false);
    try {
      await api.lendAuthority({
        department: f.department || null,
        skills: skills.length ? skills : null,
        max_risk_tier: f.max_risk_tier || null,
        per_action: num(f.per_action),
        window_amount: num(f.window_amount),
        window_actions: num(f.window_actions),
        window: f.window,
        currency: (f.currency.trim() || 'USD').toUpperCase(),
        expires_in_days: num(f.expires_in_days),
        delegable: f.delegable,
        note: f.note.trim(),
        tripwire_adverse_runs: num(f.tripwire),
        undo_window_hours: num(f.undo_window_hours),
        reversible_only: f.reversible_only,
      });
      setF(EMPTY_FORM); setDone(true);
      onLent();
    } catch (err: any) {
      setError(err?.message || 'The grant was refused.');
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-4">
      <div ref={sectionRef} className="rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.hairline}`, background: colors.surface1 }}>
        <SectionHead title="Lend authority" />
        <form onSubmit={submit} className="p-4 space-y-3">
          <p className="text-[11.5px] leading-snug" style={{ color: colors.inkTertiary }}>
            The grant is held by you, under your name. Anything above these limits goes to a person.
            {!isAdmin && ' As an operator, name a department or skills, a limit per action, a cap per window and an end date within 90 days.'}
          </p>
          <div className="grid grid-cols-2 gap-2.5">
            <Field label="Department">
              <select id="authority-dept" value={f.department} onChange={e => set({ department: e.target.value })} className={inputCls} style={inputStyle}>
                <option value="">Any department</option>
                {DEPARTMENTS.map(d => <option key={d} value={d}>{DEPARTMENT_LABELS[d]}</option>)}
              </select>
            </Field>
            <Field label="Max risk tier">
              <select value={f.max_risk_tier} onChange={e => set({ max_risk_tier: e.target.value })} className={inputCls} style={inputStyle}>
                <option value="">Any</option>
                <option value="LOW">Low</option>
                <option value="MEDIUM">Medium</option>
                <option value="HIGH">High</option>
              </select>
            </Field>
          </div>
          <Field label="Skill">
            <input value={f.skill} onChange={e => set({ skill: e.target.value })} className={inputCls} style={inputStyle}
              placeholder="e.g. handle_refund_request; leave blank for every skill in the department" />
          </Field>
          <div className="grid grid-cols-2 gap-2.5">
            <Field label="Per action">
              <input type="number" min={0} value={f.per_action} onChange={e => set({ per_action: e.target.value })} className={inputCls} style={inputStyle} />
            </Field>
            <Field label="Per window">
              <input type="number" min={0} value={f.window_amount} onChange={e => set({ window_amount: e.target.value })} className={inputCls} style={inputStyle} />
            </Field>
            <Field label="Actions per window">
              <input type="number" min={0} value={f.window_actions} onChange={e => set({ window_actions: e.target.value })} className={inputCls} style={inputStyle} />
            </Field>
            <Field label="Window">
              <select value={f.window} onChange={e => set({ window: e.target.value })} className={inputCls} style={inputStyle}>
                <option value="day">Day (UTC)</option>
                <option value="week">Week (UTC)</option>
                <option value="month">Month (UTC)</option>
              </select>
            </Field>
            <Field label="Currency">
              <input value={f.currency} onChange={e => set({ currency: e.target.value })} className={inputCls} style={inputStyle} maxLength={6} />
            </Field>
            <Field label="Expires in days">
              <input type="number" min={1} value={f.expires_in_days} onChange={e => set({ expires_in_days: e.target.value })} className={inputCls} style={inputStyle}
                placeholder={isAdmin ? 'Blank for no expiry' : 'Required, up to 90'} max={isAdmin ? undefined : 90} />
            </Field>
          </div>
          <Field label="Tripwire: suspend after N adverse runs">
            <input type="number" min={1} value={f.tripwire} onChange={e => set({ tripwire: e.target.value })} className={inputCls} style={inputStyle} placeholder="Blank for no tripwire" />
            <span className="block text-[11px] mt-1 leading-snug" style={{ color: colors.inkTertiary }}>
              An adverse run under this grant suspends it and tells you. You resume it after looking.
            </span>
          </Field>
          <Field label="Undo window (hours)">
            <input type="number" min={0} step="any" value={f.undo_window_hours} onChange={e => set({ undo_window_hours: e.target.value })}
              className={inputCls} style={inputStyle} placeholder="Blank for no undo" />
            <span className="block text-[11px] mt-1 leading-snug" style={{ color: colors.inkTertiary }}>
              A run's write can be undone by you inside this window, if the record has not moved since.
            </span>
          </Field>
          <label className="flex items-center gap-2 text-[12px] cursor-pointer" style={{ color: colors.inkMuted }}>
            <input type="checkbox" checked={f.reversible_only} onChange={e => set({ reversible_only: e.target.checked })} />
            Admit only reversible writes
          </label>
          <label className="flex items-center gap-2 text-[12px] cursor-pointer" style={{ color: colors.inkMuted }}>
            <input type="checkbox" checked={f.delegable} onChange={e => set({ delegable: e.target.checked })} />
            The holder of this grant may delegate part of it
          </label>
          <Field label="Note">
            <input value={f.note} onChange={e => set({ note: e.target.value })} className={inputCls} style={inputStyle} placeholder="Why you are lending this" />
          </Field>
          <div className="flex items-center gap-3 flex-wrap">
            <button type="submit" disabled={busy}
              className="px-3.5 py-2 rounded-lg text-[12.5px] font-semibold flex items-center gap-2 disabled:opacity-50"
              style={{ background: colors.primary, color: '#fff' }}>
              {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <PenLine className="w-3.5 h-3.5" />} Lend my authority
            </button>
            {done && <span className="text-[12px] flex items-center gap-1" style={{ color: colors.success }}><Check className="w-3.5 h-3.5" /> Authority lent. It is now in your grants.</span>}
          </div>
          {error && <div className="text-[12px] leading-snug" style={{ color: colors.error }} role="alert">{error}</div>}
        </form>

        <div className="px-4 pb-4 pt-3 space-y-3" style={{ borderTop: `1px solid ${colors.hairline}` }}>
          <div className="text-[11.5px] font-medium" style={{ color: colors.inkSubtle }}>
            {`What the record says${skills[0] ? ` about ${humanize(skills[0])}` : ''}`}
          </div>
          <Underwriting skill={skills[0] || ''} onUse={useSuggestion} />
        </div>
      </div>
      <ReplayPanel draft={draft} hasDraft={hasDraft} fallbackCurrency={fallbackCurrency} />
    </div>
  );
}

// ── Live feed ─────────────────────────────────────────────────────────────────

function TokenButton({ executionId }: { executionId: string }) {
  const { colors } = useTheme();
  const [st, setSt] = useState<'idle' | 'busy' | 'copied' | 'show' | 'error'>('idle');
  const [token, setToken] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const fetchToken = async () => {
    setSt('busy'); setErr(null);
    try {
      const r = await api.getAuthorityToken(executionId);
      const t = String(r?.token || '');
      if (!t) throw new Error('No token came back for this run.');
      setToken(t);
      try {
        await navigator.clipboard.writeText(t);
        setSt('copied');
        window.clearTimeout(timer.current);
        timer.current = window.setTimeout(() => setSt('idle'), 2000);
      } catch {
        setSt('show');
      }
    } catch (e: any) {
      setErr(e?.message || 'No token could be issued for this run.');
      setSt('error');
    }
  };

  return (
    <>
      <button onClick={fetchToken} disabled={st === 'busy'}
        title="A signed, offline-verifiable statement of whose authority this run proceeded on. Carry it to a downstream system."
        className="ml-auto px-2 py-0.5 min-h-[28px] min-w-[28px] justify-center rounded-md text-[11px] font-semibold flex items-center gap-1 disabled:opacity-50"
        style={{ background: colors.surface2, color: st === 'copied' ? colors.success : colors.inkMuted, border: `1px solid ${colors.hairline}` }}>
        {st === 'busy' ? <Loader2 className="w-3 h-3 animate-spin" /> : st === 'copied' ? <Check className="w-3 h-3" /> : <KeyRound className="w-3 h-3" />}
        {st === 'copied' ? 'Copied' : 'Token'}
      </button>
      {st === 'show' && (
        <span className="basis-full flex items-center gap-2 pl-[68px]">
          <input readOnly value={token} onFocus={e => e.currentTarget.select()} aria-label="Signed authority token"
            className="flex-1 min-w-0 px-2 py-1 rounded-md text-[11px] font-mono focus:outline-none"
            style={{ background: colors.inputBg, color: colors.ink, border: `1px solid ${colors.hairline}` }} />
          <button onClick={() => setSt('idle')} aria-label="Hide token" className="p-1 rounded-md" style={{ color: colors.inkSubtle }}>
            <X className="w-3 h-3" />
          </button>
        </span>
      )}
      {st === 'error' && err && (
        <span className="basis-full text-[11px] pl-[68px]" style={{ color: colors.error }} role="alert">{err}</span>
      )}
    </>
  );
}

type UndoUi = { open: boolean; loading: boolean; assessment: any; error: string | null; busy: boolean; result: any };

function FeedRow({ u, onChanged }: { u: any; onChanged: () => void }) {
  const { colors } = useTheme();
  const st = USE_STATUS[u.status] || { label: humanize(u.status), tone: 'muted' as Tone };
  const settled = u.status === 'used' || u.status === 'released';
  const [ud, setUd] = useState<UndoUi>({ open: false, loading: false, assessment: null, error: null, busy: false, result: null });
  const canUndo = (u.status === 'used' || u.status === 'reserved') && !!u.execution_id && !u.reversed_at;

  // First click reads the assessment; nothing is written until the person confirms.
  const toggleUndo = async () => {
    if (ud.open) { setUd(p => ({ ...p, open: false })); return; }
    setUd(p => ({ ...p, open: true, loading: true, error: null, result: null }));
    try {
      const a = await api.getAuthorityUndo(u.execution_id);
      setUd(p => ({ ...p, loading: false, assessment: a }));
    } catch (e: any) {
      setUd(p => ({ ...p, loading: false, error: e?.message || 'Whether this run can be undone could not be read.' }));
    }
  };

  const confirmUndo = async () => {
    setUd(p => ({ ...p, busy: true, error: null }));
    try {
      const r = await api.undoAuthorityRun(u.execution_id);
      setUd(p => ({ ...p, busy: false, result: r }));
      onChanged();
    } catch (e: any) {
      setUd(p => ({ ...p, busy: false, error: e?.message || 'The undo was refused.' }));
    }
  };

  const a = ud.assessment;
  const verdict = a ? undoSentence(a) : null;
  const w = a?.write;
  const r = ud.result;
  const restored = r?.restored;
  const restoredTo = restored && (typeof restored.to === 'string' || typeof restored.to === 'number') ? String(restored.to) : '';

  return (
    <div className="px-4 py-2 flex items-center gap-x-3 gap-y-1 flex-wrap text-[12.5px]"
      style={{ borderTop: `1px solid ${colors.hairline}`, color: colors.inkMuted }} title={u.reason || undefined}>
      <span className="w-14 shrink-0 text-[11px]" style={{ color: colors.inkTertiary }}>{timeAgo(u.reserved_at)}</span>
      <span className="font-medium truncate min-w-[100px] flex-1" style={{ color: colors.ink }}>
        {humanize(u.skill_id)}
        {u.department && <span className="font-normal" style={{ color: colors.inkSubtle }}>{`, ${deptLabel(u.department)}`}</span>}
      </span>
      <span className="tabular-nums text-[12px]" style={{ color: u.amount == null ? colors.inkTertiary : colors.inkMuted }}>
        {u.amount == null ? 'no amount' : moneyText(u.amount, u.currency || '')}
      </span>
      <span className="flex items-center gap-1.5">
        {u.status === 'reserved' && <span className="authority-pulse w-1.5 h-1.5 rounded-full" style={{ background: colors.primary }} aria-hidden />}
        <Pill text={st.label} tone={st.tone} />
      </span>
      {settled && (u.proof_id ? <Pill text="Proof sealed" tone="ok" /> : <Pill text="Seal missing" tone="bad" />)}
      {u.disputed && <Pill text="Rated wrong" tone="bad" />}
      {u.reversed_at && (
        <span title={u.reversed_by ? `Undone by ${u.reversed_by}` : 'Undone'}><Pill text="Undone" tone="muted" /></span>
      )}
      {canUndo && (
        <button onClick={toggleUndo} aria-expanded={ud.open}
          title="Take back the write this run made, if it can still be taken back."
          className="px-2 py-0.5 min-h-[28px] min-w-[28px] justify-center rounded-md text-[11px] font-semibold flex items-center gap-1"
          style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>
          <Undo2 className="w-3 h-3" /> Undo
        </button>
      )}
      {(u.status === 'used' || u.status === 'reserved') && u.execution_id && <TokenButton executionId={u.execution_id} />}
      {u.status === 'unlent' && (
        <span className="basis-full text-[11px] pl-[68px]" style={{ color: colors.inkTertiary }}>
          No one lent a signature for this run{u.reason ? '. Hover for the reason.' : '.'}
        </span>
      )}
      {ud.open && (
        <div className="basis-full pl-[68px] space-y-1.5" aria-live="polite">
          {ud.loading && <div className="flex items-center gap-1.5 text-[12px]" style={{ color: colors.inkSubtle }}><Loader2 className="w-3 h-3 animate-spin" /> Checking whether this run can be undone…</div>}
          {ud.error && <div className="text-[12px]" style={{ color: colors.error }} role="alert">{ud.error}</div>}
          {r ? (
            <div className="space-y-1">
              <div className="flex items-center gap-2 flex-wrap text-[12px]" style={{ color: colors.ink }}>
                <Check className="w-3.5 h-3.5" style={{ color: colors.success }} />
                <span>{`Undone by ${r.reversed_by || NOT_MEASURED}`}</span>
                {r.reversal_proof_id ? <Pill text="Proof sealed" tone="ok" /> : <Pill text="Seal missing" tone="bad" />}
              </div>
              {restored && (
                <div className="text-[11px]" style={{ color: colors.inkTertiary }}>
                  {`Restored ${humanize(restored.object_type)} ${restored.external_id ?? ''} in ${humanize(restored.system)}${restoredTo ? ` to ${restoredTo}` : ''}.`}
                </div>
              )}
            </div>
          ) : a && verdict && (
            <div className="space-y-1">
              <div className="flex items-center gap-2 flex-wrap text-[12px]">
                <Pill text={humanize(a.state)} tone={verdict.tone} />
                <span style={{ color: colors.ink }}>{verdict.text}</span>
                {a.state === 'reversed' && (a.reversal_proof_id ? <Pill text="Proof sealed" tone="ok" /> : <Pill text="Seal missing" tone="bad" />)}
              </div>
              {a.reason && a.reason !== verdict.text && <div className="text-[11px] leading-snug" style={{ color: colors.inkTertiary }}>{a.reason}</div>}
              {w && (
                <div className="text-[11px]" style={{ color: colors.inkTertiary }}>
                  {`Write: ${humanize(w.operation)} on ${humanize(w.object_type)} ${w.external_id ?? ''} in ${humanize(w.system)}.`}
                </div>
              )}
              {a.state === 'available' && (
                <button onClick={confirmUndo} disabled={ud.busy}
                  className="px-2.5 py-1 rounded-md text-[11.5px] font-semibold flex items-center gap-1.5 disabled:opacity-50"
                  style={{ background: colors.primary, color: '#fff' }}>
                  {ud.busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Undo2 className="w-3 h-3" />} Undo this run
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Autonomy balance sheet, folded into the page ─────────────────────────────

function BalancePanel() {
  const { colors } = useTheme();
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.hairline}`, background: colors.surface1 }}>
      <div className="px-4 py-2.5 flex items-center justify-between gap-3" style={{ background: colors.surface2 }}>
        <button onClick={() => setOpen(o => !o)} aria-expanded={open} aria-controls="authority-balance-body"
          className="flex items-center gap-1.5 text-[11.5px] font-medium min-w-0" style={{ color: colors.inkSubtle }}>
          {open ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          <span>Autonomy balance sheet</span>
        </button>
        <Link to="/platform/authority/balance" className="text-[11.5px] font-semibold flex items-center gap-1 whitespace-nowrap" style={{ color: colors.primary }}>
          Open full statement <ArrowRight className="w-3 h-3" />
        </Link>
      </div>
      {open ? (
        <div id="authority-balance-body" className="p-4"><AuthorityBalance embedded /></div>
      ) : (
        <p className="px-4 py-2.5 text-[11.5px]" style={{ color: colors.inkTertiary }}>
          What stood open, what ran on lent authority, what went wrong and how closely the humans looked, for a month, a quarter or a range you choose.
        </p>
      )}
    </div>
  );
}

// ── Deputies and handover ─────────────────────────────────────────────────────

function DeputiesPanel({ onChanged }: { onChanged: () => void }) {
  const { colors } = useTheme();
  const inputStyle = useInputStyle();
  const dp = usePanel(() => api.getAuthorityDeputies(), { poll: false });
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState({ deputy: '', note: '' });
  const [ho, setHo] = useState({ reason: '', until: '' });

  // An agent principal is refused (403) and a deployment without the capability answers 402: no panel.
  if (dp.notice) return null;

  const d: any = dp.data;
  const asHolder: any[] = Array.isArray(d?.as_holder) ? d.as_holder : [];
  const asDeputy: any[] = Array.isArray(d?.as_deputy) ? d.as_deputy : [];
  const open: any = d?.open_handover || null;
  const covering: any[] = Array.isArray(d?.covering) ? d.covering : [];
  const accepted = asHolder.find(x => x.status === 'accepted') || null;
  const pending = asHolder.filter(x => x.status === 'pending');
  const declined = asHolder.filter(x => x.status === 'declined');
  const offered = asDeputy.filter(x => x.status === 'pending');
  const deputyFor = asDeputy.filter(x => x.status === 'accepted');

  const btn = 'px-2.5 py-1 rounded-md text-[11.5px] font-semibold flex items-center gap-1.5 disabled:opacity-50';
  const quiet: React.CSSProperties = { background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` };
  const primary: React.CSSProperties = { background: colors.primary + '18', color: colors.primary };
  const soft: React.CSSProperties = { background: colors.surface2, border: `1px solid ${colors.hairline}` };

  const run = async (key: string, fn: () => Promise<unknown>, after?: () => void) => {
    setBusy(key); setError(null);
    try { await fn(); after?.(); await dp.reload(); onChanged(); }
    catch (e: any) { setError(e?.message || 'That change was refused.'); }
    finally { setBusy(null); }
  };

  const nameDeputy = () => {
    const who = name.deputy.trim();
    if (!who) { setError('Name the person who will cover for you.'); return; }
    run('name', () => api.nameAuthorityDeputy(who, name.note.trim()), () => setName({ deputy: '', note: '' }));
  };

  const handOver = () => {
    const reason = ho.reason.trim();
    if (!reason) { setError('Say why you are handing over, so the record explains it.'); return; }
    let until: string | null = null;
    if (ho.until) {
      const t = new Date(ho.until);
      if (!Number.isFinite(t.getTime()) || t.getTime() <= Date.now()) { setError('The return time must be in the future.'); return; }
      until = t.toISOString();
    }
    run('handover', () => api.startAuthorityHandover(reason, until), () => setHo({ reason: '', until: '' }));
  };

  const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
  const sinceText = (h: any) => `since ${whenText(h.started_at)}${h.until ? `, until ${whenText(h.until)}` : ''}`;

  return (
    <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.hairline}`, background: colors.surface1 }}>
      <SectionHead title="Deputies" />
      <div className="p-4 space-y-3">
        <p className="text-[11.5px] leading-snug" style={{ color: colors.inkTertiary }}>
          A deputy covers for you while you are away. A handover lends your active, delegable grants to your deputy until you return.
        </p>
        {dp.loading && !d && <BrainLoading variant="compact" message="Reading who covers for whom…" />}
        {dp.error && !d && <p className="text-[12px]" style={{ color: colors.error }} role="alert">{dp.error}</p>}

        {d && (
          <>
            {/* My deputy */}
            <div className="space-y-1.5">
              <div className="text-[11.5px] font-medium" style={{ color: colors.inkSubtle }}>My deputy</div>
              {accepted && (
                <div className="flex items-center gap-2 flex-wrap rounded-lg px-3 py-2" style={soft}>
                  <span className="text-[12.5px] font-medium min-w-0 break-words [overflow-wrap:anywhere]" style={{ color: colors.ink }}>{accepted.deputy}</span>
                  <Pill text="Accepted" tone="ok" />
                  <button onClick={() => run(`revoke-${accepted.id}`, () => api.revokeAuthorityDeputyship(accepted.id))} disabled={busy !== null}
                    className={`${btn} ml-auto`} style={quiet}>
                    {busy === `revoke-${accepted.id}` ? <Loader2 className="w-3 h-3 animate-spin" /> : <Ban className="w-3 h-3" />} Revoke
                  </button>
                </div>
              )}
              {pending.map(x => (
                <div key={x.id} className="text-[12px] rounded-lg px-3 py-2" style={{ ...soft, color: colors.inkMuted }}>
                  {`Waiting for ${x.deputy} to accept`}
                  {x.note && <span className="text-[11px]" style={{ color: colors.inkTertiary }}>{`. ${x.note}`}</span>}
                </div>
              ))}
              {declined.map(x => (
                <div key={x.id} className="text-[11.5px]" style={{ color: colors.inkTertiary }}>{`${x.deputy} declined to cover for you.`}</div>
              ))}
              {!accepted && pending.length === 0 && declined.length === 0 && (
                <div className="text-[12px]" style={{ color: colors.inkTertiary }}>You have not named a deputy.</div>
              )}
              <div className="grid grid-cols-1 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] gap-2 items-end pt-1">
                <Field label="Name a deputy">
                  <input value={name.deputy} onChange={e => setName({ ...name, deputy: e.target.value })} className={inputCls} style={inputStyle} placeholder="Their sign-in email" />
                </Field>
                <Field label="Note">
                  <input value={name.note} onChange={e => setName({ ...name, note: e.target.value })} className={inputCls} style={inputStyle} placeholder="Optional" />
                </Field>
                <button onClick={nameDeputy} disabled={busy !== null} className={`${btn} h-[30px]`} style={primary}>
                  {busy === 'name' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />} Ask
                </button>
              </div>
            </div>

            {/* Offered to me */}
            {(offered.length > 0 || deputyFor.length > 0) && (
              <div className="space-y-1.5">
                <div className="text-[11.5px] font-medium" style={{ color: colors.inkSubtle }}>Deputyships offered to me</div>
                {offered.map(x => (
                  <div key={x.id} className="flex items-center gap-2 flex-wrap rounded-lg px-3 py-2" style={soft}>
                    <span className="text-[12px] flex-1 min-w-[140px] break-words [overflow-wrap:anywhere]" style={{ color: colors.inkMuted }}>
                      {`${x.holder} asks you to cover for them`}
                      {x.note && <span className="text-[11px]" style={{ color: colors.inkTertiary }}>{`. ${x.note}`}</span>}
                    </span>
                    <button onClick={() => run(`accept-${x.id}`, () => api.respondToAuthorityDeputyship(x.id, true))} disabled={busy !== null}
                      className={btn} style={primary}>
                      {busy === `accept-${x.id}` ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />} Accept
                    </button>
                    <button onClick={() => run(`decline-${x.id}`, () => api.respondToAuthorityDeputyship(x.id, false))} disabled={busy !== null}
                      className={btn} style={quiet}>
                      {busy === `decline-${x.id}` ? <Loader2 className="w-3 h-3 animate-spin" /> : <X className="w-3 h-3" />} Decline
                    </button>
                  </div>
                ))}
                {deputyFor.map(x => (
                  <div key={x.id} className="text-[11.5px] break-words [overflow-wrap:anywhere]" style={{ color: colors.inkTertiary }}>{`You are the deputy for ${x.holder}.`}</div>
                ))}
              </div>
            )}

            {/* Handover */}
            <div className="space-y-1.5">
              <div className="text-[11.5px] font-medium" style={{ color: colors.inkSubtle }}>Handover</div>
              {open ? (
                <div className="rounded-lg px-3 py-2 space-y-1.5" style={{ background: colors.primary + '0f', border: `1px solid ${colors.primary}30` }}>
                  <div className="text-[12.5px] font-medium" style={{ color: colors.ink }}>
                    {`Handed over to ${open.deputy} ${sinceText(open)}`}
                  </div>
                  <div className="text-[12px]" style={{ color: colors.inkMuted }}>
                    {`${plural(Number(open.grant_count || 0), 'grant', 'grants')} lent to ${open.deputy}.`}
                  </div>
                  {Array.isArray(open.not_delegable) && open.not_delegable.length > 0 && (
                    <div className="text-[11px] leading-snug" style={{ color: colors.inkTertiary }}>
                      {`${plural(open.not_delegable.length, 'grant stayed', 'grants stayed')} with you because ${open.not_delegable.length === 1 ? 'it does' : 'they do'} not allow delegation.`}
                    </div>
                  )}
                  {Array.isArray(open.not_active) && open.not_active.length > 0 && (
                    <div className="text-[11px] leading-snug" style={{ color: colors.inkTertiary }}>
                      {`${plural(open.not_active.length, 'grant stayed', 'grants stayed')} with you because ${open.not_active.length === 1 ? 'it was' : 'they were'} not active (paused, suspended or expired).`}
                    </div>
                  )}
                  {open.reason && <div className="text-[11px]" style={{ color: colors.inkTertiary }}>{`Reason: ${open.reason}`}</div>}
                  {open.note && <div className="text-[11px] leading-snug" style={{ color: colors.inkTertiary }}>{open.note}</div>}
                  <button onClick={() => run('return', () => api.returnAuthorityHandover())} disabled={busy !== null} className={btn} style={primary}>
                    {busy === 'return' ? <Loader2 className="w-3 h-3 animate-spin" /> : <ArrowRight className="w-3 h-3" />} Return
                  </button>
                </div>
              ) : accepted ? (
                <div className="space-y-2">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    <Field label="Hand over while I am away">
                      <input value={ho.reason} onChange={e => setHo({ ...ho, reason: e.target.value })} className={inputCls} style={inputStyle} placeholder="Why you are away" />
                    </Field>
                    <Field label="Until (optional)">
                      <input type="datetime-local" value={ho.until} onChange={e => setHo({ ...ho, until: e.target.value })} className={inputCls} style={inputStyle} />
                    </Field>
                  </div>
                  <button onClick={handOver} disabled={busy !== null} className={btn} style={primary}>
                    {busy === 'handover' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Users className="w-3 h-3" />} {`Hand over to ${accepted.deputy}`}
                  </button>
                </div>
              ) : (
                <div className="text-[12px]" style={{ color: colors.inkTertiary }}>You can hand over once a deputy has accepted.</div>
              )}
              {covering.map(h => (
                <div key={h.id} className="rounded-lg px-3 py-2 text-[12px] break-words [overflow-wrap:anywhere]" style={{ ...soft, color: colors.inkMuted }}>
                  {`You are covering ${h.holder} ${sinceText(h)}.`}
                  <span className="text-[11px]" style={{ color: colors.inkTertiary }}>{` ${plural(Number(h.grant_count || 0), 'grant', 'grants')} lent to you.`}</span>
                </div>
              ))}
            </div>
          </>
        )}
        {error && <div className="text-[12px] leading-snug" style={{ color: colors.error }} role="alert">{error}</div>}
      </div>
    </div>
  );
}

// ── Portable records and trusted issuers ──────────────────────────────────────

function DeclaredView({ r }: { r: any }) {
  const { colors } = useTheme();
  const claims = r?.claims && typeof r.claims === 'object' && !Array.isArray(r.claims) ? Object.entries(r.claims) : [];
  const subject = r?.subject_kind === 'skill' ? humanize(r.subject_id) : (r?.subject_id || NOT_MEASURED);
  return (
    <div className="rounded-lg px-3 py-2 space-y-1.5" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[12.5px] font-medium min-w-0" style={{ color: colors.ink }}>{r?.issuer || NOT_MEASURED}</span>
        {r?.verified ? <Pill text="Signature verified" tone="ok" /> : <Pill text="Signature not verified" tone="bad" />}
        {r?.issuer_trusted_now ? <Pill text="Trusted issuer" tone="ok" /> : <Pill text="Not on your trusted list" tone="warn" />}
      </div>
      <div className="text-[11.5px]" style={{ color: colors.inkMuted }}>
        {`${humanize(r?.subject_kind) || 'Subject'}: ${subject}`}
        <span style={{ color: colors.inkTertiary }}>
          {`${r?.exported_at ? `. Exported ${timeAgo(r.exported_at)}` : ''}${r?.imported_at ? `, imported ${timeAgo(r.imported_at)}` : ''}${r?.imported_by ? ` by ${r.imported_by}` : ''}.`}
        </span>
      </div>
      {r?.newly_stored === false && <div className="text-[11px]" style={{ color: colors.inkTertiary }}>This record was already on file, so nothing new was stored.</div>}
      {r?.note && <div className="text-[11px] leading-snug" style={{ color: colors.inkTertiary }}>{r.note}</div>}
      {claims.length === 0 ? (
        <div className="text-[12px]" style={{ color: colors.inkTertiary }}>This record makes no claims.</div>
      ) : (
        <div>
          {claims.map(([k, c], i) => {
            const text = claimValueText(c);
            return (
              <div key={k} className="py-1 flex items-baseline justify-between gap-3 text-[12px]"
                style={{ borderTop: i === 0 ? undefined : `1px solid ${colors.hairline}`, color: colors.inkMuted }} title={claimTitle(c)}>
                <span className="min-w-0">{humanize(k)}</span>
                <span className="tabular-nums font-medium text-right" style={{ color: text === NOT_MEASURED ? colors.inkTertiary : colors.ink }}>{text}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function PortabilityPanel({ isAdmin }: { isAdmin: boolean }) {
  const { colors } = useTheme();
  const inputStyle = useInputStyle();
  const issuers = usePanel(() => api.listAuthorityIssuers(), { poll: false });
  const declared = usePanel(() => api.listAuthorityDeclared(), { poll: false });
  const [skill, setSkill] = useState('');
  const [exp, setExp] = useState<{ busy: boolean; token: string; copied: boolean; note: string; error: string | null }>(
    { busy: false, token: '', copied: false, note: '', error: null });
  const [tokenIn, setTokenIn] = useState('');
  const [imp, setImp] = useState<{ busy: boolean; result: any; error: string | null }>({ busy: false, result: null, error: null });
  const [openId, setOpenId] = useState<string | null>(null);
  const [newIssuer, setNewIssuer] = useState({ name: '', key: '', note: '' });
  const [issuerBusy, setIssuerBusy] = useState<string | null>(null);
  const [issuerError, setIssuerError] = useState<string | null>(null);

  // Operator and above only: a viewer's 403 (or an open-core 402) hides the whole panel.
  if (issuers.notice) return null;

  const btn = 'px-2.5 py-1 rounded-md text-[11.5px] font-semibold flex items-center gap-1.5 disabled:opacity-50';
  const quiet: React.CSSProperties = { background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` };
  const primary: React.CSSProperties = { background: colors.primary + '18', color: colors.primary };
  const head = 'text-[11.5px] font-medium';

  const doExport = async () => {
    const id = skill.trim();
    if (!id) { setExp(p => ({ ...p, error: 'Enter a skill id to export its track record.' })); return; }
    setExp({ busy: true, token: '', copied: false, note: '', error: null });
    try {
      const r = await api.getAuthorityTrackRecord({ skill_id: id });
      const token = String(r?.token || '');
      if (!token) throw new Error('No record came back for this skill.');
      let copied = false;
      try { await navigator.clipboard.writeText(token); copied = true; } catch { copied = false; }
      setExp({ busy: false, token, copied, note: r?.note || '', error: null });
    } catch (e: any) {
      setExp({ busy: false, token: '', copied: false, note: '', error: e?.message || 'The track record could not be exported.' });
    }
  };

  const doImport = async () => {
    const token = tokenIn.trim();
    if (!token) { setImp({ busy: false, result: null, error: 'Paste a track-record token to import.' }); return; }
    setImp({ busy: true, result: null, error: null });
    try {
      const r = await api.importAuthorityTrackRecord(token);
      setImp({ busy: false, result: r, error: null });
      declared.reload();
    } catch (e: any) {
      setImp({ busy: false, result: null, error: e?.message || 'The record could not be imported.' });
    }
  };

  const issuerRun = async (key: string, fn: () => Promise<unknown>, after?: () => void) => {
    setIssuerBusy(key); setIssuerError(null);
    try { await fn(); after?.(); await issuers.reload(); }
    catch (e: any) { setIssuerError(e?.message || 'That change was refused.'); }
    finally { setIssuerBusy(null); }
  };

  const addIssuer = () => {
    const n = newIssuer.name.trim(), k = newIssuer.key.trim();
    if (!n || !k) { setIssuerError('An issuer needs a name and its public key.'); return; }
    issuerRun('add', () => api.addAuthorityIssuer({ name: n, public_key_hex: k, note: newIssuer.note.trim() }), () => setNewIssuer({ name: '', key: '', note: '' }));
  };

  const issuerList = asList(issuers.data, 'issuers');
  const declaredList = asList(declared.data, 'declared');

  return (
    <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.hairline}`, background: colors.surface1 }}>
      <SectionHead title="Portable records and trusted issuers" />
      <div className="p-4 space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Export */}
          <div className="space-y-2 min-w-0">
            <div className={head} style={{ color: colors.inkSubtle }}>Export a track record</div>
            <div className="flex items-end gap-2">
              <Field label="Skill id" className="flex-1">
                <input value={skill} onChange={e => setSkill(e.target.value)} className={inputCls} style={inputStyle} placeholder="e.g. handle_refund_request" />
              </Field>
              <button onClick={doExport} disabled={exp.busy} className={`${btn} h-[30px]`} style={primary}>
                {exp.busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Download className="w-3 h-3" />} Export
              </button>
            </div>
            {exp.error && <div className="text-[12px]" style={{ color: colors.error }} role="alert">{exp.error}</div>}
            {exp.token && (
              <div className="space-y-1.5">
                {exp.copied ? (
                  <div className="flex items-center gap-1.5 text-[12px]" style={{ color: colors.success }}><Check className="w-3.5 h-3.5" /> Record copied to the clipboard.</div>
                ) : (
                  <div className="text-[11.5px]" style={{ color: colors.inkMuted }}>The clipboard was not available. Copy the record from here.</div>
                )}
                <input readOnly value={exp.token} onFocus={e => e.currentTarget.select()} aria-label="Signed track record"
                  className="w-full px-2 py-1 rounded-md text-[11px] font-mono focus:outline-none"
                  style={{ background: colors.inputBg, color: colors.ink, border: `1px solid ${colors.hairline}` }} />
              </div>
            )}
            {exp.note && <p className="text-[11px] leading-snug" style={{ color: colors.inkTertiary }}>{exp.note}</p>}
          </div>

          {/* Import */}
          <div className="space-y-2 min-w-0">
            <div className={head} style={{ color: colors.inkSubtle }}>Import a record</div>
            <textarea value={tokenIn} onChange={e => setTokenIn(e.target.value)} rows={3} aria-label="Track-record token"
              placeholder="Paste a signed track record from another workspace"
              className="w-full px-2.5 py-1.5 rounded-lg text-[11.5px] font-mono focus:outline-none resize-y" style={inputStyle} />
            <button onClick={doImport} disabled={imp.busy} className={btn} style={primary}>
              {imp.busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <KeyRound className="w-3 h-3" />} Import
            </button>
            {imp.error && <div className="text-[12px] leading-snug" style={{ color: colors.error }} role="alert">{imp.error}</div>}
          </div>
        </div>

        {imp.result && <DeclaredView r={imp.result} />}

        {/* Trusted issuers */}
        <div className="space-y-1.5">
          <div className={head} style={{ color: colors.inkSubtle }}>Trusted issuers</div>
          {issuers.loading && !issuers.data && <BrainLoading variant="compact" message="Reading trusted issuers…" />}
          {issuers.error && !issuers.data && <p className="text-[12px]" style={{ color: colors.error }} role="alert">{issuers.error}</p>}
          {issuers.data && issuerList.length === 0 && <div className="text-[12px]" style={{ color: colors.inkTertiary }}>No issuer is trusted yet, so imported records stay unverified.</div>}
          {issuerList.map((x, i) => (
            <div key={x.id} className="py-1.5 flex items-center gap-2 flex-wrap text-[12px]"
              style={{ borderTop: i === 0 ? undefined : `1px solid ${colors.hairline}`, color: colors.inkMuted }} title={x.note || undefined}>
              <span className="font-medium min-w-0 truncate" style={{ color: colors.ink }}>{x.name}</span>
              <span className="font-mono text-[11px]" style={{ color: colors.inkTertiary }}>{String(x.public_key_hex || '').slice(0, 16)}</span>
              <Pill text={x.active ? 'Active' : 'Revoked'} tone={x.active ? 'ok' : 'muted'} />
              {isAdmin && x.active && (
                <button onClick={() => issuerRun(`revoke-${x.id}`, () => api.revokeAuthorityIssuer(x.id))} disabled={issuerBusy !== null}
                  className={`${btn} ml-auto`} style={quiet}>
                  {issuerBusy === `revoke-${x.id}` ? <Loader2 className="w-3 h-3 animate-spin" /> : <Ban className="w-3 h-3" />} Revoke
                </button>
              )}
            </div>
          ))}
          {isAdmin && (
            <div className="rounded-lg p-3 space-y-2" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <Field label="Add issuer: name">
                  <input value={newIssuer.name} onChange={e => setNewIssuer({ ...newIssuer, name: e.target.value })} className={inputCls} style={inputStyle} />
                </Field>
                <Field label="Public key (hex)">
                  <input value={newIssuer.key} onChange={e => setNewIssuer({ ...newIssuer, key: e.target.value })} className={`${inputCls} font-mono`} style={inputStyle} />
                </Field>
              </div>
              <div className="flex items-end gap-2">
                <Field label="Note" className="flex-1">
                  <input value={newIssuer.note} onChange={e => setNewIssuer({ ...newIssuer, note: e.target.value })} className={inputCls} style={inputStyle} placeholder="Who this issuer is" />
                </Field>
                <button onClick={addIssuer} disabled={issuerBusy !== null} className={`${btn} h-[30px]`} style={primary}>
                  {issuerBusy === 'add' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />} Add issuer
                </button>
              </div>
            </div>
          )}
          {issuerError && <div className="text-[12px] leading-snug" style={{ color: colors.error }} role="alert">{issuerError}</div>}
        </div>

        {/* Declared records */}
        <div className="space-y-1.5">
          <div className={head} style={{ color: colors.inkSubtle }}>Declared records</div>
          {declared.loading && !declared.data && <BrainLoading variant="compact" message="Reading declared records…" />}
          {declared.error && !declared.data && <p className="text-[12px]" style={{ color: colors.error }} role="alert">{declared.error}</p>}
          {declared.data && declaredList.length === 0 && <div className="text-[12px]" style={{ color: colors.inkTertiary }}>No record has been imported yet.</div>}
          {declaredList.slice(0, 20).map((x, i) => (
            <div key={x.id} style={{ borderTop: i === 0 ? undefined : `1px solid ${colors.hairline}` }}>
              <button onClick={() => setOpenId(openId === x.id ? null : x.id)} aria-expanded={openId === x.id}
                className="w-full py-1.5 flex items-center gap-2 flex-wrap text-[12px] text-left" style={{ color: colors.inkMuted }}>
                {openId === x.id ? <ChevronUp className="w-3 h-3 shrink-0" /> : <ChevronDown className="w-3 h-3 shrink-0" />}
                <span className="font-medium min-w-0 break-words [overflow-wrap:anywhere]" style={{ color: colors.ink }}>{x.issuer || NOT_MEASURED}</span>
                <span className="min-w-0 truncate flex-1">{x.subject_kind === 'skill' ? humanize(x.subject_id) : x.subject_id}</span>
                <span className="text-[11px]" style={{ color: colors.inkTertiary }}>{x.imported_at ? `Imported ${timeAgo(x.imported_at)}` : ''}</span>
                {x.verified ? <Pill text="Verified" tone="ok" /> : <Pill text="Not verified" tone="bad" />}
              </button>
              {openId === x.id && <div className="pb-2"><DeclaredView r={x} /></div>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Authority() {
  const { colors } = useTheme();
  const { isAdmin } = useAuth();
  const settings = usePanel(() => api.getAuthoritySettings(), { poll: false });
  const exposure = usePanel(() => api.getAuthorityExposure());
  // The workspace ledger is operator+; a viewer's 403 simply hides its card.
  const ledger = usePanel(() => api.getAuthorityLedger(1));
  const lendRef = useRef<HTMLDivElement>(null);
  const [modeBusy, setModeBusy] = useState(false);
  const [confirmEnforce, setConfirmEnforce] = useState(false);
  const [confirmReady, setConfirmReady] = useState(false);
  // Enforce is armed only by a deliberate second step: the confirm button stays
  // disabled for a moment after it appears so a double click cannot arm it.
  useEffect(() => {
    setConfirmReady(false);
    if (!confirmEnforce) return;
    const t = setTimeout(() => setConfirmReady(true), 1500);
    return () => clearTimeout(t);
  }, [confirmEnforce]);
  const [modeError, setModeError] = useState<string | null>(null);
  const [pauseBusy, setPauseBusy] = useState(false);

  const reloadAll = () => { exposure.reload(); ledger.reload(); settings.reload(); };

  const x: any = exposure.data || {};
  const me: string | null = x.holder || null;

  // My grants: delegated-to-me first, then the rest, no duplicates.
  const grants: any[] = useMemo(() => {
    const seen = new Set<string>();
    const out: any[] = [];
    for (const g of [...(x.pending_acceptance || []), ...(x.grants || [])]) {
      if (g?.id && !seen.has(g.id)) { seen.add(g.id); out.push(g); }
    }
    return out;
  }, [x.pending_acceptance, x.grants]);

  const feed: any[] = useMemo(() => {
    const seen = new Set<string>();
    const out: any[] = [];
    for (const u of [...(x.in_flight || []), ...(x.recent || [])]) {
      if (u?.id && !seen.has(u.id)) { seen.add(u.id); out.push(u); }
    }
    return out.slice(0, 20);
  }, [x.in_flight, x.recent]);

  // Ring: today's reserved money over the money limits lent; else actions.
  const ring = useMemo(() => {
    const active = grants.filter(g => g.state === 'active');
    const cur: string = active[0]?.limits?.currency || '';
    const moneyLimit = active.filter(g => g.limits?.window_amount != null && g.limits?.currency === cur)
      .reduce((s, g) => s + Number(g.limits.window_amount), 0);
    const actionLimit = active.reduce((s, g) => s + (g.limits?.window_actions != null ? Number(g.limits.window_actions) : 0), 0);
    const hasMoney = active.some(g => g.limits?.window_amount != null && g.limits?.currency === cur);
    const hasActions = active.some(g => g.limits?.window_actions != null);
    if (hasMoney && moneyLimit > 0) {
      const used = Number(x.today?.amount || 0);
      return { fraction: used / moneyLimit, caption: `${moneyText(used, cur)} reserved of ${moneyText(moneyLimit, cur)} lent`, cur };
    }
    if (hasActions && actionLimit > 0) {
      const used = active.reduce((s, g) => s + Number(g.headroom?.actions_reserved || 0), 0);
      return { fraction: used / actionLimit, caption: `${used} of ${actionLimit} actions reserved`, cur };
    }
    return { fraction: 0, caption: 'No limits lent yet', cur };
  }, [grants, x.today]);

  const mode: string | null = settings.data?.mode || x.mode || null;
  const canToggle = isAdmin && !!settings.data && !settings.notice && !settings.error;

  const switchMode = async () => {
    const next = mode === 'enforce' ? 'observe' : 'enforce';
    if (next === 'enforce' && (!confirmEnforce || !confirmReady)) { setConfirmEnforce(true); return; }
    setModeBusy(true); setModeError(null);
    try { await api.setAuthorityMode(next); setConfirmEnforce(false); reloadAll(); }
    catch (e: any) { setModeError(e?.message || 'The mode was not changed.'); }
    finally { setModeBusy(false); }
  };

  const pauseOrResume = async (resume: boolean) => {
    setPauseBusy(true); setModeError(null);
    try {
      if (resume) await api.resumeMyAuthority(); else await api.pauseMyAuthority();
      reloadAll();
    } catch (e: any) {
      setModeError(e?.message || (resume ? 'Your authority was not resumed.' : 'Your authority was not paused.'));
    } finally { setPauseBusy(false); }
  };

  const focusLend = () => {
    lendRef.current?.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'nearest' });
    document.getElementById('authority-dept')?.focus();
  };

  if (exposure.loading) return <div className={PAGE_PAD}><BrainLoading message="Reading what runs under your name…" /></div>;
  if (exposure.notice) return <div className={PAGE_PAD}><EnterpriseNotice message={exposure.notice} /></div>;
  if (exposure.error && !exposure.data) return <div className={PAGE_PAD}><BrainError message={exposure.error} onRetry={exposure.reload} /></div>;

  const today = x.today || {};
  const showUnlent = !!ledger.data && !ledger.notice && !ledger.error;
  const unlent = Number(ledger.data?.by_status?.unlent || 0);
  const btnQuiet: React.CSSProperties = { background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` };
  const suspendedCount = grants.filter(g => g.state === 'suspended').length;
  const pausedByMe = grants.some(g => g.state === 'suspended' && g.suspend_reason === 'paused by the holder' && (!me || g.holder === me));
  const anyActive = grants.some(g => g.state === 'active' && (!me || g.holder === me));

  return (
    <div className={`h-full overflow-y-auto lg:overflow-hidden flex flex-col gap-3 ${PAGE_PAD}`} style={{ background: colors.canvas, color: colors.ink }}>
      <style>{`
        @keyframes authority-pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: .35; transform: scale(.7); } }
        .authority-pulse { animation: authority-pulse 1.4s ease-in-out infinite; }
        @media (prefers-reduced-motion: reduce) { .authority-pulse { animation: none; } }
      `}</style>

      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap shrink-0">
        <div className="min-w-0">
          <h1 className="text-[21px] font-semibold tracking-tight">Authority</h1>
          <p className="text-[12.5px] mt-0.5" style={{ color: colors.inkSubtle }}>What runs under your name, and on whose signature.</p>
        </div>
        <div className="flex items-center gap-4 flex-wrap">
          <ExposureRing fraction={ring.fraction} caption={ring.caption} />
          <div className="flex items-center gap-2 flex-wrap">
            {mode && (
              <span title={settings.data?.note || undefined}>
                <Pill text={mode === 'enforce' ? 'Enforce mode' : 'Observe mode'} tone={mode === 'enforce' ? 'primary' : 'muted'} />
              </span>
            )}
            {canToggle && (
              <>
                {!(mode !== 'enforce' && confirmEnforce) ? (
                  <button onClick={switchMode} disabled={modeBusy}
                    className="px-2.5 py-1.5 rounded-lg text-[11.5px] font-semibold flex items-center gap-1.5 disabled:opacity-50" style={btnQuiet}>
                    {modeBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : mode === 'enforce' ? <Unlock className="w-3 h-3" /> : <Lock className="w-3 h-3" />}
                    {mode === 'enforce' ? 'Switch to observe' : 'Switch to enforce'}
                  </button>
                ) : (
                  <div className="flex items-center gap-2 flex-wrap rounded-lg px-2.5 py-1.5" role="group" aria-label="Confirm enforce mode"
                    style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
                    <span className="text-[11.5px] leading-snug max-w-[320px]" style={{ color: colors.inkMuted }}>
                      Enforce mode sends every run that has no lent signature to a human for approval instead of letting it proceed.
                    </span>
                    <button onClick={switchMode} disabled={modeBusy || !confirmReady}
                      className="px-2.5 py-1.5 rounded-lg text-[11.5px] font-semibold flex items-center gap-1.5 disabled:opacity-50" style={{ background: colors.primary, color: '#fff' }}>
                      {modeBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Lock className="w-3 h-3" />}
                      {confirmReady ? 'Confirm enforce' : 'Confirm enforce (wait)'}
                    </button>
                    <button onClick={() => setConfirmEnforce(false)} className="px-2 py-1.5 rounded-lg text-[11.5px]" style={{ color: colors.inkSubtle }}>Cancel</button>
                  </div>
                )}
              </>
            )}
            {(pausedByMe || anyActive) && (
              <button onClick={() => pauseOrResume(pausedByMe)} disabled={pauseBusy}
                className="px-2.5 py-1.5 rounded-lg text-[11.5px] font-semibold flex items-center gap-1.5 disabled:opacity-50" style={btnQuiet}>
                {pauseBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : pausedByMe ? <PlayCircle className="w-3.5 h-3.5" /> : <PauseCircle className="w-3.5 h-3.5" />}
                {pausedByMe ? 'Resume my authority' : 'Pause all my authority'}
              </button>
            )}
            <button onClick={focusLend}
              className="px-3 py-1.5 rounded-lg text-[12px] font-semibold flex items-center gap-1.5" style={{ background: colors.primary, color: '#fff' }}>
              <PenLine className="w-3.5 h-3.5" /> Lend authority
            </button>
          </div>
        </div>
      </div>
      <RefreshFailed show={!!(exposure.staleError || ledger.staleError)} />
      {modeError && <div className="text-[12px] shrink-0" style={{ color: colors.error }} role="alert">{modeError}</div>}

      {/* Stats */}
      <div className={`grid grid-cols-2 ${showUnlent ? 'lg:grid-cols-5' : 'lg:grid-cols-4'} gap-3 shrink-0`}>
        <Stat label="Active grants" value={numText(x.totals?.active_grants)} />
        <Stat label="Reserved today"
          value={today.amount == null ? NOT_MEASURED : (ring.cur ? moneyText(today.amount, ring.cur) : numText(today.amount))}
          note={ring.cur ? undefined : 'No money limit lent yet'} />
        <Stat label="Runs today" value={numText(today.runs)}
          note={`${numText(today.used)} used, ${numText(today.released)} released`} />
        <Stat label="In flight" value={numText(today.in_flight)}
          note={suspendedCount > 0 ? `${suspendedCount} suspended` : undefined} />
        {showUnlent && <Stat label="Nobody's authority" value={numText(unlent)} note="runs with no lent signature, workspace-wide" />}
      </div>

      {/* Main grid: two contained scrollers */}
      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] gap-4 lg:flex-1 lg:min-h-0">
        <div className="space-y-4 min-w-0 lg:min-h-0 lg:overflow-y-auto lg:pr-1">
          <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.hairline}`, background: colors.surface1 }}>
            <SectionHead title="My grants" right={<span>{`${grants.length} shown`}</span>} />
            {grants.length === 0 ? (
              <div className="p-6">
                <BrainEmpty title="Nothing runs under your name yet" action="Lend authority on the right to let a skill act on its own, within your limits." />
              </div>
            ) : grants.map(g => <GrantCard key={g.id} g={g} me={me} onChanged={reloadAll} />)}
          </div>

          <ReviewQuality />

          <BalancePanel />

          <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.hairline}`, background: colors.surface1 }}>
            <SectionHead title="Running under my name" right={<span>Refreshes on its own</span>} />
            {feed.length === 0 ? (
              <div className="px-4 py-5 text-[12.5px]" style={{ color: colors.inkTertiary }}>Nothing has run under your authority yet.</div>
            ) : feed.map(u => <FeedRow key={u.id} u={u} onChanged={reloadAll} />)}
          </div>

          <PortabilityPanel isAdmin={isAdmin} />
        </div>

        <div className="min-w-0 space-y-4 lg:min-h-0 lg:overflow-y-auto lg:pr-1">
          <LendPanel onLent={reloadAll} sectionRef={lendRef} fallbackCurrency={ring.cur} />
          <DeputiesPanel onChanged={reloadAll} />
        </div>
      </div>
    </div>
  );
}
