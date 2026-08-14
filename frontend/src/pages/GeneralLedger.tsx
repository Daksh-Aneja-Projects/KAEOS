/**
 * KAEOS - General Ledger Workspace
 *
 * A tabbed hub over the real double-entry GL: Journal, Trial Balance, Income
 * Statement, Balance Sheet, Periods (with admin close/reopen), and Payments.
 * Every figure is derived from POSTED journal lines server-side; this page only
 * renders and formats. Money is shown as human-readable currency, headline
 * figures count up, and the balance checks are live badges.
 */
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import {
  BookOpen, Scale, TrendingUp, Landmark, CalendarClock, Wallet,
  ArrowLeft, CheckCircle2, AlertTriangle, Lock, Unlock,
} from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import { BrainLoading, BrainError } from '../components/BrainStates';
import { CountUp } from '../components/CountUp';
import { StatCard } from '../components/shared/StatCard';
import { TableCard } from '../components/shared/TableCard';
import { MiniDonut, type DonutItem } from '../components/shared/MiniDonut';
import { useLiveRefresh } from '../hooks/useLiveRefresh';
import { humanize } from '../lib/format';
import { PAGE_PAD_X } from '../lib/layout';

const num = (v: unknown): number => {
  const n = typeof v === 'number' ? v : parseFloat(String(v ?? ''));
  return Number.isFinite(n) ? n : 0;
};
const money = (v: unknown): string =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(num(v));

type TabKey = 'journal' | 'trial' | 'income' | 'balance' | 'periods' | 'payments';
const TABS: { key: TabKey; label: string; icon: typeof BookOpen }[] = [
  { key: 'journal', label: 'Journal', icon: BookOpen },
  { key: 'trial', label: 'Trial Balance', icon: Scale },
  { key: 'income', label: 'Income Statement', icon: TrendingUp },
  { key: 'balance', label: 'Balance Sheet', icon: Landmark },
  { key: 'periods', label: 'Periods', icon: CalendarClock },
  { key: 'payments', label: 'Payments', icon: Wallet },
];

/** Green when the two sides agree, amber otherwise. The one honest signal a GL owes you. */
function BalanceBadge({ ok, okText, badText }: { ok: boolean; okText: string; badText: string }) {
  const { colors } = useTheme();
  const c = ok ? colors.success : colors.warning;
  const Icon = ok ? CheckCircle2 : AlertTriangle;
  return (
    <span
      className="inline-flex items-center gap-1.5 text-[12px] font-semibold px-2.5 py-1 rounded-lg"
      style={{ background: c + '1f', color: c }}
    >
      <Icon className="w-3.5 h-3.5" />
      {ok ? okText : badText}
    </span>
  );
}

function LedgerLines({ rows }: { rows: { account_code: string; account_name: string; amount: string }[] }) {
  const { colors } = useTheme();
  if (rows.length === 0) return <div className="text-[12px] py-3" style={{ color: colors.inkTertiary }}>No posted activity.</div>;
  return (
    <div className="space-y-1.5">
      {rows.map((r, i) => (
        <div key={`${r.account_code}-${i}`} className="flex items-baseline gap-2 text-[12.5px]">
          <span className="truncate" style={{ color: colors.inkSubtle }}>
            {r.account_name}{r.account_code ? <span style={{ color: colors.inkTertiary }}> · {r.account_code}</span> : null}
          </span>
          <span className="ml-auto font-mono tabular-nums shrink-0" style={{ color: colors.ink }}>{money(r.amount)}</span>
        </div>
      ))}
    </div>
  );
}

