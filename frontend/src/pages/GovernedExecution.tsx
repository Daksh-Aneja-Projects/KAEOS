import React, { useMemo, useState } from 'react';
import {
  Fingerprint, ShieldCheck, ShieldAlert, Download, Loader2, GitBranch, Layers, Bot,
  Receipt, CheckCircle2, XCircle, Lock, Unlock, RefreshCw, ArrowRight,
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

type Tab = 'proofs' | 'ladder' | 'rehearsals' | 'gateway' | 'outcomes';

const TABS: { id: Tab; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: 'proofs', label: 'Proofs', icon: Fingerprint },
  { id: 'ladder', label: 'Trust ladder', icon: Layers },
  { id: 'rehearsals', label: 'Rehearsals', icon: GitBranch },
  { id: 'gateway', label: 'External agents', icon: Bot },
  { id: 'outcomes', label: 'Outcomes', icon: Receipt },
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
          <div key={r.id || r.entry_hash} className="px-4 py-3 flex items-center gap-3 text-[13px]" style={{ borderTop: `1px solid ${colors.hairline}`, color: colors.inkMuted }}>
            <span className="font-mono text-[11px] w-10 shrink-0" style={{ color: colors.inkTertiary }}>#{r.seq}</span>
            <Pill text={humanize(r.subject_kind || 'action')} tone="primary" />
            <span className="truncate flex-1">{r.subject_id}</span>
            {r.status && <Pill text={humanize(r.status)} tone={String(r.status).startsWith('SUCCESS') ? 'ok' : String(r.status).startsWith('BLOCKED') || String(r.status).startsWith('FAILED') ? 'bad' : 'muted'} />}
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
            Caps: {p.policy?.hourly_call_cap != null ? `${p.policy.hourly_call_cap} runs per hour` : 'no hourly cap'}, {p.policy?.daily_spend_cap_usd != null ? `$${p.policy.daily_spend_cap_usd} per day` : 'no daily spend cap'}.
          </div>
        </div>
      ))}
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
        </div>
      </div>
    </div>
  );
}
