import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Building2, Users, Activity, ShieldCheck, Lock, KeyRound,
  Layers, AlertCircle, X, Server, RotateCcw, Loader2, Timer, Wrench,
} from 'lucide-react';
import {
  api, type OpsOverview, type OpsTenant, type OpsTenantDetail,
  type OpsJob, type OpsSchedulerBeat,
} from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { StatCard } from '../components/shared/StatCard';
import { Ring } from '../components/shared/Ring';
import { MiniDonut, type DonutItem } from '../components/shared/MiniDonut';
import { TableCard } from '../components/shared/TableCard';
import { humanize, formatNumber, toPct, formatDate } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';

// Operator key lives in SESSION storage only (cleared when the tab closes) and
// in memory — never localStorage, never logged. It is the platform ADMIN_SECRET,
// not the tenant JWT, so it must not outlive the operator's working session.
const SECRET_KEY = 'kaeos-ops-secret';

type GateStatus = 'locked' | 'checking' | 'ready';

// Plan codes -> plain English. Anything unmapped falls back to humanize().
const PLAN_LABELS: Record<string, string> = {
  free: 'Free', starter: 'Starter', growth: 'Growth',
  scale: 'Scale', enterprise: 'Enterprise', unknown: 'Unassigned',
};
const planLabel = (p: string) => PLAN_LABELS[p?.toLowerCase?.()] || humanize(p) || 'Unassigned';