export default function GeneralLedger() {
  const { colors } = useTheme();
  const navigate = useNavigate();
  const [tab, setTab] = useState<TabKey>('journal');
  const [data, setData] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const fetchers: Record<TabKey, () => Promise<any>> = {
    journal: () => api.listJournalEntries(50),
    trial: () => api.getTrialBalance(),
    income: () => api.getIncomeStatement(),
    balance: () => api.getBalanceSheet(),
    periods: () => api.listPeriods(),
    payments: () => api.listPayments(),
  };

  const load = useCallback(async () => {
    try {
      const res = await fetchers[tab]();
      setData((d) => ({ ...d, [tab]: res }));
      setError(null);
    } catch (e: any) {
      if (!data[tab]) setError(e?.message || 'Failed to load the ledger');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  useEffect(() => { setLoading(!data[tab]); load(); /* eslint-disable-next-line */ }, [tab]);
  useLiveRefresh(load, { intervalMs: 20000 });

  const setPeriod = async (year: number, period: number, close: boolean) => {
    const verb = close ? 'Close' : 'Reopen';
    if (!window.confirm(`${verb} fiscal period ${year}-${String(period).padStart(2, '0')}?\n\n${close ? 'Back-dated postings into this period will be blocked.' : 'Postings into this period will be allowed again.'}`)) return;
    setBusy(true);
    try {
      if (close) await api.closePeriod({ fiscal_year: year, fiscal_period: period });
      else await api.reopenPeriod({ fiscal_year: year, fiscal_period: period });
      await load();
    } catch (e: any) {
      window.alert(e?.message || `Could not ${verb.toLowerCase()} the period`);
    } finally {
      setBusy(false);
    }
  };

  const cur = data[tab];

  return (
    <div className="h-full flex flex-col" style={{ background: colors.canvas, color: colors.ink }}>
      {/* Header + tabs (full-bleed, does not scroll) */}
      <div className={`${PAGE_PAD_X} pt-6 pb-3 shrink-0`}>
        <button
          onClick={() => navigate('/departments/finance')}
          className="inline-flex items-center gap-1.5 text-[12px] font-medium mb-3 rounded-md px-1 -ml-1 transition-colors"
          style={{ color: colors.inkSubtle }}
        >
          <ArrowLeft className="w-3.5 h-3.5" /> Finance
        </button>
        <div className="flex items-center gap-3 flex-wrap">
          <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0" style={{ background: colors.primary + '1f', color: colors.primary }}>
            <BookOpen className="w-5 h-5" />
          </div>
          <div className="min-w-0">
            <h1 className="text-[18px] font-bold leading-tight">General Ledger Workspace</h1>
            <p className="text-[12px]" style={{ color: colors.inkSubtle }}>Double-entry books, derived live from posted journal lines.</p>
          </div>
        </div>
        <div className="mt-4 flex gap-1 overflow-x-auto -mb-px" role="tablist" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
          {TABS.map((t) => {
            const active = t.key === tab;
            const Icon = t.icon;
            return (
              <button
                key={t.key}
                role="tab"
                aria-selected={active}
                onClick={() => setTab(t.key)}
                className="inline-flex items-center gap-1.5 px-3 py-2 text-[13px] font-medium whitespace-nowrap transition-colors"
                style={{
                  color: active ? colors.primary : colors.inkSubtle,
                  borderBottom: `2px solid ${active ? colors.primary : 'transparent'}`,
                }}
              >
                <Icon className="w-4 h-4" /> {t.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Content (scrolls within the view) */}
      <div className={`flex-1 overflow-y-auto ${PAGE_PAD_X} pb-8 pt-4`}>
        {loading && !cur ? (
          <BrainLoading message="Opening the ledger..." />
        ) : error && !cur ? (
          <BrainError message={error} onRetry={() => { setLoading(true); load(); }} />
        ) : (
          <div key={tab}>
            {tab === 'journal' && <JournalTab entries={cur || []} />}
            {tab === 'trial' && <TrialTab tb={cur} />}
            {tab === 'income' && <IncomeTab is={cur} />}
            {tab === 'balance' && <BalanceTab bs={cur} />}
            {tab === 'periods' && <PeriodsTab data={cur} busy={busy} onSet={setPeriod} />}
            {tab === 'payments' && <PaymentsTab payments={cur || []} />}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Journal ───
function JournalTab({ entries }: { entries: any[] }) {
  const { colors } = useTheme();
  const th = 'text-left text-[11px] font-semibold uppercase tracking-wide px-3 py-2';
  const td = 'px-3 py-2 text-[12.5px]';
  return (
    <TableCard minWidth={880}>
      <table className="w-full border-collapse">
        <thead>
          <tr style={{ background: colors.surface2, color: colors.inkSubtle, borderBottom: `1px solid ${colors.hairline}` }}>
            <th className={th}>Entry</th>
            <th className={th}>Date</th>
            <th className={th}>Description</th>
            <th className={th}>Source</th>
            <th className={th}>Status</th>
            <th className={`${th} text-right`}>Debit</th>
            <th className={`${th} text-right`}>Credit</th>
          </tr>
        </thead>
        <tbody>
          {entries.length === 0 && (
            <tr><td className={td} colSpan={7} style={{ color: colors.inkTertiary }}>No journal entries yet.</td></tr>
          )}
          {entries.map((e) => {
            const posted = String(e.status).toUpperCase() === 'POSTED';
            const sc = posted ? colors.success : colors.warning;
            return (
              <tr key={e.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                <td className={`${td} font-mono`} style={{ color: colors.ink }}>{e.entry_number || '—'}</td>
                <td className={td} style={{ color: colors.inkSubtle }}>{e.entry_date || '—'}</td>
                <td className={td} style={{ color: colors.ink }}>
                  <span className="block truncate max-w-[320px]" title={e.description}>{e.description || 'Journal entry'}</span>
                  {e.reference && <span className="text-[11px]" style={{ color: colors.inkTertiary }}>Ref {e.reference}</span>}
                </td>
                <td className={td} style={{ color: colors.inkSubtle }}>{humanize(e.source_module) || 'Manual'}</td>
                <td className={td}>
                  <span className="text-[11px] font-semibold px-1.5 py-0.5 rounded-md" style={{ background: sc + '1f', color: sc }}>{humanize(e.status)}</span>
                </td>
                <td className={`${td} text-right font-mono tabular-nums`} style={{ color: colors.ink }}>{money(e.total_debit)}</td>
                <td className={`${td} text-right font-mono tabular-nums`} style={{ color: colors.ink }}>{money(e.total_credit)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </TableCard>
  );
}

// ─── Trial Balance ───
function TrialTab({ tb }: { tb: any }) {
  const { colors } = useTheme();
  if (!tb) return null;
  const accounts: any[] = tb.accounts || [];
  const drift: any[] = tb.balance_cache_drift || [];
  const th = 'text-left text-[11px] font-semibold uppercase tracking-wide px-3 py-2';
  const td = 'px-3 py-2 text-[12.5px]';
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <BalanceBadge ok={!!tb.in_balance} okText="In balance" badText="Out of balance" />
        {drift.length > 0 && (
          <span className="inline-flex items-center gap-1.5 text-[12px] font-medium px-2.5 py-1 rounded-lg" style={{ background: colors.warning + '1f', color: colors.warning }}>
            <AlertTriangle className="w-3.5 h-3.5" /> {drift.length} cached balance{drift.length === 1 ? '' : 's'} drifted from the ledger
          </span>
        )}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-xl">
        <StatCard label="Total Debits" value={num(tb.total_debits)} format="currency" decimals={2} />
        <StatCard label="Total Credits" value={num(tb.total_credits)} format="currency" decimals={2} />
      </div>
      <TableCard minWidth={720}>
        <table className="w-full border-collapse">
          <thead>
            <tr style={{ background: colors.surface2, color: colors.inkSubtle, borderBottom: `1px solid ${colors.hairline}` }}>
              <th className={th}>Account</th>
              <th className={th}>Type</th>
              <th className={`${th} text-right`}>Debits</th>
              <th className={`${th} text-right`}>Credits</th>
              <th className={`${th} text-right`}>Balance</th>
            </tr>
          </thead>
          <tbody>
            {accounts.map((a) => (
              <tr key={a.account_id || a.account_code} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                <td className={td} style={{ color: colors.ink }}>
                  {a.account_name} <span className="font-mono text-[11px]" style={{ color: colors.inkTertiary }}>{a.account_code}</span>
                </td>
                <td className={td} style={{ color: colors.inkSubtle }}>{humanize(a.account_type)}</td>
                <td className={`${td} text-right font-mono tabular-nums`} style={{ color: colors.inkSubtle }}>{money(a.debits)}</td>
                <td className={`${td} text-right font-mono tabular-nums`} style={{ color: colors.inkSubtle }}>{money(a.credits)}</td>
                <td className={`${td} text-right font-mono tabular-nums font-semibold`} style={{ color: colors.ink }}>{money(a.balance)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableCard>
      <p className="text-[11.5px] leading-relaxed max-w-2xl" style={{ color: colors.inkTertiary }}>{tb.note}</p>
    </div>
  );
}

// ─── Income Statement ───
function IncomeTab({ is }: { is: any }) {
  const { colors } = useTheme();
  if (!is) return null;
  const rev = num(is.total_revenue);
  const exp = num(is.total_expenses);
  const net = num(is.net_income);
  const expLines: DonutItem[] = (is.expenses || []).map((e: any) => ({ label: e.account_name, value: num(e.amount) }));
  const revLines: any[] = is.revenue || [];
  const scale = Math.max(rev, exp, 1);
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard label="Revenue" value={rev} format="currency" decimals={2} accent={colors.success} />
        <StatCard label="Expenses" value={exp} format="currency" decimals={2} accent={colors.warning} />
        <StatCard label="Net Income" value={net} format="currency" decimals={2} accent={net >= 0 ? colors.success : colors.error} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Revenue vs Expenses live bars */}
        <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <h3 className="text-[12px] font-semibold uppercase tracking-wide mb-4" style={{ color: colors.inkSubtle }}>Revenue vs Expenses</h3>
          {[
            { label: 'Revenue', value: rev, c: colors.success },
            { label: 'Expenses', value: exp, c: colors.warning },
          ].map((b) => (
            <div key={b.label} className="mb-3 last:mb-0">
              <div className="flex items-baseline justify-between mb-1 text-[12px]">
                <span style={{ color: colors.inkSubtle }}>{b.label}</span>
                <CountUp value={b.value} prefix="$" decimals={2} className="font-mono tabular-nums" />
              </div>
              <div className="h-3 rounded" style={{ background: colors.canvas }}>
                <div className="h-3 rounded transition-all duration-700" style={{ width: `${Math.max((b.value / scale) * 100, b.value > 0 ? 3 : 0)}%`, background: b.c }} />
              </div>
            </div>
          ))}
          <div className="mt-4 pt-3 flex items-center justify-between" style={{ borderTop: `1px solid ${colors.hairline}` }}>
            <span className="text-[12px]" style={{ color: colors.inkSubtle }}>Net Income</span>
            <CountUp value={net} prefix="$" decimals={2} className="text-[15px] font-bold tabular-nums" />
          </div>
        </div>

        {/* Expense breakdown donut */}
        <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <h3 className="text-[12px] font-semibold uppercase tracking-wide mb-4" style={{ color: colors.inkSubtle }}>Expense Breakdown</h3>
          {expLines.length > 0 ? (
            <MiniDonut items={expLines} size={104} centerLabel="expenses" />
          ) : (
            <div className="text-[12px] py-6" style={{ color: colors.inkTertiary }}>No posted expenses in this period.</div>
          )}
        </div>
      </div>

      {revLines.length > 0 && (
        <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <h3 className="text-[12px] font-semibold uppercase tracking-wide mb-3" style={{ color: colors.inkSubtle }}>Revenue Detail</h3>
          <LedgerLines rows={revLines} />
        </div>
      )}
      <p className="text-[11.5px] leading-relaxed max-w-2xl" style={{ color: colors.inkTertiary }}>{is.note}</p>
    </div>
  );
}

// ─── Balance Sheet ───
function BalanceTab({ bs }: { bs: any }) {
  const { colors } = useTheme();
  if (!bs) return null;
  const ta = num(bs.total_assets);
  const tl = num(bs.total_liabilities);
  const te = num(bs.total_equity);
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <BalanceBadge ok={!!bs.balanced} okText="Assets = Liabilities + Equity" badText="Balance sheet does not tie" />
        <span className="text-[12px] font-mono tabular-nums" style={{ color: colors.inkSubtle }}>
          {money(ta)} = {money(tl)} + {money(te)}
        </span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard label="Total Assets" value={ta} format="currency" decimals={2} accent={colors.primary} />
        <StatCard label="Total Liabilities" value={tl} format="currency" decimals={2} accent={colors.warning} />
        <StatCard label="Total Equity" value={te} format="currency" decimals={2} accent={colors.success} />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {[
          { title: 'Assets', rows: bs.assets || [], total: ta },
          { title: 'Liabilities', rows: bs.liabilities || [], total: tl },
          { title: 'Equity', rows: bs.equity || [], total: te },
        ].map((col) => (
          <div key={col.title} className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
            <div className="flex items-baseline justify-between mb-3">
              <h3 className="text-[12px] font-semibold uppercase tracking-wide" style={{ color: colors.inkSubtle }}>{col.title}</h3>
              <span className="text-[13px] font-bold font-mono tabular-nums" style={{ color: colors.ink }}>{money(col.total)}</span>
            </div>
            <LedgerLines rows={col.rows} />
          </div>
        ))}
      </div>
      <p className="text-[11.5px] leading-relaxed max-w-2xl" style={{ color: colors.inkTertiary }}>{bs.note}</p>
    </div>
  );
}

// ─── Periods ───
function PeriodsTab({ data, busy, onSet }: { data: any; busy: boolean; onSet: (y: number, p: number, close: boolean) => void }) {
  const { colors } = useTheme();
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [period, setPeriod] = useState(now.getMonth() + 1);
  const periods: any[] = data?.periods || [];
  const th = 'text-left text-[11px] font-semibold uppercase tracking-wide px-3 py-2';
  const td = 'px-3 py-2 text-[12.5px]';

  return (
    <div className="space-y-5">
      {/* Close a period */}
      <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        <h3 className="text-[12px] font-semibold uppercase tracking-wide mb-1" style={{ color: colors.inkSubtle }}>Close a fiscal period</h3>
        <p className="text-[12px] mb-3" style={{ color: colors.inkTertiary }}>Closing a period stops back-dated postings into a reported window. This action is confirmed and audited.</p>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-[11px] font-medium" style={{ color: colors.inkSubtle }}>
            <span className="block mb-1">Fiscal year</span>
            <input type="number" value={year} min={1900} max={2200} onChange={(e) => setYear(parseInt(e.target.value) || year)}
              className="w-28 px-2.5 py-1.5 rounded-lg text-[13px] tabular-nums outline-none"
              style={{ background: colors.canvas, border: `1px solid ${colors.hairline}`, color: colors.ink }} />
          </label>
          <label className="text-[11px] font-medium" style={{ color: colors.inkSubtle }}>
            <span className="block mb-1">Period (month)</span>
            <input type="number" value={period} min={1} max={12} onChange={(e) => setPeriod(Math.min(12, Math.max(1, parseInt(e.target.value) || 1)))}
              className="w-24 px-2.5 py-1.5 rounded-lg text-[13px] tabular-nums outline-none"
              style={{ background: colors.canvas, border: `1px solid ${colors.hairline}`, color: colors.ink }} />
          </label>
          <button
            disabled={busy}
            onClick={() => onSet(year, period, true)}
            className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-[13px] font-semibold transition-opacity disabled:opacity-50"
            style={{ background: colors.primary, color: '#fff' }}
          >
            <Lock className="w-3.5 h-3.5" /> Close period
          </button>
        </div>
      </div>

      <TableCard minWidth={640}>
        <table className="w-full border-collapse">
          <thead>
            <tr style={{ background: colors.surface2, color: colors.inkSubtle, borderBottom: `1px solid ${colors.hairline}` }}>
              <th className={th}>Period</th>
              <th className={th}>Status</th>
              <th className={th}>Closed by</th>
              <th className={th}>Closed at</th>
              <th className={`${th} text-right`}>Action</th>
            </tr>
          </thead>
          <tbody>
            {periods.length === 0 && (
              <tr><td className={td} colSpan={5} style={{ color: colors.inkTertiary }}>No closed periods. Periods without a row are open by default.</td></tr>
            )}
            {periods.map((p) => {
              const closed = String(p.status).toUpperCase() === 'CLOSED';
              const sc = closed ? colors.warning : colors.success;
              return (
                <tr key={`${p.fiscal_year}-${p.fiscal_period}`} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                  <td className={`${td} font-mono`} style={{ color: colors.ink }}>{p.fiscal_year}-{String(p.fiscal_period).padStart(2, '0')}</td>
                  <td className={td}><span className="text-[11px] font-semibold px-1.5 py-0.5 rounded-md" style={{ background: sc + '1f', color: sc }}>{humanize(p.status)}</span></td>
                  <td className={td} style={{ color: colors.inkSubtle }}>{p.closed_by || '—'}</td>
                  <td className={td} style={{ color: colors.inkSubtle }}>{p.closed_at ? new Date(p.closed_at).toLocaleString() : '—'}</td>
                  <td className={`${td} text-right`}>
                    <button
                      disabled={busy}
                      onClick={() => onSet(p.fiscal_year, p.fiscal_period, !closed)}
                      className="inline-flex items-center gap-1 text-[12px] font-medium px-2 py-1 rounded-md transition-opacity disabled:opacity-50"
                      style={{ color: closed ? colors.success : colors.warning, background: (closed ? colors.success : colors.warning) + '14' }}
                    >
                      {closed ? <><Unlock className="w-3.5 h-3.5" /> Reopen</> : <><Lock className="w-3.5 h-3.5" /> Close</>}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </TableCard>
      {data?.note && <p className="text-[11.5px] leading-relaxed max-w-2xl" style={{ color: colors.inkTertiary }}>{data.note}</p>}
    </div>
  );
}

// ─── Payments ───
function PaymentsTab({ payments }: { payments: any[] }) {
  const { colors } = useTheme();
  const total = payments.reduce((s, p) => s + num(p.amount), 0);
  const byMethod: Record<string, number> = {};
  payments.forEach((p) => { const m = humanize(p.method) || 'Other'; byMethod[m] = (byMethod[m] || 0) + num(p.amount); });
  const donut: DonutItem[] = Object.entries(byMethod).map(([label, value]) => ({ label, value }));
  const th = 'text-left text-[11px] font-semibold uppercase tracking-wide px-3 py-2';
  const td = 'px-3 py-2 text-[12.5px]';
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <StatCard label="Total Paid" value={total} format="currency" decimals={2} accent={colors.primary} className="lg:col-span-1" />
        {donut.length > 0 && (
          <div className="lg:col-span-2 rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
            <h3 className="text-[12px] font-semibold uppercase tracking-wide mb-3" style={{ color: colors.inkSubtle }}>By Payment Method</h3>
            <MiniDonut items={donut} size={96} centerLabel="paid" />
          </div>
        )}
      </div>
      <TableCard minWidth={720}>
        <table className="w-full border-collapse">
          <thead>
            <tr style={{ background: colors.surface2, color: colors.inkSubtle, borderBottom: `1px solid ${colors.hairline}` }}>
              <th className={th}>Payment</th>
              <th className={th}>Method</th>
              <th className={th}>Status</th>
              <th className={th}>Date</th>
              <th className={`${th} text-right`}>Amount</th>
            </tr>
          </thead>
          <tbody>
            {payments.length === 0 && (
              <tr><td className={td} colSpan={5} style={{ color: colors.inkTertiary }}>No payments recorded yet.</td></tr>
            )}
            {payments.map((p, i) => {
              const paid = String(p.status).toUpperCase() === 'PAID' || String(p.status).toUpperCase() === 'COMPLETED';
              const sc = paid ? colors.success : colors.warning;
              return (
                <tr key={p.id || i} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                  <td className={`${td} font-mono`} style={{ color: colors.ink }}>{p.number || p.id?.slice(0, 8) || '—'}</td>
                  <td className={td} style={{ color: colors.inkSubtle }}>{humanize(p.method)}</td>
                  <td className={td}><span className="text-[11px] font-semibold px-1.5 py-0.5 rounded-md" style={{ background: sc + '1f', color: sc }}>{humanize(p.status)}</span></td>
                  <td className={td} style={{ color: colors.inkSubtle }}>{p.date || '—'}</td>
                  <td className={`${td} text-right font-mono tabular-nums font-semibold`} style={{ color: colors.ink }}>{money(p.amount)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </TableCard>
    </div>
  );
}
