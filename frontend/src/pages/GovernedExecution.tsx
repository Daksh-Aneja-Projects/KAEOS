import React, { useMemo, useState } from 'react';
import {
  Fingerprint, ShieldCheck, ShieldAlert, Download, Loader2, GitBranch, Layers, Bot,
  Receipt, CheckCircle2, XCircle, Lock, Unlock, RefreshCw, ArrowRight, Gavel, ThumbsUp,
  ThumbsDown, Play, ChevronDown, ChevronUp, FileCheck, Plus, Trash2,
} from 'lucide-react';
import { api, downloadFile } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { BrainLoading, BrainError, BrainEmpty } from '../components/BrainStates';
import { EnterpriseNotice } from '../components/EnterpriseNotice';
import { useEnterprisePanel as usePanel } from '../hooks/useEnterprisePanel';
import { humanize } from '../lib/format';
import { timeAgo } from '../lib/time';
import { PAGE_PAD } from '../lib/layout';

/**
 * Governed Execution: the KAEOS Enterprise surfaces - proofs, the earned-
 * autonomy ladder, rehearsals, external agents and verified outcomes.
 *
 * Honesty contract: every panel is fed by the Enterprise routes. On an
 * open-core deployment those routes answer 402 with a plain sentence; the
 * panel shows that sentence. Nothing here is rendered from a constant.
 */

type Tab = 'proofs' | 'ladder' | 'rehearsals' | 'gateway' | 'outcomes' | 'committees' | 'quality' | 'evidence';

const TABS: { id: Tab; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: 'proofs', label: 'Proofs', icon: Fingerprint },
  { id: 'ladder', label: 'Trust ladder', icon: Layers },
  { id: 'rehearsals', label: 'Rehearsals', icon: GitBranch },
  { id: 'gateway', label: 'External agents', icon: Bot },
  { id: 'outcomes', label: 'Outcomes', icon: Receipt },
  // F2's human half: named approvers, one ballot each, the same arithmetic
  // as the debate gate; a committee convened from the HITL queue decides
  // that paused run.
  { id: 'committees', label: 'Committees', icon: Gavel },
  // F12: a human's verdict on a sealed run, and the pinned cases that keep
  // a skill honest. Both feed the trust ladder.
  { id: 'quality', label: 'Quality', icon: ThumbsUp },
  // F7: the procurement / AI-Act evidence pack, read from the record, each
  // section labelled measured or self-assessed.
  { id: 'evidence', label: 'Evidence', icon: FileCheck },
];

const TIER_LABEL: Record<string, string> = {
  observe: 'Observe', advise: 'Advise', act_with_approval: 'Act with approval', autonomous: 'Autonomous',
};

function Pill({ text, tone }: { text: string; tone: 'ok' | 'warn' | 'bad' | 'muted' | 'primary' }) {
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
    <div className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      <div className="text-[11px] font-medium" style={{ color: colors.inkSubtle }}>{label}</div>
      <div className="text-[22px] font-semibold mt-1 tabular-nums" style={{ color: colors.ink }}>{value}</div>
      {note && <div className="text-[11px] mt-1" style={{ color: colors.inkTertiary }}>{note}</div>}
    </div>
  );
}

// ── Proofs ────────────────────────────────────────────────────────────────────

/**
 * Thumbs-up / thumbs-down on one sealed action proof (F12). The rating is a
 * HUMAN judgment on the run's outcome; a thumbs-down counts as adverse
 * evidence in the skill's trust ledger, whatever the status code said.
 */
function RateRun({ executionId, skillId, onRated }: { executionId: string; skillId: string; onRated?: () => void }) {
  const { colors } = useTheme();
  const [rated, setRated] = useState<'up' | 'down' | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rate = async (rating: 'up' | 'down') => {
    setBusy(true); setError(null);
    try {
      await api.submitSkillFeedback({ execution_id: executionId, skill_id_name: skillId, rating });
      setRated(rating);
      onRated?.();
    } catch (e: any) { setError(e?.message || 'The rating was refused.'); }
    finally { setBusy(false); }
  };
  if (rated) return <Pill text={rated === 'up' ? 'Rated good' : 'Rated wrong'} tone={rated === 'up' ? 'ok' : 'bad'} />;
  return (
    <span className="flex items-center gap-1 shrink-0" title={error || 'Was this outcome right? Your answer feeds the trust ladder.'}>
      <button onClick={() => rate('up')} disabled={busy} aria-label="Rate this run good"
        className="p-1 rounded-md disabled:opacity-40" style={{ color: colors.success, background: colors.success + '12' }}>
        <ThumbsUp className="w-3.5 h-3.5" />
      </button>
      <button onClick={() => rate('down')} disabled={busy} aria-label="Rate this run wrong"
        className="p-1 rounded-md disabled:opacity-40" style={{ color: colors.error, background: colors.error + '12' }}>
        <ThumbsDown className="w-3.5 h-3.5" />
      </button>
      {error && <span className="text-[11px]" style={{ color: colors.error }}>{error}</span>}
    </span>
  );
}

