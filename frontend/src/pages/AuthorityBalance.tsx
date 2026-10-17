import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router';
import { ArrowLeft, Download, Loader2 } from 'lucide-react';
import { api, downloadFile, ApiError } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { BrainLoading, BrainError } from '../components/BrainStates';
import { EnterpriseNotice } from '../components/EnterpriseNotice';
import { humanize } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';
import { DEPARTMENT_LABELS, type DepartmentSlug } from '../lib/departments';

/**
 * Autonomy balance sheet: for a period, what stood open, what ran on lent
 * authority, what went wrong, and how well the humans in the loop looked.
 *
 * Rendered twice: as a collapsible panel inside the Authority page
 * (`embedded`) and as a full statement on /platform/authority/balance.
 * Honesty contract: every figure is the server's. A figure the record does not
 * hold reads "Not measured", an amount no run stated reads "Not stated", and
 * an unknown amount is never shown as zero.
 */

type PeriodKind = 'month' | 'quarter' | 'custom';
type Tone = 'ok' | 'warn' | 'bad' | 'muted' | 'primary';

const NOT_MEASURED = 'Not measured';
const NOT_STATED = 'Not stated';

const GRANT_STATE_LABEL: Record<string, string> = {
  active: 'Active', expired: 'Expired', revoked: 'Revoked', pending: 'Waiting for acceptance',
  suspended: 'Suspended', declined: 'Declined',
};