export default function OperatorConsole() {
  const { colors } = useTheme();
  const [status, setStatus] = useState<GateStatus>('locked');
  const [keyInput, setKeyInput] = useState('');
  const [error, setError] = useState<string | null>(null);

  const secretRef = useRef<string>('');
  const [overview, setOverview] = useState<OpsOverview | null>(null);
  const [tenants, setTenants] = useState<OpsTenant[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<OpsTenantDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  // Remediation state: the durable job queue + the scheduler heartbeat.
  const [jobs, setJobs] = useState<OpsJob[]>([]);
  const [beats, setBeats] = useState<Record<string, OpsSchedulerBeat>>({});
  const [showAllJobs, setShowAllJobs] = useState(false);
  const [requeueing, setRequeueing] = useState<string | null>(null);
  const [remedyNote, setRemedyNote] = useState<string | null>(null);

  // Load the fleet with a candidate secret. Returns true on success so both the
  // unlock button and the silent session-restore share one path. The gate rides
  // on overview+tenants; jobs/scheduler are best-effort so an older backend
  // without them still unlocks the console.
  const loadFleet = async (secret: string): Promise<boolean> => {
    const [ov, tn] = await Promise.all([api.opsOverview(secret), api.opsTenants(secret)]);
    setOverview(ov);
    setTenants(tn.tenants);
    void api.opsJobs(secret).then(j => setJobs(j.jobs)).catch(() => {});
    void api.opsScheduler(secret).then(s => setBeats(s.jobs || {})).catch(() => {});
    return true;
  };

  const requeue = async (jobId: string) => {
    if (!secretRef.current) return;
    setRequeueing(jobId);
    setRemedyNote(null);
    try {
      await api.opsRequeueJob(jobId, secretRef.current);
      setJobs(prev => prev.map(j => j.id === jobId
        ? { ...j, status: 'QUEUED', attempts: 0, last_error: null } : j));
      setRemedyNote('Job requeued. The queue picks it up within 15 seconds.');
    } catch (e: any) {
      setRemedyNote(String(e?.message || '').includes('404')
        ? 'That job is no longer failed, so there was nothing to requeue.'
        : 'Could not requeue that job. Try again.');
    } finally {
      setRequeueing(null);
    }
  };

  const unlock = async (candidate: string) => {
    const secret = candidate.trim();
    if (!secret) { setError('Enter the operator key to continue.'); return; }
    setStatus('checking');
    setError(null);
    try {
      await loadFleet(secret);
      secretRef.current = secret;
      sessionStorage.setItem(SECRET_KEY, secret);
      setKeyInput('');
      setStatus('ready');
    } catch (e: any) {
      // Fail closed: a rejected key never persists, and we say so plainly.
      sessionStorage.removeItem(SECRET_KEY);
      secretRef.current = '';
      const msg = String(e?.message || '');
      setError(
        msg.includes('403') || /invalid admin secret/i.test(msg)
          ? 'That operator key was rejected. Check the key and try again.'
          : /disabled|not configured|503/i.test(msg)
            ? 'Operator access is disabled on this deployment (no operator key configured).'
            : msg || 'Could not reach the operator console.',
      );
      setStatus('locked');
    }
  };

  const lock = () => {
    sessionStorage.removeItem(SECRET_KEY);
    secretRef.current = '';
    setOverview(null); setTenants([]); setSelectedId(null); setDetail(null);
    setJobs([]); setBeats({}); setRemedyNote(null);
    setStatus('locked');
  };

  // Restore a live session on mount (e.g. after a route change) without a re-prompt.
  useEffect(() => {
    const saved = sessionStorage.getItem(SECRET_KEY);
    if (saved) void unlock(saved);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep the fleet live once unlocked; pause when the tab is hidden.
  useEffect(() => {
    if (status !== 'ready') return;
    const refresh = () => {
      if (!secretRef.current) return;
      void loadFleet(secretRef.current).catch(() => {/* transient; keep last good */});
    };
    let id: ReturnType<typeof setInterval> | null = null;
    const start = () => { id = setInterval(refresh, 20_000); };
    const onVis = () => { if (document.hidden) { if (id) clearInterval(id); id = null; } else { refresh(); if (!id) start(); } };
    start();
    document.addEventListener('visibilitychange', onVis);
    return () => { if (id) clearInterval(id); document.removeEventListener('visibilitychange', onVis); };
  }, [status]);

  // Drill-in: fetch the selected tenant's detail.
  useEffect(() => {
    if (!selectedId || !secretRef.current) { setDetail(null); return; }
    let cancelled = false;
    setDetailLoading(true);
    api.opsTenantDetail(selectedId, secretRef.current)
      .then(d => { if (!cancelled) setDetail(d); })
      .catch(() => { if (!cancelled) setDetail(null); })
      .finally(() => { if (!cancelled) setDetailLoading(false); });
    return () => { cancelled = true; };
  }, [selectedId]);

  const planDonut: DonutItem[] = useMemo(() => {
    const dist = overview?.plan_distribution || {};
    return Object.entries(dist)
      .map(([k, v]) => ({ label: planLabel(k), value: v }))
      .sort((a, b) => b.value - a.value);
  }, [overview]);

  const blendedPct = toPct(overview?.blended_safe_autonomy_rate);

  // ─── Gate ──────────────────────────────────────────────────────
  if (status !== 'ready') {
    return (
      <div className={`${PAGE_PAD} h-full flex items-center justify-center`}>
        <div className="w-full max-w-md">
          <div className="rounded-2xl p-7" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
            <div className="w-12 h-12 rounded-xl flex items-center justify-center mb-4" style={{ background: colors.primary + '18' }}>
              <ShieldCheck className="w-6 h-6" style={{ color: colors.primary }} />
            </div>
            <h1 className="text-[20px] font-semibold tracking-tight" style={{ color: colors.ink }}>Operator Console</h1>
            <p className="text-[13px] mt-1.5 leading-relaxed" style={{ color: colors.inkSubtle }}>
              Cross-tenant fleet operations. This console is gated by the platform operator key, which is
              separate from your KAEOS sign-in. The key stays in this browser tab only and is never stored or logged.
            </p>

            <form
              className="mt-5"
              onSubmit={e => { e.preventDefault(); void unlock(keyInput); }}
            >
              <label htmlFor="ops-key" className="text-[12px] font-medium" style={{ color: colors.inkMuted }}>Operator key</label>
              <div className="mt-1.5 relative">
                <KeyRound className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: colors.inkSubtle }} />
                <input
                  id="ops-key"
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  value={keyInput}
                  onChange={e => { setKeyInput(e.target.value); if (error) setError(null); }}
                  placeholder="Enter operator key"
                  className="w-full pl-9 pr-3 py-2.5 rounded-lg text-[13px] focus:outline-none focus:ring-1"
                  style={{ background: colors.inputBg, border: `1px solid ${error ? colors.error : colors.hairline}`, color: colors.ink }}
                  aria-invalid={!!error}
                  aria-describedby={error ? 'ops-key-error' : undefined}
                />
              </div>

              {error && (
                <div id="ops-key-error" role="alert" className="mt-2.5 flex items-start gap-2 text-[12px]" style={{ color: colors.error }}>
                  <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              <button
                type="submit"
                disabled={status === 'checking'}
                className="mt-4 w-full py-2.5 rounded-lg text-[13px] font-semibold text-white flex items-center justify-center gap-2 disabled:opacity-60"
                style={{ background: colors.primary }}
              >
                {status === 'checking'
                  ? <><span className="w-4 h-4 border-2 border-white/60 border-t-transparent rounded-full animate-spin" /> Verifying…</>
                  : <><Lock className="w-4 h-4" /> Unlock console</>}
              </button>
            </form>
          </div>
        </div>
      </div>
    );
  }

  // ─── Console ───────────────────────────────────────────────────
  return (
    <div className={`${PAGE_PAD} space-y-6`}>
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl flex items-center justify-center" style={{ background: colors.primary + '18' }}>
            <Server className="w-5 h-5" style={{ color: colors.primary }} />
          </div>
          <div>
            <h1 className="text-[24px] font-bold tracking-tight" style={{ color: colors.ink }}>Operator Console</h1>
            <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>
              Cross-tenant fleet overview. Reads bypass tenant isolation by design, so this view is operator-only.
            </p>
          </div>
        </div>
        <button onClick={lock}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium"
          style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.inkSubtle }}>
          <Lock className="w-3.5 h-3.5" /> Lock console
        </button>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Tenants" value={overview?.tenant_count ?? 0} icon={<Building2 className="w-4 h-4" />} />
        <StatCard label="Active" value={overview?.active_tenants ?? 0} accent={colors.success} icon={<Users className="w-4 h-4" />} />
        <StatCard label="Executions" value={overview?.total_executions ?? 0} accent={colors.info} icon={<Activity className="w-4 h-4" />} />

        {/* Blended safe-autonomy — honesty contract: null renders as a note, never 0. */}
        <div className="rounded-xl p-5 flex items-center gap-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          {blendedPct != null ? (
            <>
              <Ring value={blendedPct} size={72} strokeWidth={7} label="safe" />
              <div className="min-w-0">
                <div className="text-[12px] font-medium uppercase tracking-wide" style={{ color: colors.inkSubtle }}>Blended safe autonomy</div>
                <div className="text-[11px] mt-1" style={{ color: colors.inkTertiary }}>Across all tenants, last 30 days</div>
              </div>
            </>
          ) : (
            <div className="min-w-0">
              <div className="text-[12px] font-medium uppercase tracking-wide" style={{ color: colors.inkSubtle }}>Blended safe autonomy</div>
              <div className="text-[13px] mt-1.5 leading-snug" style={{ color: colors.inkMuted }}>
                Not enough activity to report yet.
              </div>
              <div className="text-[11px] mt-1" style={{ color: colors.inkTertiary }}>No executions in the last 30 days.</div>
            </div>
          )}
        </div>
      </div>

      {/* Plan distribution + tenants + detail */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Plan mix */}
        <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="flex items-center gap-2 mb-4">
            <Layers className="w-4 h-4" style={{ color: colors.primary }} />
            <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Plan distribution</span>
          </div>
          {planDonut.length > 0
            ? <MiniDonut items={planDonut} size={112} centerLabel="tenants" />
            : <div className="text-[13px] py-8 text-center" style={{ color: colors.inkTertiary }}>No tenants yet.</div>}
        </div>

        {/* Tenants table */}
        <div className="lg:col-span-2">
          <TableCard minWidth={760}>
            <div className="grid px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wide sticky top-0"
              style={{ background: colors.surface2, color: colors.inkSubtle, gridTemplateColumns: '1.7fr 0.9fr 0.9fr 0.7fr 0.7fr 1fr' }}>
              <span>Tenant</span><span>Plan</span><span>Status</span>
              <span className="text-right">Agents</span><span className="text-right">Runs</span><span className="text-right">Created</span>
            </div>
            <div className="max-h-[420px] overflow-y-auto">
              {tenants.map(t => {
                const active = selectedId === t.id;
                return (
                  <button key={t.id} onClick={() => setSelectedId(t.id)}
                    className="grid w-full px-4 py-3 text-left items-center transition-colors"
                    style={{
                      gridTemplateColumns: '1.7fr 0.9fr 0.9fr 0.7fr 0.7fr 1fr',
                      borderTop: `1px solid ${colors.hairline}`,
                      background: active ? colors.primary + '12' : 'transparent',
                    }}>
                    <span className="flex items-center gap-2 min-w-0">
                      <span className="text-[13px] font-medium truncate" style={{ color: colors.ink }}>{t.name}</span>
                    </span>
                    <span className="text-[12px] truncate" style={{ color: colors.inkMuted }}>{planLabel(t.plan)}</span>
                    <span className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: t.is_active ? colors.success : colors.inkTertiary }} />
                      <span className="text-[12px]" style={{ color: t.is_active ? colors.success : colors.inkTertiary }}>{t.is_active ? 'Active' : 'Inactive'}</span>
                    </span>
                    <span className="text-[12px] font-mono text-right" style={{ color: colors.inkMuted }}>{formatNumber(t.agent_count)}</span>
                    <span className="text-[12px] font-mono text-right" style={{ color: colors.inkMuted }}>{formatNumber(t.execution_count)}</span>
                    <span className="text-[12px] text-right truncate" style={{ color: colors.inkTertiary }}>{formatDate(t.created_at) || '--'}</span>
                  </button>
                );
              })}
              {tenants.length === 0 && (
                <div className="px-4 py-10 text-center text-[13px]" style={{ color: colors.inkTertiary }}>No tenants provisioned.</div>
              )}
            </div>
          </TableCard>
        </div>
      </div>

      {/* Tenant drill-in */}
      {selectedId && (
        <TenantDetailPanel
          detail={detail}
          loading={detailLoading}
          colors={colors}
          onClose={() => setSelectedId(null)}
        />
      )}

      {/* Remediation: background-job heartbeat + the durable job queue */}
      <SchedulerHeartbeat beats={beats} colors={colors} />
      <JobQueuePanel
        jobs={jobs}
        showAll={showAllJobs}
        onToggleShowAll={() => setShowAllJobs(v => !v)}
        requeueing={requeueing}
        onRequeue={requeue}
        note={remedyNote}
        colors={colors}
      />
    </div>
  );
}