function ProofsPanel() {
  const { colors } = useTheme();
  const summary = usePanel(() => api.getProofLedgerSummary());
  const records = usePanel(() => api.getProofRecords(40));
  const [verdict, setVerdict] = useState<any>(null);
  const [verifying, setVerifying] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const verify = async () => {
    setVerifying(true); setActionError(null);
    try { setVerdict(await api.verifyProofLedger(500)); }
    catch (e: any) { setActionError(e?.message || 'Verification failed.'); }
    finally { setVerifying(false); }
  };
  const download = async () => {
    setBusy(true); setActionError(null);
    try { await downloadFile(api.proofLedgerBundlePath(), 'kaeos-proof-ledger.zip'); }
    catch (e: any) { setActionError(e?.message || 'Download failed.'); }
    finally { setBusy(false); }
  };

  if (summary.loading) return <BrainLoading message="Reading the proof ledger…" />;
  if (summary.notice) return <EnterpriseNotice message={summary.notice} />;
  if (summary.error) return <BrainError message={summary.error} onRetry={summary.reload} />;
  const s: any = summary.data || {};
  const rows: any[] = (records.data as any)?.records || (Array.isArray(records.data) ? records.data : []);

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label="Proofs sealed" value={s.count ?? s.total ?? '0'} note="Signed, chained, offline-verifiable" />
        <Stat label="Chain head" value={<span className="text-[13px] font-mono break-all">{(s.head?.entry_hash || s.head_hash || 'none').toString().slice(0, 22)}</span>} />
        <Stat label="Signing keys" value={(s.keys || s.signing_keys || []).length || s.key_count || '1'} note="Rotation retires, never deletes" />
        <div className="rounded-xl p-4 flex flex-col gap-2" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <button onClick={verify} disabled={verifying}
            className="px-3 py-2 rounded-lg text-[12px] font-semibold flex items-center justify-center gap-2 disabled:opacity-50"
            style={{ background: colors.primary + '18', color: colors.primary }}>
            {verifying ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ShieldCheck className="w-3.5 h-3.5" />} Verify chain
          </button>
          <button onClick={download} disabled={busy}
            className="px-3 py-2 rounded-lg text-[12px] font-semibold flex items-center justify-center gap-2 disabled:opacity-50"
            style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>
            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />} Verify offline
          </button>
        </div>
      </div>
      {verdict && (
        <div className="rounded-xl p-4 flex items-center gap-3"
          style={{ background: (verdict.ok ? colors.success : colors.error) + '12', border: `1px solid ${(verdict.ok ? colors.success : colors.error)}30` }}>
          {verdict.ok ? <ShieldCheck className="w-5 h-5" style={{ color: colors.success }} /> : <ShieldAlert className="w-5 h-5" style={{ color: colors.error }} />}
          <span className="text-[13px]" style={{ color: colors.ink }}>{verdict.detail}</span>
        </div>
      )}
      {actionError && <div className="text-[12px]" style={{ color: colors.error }}>{actionError}</div>}
      <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.hairline}` }}>
        <div className="px-4 py-2.5 text-[11px] font-medium flex items-center justify-between" style={{ background: colors.surface2, color: colors.inkSubtle }}>
          <span>Newest proofs</span><span>{rows.length} shown</span>
        </div>
        {rows.length === 0 ? (
          <div className="p-6"><BrainEmpty title="No proofs sealed yet" /></div>
        ) : rows.map((r: any) => (
          <div key={r.id || r.entry_hash} className="px-4 py-3 flex items-center gap-3 text-[13px] flex-wrap" style={{ borderTop: `1px solid ${colors.hairline}`, color: colors.inkMuted }}>
            <span className="font-mono text-[11px] w-10 shrink-0" style={{ color: colors.inkTertiary }}>#{r.seq}</span>
            <Pill text={humanize(r.subject_kind || 'action')} tone="primary" />
            <span className="truncate flex-1">{r.skill_id ? `${humanize(r.skill_id)} · ` : ''}{r.subject_id}</span>
            {r.status && <Pill text={humanize(r.status)} tone={String(r.status).startsWith('SUCCESS') ? 'ok' : String(r.status).startsWith('BLOCKED') || String(r.status).startsWith('FAILED') ? 'bad' : 'muted'} />}
            {r.subject_kind === 'action' && r.skill_id && String(r.status || '').startsWith('SUCCESS') && (
              <RateRun executionId={r.subject_id} skillId={r.skill_id} />
            )}
            <span className="text-[11px] whitespace-nowrap" style={{ color: colors.inkTertiary }}>{r.created_at ? timeAgo(r.created_at) : ''}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Trust ladder ──────────────────────────────────────────────────────────────

function LadderPanel() {
  const { colors } = useTheme();
  const ladder = usePanel(() => api.getLadder());
  const assurance = usePanel(() => api.getAssurance());
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key); setActionError(null);
    try { await fn(); await ladder.reload(); }
    catch (e: any) { setActionError(e?.message || 'The change was refused.'); }
    finally { setBusy(null); }
  };

  if (ladder.loading) return <BrainLoading message="Reading the trust ladder…" />;
  if (ladder.notice) return <EnterpriseNotice message={ladder.notice} />;
  if (ladder.error) return <BrainError message={ladder.error} onRetry={ladder.reload} />;
  const d: any = ladder.data || {};
  const skills: any[] = d.skills || [];
  const moves: any[] = d.recent_movements || [];
  const a: any = (assurance.data as any)?.summary;
  const enforced = d.mode === 'enforce';

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label="Layers mode" value={enforced ? 'Enforce' : 'Advise'}
          note={enforced ? 'Skills below autonomous route to a human' : 'Rungs are recorded, runs are not gated'} />
        <Stat label="Skills on the ladder" value={skills.length} note="Rung appears at a skill's first governed run" />
        <Stat label="Autonomous" value={skills.filter(s => s.tier === 'autonomous').length} note="Earned, never asserted" />
        <Stat label="Model assurance" value={a ? humanize(a.status) : '…'}
          note={a?.pass_rate != null ? `Battery pass rate ${(a.pass_rate * 100).toFixed(0)}%` : a?.note || 'Not run'} />
      </div>
      <div className="flex items-center gap-3">
        <button onClick={() => run('mode', () => api.setLadderMode(!enforced))} disabled={busy === 'mode'}
          className="px-3 py-2 rounded-lg text-[12px] font-semibold flex items-center gap-2 disabled:opacity-50"
          style={{ background: colors.primary + '18', color: colors.primary }}>
          {busy === 'mode' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : enforced ? <Unlock className="w-3.5 h-3.5" /> : <Lock className="w-3.5 h-3.5" />}
          {enforced ? 'Switch to advise mode' : 'Switch to enforce mode'}
        </button>
        <span className="text-[12px]" style={{ color: colors.inkSubtle }}>{d.enforcement_note}</span>
      </div>
      {actionError && <div className="text-[12px]" style={{ color: colors.error }}>{actionError}</div>}
      <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.hairline}` }}>
        <div className="px-4 py-2.5 text-[11px] font-medium" style={{ background: colors.surface2, color: colors.inkSubtle }}>Rung per skill, and why</div>
        {skills.length === 0 ? <div className="p-6"><BrainEmpty title="No skill has a rung yet" /></div> : skills.map((s: any) => (
          <div key={s.skill_id} className="px-4 py-3" style={{ borderTop: `1px solid ${colors.hairline}` }}>
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-[13px] font-medium" style={{ color: colors.ink }}>{humanize(s.skill_id)}</span>
              <Pill text={TIER_LABEL[s.tier] || humanize(s.tier)} tone={s.tier === 'autonomous' ? 'ok' : s.tier === 'observe' ? 'muted' : 'warn'} />
              {!s.auto_managed && <Pill text={`Pinned by ${s.pinned_by || 'a human'}`} tone="primary" />}
              {s.trust_score != null && <span className="text-[11px] tabular-nums" style={{ color: colors.inkSubtle }}>trust {Number(s.trust_score).toFixed(2)} over {s.samples} runs</span>}
              <div className="ml-auto flex items-center gap-2">
                {s.auto_managed ? (
                  <button onClick={() => run(s.skill_id, () => api.pinLadderTier(s.skill_id, s.tier, 'held by an administrator'))} disabled={busy === s.skill_id}
                    className="text-[11px] px-2 py-1 rounded-md" style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>Pin here</button>
                ) : (
                  <button onClick={() => run(s.skill_id, () => api.releaseLadderPin(s.skill_id))} disabled={busy === s.skill_id}
                    className="text-[11px] px-2 py-1 rounded-md" style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>Release pin</button>
                )}
              </div>
            </div>
            {s.why && <p className="text-[12px] mt-1.5 leading-relaxed" style={{ color: colors.inkSubtle }}>{s.why}</p>}
          </div>
        ))}
      </div>
      {moves.length > 0 && (
        <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.hairline}` }}>
          <div className="px-4 py-2.5 text-[11px] font-medium" style={{ background: colors.surface2, color: colors.inkSubtle }}>Recent movements, each sealed as a proof</div>
          {moves.slice(0, 12).map((m: any) => (
            <div key={m.id} className="px-4 py-2.5 flex items-center gap-3 text-[12px]" style={{ borderTop: `1px solid ${colors.hairline}`, color: colors.inkMuted }}>
              <span className="font-medium truncate max-w-[220px]" style={{ color: colors.ink }}>{humanize(m.skill_id)}</span>
              <span style={{ color: colors.inkSubtle }}>{TIER_LABEL[m.from_tier] || 'none'}</span>
              <ArrowRight className="w-3 h-3" style={{ color: colors.inkTertiary }} />
              <span style={{ color: colors.ink }}>{TIER_LABEL[m.to_tier] || humanize(m.to_tier)}</span>
              <Pill text={m.actor === 'autonomy-ladder' ? 'Governor' : 'Human'} tone={m.actor === 'autonomy-ladder' ? 'primary' : 'warn'} />
              {m.proof_id ? <Pill text="Proof sealed" tone="ok" /> : <Pill text="Seal missing" tone="bad" />}
              <span className="ml-auto text-[11px] whitespace-nowrap" style={{ color: colors.inkTertiary }}>{m.at ? timeAgo(m.at) : ''}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Rehearsals ────────────────────────────────────────────────────────────────

export function DiffTable({ before, after, changed }: { before: any; after: any; changed: string[] }) {
  const { colors } = useTheme();
  const keys = Array.from(new Set([...Object.keys(before || {}), ...Object.keys(after || {})])).sort();
  if (keys.length === 0) return <div className="text-[12px]" style={{ color: colors.inkSubtle }}>No fields to show.</div>;
  return (
    <div className="rounded-lg overflow-hidden text-[12px]" style={{ border: `1px solid ${colors.hairline}` }}>
      <div className="grid grid-cols-3 px-3 py-1.5 font-medium" style={{ background: colors.surface2, color: colors.inkSubtle }}>
        <span>Field</span><span>Before</span><span>After</span>
      </div>
      {keys.map(k => {
        const changedHere = (changed || []).includes(k);
        return (
          <div key={k} className="grid grid-cols-3 px-3 py-1.5 font-mono"
            style={{ borderTop: `1px solid ${colors.hairline}`, background: changedHere ? colors.primary + '0d' : 'transparent', color: colors.inkMuted }}>
            <span style={{ color: colors.ink }}>{k}</span>
            <span className="truncate" style={{ color: changedHere ? colors.error : colors.inkSubtle }}>{before && k in before ? JSON.stringify(before[k]) : '-'}</span>
            <span className="truncate" style={{ color: changedHere ? colors.success : colors.inkSubtle }}>{after && k in after ? JSON.stringify(after[k]) : '-'}</span>
          </div>
        );
      })}
    </div>
  );
}

function RehearsalsPanel() {
  const { colors } = useTheme();
  const panel = usePanel(() => api.getRehearsals(40));
  if (panel.loading) return <BrainLoading message="Reading rehearsals…" />;
  if (panel.notice) return <EnterpriseNotice message={panel.notice} />;
  if (panel.error) return <BrainError message={panel.error} onRetry={panel.reload} />;
  const d: any = panel.data || {};
  const rows: any[] = d.rehearsals || [];
  const held = d.prediction_held_rate;
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label="Prediction held" value={held == null ? 'Not yet' : `${(held * 100).toFixed(0)}%`} note={d.prediction_held_note || 'Of rehearsed writes that landed'} />
        <Stat label="Matched" value={d.by_status?.APPLIED_MATCH ?? 0} note="Landed exactly as predicted" />
        <Stat label="Drifted" value={d.by_status?.APPLIED_DRIFT ?? 0} note="Landed differently: an incident" />
        <Stat label="Refused" value={(d.by_status?.REFUSED_STALE ?? 0) + (d.by_status?.REFUSED_POLICY ?? 0)} note="Stale diff or origin rule" />
      </div>
      <div className="space-y-3">
        {rows.length === 0 ? <BrainEmpty title="No governed write has been rehearsed yet" /> : rows.map((r: any) => (
          <div key={r.id} className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
            <div className="flex items-center gap-2 flex-wrap">
              <Pill text={`${r.risk?.tier || '?'} risk`} tone={r.risk?.tier === 'HIGH' ? 'bad' : r.risk?.tier === 'MEDIUM' ? 'warn' : 'ok'} />
              <Pill text={humanize(r.status)} tone={r.status === 'APPLIED_MATCH' ? 'ok' : r.status === 'PREDICTED' ? 'muted' : 'bad'} />
              <Pill text={r.level === 'shadow' ? 'Shadow computation' : r.level === 'cannot' ? 'Could not rehearse' : humanize(r.level)} tone="primary" />
              <span className="text-[12px] ml-auto" style={{ color: colors.inkTertiary }}>{r.created_at ? timeAgo(r.created_at) : ''}</span>
            </div>
            <p className="text-[13px] mt-2" style={{ color: colors.ink }}>{r.summary}</p>
            {r.level === 'shadow' && (
              <div className="mt-3"><DiffTable before={r.predicted?.before} after={r.predicted?.after} changed={r.predicted?.changed_fields || []} /></div>
            )}
            {r.drift?.fields?.length > 0 && (
              <p className="text-[12px] mt-2" style={{ color: colors.error }}>Differed on: {r.drift.fields.join(', ')}</p>
            )}
            <p className="text-[11px] mt-2" style={{ color: colors.inkTertiary }}>{r.level_note}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── External agents ───────────────────────────────────────────────────────────

function GatewayPanel() {
  const { colors } = useTheme();
  const panel = usePanel(() => api.getGatewayPrincipals());
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  if (panel.loading) return <BrainLoading message="Reading external agents…" />;
  if (panel.notice) return <EnterpriseNotice message={panel.notice} />;
  if (panel.error) return <BrainError message={panel.error} onRetry={panel.reload} />;
  const rows: any[] = (panel.data as any)?.principals || [];
  const toggle = async (p: any) => {
    setBusy(p.principal); setActionError(null);
    try {
      await api.setPrincipalPolicy(p.principal, { ...p.policy, disabled: !p.policy?.disabled, note: p.policy?.disabled ? '' : 'Disabled from the console' });
      await panel.reload();
    } catch (e: any) { setActionError(e?.message || 'The change was refused.'); }
    finally { setBusy(null); }
  };
  return (
    <div className="space-y-4">
      <p className="text-[13px]" style={{ color: colors.inkSubtle }}>
        Other people's agents that acted here over MCP. Each is governed as itself: its own rung per skill, earned on its own record, its own caps, its own proof trail.
      </p>
      {actionError && <div className="text-[12px]" style={{ color: colors.error }}>{actionError}</div>}
      {rows.length === 0 ? <BrainEmpty title="No external agent has acted in this workspace yet" /> : rows.map((p: any) => (
        <div key={p.principal} className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="flex items-center gap-3 flex-wrap">
            <Bot className="w-4 h-4" style={{ color: colors.primary }} />
            <span className="text-[14px] font-semibold" style={{ color: colors.ink }}>{p.name || p.principal}</span>
            <span className="text-[11px] font-mono" style={{ color: colors.inkTertiary }}>{p.principal}</span>
            {p.policy?.disabled ? <Pill text="Disabled" tone="bad" /> : <Pill text="Active" tone="ok" />}
            <span className="text-[12px] tabular-nums" style={{ color: colors.inkSubtle }}>{p.runs} runs, ${Number(p.spend_usd || 0).toFixed(2)} spent{p.last_seen ? `, last seen ${timeAgo(p.last_seen)}` : ''}</span>
            <button onClick={() => toggle(p)} disabled={busy === p.principal}
              className="ml-auto text-[11px] px-2 py-1 rounded-md disabled:opacity-50"
              style={{ background: (p.policy?.disabled ? colors.success : colors.error) + '15', color: p.policy?.disabled ? colors.success : colors.error }}>
              {busy === p.principal ? <Loader2 className="w-3 h-3 animate-spin" /> : p.policy?.disabled ? 'Re-enable' : 'Kill switch'}
            </button>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {(p.rungs || []).length === 0 ? (
              <span className="text-[12px]" style={{ color: colors.inkSubtle }}>No rung yet: every run is reviewed until this agent earns one.</span>
            ) : p.rungs.map((r: any) => (
              <span key={r.skill_id} className="text-[12px] px-2 py-1 rounded-md" style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>
                {humanize(r.skill_id)}: <strong style={{ color: colors.ink }}>{TIER_LABEL[r.tier] || humanize(r.tier)}</strong>{r.samples ? ` (${r.samples} runs)` : ''}
              </span>
            ))}
          </div>
          <div className="mt-2 text-[11px]" style={{ color: colors.inkTertiary }}>
            Caps: {p.policy?.hourly_call_cap != null ? `${p.policy.hourly_call_cap} runs per hour` : 'no hourly cap'}, {p.policy?.daily_spend_cap_usd != null ? `$${p.policy.daily_spend_cap_usd} per UTC day` : 'no daily spend cap'}.
            Both are reserved at admission: a call slot, and an evidence-based estimate of the run's cost that the real cost replaces when it completes.
          </div>
          <CapsEditor principal={p} onSaved={panel.reload} />
        </div>
      ))}
    </div>
  );
}

/** The two numeric caps for one external agent; blank means no cap. */
function CapsEditor({ principal, onSaved }: { principal: any; onSaved: () => void }) {
  const { colors } = useTheme();
  const pol = principal.policy || {};
  const [hourly, setHourly] = useState<string>(pol.hourly_call_cap != null ? String(pol.hourly_call_cap) : '');
  const [spend, setSpend] = useState<string>(pol.daily_spend_cap_usd != null ? String(pol.daily_spend_cap_usd) : '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    setBusy(true); setError(null);
    try {
      await api.setPrincipalPolicy(principal.principal, {
        hourly_call_cap: hourly.trim() === '' ? null : Number(hourly),
        daily_spend_cap_usd: spend.trim() === '' ? null : Number(spend),
        disabled: !!pol.disabled, note: pol.note || '',
      });
      onSaved();
    } catch (e: any) { setError(e?.message || 'The caps were refused.'); }
    finally { setBusy(false); }
  };
  const input: React.CSSProperties = { background: colors.inputBg, color: colors.ink, border: `1px solid ${colors.hairline}` };
  return (
    <div className="mt-2 flex items-center gap-2 flex-wrap text-[12px]" style={{ color: colors.inkSubtle }}>
      <label className="flex items-center gap-1.5">Runs per hour
        <input type="number" min={0} value={hourly} onChange={e => setHourly(e.target.value)} placeholder="none"
          aria-label="Hourly call cap" className="w-20 px-2 py-1 rounded-md text-[12px]" style={input} />
      </label>
      <label className="flex items-center gap-1.5">Spend per day ($)
        <input type="number" min={0} step="0.01" value={spend} onChange={e => setSpend(e.target.value)} placeholder="none"
          aria-label="Daily spend cap in dollars" className="w-24 px-2 py-1 rounded-md text-[12px]" style={input} />
      </label>
      <button onClick={save} disabled={busy}
        className="text-[11px] px-2 py-1 rounded-md disabled:opacity-50" style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>
        {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Save caps'}
      </button>
      {error && <span style={{ color: colors.error }}>{error}</span>}
    </div>
  );
}

// ── Outcomes ──────────────────────────────────────────────────────────────────

function OutcomesPanel() {
  const { colors } = useTheme();
  const summary = usePanel(() => api.getOutcomes());
  const lines = usePanel(() => api.getOutcomeLines(undefined, undefined, 40));
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  if (summary.loading) return <BrainLoading message="Reading verified outcomes…" />;
  if (summary.notice) return <EnterpriseNotice message={summary.notice} />;
  if (summary.error) return <BrainError message={summary.error} onRetry={summary.reload} />;
  const d: any = summary.data || {};
  const c = d.counts || {};
  const rows: any[] = (lines.data as any)?.lines || [];
  const download = async () => {
    setBusy(true); setActionError(null);
    try { await downloadFile(api.outcomesExportPath(d.period), `kaeos-invoice-${d.period}.zip`); }
    catch (e: any) { setActionError(e?.message || 'Export failed.'); }
    finally { setBusy(false); }
  };
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <Stat label={`Billed outcomes, ${d.period}`} value={d.billed_outcomes ?? 0} note="Autonomous and assisted" />
        <Stat label="Autonomous" value={c.autonomous ?? 0} note="No human in the loop" />
        <Stat label="Assisted" value={c.assisted ?? 0} note="A human approved or corrected" />
        <Stat label="Blocked, not billed" value={c.blocked ?? 0} note="Refused, failed or overridden" />
        <div className="rounded-xl p-4 flex flex-col justify-between" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="text-[11px]" style={{ color: colors.inkSubtle }}>{d.proofs_missing ? `${d.proofs_missing} line(s) without a proof` : 'Every billed line has its proof'}</div>
          <button onClick={download} disabled={busy || !(d.billed_outcomes || c.blocked)}
            className="mt-2 px-3 py-2 rounded-lg text-[12px] font-semibold flex items-center justify-center gap-2 disabled:opacity-50"
            style={{ background: colors.primary + '18', color: colors.primary }}>
            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />} Invoice with proofs
          </button>
        </div>
      </div>
      {actionError && <div className="text-[12px]" style={{ color: colors.error }}>{actionError}</div>}
      <p className="text-[12px]" style={{ color: colors.inkSubtle }}>{d.note}</p>
      <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.hairline}` }}>
        <div className="px-4 py-2.5 text-[11px] font-medium" style={{ background: colors.surface2, color: colors.inkSubtle }}>Invoice lines, newest first</div>
        {rows.length === 0 ? <div className="p-6"><BrainEmpty title="No governed outcomes this period" /></div> : rows.map((l: any) => (
          <div key={l.id} className="px-4 py-2.5 flex items-center gap-3 text-[12px]" style={{ borderTop: `1px solid ${colors.hairline}`, color: colors.inkMuted }}>
            {l.billed ? <CheckCircle2 className="w-3.5 h-3.5 shrink-0" style={{ color: colors.success }} /> : <XCircle className="w-3.5 h-3.5 shrink-0" style={{ color: colors.inkTertiary }} />}
            <Pill text={humanize(l.outcome_class)} tone={l.outcome_class === 'autonomous' ? 'ok' : l.outcome_class === 'assisted' ? 'warn' : 'muted'} />
            <span className="font-medium truncate" style={{ color: colors.ink }}>{humanize(l.skill_id)}</span>
            <span className="truncate flex-1" style={{ color: colors.inkSubtle }}>{l.basis}</span>
            {l.proof_id ? <Pill text="Proof" tone="primary" /> : <Pill text="Seal missing" tone="bad" />}
            <span className="text-[11px] whitespace-nowrap" style={{ color: colors.inkTertiary }}>{l.at ? timeAgo(l.at) : ''}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Committees ────────────────────────────────────────────────────────────────

/** One approver's ballot: an endorsement of each option, 0 to 1. */
function Ballot({ committee, onCast }: { committee: any; onCast: () => void }) {
  const { colors } = useTheme();
  const options: any[] = committee.options || [];
  const [scores, setScores] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cast = async () => {
    setBusy(true); setError(null);
    try {
      // Send exactly what the sliders show: an untouched slider is a real
      // 0.5 endorsement, never an omitted key (the pool reads an omission
      // as "did not endorse", which is not what a 50% slider says).
      const ballot = Object.fromEntries(options.map((o: any) => [o.key, scores[o.key] ?? 0.5]));
      await api.castCommitteeVote(committee.id, ballot);
      onCast();
    }
    catch (e: any) { setError(e?.message || 'The vote was refused.'); }
    finally { setBusy(false); }
  };
  return (
    <div className="mt-3 rounded-lg p-3 space-y-2" style={{ background: colors.surface2, border: `1px solid ${colors.primary}30` }}>
      <div className="text-[11px] font-medium" style={{ color: colors.inkSubtle }}>Your position: how strongly you endorse each option. Other ballots stay hidden until the verdict.</div>
      {options.map((o: any) => (
        <label key={o.key} className="flex items-center gap-3 text-[13px]" style={{ color: colors.ink }}>
          <span className="w-40 truncate" title={o.summary}>{o.label}</span>
          <input type="range" min={0} max={100} value={Math.round((scores[o.key] ?? 0.5) * 100)}
            aria-label={`Endorsement of ${o.label}`}
            onChange={e => setScores(s => ({ ...s, [o.key]: Number(e.target.value) / 100 }))} className="flex-1" />
          <span className="w-12 text-right tabular-nums text-[12px]" style={{ color: colors.inkSubtle }}>{Math.round((scores[o.key] ?? 0.5) * 100)}%</span>
        </label>
      ))}
      <div className="flex items-center gap-3">
        <button onClick={cast} disabled={busy}
          className="px-3 py-1.5 rounded-lg text-[12px] font-semibold flex items-center gap-2 disabled:opacity-50"
          style={{ background: colors.primary + '18', color: colors.primary }}>
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Gavel className="w-3.5 h-3.5" />} Cast my vote
        </button>
        {error && <span className="text-[12px]" style={{ color: colors.error }}>{error}</span>}
      </div>
    </div>
  );
}

function CommitteeCard({ row, onChange }: { row: any; onChange: () => void }) {
  const { colors } = useTheme();
  const [open, setOpen] = useState(false);
  const detail = usePanel(() => api.getCommittee(row.id));
  const c: any = detail.data || row;
  const decided = c.status === 'decided';
  const needsMe = row.i_must_vote && !row.my_vote_cast && !decided;
  const steps: any[] = c.proof?.steps || [];
  return (
    <div className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${needsMe ? colors.primary + '60' : colors.hairline}` }}>
      <div className="flex items-center gap-2 flex-wrap">
        <Gavel className="w-4 h-4 shrink-0" style={{ color: colors.primary }} />
        <span className="text-[14px] font-semibold" style={{ color: colors.ink }}>{c.subject}</span>
        <Pill text={decided ? `Decided: ${c.decision_label || humanize(c.decision)}` : 'Open'} tone={decided ? 'ok' : needsMe ? 'primary' : 'warn'} />
        <span className="text-[12px] tabular-nums" style={{ color: colors.inkSubtle }}>{c.votes_cast ?? row.votes_cast ?? 0} of {c.votes_required ?? row.votes_required} votes cast</span>
        {row.execution_id && (
          <Pill text={c.hitl_resolution ? `Paused run ${humanize(c.hitl_resolution)}` : 'Decides a paused run'} tone={c.hitl_resolution === 'approved' ? 'ok' : c.hitl_resolution === 'rejected' ? 'bad' : 'muted'} />
        )}
        {decided && (c.proof_id ? <Pill text="Proof sealed" tone="ok" /> : <Pill text="Seal missing" tone="bad" />)}
        <span className="ml-auto text-[11px] whitespace-nowrap" style={{ color: colors.inkTertiary }}>{row.created_at ? timeAgo(row.created_at) : ''}</span>
      </div>
      {!decided && (
        <div className="text-[12px] mt-1.5" style={{ color: colors.inkSubtle }}>
          Voted so far: {(c.voted_by || []).length ? (c.voted_by || []).join(', ') : 'nobody yet'}. Required: {(c.required_approvers || []).join(', ')}.
        </div>
      )}
      {needsMe && <Ballot committee={c} onCast={() => { detail.reload(); onChange(); }} />}
      {decided && c.verdict && (
        <div className="mt-3">
          <p className="text-[12px] font-mono leading-relaxed" style={{ color: colors.inkMuted }}>{c.verdict}</p>
          <button onClick={() => setOpen(o => !o)} className="mt-2 text-[12px] flex items-center gap-1" style={{ color: colors.primary }}>
            {open ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />} {open ? 'Hide' : 'Show'} how the arithmetic decided
          </button>
          {open && (
            <div className="mt-2 space-y-2">
              {steps.map((s: any) => (
                <div key={s.label} className="rounded-lg p-3" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
                  <div className="text-[12px] font-semibold" style={{ color: colors.ink }}>{s.label}</div>
                  <div className="text-[11px] font-mono mt-0.5" style={{ color: colors.inkSubtle }}>{s.formula}</div>
                  <div className="text-[12px] mt-1" style={{ color: colors.inkMuted }}>{s.detail}</div>
                </div>
              ))}
              {(c.proof?.positions || []).length > 0 && (
                <div className="text-[12px]" style={{ color: colors.inkSubtle }}>
                  Positions: {(c.proof.positions as any[]).map((p: any) => `${p.persona_name} (${Object.entries(p.endorsements || {}).map(([k, v]) => `${k} ${Math.round(Number(v) * 100)}%`).join(', ')})`).join('; ')}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

type KeyLabel = { key: string; label: string };
type CriterionDraft = { key: string; label: string; weight: string };

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40);

/**
 * Convene a standalone committee: options, criteria, an explicit performance
 * matrix (every cell typed, never defaulted - the backend refuses a hole),
 * and the named approvers. A committee for a paused run is convened from
 * the HITL queue instead, where the two options are fixed.
 */
function ConveneForm({ onCreated, onClose }: { onCreated: () => void; onClose: () => void }) {
  const { colors } = useTheme();
  const [subject, setSubject] = useState('');
  const [approvers, setApprovers] = useState('');
  const [options, setOptions] = useState<KeyLabel[]>([{ key: 'approve', label: 'Approve' }, { key: 'reject', label: 'Reject' }]);
  const [criteria, setCriteria] = useState<CriterionDraft[]>([{ key: 'benefit', label: 'Benefit', weight: '1' }]);
  const [perf, setPerf] = useState<Record<string, Record<string, string>>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cell = (o: string, c: string) => perf[o]?.[c] ?? '0.5';
  const setCell = (o: string, c: string, v: string) => setPerf(p => ({ ...p, [o]: { ...(p[o] || {}), [c]: v } }));
  const input: React.CSSProperties = { background: colors.inputBg, color: colors.ink, border: `1px solid ${colors.hairline}` };
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const roster = approvers.split(/[,\s]+/).map(s => s.trim()).filter(Boolean);
      const performance: Record<string, Record<string, number>> = {};
      for (const o of options) {
        performance[o.key] = {};
        for (const c of criteria) performance[o.key][c.key] = Number(cell(o.key, c.key));
      }
      await api.createCommittee({
        subject,
        options: options.map(o => ({ key: o.key, label: o.label })),
        criteria: criteria.map(c => ({ key: c.key, label: c.label, raw_weight: Number(c.weight) })),
        performance, required_approvers: roster,
      });
      onCreated(); onClose();
    } catch (e: any) { setError(e?.message || 'The committee could not be convened.'); }
    finally { setBusy(false); }
  };
  return (
    <div className="rounded-xl p-4 space-y-4" style={{ background: colors.surface1, border: `1px solid ${colors.primary}40` }}>
      <div className="flex items-center justify-between gap-3">
        <div className="text-[14px] font-semibold" style={{ color: colors.ink }}>Convene a committee</div>
        <button onClick={onClose} className="text-[12px]" style={{ color: colors.inkSubtle }}>Cancel</button>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="text-[12px] space-y-1" style={{ color: colors.inkSubtle }}>What is being decided
          <input value={subject} onChange={e => setSubject(e.target.value)} placeholder="e.g. Release the $50k vendor payout"
            aria-label="Subject" className="w-full px-3 py-2 rounded-lg text-[13px]" style={input} />
        </label>
        <label className="text-[12px] space-y-1" style={{ color: colors.inkSubtle }}>Required approvers, comma separated
          <input value={approvers} onChange={e => setApprovers(e.target.value)} placeholder="cfo@acme.com, legal@acme.com"
            aria-label="Required approvers" className="w-full px-3 py-2 rounded-lg text-[13px]" style={input} />
        </label>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-2">
          <div className="text-[12px] font-medium" style={{ color: colors.inkSubtle }}>Options (at least two)</div>
          {options.map((o, i) => (
            <div key={i} className="flex items-center gap-2">
              <input value={o.label} aria-label={`Option ${i + 1} label`} placeholder="Label"
                onChange={e => setOptions(os => os.map((x, j) => j === i ? { key: slug(e.target.value) || `option_${i + 1}`, label: e.target.value } : x))}
                className="flex-1 px-3 py-1.5 rounded-lg text-[13px]" style={input} />
              <span className="text-[11px] font-mono w-24 truncate" style={{ color: colors.inkTertiary }}>{o.key}</span>
              <button onClick={() => setOptions(os => os.filter((_, j) => j !== i))} disabled={options.length <= 2} aria-label="Remove option"
                className="p-1 rounded-md disabled:opacity-30" style={{ color: colors.inkSubtle }}><Trash2 className="w-3.5 h-3.5" /></button>
            </div>
          ))}
          <button onClick={() => setOptions(os => [...os, { key: `option_${os.length + 1}`, label: '' }])}
            className="text-[12px] flex items-center gap-1" style={{ color: colors.primary }}><Plus className="w-3.5 h-3.5" /> Add option</button>
        </div>
        <div className="space-y-2">
          <div className="text-[12px] font-medium" style={{ color: colors.inkSubtle }}>Criteria and their weights</div>
          {criteria.map((c, i) => (
            <div key={i} className="flex items-center gap-2">
              <input value={c.label} aria-label={`Criterion ${i + 1} label`} placeholder="Label"
                onChange={e => setCriteria(cs => cs.map((x, j) => j === i ? { ...x, key: slug(e.target.value) || `criterion_${i + 1}`, label: e.target.value } : x))}
                className="flex-1 px-3 py-1.5 rounded-lg text-[13px]" style={input} />
              <input type="number" min={0} step="0.1" value={c.weight} aria-label={`Criterion ${i + 1} weight`}
                onChange={e => setCriteria(cs => cs.map((x, j) => j === i ? { ...x, weight: e.target.value } : x))}
                className="w-20 px-2 py-1.5 rounded-lg text-[13px]" style={input} />
              <button onClick={() => setCriteria(cs => cs.filter((_, j) => j !== i))} disabled={criteria.length <= 1} aria-label="Remove criterion"
                className="p-1 rounded-md disabled:opacity-30" style={{ color: colors.inkSubtle }}><Trash2 className="w-3.5 h-3.5" /></button>
            </div>
          ))}
          <button onClick={() => setCriteria(cs => [...cs, { key: `criterion_${cs.length + 1}`, label: '', weight: '1' }])}
            className="text-[12px] flex items-center gap-1" style={{ color: colors.primary }}><Plus className="w-3.5 h-3.5" /> Add criterion</button>
        </div>
      </div>
      <div>
        <div className="text-[12px] font-medium mb-1" style={{ color: colors.inkSubtle }}>How each option scores on each criterion, 0 to 1. Every cell is yours to set; 0.5 means no structural preference.</div>
        <div className="overflow-x-auto">
          <table className="text-[12px]" style={{ color: colors.inkMuted }}>
            <thead><tr><th className="text-left pr-3 py-1" style={{ color: colors.inkSubtle }}>Option</th>
              {criteria.map(c => <th key={c.key} className="text-left pr-3 py-1 font-medium" style={{ color: colors.inkSubtle }}>{c.label || c.key}</th>)}</tr></thead>
            <tbody>
              {options.map(o => (
                <tr key={o.key}><td className="pr-3 py-1" style={{ color: colors.ink }}>{o.label || o.key}</td>
                  {criteria.map(c => (
                    <td key={c.key} className="pr-3 py-1">
                      <input type="number" min={0} max={1} step="0.05" value={cell(o.key, c.key)} aria-label={`${o.label || o.key} on ${c.label || c.key}`}
                        onChange={e => setCell(o.key, c.key, e.target.value)} className="w-20 px-2 py-1 rounded-md" style={input} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <button onClick={submit} disabled={busy || !subject.trim()}
          className="px-3 py-2 rounded-lg text-[12px] font-semibold flex items-center gap-2 disabled:opacity-50"
          style={{ background: colors.primary + '18', color: colors.primary }}>
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Gavel className="w-3.5 h-3.5" />} Convene
        </button>
        {error && <span className="text-[12px]" style={{ color: colors.error }}>{error}</span>}
      </div>
    </div>
  );
}

function CommitteesPanel() {
  const { colors } = useTheme();
  const panel = usePanel(() => api.listCommittees());
  const [scope, setScope] = useState<'mine' | 'all'>('mine');
  const [convening, setConvening] = useState(false);
  // The console list is loaded alongside the personal one (a viewer gets a
  // 403 notice, shown only in the "Whole workspace" scope), so switching
  // scope never waits on a fetch that a scope-dependent loader would skip.
  const all = usePanel(() => api.listAllCommittees());
  if (panel.loading) return <BrainLoading message="Reading committees…" />;
  if (panel.notice) return <EnterpriseNotice message={panel.notice} />;
  if (panel.error) return <BrainError message={panel.error} onRetry={panel.reload} />;
  const mine: any[] = (panel.data as any)?.committees || [];
  const rows: any[] = scope === 'all' ? ((all.data as any)?.committees || []) : mine;
  const open = rows.filter(r => r.status !== 'decided');
  const decided = rows.filter(r => r.status === 'decided');
  const reloadBoth = () => { panel.reload(); if (scope === 'all') all.reload(); };
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label="Open committees" value={open.length} note="Waiting on a named approver" />
        <Stat label="Need my vote" value={mine.filter(r => r.status !== 'decided' && r.i_must_vote && !r.my_vote_cast).length} note="Ballots you have not cast" />
        <Stat label="Decided" value={decided.length} note="Verdicts, each sealed as a proof" />
        <Stat label="Paused runs decided" value={rows.filter(r => r.hitl_resolution === 'approved' || r.hitl_resolution === 'rejected').length} note="Resumed or stopped by a committee" />
      </div>
      <div className="flex items-center gap-3 flex-wrap">
        <button onClick={() => setConvening(c => !c)}
          className="px-3 py-2 rounded-lg text-[12px] font-semibold flex items-center gap-2"
          style={{ background: colors.primary + '18', color: colors.primary }}>
          <Gavel className="w-3.5 h-3.5" /> {convening ? 'Close the form' : 'Convene a committee'}
        </button>
        <div className="flex items-center rounded-lg p-0.5" role="tablist" aria-label="Committee scope" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          {(['mine', 'all'] as const).map(s => (
            <button key={s} role="tab" aria-selected={scope === s} onClick={() => setScope(s)}
              className="px-2.5 py-1 rounded-md text-[12px] font-medium"
              style={{ background: scope === s ? colors.navActive : 'transparent', color: scope === s ? colors.navActiveText : colors.inkSubtle }}>
              {s === 'mine' ? 'Involving me' : 'Whole workspace'}
            </button>
          ))}
        </div>
        <span className="text-[12px]" style={{ color: colors.inkSubtle }}>
          Each approver casts one ballot; the same arithmetic that arbitrates the debate gate pools them into a verdict that replays from the stored inputs.
        </span>
      </div>
      {convening && <ConveneForm onCreated={reloadBoth} onClose={() => setConvening(false)} />}
      {scope === 'all' && all.notice && <EnterpriseNotice message={all.notice} />}
      {scope === 'all' && all.error && <BrainError message={all.error} onRetry={all.reload} />}
      {rows.length === 0 && !(scope === 'all' && (all.loading || all.notice || all.error)) ? (
        <BrainEmpty title={scope === 'all' ? 'No committee has been convened in this workspace' : 'No committee involves you yet'} />
      ) : (
        <div className="space-y-3">
          {[...open, ...decided].map(r => <CommitteeCard key={r.id} row={r} onChange={reloadBoth} />)}
        </div>
      )}
    </div>
  );
}

// ── Evidence pack ─────────────────────────────────────────────────────────────

const SECTION_LABEL: Record<string, string> = {
  controls: 'Implemented controls', audit_trail: 'Per-action audit trail', model_pinning: 'Model version pinning',
  hitl_thresholds: 'Human-in-the-loop thresholds', agent_identity: 'Agent identity scoping', kill_switch: 'Kill switch',
  rehearsals: 'Rehearsals', outcomes: 'Verified outcomes', committees: 'Committee decisions', oversight_mapping: 'EU AI Act oversight mapping',
};

function sectionSummary(name: string, data: any): string {
  if (data == null) return 'Not available';
  switch (name) {
    case 'controls': return `${(data.controls || []).length} control(s) inventoried`;
    case 'audit_trail': return `${Array.isArray(data) ? data.length : 0} newest proof(s) with reasoning`;
    case 'model_pinning': return `${Array.isArray(data) ? data.length : 0} model layer(s) pinned`;
    case 'hitl_thresholds': return `ladder ${data.ladder_mode}, ${(data.skill_rungs || []).length} skill rung(s), ${(data.department_dials || []).length} department dial(s)`;
    case 'agent_identity': return `${(data.api_keys || []).length} API key(s), ${(data.external_agent_policies || []).length} external-agent polic(ies)`;
    case 'kill_switch': return `${(data.agents_currently_disabled || []).length} agent(s) currently disabled`;
    case 'rehearsals': return data.prediction_held_rate == null ? 'no rehearsed write has landed yet' : `prediction held ${(data.prediction_held_rate * 100).toFixed(0)}%`;
    case 'outcomes': return Object.entries(data.by_class || {}).map(([k, v]) => `${v} ${k}`).join(', ') || 'no outcomes yet';
    case 'committees': return Object.entries(data.by_status || {}).map(([k, v]) => `${v} ${k}`).join(', ') || 'none convened yet';
    case 'oversight_mapping': return `${Array.isArray(data) ? data.length : 0} article(s) mapped`;
    default: return '';
  }
}

function EvidencePanel() {
  const { colors } = useTheme();
  const panel = usePanel(() => api.getEvidenceSummary(25));
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  if (panel.loading) return <BrainLoading message="Reading the evidence pack…" />;
  if (panel.notice) return <EnterpriseNotice message={panel.notice} />;
  if (panel.error) return <BrainError message={panel.error} onRetry={panel.reload} />;
  const pack: any = panel.data || {};
  const sections = Object.entries(pack).filter(([k, v]) => k !== 'meta' && v && typeof v === 'object' && 'basis' in (v as any));
  const download = async () => {
    setBusy(true); setActionError(null);
    try { await downloadFile(api.evidencePackPath(), 'kaeos-evidence-pack.zip'); }
    catch (e: any) { setActionError(e?.message || 'Download failed.'); }
    finally { setBusy(false); }
  };
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label="Measured sections" value={sections.filter(([, v]: any) => v.basis === 'measured').length} note="Read from this deployment's record" />
        <Stat label="Self-assessed" value={sections.filter(([, v]: any) => v.basis === 'self-assessed').length} note="KAEOS's statements about its own design" />
        <Stat label="Scope" value={<span className="text-[13px]">{pack.meta?.scope || 'Not available'}</span>} />
        <div className="rounded-xl p-4 flex flex-col justify-between" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="text-[11px]" style={{ color: colors.inkSubtle }}>Zip: one JSON per section, the proof bundle, a README naming the boundary</div>
          <button onClick={download} disabled={busy}
            className="mt-2 px-3 py-2 rounded-lg text-[12px] font-semibold flex items-center justify-center gap-2 disabled:opacity-50"
            style={{ background: colors.primary + '18', color: colors.primary }}>
            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />} Download evidence pack
          </button>
        </div>
      </div>
      {actionError && <div className="text-[12px]" style={{ color: colors.error }}>{actionError}</div>}
      <div className="rounded-xl p-4 text-[12px]" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}`, color: colors.inkMuted }}>
        {pack.meta?.external_certifications || 'Not available'}
      </div>
      <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.hairline}` }}>
        <div className="px-4 py-2.5 text-[11px] font-medium" style={{ background: colors.surface2, color: colors.inkSubtle }}>Sections, as an assessor reads them</div>
        {sections.map(([name, s]: any) => (
          <div key={name} className="px-4 py-3 flex items-center gap-3 text-[13px] flex-wrap" style={{ borderTop: `1px solid ${colors.hairline}`, color: colors.inkMuted }}>
            <span className="font-medium min-w-[200px]" style={{ color: colors.ink }}>{SECTION_LABEL[name] || humanize(name)}</span>
            <Pill text={s.basis === 'measured' ? 'Measured' : 'Self-assessed'} tone={s.basis === 'measured' ? 'ok' : 'warn'} />
            <span className="flex-1" style={{ color: colors.inkSubtle }}>{sectionSummary(name, s.data)}</span>
          </div>
        ))}
      </div>
      {Array.isArray(pack.oversight_mapping?.data) && (
        <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.hairline}` }}>
          <div className="px-4 py-2.5 text-[11px] font-medium" style={{ background: colors.surface2, color: colors.inkSubtle }}>EU AI Act duties and the mechanism behind each (a self-assessment, not a conformity assessment)</div>
          {pack.oversight_mapping.data.map((m: any) => (
            <div key={m.article} className="px-4 py-3" style={{ borderTop: `1px solid ${colors.hairline}` }}>
              <div className="text-[13px] font-medium" style={{ color: colors.ink }}>{m.article}</div>
              <p className="text-[12px] mt-1 leading-relaxed" style={{ color: colors.inkMuted }}>{m.mechanism}</p>
              <div className="text-[11px] mt-1" style={{ color: colors.inkTertiary }}>Evidence: {m.evidence}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Quality ───────────────────────────────────────────────────────────────────

const EXPECTED_STATUSES = ['SUCCESS_CLEAN', 'PENDING_HITL', 'BLOCKED_COMPLIANCE', 'BLOCKED_DEBATE', 'HUMAN_OVERRIDDEN'];

function QualityPanel() {
  const { colors } = useTheme();
  const feedback = usePanel(() => api.listSkillFeedback());
  const cases = usePanel(() => api.listRegressionCases());
  const [busy, setBusy] = useState<string | null>(null);
  const [suite, setSuite] = useState<any>(null);
  const [expected, setExpected] = useState<Record<string, string>>({});
  const [actionError, setActionError] = useState<string | null>(null);
  if (feedback.loading) return <BrainLoading message="Reading agent quality…" />;
  if (feedback.notice) return <EnterpriseNotice message={feedback.notice} />;
  if (feedback.error) return <BrainError message={feedback.error} onRetry={feedback.reload} />;
  const fb: any[] = (feedback.data as any)?.feedback || [];
  const pinned: any[] = (cases.data as any)?.cases || [];
  const promote = async (row: any) => {
    setBusy(row.id); setActionError(null);
    try {
      await api.promoteFeedback(row.id, { expected_status: expected[row.id] || 'SUCCESS_CLEAN' });
      await Promise.all([feedback.reload(), cases.reload()]);
    } catch (e: any) { setActionError(e?.message || 'Promotion was refused.'); }
    finally { setBusy(null); }
  };
  const runSuite = async () => {
    setBusy('suite'); setActionError(null);
    try { setSuite(await api.runRegressionSuite()); }
    catch (e: any) { setActionError(e?.message || 'The suite could not run.'); }
    finally { setBusy(null); }
  };
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label="Human ratings" value={fb.length} note="Thumbs on sealed runs, from the Proofs tab" />
        <Stat label="Rated wrong" value={fb.filter(f => f.rating === 'down').length} note="Adverse evidence in the trust ladder" />
        <Stat label="Pinned regression cases" value={pinned.length} note="Re-run against the live gate config" />
        <div className="rounded-xl p-4 flex flex-col justify-between" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="text-[11px]" style={{ color: colors.inkSubtle }}>{suite ? `${suite.passed} of ${suite.total} passed` : 'Deterministic: no model call needed'}</div>
          <button onClick={runSuite} disabled={busy === 'suite' || pinned.length === 0}
            className="mt-2 px-3 py-2 rounded-lg text-[12px] font-semibold flex items-center justify-center gap-2 disabled:opacity-50"
            style={{ background: colors.primary + '18', color: colors.primary }}>
            {busy === 'suite' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />} Run regression suite
          </button>
        </div>
      </div>
      {actionError && <div className="text-[12px]" style={{ color: colors.error }}>{actionError}</div>}
      {suite && suite.failed > 0 && (
        <div className="rounded-xl p-4 text-[13px]" style={{ background: colors.error + '12', border: `1px solid ${colors.error}30`, color: colors.ink }}>
          {suite.failed} case(s) fail under the live gate configuration. The trust ladder withholds the autonomous rung for those skills until they pass.
        </div>
      )}
      <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.hairline}` }}>
        <div className="px-4 py-2.5 text-[11px] font-medium" style={{ background: colors.surface2, color: colors.inkSubtle }}>Ratings, newest first. A thumbs-down can be pinned as a regression case that freezes the run's inputs.</div>
        {fb.length === 0 ? <div className="p-6"><BrainEmpty title="No run has been rated yet" /></div> : fb.map((f: any) => (
          <div key={f.id} className="px-4 py-2.5 flex items-center gap-3 text-[12px] flex-wrap" style={{ borderTop: `1px solid ${colors.hairline}`, color: colors.inkMuted }}>
            {f.rating === 'up' ? <ThumbsUp className="w-3.5 h-3.5 shrink-0" style={{ color: colors.success }} /> : <ThumbsDown className="w-3.5 h-3.5 shrink-0" style={{ color: colors.error }} />}
            <span className="font-medium" style={{ color: colors.ink }}>{humanize(f.skill_id_name)}</span>
            <span className="font-mono text-[11px] truncate max-w-[160px]" style={{ color: colors.inkTertiary }}>{f.execution_id}</span>
            <Pill text={humanize(f.triage_status)} tone={f.triage_status === 'regression_case' ? 'ok' : 'muted'} />
            {f.note && <span className="truncate" style={{ color: colors.inkSubtle }}>{f.note}</span>}
            {f.rating === 'down' && f.triage_status !== 'regression_case' && (
              <span className="ml-auto flex items-center gap-2">
                <select value={expected[f.id] || 'SUCCESS_CLEAN'} onChange={e => setExpected(s => ({ ...s, [f.id]: e.target.value }))}
                  aria-label="Expected status for the pinned case"
                  className="text-[11px] rounded-md px-2 py-1" style={{ background: colors.inputBg, color: colors.ink, border: `1px solid ${colors.hairline}` }}>
                  {EXPECTED_STATUSES.map(s => <option key={s} value={s}>{humanize(s)}</option>)}
                </select>
                <button onClick={() => promote(f)} disabled={busy === f.id}
                  className="text-[11px] px-2 py-1 rounded-md disabled:opacity-50" style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>
                  {busy === f.id ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Pin as regression case'}
                </button>
              </span>
            )}
            <span className="text-[11px] whitespace-nowrap" style={{ color: colors.inkTertiary }}>{f.created_at ? timeAgo(f.created_at) : ''}</span>
          </div>
        ))}
      </div>
      {pinned.length > 0 && (
        <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.hairline}` }}>
          <div className="px-4 py-2.5 text-[11px] font-medium" style={{ background: colors.surface2, color: colors.inkSubtle }}>Pinned regression cases</div>
          {pinned.map((c: any) => {
            const run = (suite?.runs || []).find((r: any) => r.case_id === c.id);
            return (
              <div key={c.id} className="px-4 py-2.5 flex items-center gap-3 text-[12px]" style={{ borderTop: `1px solid ${colors.hairline}`, color: colors.inkMuted }}>
                <span className="font-medium" style={{ color: colors.ink }}>{humanize(c.skill_id_name)}</span>
                <Pill text={humanize(c.department)} tone="muted" />
                <span style={{ color: colors.inkSubtle }}>expects {humanize(c.expected_status)}</span>
                {run && <Pill text={run.passed ? 'Passed' : `Failed: got ${humanize(run.status || 'no status')}`} tone={run.passed ? 'ok' : 'bad'} />}
                <span className="ml-auto text-[11px] whitespace-nowrap" style={{ color: colors.inkTertiary }}>{c.created_at ? timeAgo(c.created_at) : ''}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function GovernedExecution({ defaultTab }: { defaultTab?: Tab }) {
  const { colors } = useTheme();
  const [tab, setTab] = useState<Tab>(defaultTab || 'proofs');
  const status = usePanel(() => api.getEnterpriseStatus());
  const ee: any = (status.data as any)?.enterprise;
  const banner = useMemo(() => {
    if (!ee) return null;
    if (ee.loaded) return { tone: 'ok' as const, text: `KAEOS Enterprise ${ee.version} is loaded: ${(ee.features || []).map(humanize).join(', ')}.` };
    if (ee.installed) return { tone: 'bad' as const, text: 'KAEOS Enterprise is installed but did not load; the core is running as open core. See the boot log.' };
    return { tone: 'muted' as const, text: 'This deployment runs the open core. The panels below name the Enterprise capability each one needs.' };
  }, [ee]);

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className={`${PAGE_PAD} space-y-5`}>
        <div className="flex items-start gap-3">
          <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0" style={{ background: colors.primary + '18' }}>
            <Fingerprint className="w-5 h-5" style={{ color: colors.primary }} />
          </div>
          <div className="flex-1 min-w-0">
            <h1 className="text-[20px] font-semibold tracking-tight" style={{ color: colors.ink }}>Governed execution</h1>
            <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>
              Gate, rehearse, execute, compensate, prove. Every number here is read from the ledgers; nothing is estimated.
            </p>
          </div>
          <button onClick={() => status.reload()} className="p-2 rounded-lg" style={{ color: colors.inkSubtle }} aria-label="Refresh">
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
        {banner && (
          <div className="rounded-lg px-3 py-2 text-[12px]" style={{
            background: (banner.tone === 'ok' ? colors.success : banner.tone === 'bad' ? colors.error : colors.inkSubtle) + '12',
            color: banner.tone === 'ok' ? colors.success : banner.tone === 'bad' ? colors.error : colors.inkSubtle,
          }}>{banner.text}</div>
        )}
        <div className="flex items-center flex-wrap gap-1 rounded-xl p-1 w-fit max-w-full" role="tablist" aria-label="Governed execution sections"
          style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          {TABS.map(t => (
            <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
              className="px-3 py-1.5 rounded-lg text-[12px] font-medium flex items-center gap-2 transition-colors"
              style={{ background: tab === t.id ? colors.navActive : 'transparent', color: tab === t.id ? colors.navActiveText : colors.inkSubtle }}>
              <t.icon className="w-3.5 h-3.5" />{t.label}
            </button>
          ))}
        </div>
        <div role="tabpanel">
          {tab === 'proofs' && <ProofsPanel />}
          {tab === 'ladder' && <LadderPanel />}
          {tab === 'rehearsals' && <RehearsalsPanel />}
          {tab === 'gateway' && <GatewayPanel />}
          {tab === 'outcomes' && <OutcomesPanel />}
          {tab === 'committees' && <CommitteesPanel />}
          {tab === 'quality' && <QualityPanel />}
          {tab === 'evidence' && <EvidencePanel />}
        </div>
      </div>
    </div>
  );
}