function numText(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(Number(n))) return NOT_MEASURED;
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function pctText(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(Number(n))) return NOT_MEASURED;
  return `${Number(n).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
}

function runsText(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(Number(n))) return NOT_MEASURED;
  return `${numText(n)} run${Number(n) === 1 ? '' : 's'}`;
}

/** A count the server may send as a bare number or as { runs }. */
function countOf(v: any): number | null {
  if (v == null) return null;
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (typeof v === 'object' && v.runs != null && Number.isFinite(Number(v.runs))) return Number(v.runs);
  return null;
}

function deptLabel(slug: string): string {
  return DEPARTMENT_LABELS[slug as DepartmentSlug] || humanize(slug);
}

function whenText(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isFinite(d.getTime()) ? d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : String(iso);
}

function slug(s: string): string {
  return String(s || 'statement').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'statement';
}

/** Signed change for a delta; null means the two periods cannot be compared. */
function deltaText(n: number | null | undefined, unit: string): string {
  if (n == null || !Number.isFinite(Number(n))) return 'Not comparable';
  const v = Number(n);
  if (v === 0) return 'No change';
  const body = Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 1 });
  return `${v > 0 ? '+' : '-'}${body}${unit}`;
}

// ── Small pieces (this file owns its own so the Authority page and this one never import each other) ──

function Pill({ text, tone }: { text: string; tone: Tone }) {
  const { colors } = useTheme();
  const c = tone === 'ok' ? colors.success : tone === 'warn' ? colors.warning : tone === 'bad' ? colors.error
    : tone === 'primary' ? colors.primary : colors.inkSubtle;
  return (
    <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold whitespace-nowrap"
      style={{ background: c + '18', color: c, border: `1px solid ${c}30` }}>{text}</span>
  );
}

function Card({ title, right, children }: { title: string; right?: React.ReactNode; children: React.ReactNode }) {
  const { colors } = useTheme();
  return (
    <div className="rounded-xl overflow-hidden min-w-0" style={{ border: `1px solid ${colors.hairline}`, background: colors.surface1 }}>
      <div className="px-4 py-2 text-[11.5px] font-medium flex items-center justify-between gap-3"
        style={{ background: colors.surface2, color: colors.inkSubtle }}>
        <span>{title}</span>{right}
      </div>
      <div className="px-4 py-2.5">{children}</div>
    </div>
  );
}

function Row({ label, value, caption, first }: { label: string; value: React.ReactNode; caption?: React.ReactNode; first?: boolean }) {
  const { colors } = useTheme();
  return (
    <div className="py-1.5" style={{ borderTop: first ? undefined : `1px solid ${colors.hairline}` }}>
      <div className="flex items-baseline justify-between gap-3 text-[12.5px]">
        <span style={{ color: colors.inkMuted }}>{label}</span>
        <span className="tabular-nums font-medium text-right" style={{ color: colors.ink }}>{value}</span>
      </div>
      {caption ? <div className="text-[11px] leading-snug mt-0.5" style={{ color: colors.inkTertiary }}>{caption}</div> : null}
    </div>
  );
}

function Caption({ children }: { children: React.ReactNode }) {
  const { colors } = useTheme();
  return <p className="text-[11px] leading-snug mt-1.5" style={{ color: colors.inkTertiary }}>{children}</p>;
}

/** Interval bar: the 95 percent range of a rate against 0 to 100, with the point inside it. */
function RangeBar({ point, lo, hi }: { point: number | null; lo: number; hi: number }) {
  const { colors } = useTheme();
  const l = Math.max(0, Math.min(100, lo)), h = Math.max(l, Math.min(100, hi));
  return (
    <div className="mt-1.5">
      <div className="relative h-2 rounded-full" style={{ background: colors.hairline }} role="img"
        aria-label={`95 percent interval ${lo} to ${hi} percent`}>
        <div className="absolute top-0 h-2 rounded-full" style={{ left: `${l}%`, width: `${Math.max(1, h - l)}%`, background: colors.primary + '66' }} />
        {point != null && <div className="absolute -top-0.5 w-0.5 h-3 rounded" style={{ left: `${Math.max(0, Math.min(100, point))}%`, background: colors.primary }} />}
      </div>
      <div className="flex justify-between text-[11px] mt-1" style={{ color: colors.inkTertiary }}>
        <span>0%</span><span>{`95% interval ${numText(lo)}% to ${numText(hi)}%`}</span><span>100%</span>
      </div>
    </div>
  );
}

/** A Money figure: the amount only when the record holds one, else "Not measured" with the server's note. */
function moneyRow(label: string, m: any, first?: boolean, extra?: string): React.ReactNode {
  const amount = m?.amount;
  const known = amount != null && Number.isFinite(Number(amount));
  const withAmt = m?.runs_with_amount, runs = m?.runs, without = m?.runs_without_amount;
  const bits: string[] = [];
  if (m?.note) bits.push(String(m.note));
  else if (known && Number(without) > 0) bits.push(`${numText(without)} run${Number(without) === 1 ? '' : 's'} stated no amount and are not in this total.`);
  else if (!known && withAmt != null && runs != null) bits.push(`${numText(withAmt)} of ${numText(runs)} runs stated an amount.`);
  if (extra) bits.push(extra);
  return <Row first={first} label={label} value={known ? numText(amount) : NOT_MEASURED} caption={bits.length ? bits.join(' ') : undefined} />;
}

// ── Sections ──────────────────────────────────────────────────────────────────

function PositionCard({ d }: { d: any }) {
  const p = d.position || {};
  const states = Object.entries(p.by_state || {}).filter(([, n]) => Number(n) > 0);
  return (
    <Card title="Position">
      <Row first label="Open grants" value={numText(p.open_grants)}
        caption={states.length ? states.map(([k, n]) => `${numText(n as number)} ${(GRANT_STATE_LABEL[k] || humanize(k)).toLowerCase()}`).join(', ') : undefined} />
      <Row label="People who have lent authority" value={numText(p.holders)} />
      <Row label="Lent ceiling per window" value={p.lent_ceiling_per_window == null ? NOT_MEASURED : numText(p.lent_ceiling_per_window)}
        caption={p.lent_ceiling_per_window == null ? undefined : 'Across grants with a money limit'} />
      <Row label="Grants with no money limit" value={numText(p.grants_without_money_limit)} />
      {p.note && <Caption>{p.note}</Caption>}
    </Card>
  );
}

function FlowCard({ d }: { d: any }) {
  const f = d.flow || {};
  const adv = f.adverse_under_lent_authority || {};
  const un = f.unlent || {};
  const advBits: string[] = [];
  if (adv.rated_wrong != null) advBits.push(`${numText(adv.rated_wrong)} rated wrong`);
  if (adv.failed != null) advBits.push(`${numText(adv.failed)} failed`);
  return (
    <Card title="Flow">
      <Row first label="Proceeded on lent authority" value={runsText(f.proceeded_on_lent_authority?.runs)} />
      {moneyRow('Amount that proceeded', f.proceeded_on_lent_authority)}
      <Row label="Went wrong under lent authority" value={runsText(adv.runs)} caption={advBits.length ? advBits.join(', ') : undefined} />
      {moneyRow('Amount that went wrong', adv)}
      <Row label="Released, nothing happened" value={runsText(countOf(f.released_nothing_happened))} />
      <Row label="Refused at the write" value={runsText(countOf(f.refused_at_the_write))}
        caption="The lender's authority was gone by the time the write was due." />
      <Row label="Ran on nobody's authority" value={runsText(un.runs)}
        caption={un.routed_to_a_human != null || un.proceeded_in_observe_mode != null
          ? `${numText(un.routed_to_a_human)} routed to a person, ${numText(un.proceeded_in_observe_mode)} proceeded in observe mode`
          : undefined} />
      <Row label="In flight at the end of the period" value={runsText(countOf(f.in_flight_at_period_end))} />
    </Card>
  );
}

function OversightCard({ d }: { d: any }) {
  const { colors } = useTheme();
  const o = d.oversight || {};
  const grade = o.evidence_grade_pct;
  const gradeKnown = grade != null && Number.isFinite(Number(grade));
  const ci = Array.isArray(o.override_rate_ci_pct) && o.override_rate_ci_pct.length === 2 ? o.override_rate_ci_pct : null;
  const ciOk = ci && ci[0] != null && ci[1] != null && Number.isFinite(Number(ci[0])) && Number.isFinite(Number(ci[1]));
  return (
    <Card title="Oversight">
      <div className="pb-2">
        <div className="text-[26px] leading-none font-semibold tabular-nums" style={{ color: colors.ink }}>
          {gradeKnown ? pctText(grade) : NOT_MEASURED}
        </div>
        <div className="text-[12px] mt-1" style={{ color: colors.inkMuted }}>of human decisions were evidence-grade</div>
        {gradeKnown && (
          <div className="h-1 rounded-full overflow-hidden mt-2" style={{ background: colors.hairline }} aria-hidden>
            <div className="h-full rounded-full" style={{ width: `${Math.max(0, Math.min(100, Number(grade)))}%`, background: colors.primary, transition: 'width 600ms ease-out' }} />
          </div>
        )}
      </div>
      <Row first label="Human decisions" value={numText(o.human_decisions)} />
      <Row label="Decided quickly" value={pctText(o.quick_rate_pct)} />
      <Row label="Reviews counted for the override rate" value={numText(o.counted_reviews)} />
      <div className="py-1.5" style={{ borderTop: `1px solid ${colors.hairline}` }}>
        <div className="flex items-baseline justify-between gap-3 text-[12.5px]">
          <span style={{ color: colors.inkMuted }}>Override rate</span>
          <span className="tabular-nums font-medium" style={{ color: colors.ink }}>{pctText(o.override_rate_pct)}</span>
        </div>
        {ciOk ? <RangeBar point={o.override_rate_pct == null ? null : Number(o.override_rate_pct)} lo={Number(ci[0])} hi={Number(ci[1])} />
          : <div className="text-[11px] mt-0.5" style={{ color: colors.inkTertiary }}>No interval: too few counted reviews to bound it.</div>}
      </div>
      {o.note && <Caption>{o.note}</Caption>}
    </Card>
  );
}

function BreakdownTable({ title, rows, label }: { title: string; rows: Record<string, any> | undefined; label: (k: string) => string }) {
  const { colors } = useTheme();
  const list = Object.entries(rows || {}).sort((a, b) => Number(b[1]?.runs || 0) - Number(a[1]?.runs || 0));
  const th = 'text-left font-medium py-1 pr-3 whitespace-nowrap';
  const td = 'py-1 pr-3 tabular-nums whitespace-nowrap';
  return (
    <Card title={title}>
      {list.length === 0 ? (
        <div className="text-[12px] py-1" style={{ color: colors.inkTertiary }}>Nothing ran on lent authority in this period.</div>
      ) : (
        <div className="overflow-auto max-h-52">
          <table className="w-full text-[12px]" style={{ color: colors.inkMuted }}>
            <thead>
              <tr style={{ color: colors.inkSubtle, borderBottom: `1px solid ${colors.hairline}` }}>
                <th className={th}>Name</th><th className={th}>Runs</th><th className={th}>Amount</th><th className={th}>Went wrong</th>
              </tr>
            </thead>
            <tbody>
              {list.map(([k, v], i) => {
                const amt = v?.amount;
                const known = amt != null && Number.isFinite(Number(amt));
                const partial = known && v?.with_amount != null && v?.runs != null && Number(v.with_amount) < Number(v.runs);
                return (
                  <tr key={k} style={{ borderTop: i === 0 ? undefined : `1px solid ${colors.hairline}` }}>
                    <td className="py-1 pr-3 max-w-[160px] truncate" style={{ color: colors.ink }} title={label(k)}>{label(k)}</td>
                    <td className={td}>{numText(v?.runs)}</td>
                    <td className={td} style={{ color: known ? colors.inkMuted : colors.inkTertiary }}
                      title={partial ? `${v.with_amount} of ${v.runs} runs stated an amount` : undefined}>
                      {known ? `${numText(amt)}${partial ? '*' : ''}` : NOT_STATED}
                    </td>
                    <td className={td}>{numText(v?.adverse)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

const DELTA_ROWS: {
  key: string; label: string; unit: string; good: 'up' | 'down' | null;
  prev: (p: any) => number | null | undefined;
}[] = [
  { key: 'proceeded_runs', label: 'Runs that proceeded', unit: '', good: null, prev: p => p?.flow?.proceeded_on_lent_authority?.runs },
  { key: 'proceeded_amount', label: 'Amount that proceeded', unit: '', good: null, prev: p => p?.flow?.proceeded_on_lent_authority?.amount },
  { key: 'adverse_runs', label: 'Runs that went wrong', unit: '', good: 'down', prev: p => p?.flow?.adverse_under_lent_authority?.runs },
  { key: 'unlent_runs', label: "Runs on nobody's authority", unit: '', good: 'down', prev: p => p?.flow?.unlent?.runs },
  { key: 'override_rate_pct', label: 'Override rate', unit: ' pts', good: null, prev: p => p?.oversight?.override_rate_pct },
  { key: 'evidence_grade_pct', label: 'Evidence-grade share', unit: ' pts', good: 'up', prev: p => p?.oversight?.evidence_grade_pct },
];

function VersusCard({ d }: { d: any }) {
  const { colors } = useTheme();
  const prev = d.previous;
  const ch = d.change || {};
  return (
    <Card title="Versus the previous period" right={prev?.period?.label ? <span>{prev.period.label}</span> : undefined}>
      {!prev ? (
        <div className="text-[12px] py-1" style={{ color: colors.inkTertiary }}>There is no earlier period on the record to compare with.</div>
      ) : (
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-x-4">
          {DELTA_ROWS.map(r => {
            const v = ch[r.key];
            const known = v != null && Number.isFinite(Number(v));
            const n = known ? Number(v) : 0;
            const c = !known || n === 0 || r.good == null ? colors.inkMuted
              : ((r.good === 'up') === (n > 0)) ? colors.success : colors.warning;
            const was = r.prev(prev);
            return (
              <div key={r.key} className="py-1.5" style={{ borderTop: `1px solid ${colors.hairline}` }}>
                <div className="text-[11px]" style={{ color: colors.inkSubtle }}>{r.label}</div>
                <div className="text-[15px] font-semibold tabular-nums" style={{ color: known ? c : colors.inkTertiary }}>{deltaText(v, r.unit)}</div>
                <div className="text-[11px]" style={{ color: colors.inkTertiary }}>
                  {was == null ? 'Previous: Not measured' : `Previous: ${r.unit ? pctText(was) : numText(was)}`}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

function OpenGrants({ grants }: { grants: any[] }) {
  const { colors } = useTheme();
  if (!grants.length) return null;
  return (
    <details className="rounded-xl" style={{ border: `1px solid ${colors.hairline}`, background: colors.surface1 }}>
      <summary className="px-4 py-2 text-[11.5px] font-medium cursor-pointer" style={{ color: colors.inkSubtle }}>
        {`Open grants in this statement (${grants.length})`}
      </summary>
      <div className="px-4 pb-2">
        {grants.slice(0, 40).map((g, i) => {
          const s = g.scope || {};
          const where = [s.department ? deptLabel(s.department) : '', Array.isArray(s.skills) && s.skills.length ? s.skills.map((x: string) => humanize(x)).join(', ') : '']
            .filter(Boolean).join(', ') || 'Any department';
          return (
            <div key={g.id || i} className="py-1.5 flex items-center gap-2 flex-wrap text-[12px]" style={{ borderTop: `1px solid ${colors.hairline}`, color: colors.inkMuted }}>
              <span className="font-medium min-w-0 truncate" style={{ color: colors.ink }}>{g.holder || NOT_MEASURED}</span>
              <span className="min-w-0 truncate flex-1">{where}</span>
              <Pill text={GRANT_STATE_LABEL[g.state] || humanize(g.state)} tone={g.state === 'active' ? 'ok' : g.state === 'revoked' ? 'bad' : 'muted'} />
            </div>
          );
        })}
      </div>
    </details>
  );
}

// ── The statement ─────────────────────────────────────────────────────────────

export default function AuthorityBalance({ embedded = false }: { embedded?: boolean }) {
  const { colors } = useTheme();
  const [period, setPeriod] = useState<PeriodKind>('month');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [st, setSt] = useState<{ loading: boolean; data: any; error: string | null; notice: string | null }>(
    { loading: true, data: null, error: null, notice: null });
  const [nonce, setNonce] = useState(0);
  const [exporting, setExporting] = useState<null | 'text' | 'json'>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const seq = useRef(0);

  const customReady = period !== 'custom' || (!!start && !!end && start <= end);
  const startIso = period === 'custom' && start ? `${start}T00:00:00Z` : undefined;
  const endIso = period === 'custom' && end ? `${end}T23:59:59Z` : undefined;
  const query = useMemo(() => ({ period, start: startIso, end: endIso }), [period, startIso, endIso]);

  useEffect(() => {
    if (!customReady) return;
    const id = ++seq.current;
    setSt(prev => ({ ...prev, loading: true, error: null, notice: null }));
    api.getAuthorityBalance({ ...query, previous: true })
      .then((data: any) => { if (id === seq.current) setSt({ loading: false, data, error: null, notice: null }); })
      .catch((e: any) => {
        if (id !== seq.current) return;
        if (e instanceof ApiError && (e.status === 402 || e.status === 403)) setSt({ loading: false, data: null, error: null, notice: e.message });
        else setSt({ loading: false, data: null, error: e?.message || 'The statement could not be read.', notice: null });
      });
  }, [query, customReady, nonce]);

  const d = st.data;
  const exportAs = async (format: 'text' | 'json') => {
    setExporting(format); setExportError(null);
    try {
      const label = slug(d?.period?.label || period);
      await downloadFile(api.authorityBalanceExportPath(query, format), `authority-balance-${label}.${format === 'text' ? 'txt' : 'json'}`);
    } catch (e: any) {
      setExportError(e?.message || 'The statement could not be exported.');
    } finally { setExporting(null); }
  };

  const inputStyle: React.CSSProperties = { background: colors.inputBg, color: colors.ink, border: `1px solid ${colors.hairline}` };
  const btn = 'px-2.5 py-1.5 rounded-lg text-[11.5px] font-semibold flex items-center gap-1.5 disabled:opacity-50';
  const quiet: React.CSSProperties = { background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` };

  const controls = (
    <div className="flex items-end gap-2 flex-wrap">
      <label className="block">
        <span className="block text-[11px] mb-1" style={{ color: colors.inkSubtle }}>Period</span>
        <select value={period} onChange={e => setPeriod(e.target.value as PeriodKind)} aria-label="Statement period"
          className="px-2.5 py-1.5 rounded-lg text-[12.5px] focus:outline-none" style={inputStyle}>
          <option value="month">This month</option>
          <option value="quarter">This quarter</option>
          <option value="custom">Custom</option>
        </select>
      </label>
      {period === 'custom' && (
        <>
          <label className="block">
            <span className="block text-[11px] mb-1" style={{ color: colors.inkSubtle }}>From</span>
            <input type="date" value={start} max={end || undefined} onChange={e => setStart(e.target.value)}
              className="px-2.5 py-1.5 rounded-lg text-[12.5px] focus:outline-none" style={inputStyle} />
          </label>
          <label className="block">
            <span className="block text-[11px] mb-1" style={{ color: colors.inkSubtle }}>To</span>
            <input type="date" value={end} min={start || undefined} onChange={e => setEnd(e.target.value)}
              className="px-2.5 py-1.5 rounded-lg text-[12.5px] focus:outline-none" style={inputStyle} />
          </label>
        </>
      )}
      <span className="ml-auto flex items-center gap-2 flex-wrap">
        <button onClick={() => exportAs('text')} disabled={!customReady || exporting !== null || !d} className={btn} style={quiet}>
          {exporting === 'text' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Download className="w-3 h-3" />} Export statement
        </button>
        <button onClick={() => exportAs('json')} disabled={!customReady || exporting !== null || !d} className={btn} style={quiet}>
          {exporting === 'json' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Download className="w-3 h-3" />} Export JSON
        </button>
      </span>
    </div>
  );

  let body: React.ReactNode;
  if (!customReady) {
    body = (
      <p className="text-[12.5px] py-3" style={{ color: colors.inkTertiary }}>
        {start && end && start > end ? 'The start date is after the end date. Pick a range that runs forward.' : 'Pick both dates to read a custom period.'}
      </p>
    );
  } else if (st.loading && !d) {
    body = <BrainLoading variant="compact" message="Reading the statement for this period…" />;
  } else if (st.notice) {
    body = <EnterpriseNotice message={st.notice} />;
  } else if (st.error) {
    body = <BrainError message={st.error} onRetry={() => setNonce(n => n + 1)} />;
  } else if (d) {
    body = (
      <div className="space-y-3" style={{ opacity: st.loading ? 0.55 : 1, transition: 'opacity 150ms' }}>
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="text-[14px] font-semibold" style={{ color: colors.ink }}>{d.period?.label || humanize(period)}</span>
          {d.period?.start && d.period?.end && (
            <span className="text-[11.5px]" style={{ color: colors.inkTertiary }}>{`${whenText(d.period.start)} to ${whenText(d.period.end)}`}</span>
          )}
        </div>
        <div className={`grid grid-cols-1 ${embedded ? 'md:grid-cols-2' : 'lg:grid-cols-3'} gap-3`}>
          <PositionCard d={d} />
          <FlowCard d={d} />
          <OversightCard d={d} />
        </div>
        <div className={`grid grid-cols-1 ${embedded ? 'md:grid-cols-2' : 'lg:grid-cols-3'} gap-3`}>
          <BreakdownTable title="By holder" rows={d.flow?.by_holder} label={k => k} />
          <BreakdownTable title="By department" rows={d.flow?.by_department} label={deptLabel} />
          <BreakdownTable title="By skill" rows={d.flow?.by_skill} label={humanize} />
        </div>
        <VersusCard d={d} />
        <OpenGrants grants={Array.isArray(d.open_grants) ? d.open_grants : []} />
        <div className="text-[11px] leading-snug space-y-0.5" style={{ color: colors.inkTertiary }}>
          {d.basis && <p>{d.basis}</p>}
          {d.generated_at && <p>{`Generated ${whenText(d.generated_at)}`}</p>}
        </div>
      </div>
    );
  }

  const inner = (
    <div className="space-y-3">
      {controls}
      {exportError && <p className="text-[12px]" style={{ color: colors.error }} role="alert">{exportError}</p>}
      {body}
    </div>
  );

  if (embedded) return inner;

  return (
    <div className={`h-full overflow-y-auto ${PAGE_PAD}`} style={{ background: colors.canvas, color: colors.ink }}>
      <div className="space-y-4 max-w-[1280px]">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="min-w-0">
            <h1 className="text-[21px] font-semibold tracking-tight">Autonomy balance sheet</h1>
            <p className="text-[12.5px] mt-0.5" style={{ color: colors.inkSubtle }}>
              What stood open, what ran on lent authority, what went wrong, and whether the humans in the loop looked.
            </p>
          </div>
          <Link to="/platform/authority" className="px-2.5 py-1.5 rounded-lg text-[11.5px] font-semibold flex items-center gap-1.5" style={quiet}>
            <ArrowLeft className="w-3.5 h-3.5" /> Back to Authority
          </Link>
        </div>
        {inner}
      </div>
    </div>
  );
}