// ─── Remediation: scheduler heartbeat ──────────────────────────────
// Plain-English age for a heartbeat/job timestamp; never a raw ISO string.
function ago(iso: string | null): string {
  if (!iso) return 'never';
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return 'just now';
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return h < 48 ? `${h}h ago` : `${Math.floor(h / 24)}d ago`;
}

function SchedulerHeartbeat({ beats, colors }: {
  beats: Record<string, OpsSchedulerBeat>;
  colors: Record<string, string>;
}) {
  const rows = Object.entries(beats).sort(([a], [b]) => a.localeCompare(b));
  return (
    <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      <div className="flex items-center gap-2 mb-1">
        <Timer className="w-4 h-4" style={{ color: colors.primary }} />
        <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Background jobs, last run</span>
      </div>
      <p className="text-[12px] mb-3" style={{ color: colors.inkSubtle }}>
        Every scheduled job's most recent run on the leader. A red job is failing every tick even while the public status page stays green.
      </p>
      {rows.length === 0 ? (
        <div className="text-[13px] py-4 text-center" style={{ color: colors.inkTertiary }}>
          No runs recorded yet. Heartbeats appear as the scheduler ticks.
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {rows.map(([name, b]) => (
            <span key={name}
              title={b.error ? `Last error: ${b.error}` : `Last ran ${ago(b.at)}`}
              className="inline-flex items-center gap-1.5 text-[12px] px-2.5 py-1 rounded-full"
              style={{
                background: b.ok ? colors.surface2 : colors.error + '14',
                border: `1px solid ${b.ok ? colors.hairline : colors.error + '55'}`,
                color: b.ok ? colors.inkMuted : colors.error,
              }}>
              <span className="w-2 h-2 rounded-full" style={{ background: b.ok ? colors.success : colors.error }} />
              {humanize(name)}
              <span style={{ color: b.ok ? colors.inkTertiary : colors.error }}>{ago(b.at)}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Remediation: durable job queue ────────────────────────────────
function JobQueuePanel({ jobs, showAll, onToggleShowAll, requeueing, onRequeue, note, colors }: {
  jobs: OpsJob[];
  showAll: boolean;
  onToggleShowAll: () => void;
  requeueing: string | null;
  onRequeue: (id: string) => void;
  note: string | null;
  colors: Record<string, string>;
}) {
  const failed = jobs.filter(j => j.status === 'FAILED');
  const visible = showAll ? jobs : failed;
  const statusColor = (s: string) =>
    s === 'FAILED' ? colors.error : s === 'RUNNING' ? colors.info
      : s === 'QUEUED' ? colors.warning : colors.success;

  return (
    <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      <div className="flex items-center justify-between gap-3 px-5 py-3 border-b flex-wrap" style={{ borderColor: colors.hairline }}>
        <div className="flex items-center gap-2 min-w-0">
          <Wrench className="w-4 h-4 shrink-0" style={{ color: colors.primary }} />
          <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Durable job queue</span>
          <span className="text-[11px] px-2 py-0.5 rounded-full font-medium"
            style={{
              background: failed.length ? colors.error + '14' : colors.surface2,
              color: failed.length ? colors.error : colors.inkSubtle,
              border: `1px solid ${failed.length ? colors.error + '55' : colors.hairline}`,
            }}>
            {failed.length === 0 ? 'nothing failed' : `${failed.length} failed`}
          </span>
        </div>
        <button onClick={onToggleShowAll}
          className="text-[12px] px-2.5 py-1 rounded-lg font-medium"
          style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.inkSubtle }}>
          {showAll ? 'Show failed only' : 'Show every status'}
        </button>
      </div>

      {note && (
        <div className="px-5 py-2 text-[12px] border-b" style={{ borderColor: colors.hairline, color: colors.inkSubtle, background: colors.canvas }}>
          {note}
        </div>
      )}

      {visible.length === 0 ? (
        <div className="px-5 py-8 text-center text-[13px]" style={{ color: colors.inkTertiary }}>
          {showAll
            ? 'The queue is empty. Durable work appears here as it is enqueued.'
            : 'No failed jobs. When a background job exhausts its retries it lands here for a manual requeue.'}
        </div>
      ) : (
        <div className="max-h-[320px] overflow-y-auto">
          {visible.map((j, i) => (
            <div key={j.id} className="px-5 py-3 flex items-start gap-3"
              style={{ borderTop: i > 0 ? `1px solid ${colors.hairline}` : undefined }}>
              <span className="w-2 h-2 rounded-full mt-1.5 shrink-0" style={{ background: statusColor(j.status) }} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[13px] font-medium" style={{ color: colors.ink }}>{humanize(j.job_type)}</span>
                  <span className="text-[11px] font-medium" style={{ color: statusColor(j.status) }}>{humanize(j.status)}</span>
                  <span className="text-[11px]" style={{ color: colors.inkTertiary }}>
                    attempt {j.attempts} of {j.max_attempts} · {ago(j.updated_at || j.created_at)}
                  </span>
                </div>
                {j.last_error && (
                  <p className="text-[12px] mt-0.5 truncate" title={j.last_error} style={{ color: colors.inkSubtle }}>
                    {j.last_error}
                  </p>
                )}
              </div>
              {j.status === 'FAILED' && (
                <button onClick={() => onRequeue(j.id)} disabled={requeueing === j.id}
                  title="Reset attempts and run this job again"
                  className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[12px] font-semibold shrink-0 disabled:opacity-60"
                  style={{ background: colors.primary, color: '#fff' }}>
                  {requeueing === j.id
                    ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    : <RotateCcw className="w-3.5 h-3.5" />}
                  Requeue
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Tenant detail ─────────────────────────────────────────────────
function TenantDetailPanel({
  detail, loading, colors, onClose,
}: {
  detail: OpsTenantDetail | null;
  loading: boolean;
  colors: Record<string, string>;
  onClose: () => void;
}) {
  // Flatten one level of the usage object (matches the app's System Stats view)
  // so nested rating buckets render as readable rows instead of "[object Object]".
  const usageRows = useMemo(() => {
    const u = detail?.usage || {};
    return Object.entries(u).flatMap(([k, v]) =>
      v && typeof v === 'object' && !Array.isArray(v)
        ? Object.entries(v).map(([k2, v2]) => [`${k} · ${k2}`, v2] as const)
        : [[k, v] as const],
    );
  }, [detail]);

  const sar = toPct(detail?.health?.safe_autonomy_rate);

  return (
    <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      <div className="flex items-center justify-between px-5 py-3 border-b" style={{ borderColor: colors.hairline }}>
        <div className="flex items-center gap-2 min-w-0">
          <Building2 className="w-4 h-4 flex-shrink-0" style={{ color: colors.primary }} />
          <span className="text-[14px] font-semibold truncate" style={{ color: colors.ink }}>
            {detail?.name || 'Tenant'}
          </span>
          {detail && (
            <span className="text-[11px] px-2 py-0.5 rounded-full font-medium flex-shrink-0"
              style={{ background: colors.primary + '18', color: colors.primary }}>{planLabel(detail.plan)}</span>
          )}
        </div>
        <button onClick={onClose} aria-label="Close tenant detail"
          className="p-1 rounded hover:opacity-70" style={{ color: colors.inkSubtle }}>
          <X className="w-4 h-4" />
        </button>
      </div>

      {loading && !detail ? (
        <div className="px-5 py-10 flex items-center justify-center gap-2 text-[13px]" style={{ color: colors.inkSubtle }}>
          <span className="w-4 h-4 border-2 rounded-full animate-spin" style={{ borderColor: colors.primary, borderTopColor: 'transparent' }} />
          Loading tenant…
        </div>
      ) : !detail ? (
        <div className="px-5 py-10 text-center text-[13px]" style={{ color: colors.inkTertiary }}>Tenant detail unavailable.</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-5 p-5">
          {/* Health */}
          <div>
            <div className="text-[11px] font-bold uppercase tracking-wide mb-2.5" style={{ color: colors.inkTertiary }}>Health</div>
            <div className="flex items-center gap-4">
              {sar != null ? (
                <Ring value={sar} size={64} strokeWidth={6} label="safe" />
              ) : (
                <div className="w-16 h-16 rounded-full flex items-center justify-center text-center text-[10px] px-1"
                  style={{ border: `2px dashed ${colors.hairlineStrong}`, color: colors.inkTertiary }}>
                  not measured
                </div>
              )}
              <div className="space-y-1">
                <StatLine label="Agents" value={formatNumber(detail.health.agent_count)} colors={colors} />
                <StatLine label="Executions" value={formatNumber(detail.health.execution_count)} colors={colors} />
                <StatLine label="Status" value={detail.is_active ? 'Active' : 'Inactive'} colors={colors} />
              </div>
            </div>
            {sar == null && (
              <p className="text-[11px] mt-2" style={{ color: colors.inkTertiary }}>
                Safe-autonomy rate needs recent activity to report.
              </p>
            )}
          </div>

          {/* Entitlements */}
          <div>
            <div className="text-[11px] font-bold uppercase tracking-wide mb-2.5" style={{ color: colors.inkTertiary }}>Entitlements</div>
            {detail.entitlements.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {detail.entitlements.map(e => (
                  <span key={e} className="text-[11px] px-2 py-0.5 rounded-full font-medium"
                    style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.inkMuted }}>
                    {humanize(e)}
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-[12px]" style={{ color: colors.inkTertiary }}>No entitlements on this plan.</p>
            )}
          </div>

          {/* Usage */}
          <div>
            <div className="text-[11px] font-bold uppercase tracking-wide mb-2.5" style={{ color: colors.inkTertiary }}>Usage (current period)</div>
            {usageRows.length > 0 ? (
              <div className="space-y-1">
                {usageRows.map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-3 text-[12px]">
                    <span className="truncate" style={{ color: colors.inkSubtle }}>{humanize(String(k))}</span>
                    <span className="font-mono flex-shrink-0" style={{ color: colors.ink }}>
                      {Array.isArray(v) ? `${v.length}` : typeof v === 'number' ? formatNumber(v) : String(v)}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-[12px]" style={{ color: colors.inkTertiary }}>No usage recorded this period.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function StatLine({ label, value, colors }: { label: string; value: string; colors: Record<string, string> }) {
  return (
    <div className="flex items-center gap-2 text-[12px]">
      <span style={{ color: colors.inkSubtle }}>{label}</span>
      <span className="font-mono font-medium" style={{ color: colors.ink }}>{value}</span>
    </div>
  );
}
