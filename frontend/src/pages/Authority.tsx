import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  PenLine, Loader2, Lock, Unlock, ChevronDown, ChevronUp, Check, X, ArrowRight, Share2, Ban, Sparkles,
  PauseCircle, PlayCircle, KeyRound, History,
} from 'lucide-react';
import { api } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { useAuth } from '../context/AuthContext';
import { BrainLoading, BrainError, BrainEmpty } from '../components/BrainStates';
import { EnterpriseNotice } from '../components/EnterpriseNotice';
import { useEnterprisePanel as usePanel } from '../hooks/useEnterprisePanel';
import { humanize } from '../lib/format';
import { timeAgo } from '../lib/time';
import { PAGE_PAD } from '../lib/layout';
import { DEPARTMENTS, DEPARTMENT_LABELS, type DepartmentSlug } from '../lib/departments';

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
            <span className="text-[12px]" style={{ color: colors.inkMuted }}>{`Waiting for ${g.holder} to accept`}</span>
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

      {error && <div className="text-[12px]" style={{ color: colors.error }}>{error}</div>}
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
    setState(prev => ({ ...prev, loading: true, error: null }));
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
  if (state.error) return <p className="text-[12px]" style={{ color: colors.error }}>{state.error}</p>;
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
  const rq = usePanel(() => api.getAuthorityReviewers(90));
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
        {rq.error && !d && <p className="text-[12px]" style={{ color: colors.error }}>{rq.error}</p>}
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
                      <td className="py-1.5 pr-3 max-w-[200px] truncate" style={{ color: colors.ink }} title={x.approver || undefined}>{x.approver || NOT_MEASURED}</td>
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
};

function LendPanel({ onLent, sectionRef, fallbackCurrency }: {
  onLent: () => void; sectionRef: React.RefObject<HTMLDivElement | null>; fallbackCurrency: string;
}) {
  const { colors } = useTheme();
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
              <input type="number" min={1} value={f.expires_in_days} onChange={e => set({ expires_in_days: e.target.value })} className={inputCls} style={inputStyle} placeholder="Blank for no expiry" />
            </Field>
          </div>
          <Field label="Tripwire: suspend after N adverse runs">
            <input type="number" min={1} value={f.tripwire} onChange={e => set({ tripwire: e.target.value })} className={inputCls} style={inputStyle} placeholder="Blank for no tripwire" />
            <span className="block text-[11px] mt-1 leading-snug" style={{ color: colors.inkTertiary }}>
              An adverse run under this grant suspends it and tells you. You resume it after looking.
            </span>
          </Field>
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
        className="ml-auto px-2 py-0.5 rounded-md text-[11px] font-semibold flex items-center gap-1 disabled:opacity-50"
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

function FeedRow({ u }: { u: any }) {
  const { colors } = useTheme();
  const st = USE_STATUS[u.status] || { label: humanize(u.status), tone: 'muted' as Tone };
  const settled = u.status === 'used' || u.status === 'released';
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
      {(u.status === 'used' || u.status === 'reserved') && u.execution_id && <TokenButton executionId={u.execution_id} />}
      {u.status === 'unlent' && (
        <span className="basis-full text-[11px] pl-[68px]" style={{ color: colors.inkTertiary }}>
          No one lent a signature for this run{u.reason ? '. Hover for the reason.' : '.'}
        </span>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Authority() {
  const { colors } = useTheme();
  const { isAdmin } = useAuth();
  const settings = usePanel(() => api.getAuthoritySettings());
  const exposure = usePanel(() => api.getAuthorityExposure());
  // The workspace ledger is operator+; a viewer's 403 simply hides its card.
  const ledger = usePanel(() => api.getAuthorityLedger(1));
  const lendRef = useRef<HTMLDivElement>(null);
  const [modeBusy, setModeBusy] = useState(false);
  const [confirmEnforce, setConfirmEnforce] = useState(false);
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
    if (next === 'enforce' && !confirmEnforce) { setConfirmEnforce(true); return; }
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
  if (exposure.error) return <div className={PAGE_PAD}><BrainError message={exposure.error} onRetry={exposure.reload} /></div>;

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
                <button onClick={switchMode} disabled={modeBusy}
                  className="px-2.5 py-1.5 rounded-lg text-[11.5px] font-semibold flex items-center gap-1.5 disabled:opacity-50" style={btnQuiet}>
                  {modeBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : mode === 'enforce' ? <Unlock className="w-3 h-3" /> : <Lock className="w-3 h-3" />}
                  {mode === 'enforce' ? 'Switch to observe' : confirmEnforce ? 'Confirm: send unlent runs to a human' : 'Switch to enforce'}
                </button>
                {confirmEnforce && (
                  <button onClick={() => setConfirmEnforce(false)} className="px-2 py-1.5 rounded-lg text-[11.5px]" style={{ color: colors.inkSubtle }}>Cancel</button>
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
      {modeError && <div className="text-[12px] shrink-0" style={{ color: colors.error }}>{modeError}</div>}

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

          <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.hairline}`, background: colors.surface1 }}>
            <SectionHead title="Running under my name" right={<span>Refreshes on its own</span>} />
            {feed.length === 0 ? (
              <div className="px-4 py-5 text-[12.5px]" style={{ color: colors.inkTertiary }}>Nothing has run under your authority yet.</div>
            ) : feed.map(u => <FeedRow key={u.id} u={u} />)}
          </div>
        </div>

        <div className="min-w-0 lg:min-h-0 lg:overflow-y-auto lg:pr-1">
          <LendPanel onLent={reloadAll} sectionRef={lendRef} fallbackCurrency={ring.cur} />
        </div>
      </div>
    </div>
  );
}
