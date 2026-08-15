import React, { useEffect, useId, useState } from 'react';
import {
  ShoppingCart, ClipboardList, FileCheck2, PackageCheck, Building2,
  Search, RefreshCw, Loader2, ShieldCheck, CheckCircle2, XCircle,
  AlertTriangle, GitCompareArrows, Gavel, MinusCircle, Sparkles,
  BrainCircuit, Plus, X, TrendingUp,
} from 'lucide-react';
import { api } from '../api/client';
import type {
  ProcurementDashboard, RequisitionRow, PurchaseOrderRow, GoodsReceiptRow,
  VendorRow, ProcurementGate, ApprovalOutcome, ThreeWayMatch,
  SourcingAssessment, SpendGuardResult,
} from '../api/endpoints/procurement';
import { useTheme } from '../context/ThemeContext';
import { CountUp } from '../components/CountUp';
import Ring from '../components/shared/Ring';
import StatCard from '../components/shared/StatCard';
import TableCard from '../components/shared/TableCard';
import LiveBadge from '../components/LiveBadge';
import DomainAnalytics from '../components/DomainAnalytics';
import { useFocusTrap } from '../hooks/useFocusTrap';
import { announce } from '../components/a11y/LiveRegion';
import { humanize, formatCurrency, formatDate } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';
import { useLiveRefresh } from '../hooks/useLiveRefresh';

const ACCENT = '#8b5cf6';

type Tab = 'overview' | 'requisitions' | 'purchase-orders' | 'goods-receipts' | 'vendors' | 'analytics';
const VALID: Tab[] = ['overview', 'requisitions', 'purchase-orders', 'goods-receipts', 'vendors', 'analytics'];

/** Plain-English copy for the gated 7-gate pipeline's run status (never render
 * the raw status string). Mirrors app.agents.runtime.AgentExecutor states. */
const RUN_STATUS_COPY: Record<string, string> = {
  SUCCESS_CLEAN: 'Assessment complete.',
  PENDING_HITL: 'Routed to a human reviewer for approval before it can proceed.',
  BLOCKED_COMPLIANCE: 'Blocked by a compliance check.',
  BLOCKED_FAIRNESS: 'Held for a fairness review.',
  BLOCKED_DEBATE: 'Blocked after multi-agent debate.',
  ESCALATED_DEBATE: 'Escalated to a human after multi-agent debate.',
  HUMAN_OVERRIDDEN: 'Rejected by a human reviewer.',
  FAILED_ACTUATION: 'The recommendation was produced but a downstream write failed.',
  FAILED_AUDIT: 'Blocked by a post-execution audit check.',
};

/** Plain-English copy for each source-to-pay control. */
const GATE_COPY: Record<string, { title: string; ok: string }> = {
  SPEND_AUTHORIZATION: { title: 'Spend authorization', ok: "Amount is within the approver's delegated limit." },
  SEGREGATION_OF_DUTIES: { title: 'Segregation of duties', ok: 'Requester, approver and receiver are distinct people.' },
  THREE_WAY_MATCH: { title: 'Three-way match', ok: 'Every linked invoice reconciles with the PO and goods receipt.' },
  OFAC_SANCTIONS: { title: 'Sanctions screening', ok: 'Vendor is not on a denied-parties list.' },
  PO_STATE: { title: 'Purchase order state', ok: 'The order is awaiting approval.' },
};
const STATUS_COPY: Record<string, string> = {
  PASS: 'Cleared', BLOCK: 'Blocked', ADVISORY: 'Could not verify', NOT_APPLICABLE: 'Not applicable',
};
const MATCH_COPY: Record<string, string> = {
  MATCHED: 'Matched', EXCEPTION: 'Exception', PENDING_RECEIPT: 'Awaiting receipt', NO_PO: 'No purchase order',
};

const ProcurementView: React.FC<{ domain?: string; defaultTab?: string }> = ({ defaultTab }) => {
  const { colors } = useTheme();
  const [tab, setTab] = useState<Tab>(
    defaultTab && VALID.includes(defaultTab as Tab) ? (defaultTab as Tab) : 'overview',
  );
  const [loading, setLoading] = useState(true);
  const [searchQ, setSearchQ] = useState('');
  const [actionMsg, setActionMsg] = useState('');
  const [lastSync, setLastSync] = useState<number | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const [dash, setDash] = useState<ProcurementDashboard | null>(null);
  const [reqs, setReqs] = useState<RequisitionRow[]>([]);
  const [pos, setPos] = useState<PurchaseOrderRow[]>([]);
  const [receipts, setReceipts] = useState<GoodsReceiptRow[]>([]);
  const [vendors, setVendors] = useState<VendorRow[]>([]);

  // Governance action panels (last action wins).
  const [approval, setApproval] = useState<{ po: string; outcome: ApprovalOutcome } | null>(null);
  const [guard, setGuard] = useState<SpendGuardResult | null>(null);
  const [match, setMatch] = useState<{ po: string; result: ThreeWayMatch } | null>(null);
  const [screen, setScreen] = useState<{ vendor: string; gate: ProcurementGate } | null>(null);
  const [assess, setAssess] = useState<{ item: string; result: SourcingAssessment } | null>(null);
  const [screenInput, setScreenInput] = useState('');

  // "New ..." create panels.
  const [newReqOpen, setNewReqOpen] = useState(false);
  const [newPoOpen, setNewPoOpen] = useState(false);

  useEffect(() => { loadData(); }, []);
  useLiveRefresh(loadData, { intervalMs: 20000 });

  async function loadData() {
    setLoading(true);
    const r = await Promise.allSettled([
      api.getProcurementDashboard(),
      api.getRequisitions(),
      api.getPurchaseOrders(),
      api.getGoodsReceipts(),
      api.getProcurementVendors(),
    ]);
    const val = (i: number, d: any) => (r[i].status === 'fulfilled' ? (r[i] as any).value ?? d : d);
    setDash(val(0, null));
    setReqs(val(1, []));
    setPos(val(2, []));
    setReceipts(val(3, []));
    setVendors(val(4, []));
    setLastSync(Date.now());
    setLoading(false);
  }

  async function approve(po: PurchaseOrderRow) {
    setBusy(po.id); setActionMsg(''); setMatch(null); setGuard(null);
    try {
      // The deterministic four-control chain (binding) and the Spend Guard
      // Agent's gated plain-English read (advisory) run together, so the
      // approval panel shows both the verdict and why it makes sense in one
      // pass - the Spend Guard Agent never decides, it explains.
      const [outcome, guardResult] = await Promise.all([
        api.approvePurchaseOrder(po.id),
        api.guardPurchaseOrder(po.id).catch(() => null),
      ]);
      setApproval({ po: po.po_number, outcome });
      if (guardResult) setGuard(guardResult);
      setActionMsg(outcome.approved
        ? `Purchase order ${po.po_number} approved. All four controls cleared.`
        : `Purchase order ${po.po_number} held. ${outcome.message || 'A control blocked the approval.'}`);
      await loadData();
    } catch (e: any) {
      setActionMsg(`Approval failed: ${e?.message || e}`);
    } finally { setBusy(null); }
  }

  async function checkMatch(po: PurchaseOrderRow) {
    setBusy(po.id); setActionMsg(''); setApproval(null); setGuard(null);
    try {
      const result = await api.getThreeWayMatch(po.id);
      setMatch({ po: po.po_number, result });
    } catch (e: any) {
      setActionMsg(`Three-way match failed: ${e?.message || e}`);
    } finally { setBusy(null); }
  }

  async function assessRequisition(r: RequisitionRow) {
    setBusy(r.id); setActionMsg('');
    try {
      const result = await api.assessRequisition(r.id);
      setAssess({ item: r.item, result });
    } catch (e: any) {
      setActionMsg(`Assessment failed: ${e?.message || e}`);
    } finally { setBusy(null); }
  }

  async function screenVendorByName(name: string) {
    const clean = name.trim();
    if (!clean) return;
    setBusy(`screen:${clean}`); setActionMsg('');
    try {
      const gate = await api.screenVendor(clean);
      setScreen({ vendor: clean, gate });
    } catch (e: any) {
      setActionMsg(`Vendor screen failed: ${e?.message || e}`);
    } finally { setBusy(null); }
  }

  async function screenVendor(v: VendorRow) {
    setBusy(v.vendor); setActionMsg('');
    try {
      const gate = await api.screenVendor(v.vendor);
      setScreen({ vendor: v.vendor, gate });
    } catch (e: any) {
      setActionMsg(`Vendor screen failed: ${e?.message || e}`);
    } finally { setBusy(null); }
  }

  const statusColor = (s: string) => {
    const n = (s || '').toUpperCase();
    if (['APPROVED', 'RECEIVED', 'SUCCESS'].includes(n)) return colors.success;
    if (['DRAFT', 'PENDING_APPROVAL', 'ORDERED'].includes(n)) return colors.warning;
    if (['CANCELLED'].includes(n)) return colors.error;
    return colors.inkSubtle;
  };
  const Badge = ({ status }: { status: string }) => (
    <span className="text-[11px] font-medium px-2 py-0.5 rounded-full uppercase tracking-wide"
      style={{ background: statusColor(status) + '18', color: statusColor(status) }}>
      {humanize(status) || 'N/A'}
    </span>
  );
  const EmptyState = ({ icon: Icon, title, sub }: { icon: React.ElementType; title: string; sub: string }) => (
    <div className="rounded-xl p-14 text-center" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      <Icon className="w-11 h-11 mx-auto mb-3" style={{ color: colors.inkTertiary }} />
      <p className="text-[14px] font-medium" style={{ color: colors.inkSubtle }}>{title}</p>
      <p className="text-[12px] mt-1" style={{ color: colors.inkTertiary }}>{sub}</p>
    </div>
  );

  const TABS: { key: Tab; label: string; icon: React.ElementType }[] = [
    { key: 'overview', label: 'Overview', icon: ShoppingCart },
    { key: 'requisitions', label: 'Requisitions', icon: ClipboardList },
    { key: 'purchase-orders', label: 'Purchase Orders', icon: FileCheck2 },
    { key: 'goods-receipts', label: 'Goods Receipts', icon: PackageCheck },
    { key: 'vendors', label: 'Vendors', icon: Building2 },
    { key: 'analytics', label: 'Analytics', icon: TrendingUp },
  ];
  const activeTab = TABS.find(t => t.key === tab)!;
  const moveTab = (e: React.KeyboardEvent, i: number) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const next = TABS[(i + (e.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length];
    setTab(next.key);
    document.getElementById(`prc-tab-${next.key}`)?.focus();
  };

  const pendingShare = dash && dash.purchase_orders_open > 0
    ? Math.round((dash.pending_approval / dash.purchase_orders_open) * 100) : null;

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className={`${PAGE_PAD} space-y-5`}>
        {/* Header */}
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <h1 className="text-[22px] font-bold tracking-tight flex items-center gap-2">
              <activeTab.icon className="w-6 h-6" style={{ color: ACCENT }} />
              {activeTab.label}
            </h1>
            <p className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>
              Procurement · every purchase order clears four source-to-pay controls before approval
            </p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <button onClick={() => setNewReqOpen(true)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-semibold text-white"
              style={{ background: ACCENT }}>
              <Plus className="w-3.5 h-3.5" /> New Requisition
            </button>
            <button onClick={() => setNewPoOpen(true)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-semibold"
              style={{ background: colors.surface1, border: `1px solid ${colors.hairline}`, color: colors.ink }}>
              <Plus className="w-3.5 h-3.5" /> New Purchase Order
            </button>
            <LiveBadge lastSync={lastSync} />
            <button onClick={loadData} aria-label="Refresh procurement data" className="p-2 rounded-lg transition-colors" style={{ color: colors.inkSubtle }}>
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        <NewRequisitionModal open={newReqOpen} onClose={() => setNewReqOpen(false)} colors={colors}
          onCreated={async (m) => { setActionMsg(m); await loadData(); }} />
        <NewPurchaseOrderModal open={newPoOpen} onClose={() => setNewPoOpen(false)} colors={colors}
          onCreated={async (m) => { setActionMsg(m); await loadData(); }} />

        {/* Tabs */}
        <div className="flex gap-1 p-1 rounded-xl overflow-x-auto" role="tablist" aria-label="Procurement sections" style={{ background: colors.surface1 }}>
          {TABS.map((t, i) => (
            <button key={t.key} id={`prc-tab-${t.key}`} role="tab" aria-selected={tab === t.key}
              tabIndex={tab === t.key ? 0 : -1} onClick={() => setTab(t.key)} onKeyDown={e => moveTab(e, i)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-medium transition-all whitespace-nowrap"
              style={{
                background: tab === t.key ? colors.canvas : 'transparent',
                color: tab === t.key ? ACCENT : colors.inkSubtle,
                boxShadow: tab === t.key ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
              }}>
              <t.icon className="w-3.5 h-3.5" />
              {t.label}
            </button>
          ))}
        </div>

        {/* Action feedback */}
        {actionMsg && (
          <div className="px-4 py-2.5 rounded-lg text-[12px] font-medium flex items-center gap-2"
            style={{ background: /failed|held/.test(actionMsg) ? colors.error + '15' : colors.success + '15',
                     color: /failed|held/.test(actionMsg) ? colors.error : colors.success }}>
            {/failed|held/.test(actionMsg) ? <XCircle className="w-4 h-4" /> : <CheckCircle2 className="w-4 h-4" />}
            {actionMsg}
            <button onClick={() => setActionMsg('')} className="ml-auto text-[11px] opacity-60 hover:opacity-100">dismiss</button>
          </div>
        )}

        {/* Governance panels (last action) */}
        {approval && (
          <div className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Gavel className="w-4 h-4" style={{ color: ACCENT }} />
                <span className="text-[12px] font-semibold">Four-control gate · PO {approval.po}</span>
              </div>
              <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full"
                style={{ background: (approval.outcome.approved ? colors.success : colors.error) + '18', color: approval.outcome.approved ? colors.success : colors.error }}>
                {approval.outcome.approved ? 'Approved' : 'Held (fail-closed)'}
              </span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
              {approval.outcome.gates.map((g, i) => <GateCell key={i} gate={g} colors={colors} />)}
            </div>
            {guard && (
              <div className="mt-3 pt-3 flex items-start gap-2" style={{ borderTop: `1px solid ${colors.hairline}` }}>
                <BrainCircuit className="w-4 h-4 mt-0.5 shrink-0" style={{ color: ACCENT }} />
                <div className="min-w-0">
                  <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: colors.inkSubtle }}>
                    Spend Guard Agent
                  </p>
                  <p className="text-[12px] mt-0.5 leading-relaxed" style={{ color: colors.ink }}>
                    {guard.rationale?.recommendation
                      || RUN_STATUS_COPY[guard.gated.status]
                      || 'The agent could not produce a rationale for this order.'}
                  </p>
                </div>
              </div>
            )}
          </div>
        )}
        {match && (
          <div className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
            <div className="flex items-center gap-2 mb-2">
              <GitCompareArrows className="w-4 h-4" style={{ color: ACCENT }} />
              <span className="text-[12px] font-semibold">Three-way match · PO {match.po}</span>
            </div>
            {match.result.invoice_count === 0 ? (
              <p className="text-[12px]" style={{ color: colors.inkSubtle }}>No invoices are linked to this purchase order yet, so there is nothing to reconcile. The match re-runs automatically at settlement.</p>
            ) : (
              <div className="space-y-2">
                {match.result.matches.map((m, i) => {
                  const good = m.status === 'MATCHED';
                  const c = good ? colors.success : m.status === 'EXCEPTION' ? colors.error : colors.warning;
                  return (
                    <div key={i} className="rounded-lg p-2.5" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                      <div className="flex items-center gap-2">
                        <span className="text-[12px] font-mono font-medium">{m.invoice_number}</span>
                        <span className="text-[11px] font-semibold px-1.5 py-0.5 rounded-full" style={{ background: c + '18', color: c }}>{MATCH_COPY[m.status] || humanize(m.status)}</span>
                      </div>
                      {m.reasons.length > 0 && (
                        <ul className="mt-1.5 space-y-0.5">
                          {m.reasons.map((r, j) => <li key={j} className="text-[11px]" style={{ color: colors.inkSubtle }}>· {r}</li>)}
                        </ul>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
        {screen && (
          <div className="rounded-xl p-4 flex items-start gap-2"
            style={{ background: (screen.gate.blocking ? colors.error : colors.success) + '10', border: `1px solid ${(screen.gate.blocking ? colors.error : colors.success)}33` }}>
            {screen.gate.blocking ? <XCircle className="w-4 h-4 mt-0.5 shrink-0" style={{ color: colors.error }} /> : <ShieldCheck className="w-4 h-4 mt-0.5 shrink-0" style={{ color: colors.success }} />}
            <div>
              <p className="text-[12px] font-semibold" style={{ color: screen.gate.blocking ? colors.error : colors.success }}>
                Sanctions screen · {screen.vendor}
              </p>
              <p className="text-[11px] mt-0.5" style={{ color: colors.inkSubtle }}>
                {screen.gate.reasons.length ? screen.gate.reasons.join(' ') : GATE_COPY.OFAC_SANCTIONS.ok}
              </p>
            </div>
          </div>
        )}
        {assess && (
          <div className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
            <div className="flex items-center gap-2 mb-2">
              <Sparkles className="w-4 h-4" style={{ color: ACCENT }} />
              <span className="text-[12px] font-semibold">Sourcing Agent · {assess.item}</span>
            </div>
            {assess.result.assessment ? (
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                <AssessCell label="Policy fit" ok={assess.result.assessment.compliant} colors={colors} />
                <AssessCell label="Price reasonable" ok={assess.result.assessment.price_reasonable} colors={colors} />
                <AssessCell label="Recommend raising a PO" ok={assess.result.assessment.recommend_po} colors={colors} />
                {(assess.result.assessment.flags || []).length > 0 && (
                  <div className="sm:col-span-3 rounded-lg p-2.5" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                    <ul className="space-y-0.5">
                      {assess.result.assessment.flags!.map((f, j) => <li key={j} className="text-[11px]" style={{ color: colors.inkSubtle }}>· {f}</li>)}
                    </ul>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-[12px]" style={{ color: colors.inkSubtle }}>
                {assess.result.reason || RUN_STATUS_COPY[assess.result.status] || 'The agent has not reached a clean recommendation yet.'}
              </p>
            )}
          </div>
        )}

        {/* Search (non-overview, non-analytics) */}
        {tab !== 'overview' && tab !== 'analytics' && (
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: colors.inkSubtle }} />
            <input type="text" value={searchQ} onChange={e => setSearchQ(e.target.value)}
              placeholder={`Search ${activeTab.label.toLowerCase()}...`}
              className="w-full pl-9 pr-4 py-2 rounded-lg border text-[12px] focus:outline-none focus:ring-1"
              style={{ background: colors.surface1, borderColor: colors.hairline, color: colors.ink }} />
          </div>
        )}

        {loading && !dash ? (
          <div className="flex items-center justify-center py-20"><Loader2 className="w-6 h-6 animate-spin" style={{ color: ACCENT }} /></div>
        ) : (
          <>
            {/* ═══ OVERVIEW ═══ */}
            {tab === 'overview' && (
              <div className="space-y-5">
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                  <div className="rounded-xl p-5 flex items-center gap-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                    {pendingShare != null
                      ? <Ring value={pendingShare} max={100} size={104} color={ACCENT} label="to approve" />
                      : <div className="w-[104px] h-[104px] rounded-full flex items-center justify-center text-center text-[11px] px-3 shrink-0" style={{ border: `2px dashed ${colors.hairline}`, color: colors.inkTertiary }}>No open orders</div>}
                    <div className="min-w-0">
                      <p className="text-[12px] font-semibold uppercase tracking-wide" style={{ color: colors.inkSubtle }}>Approval queue</p>
                      <p className="text-[13px] mt-1" style={{ color: colors.ink }}>
                        <CountUp value={dash?.pending_approval || 0} className="font-bold" /> of{' '}
                        <CountUp value={dash?.purchase_orders_open || 0} className="font-bold" /> open orders await a gated approval.
                      </p>
                      <p className="text-[12px] mt-1.5" style={{ color: colors.inkSubtle }}>
                        <CountUp value={dash?.open_requisitions || 0} className="font-semibold" /> requisitions are still upstream of a PO.
                      </p>
                    </div>
                  </div>
                  <div className="rounded-xl p-5 flex flex-col justify-center" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                    <p className="text-[12px] font-semibold uppercase tracking-wide" style={{ color: colors.inkSubtle }}>Committed spend</p>
                    <CountUp value={dash?.committed_spend || 0} prefix="$" className="text-[30px] font-bold tracking-tight tabular-nums mt-1" />
                    <p className="text-[12px] mt-1" style={{ color: colors.inkSubtle }}>on approved and ordered purchase orders</p>
                  </div>
                  <div className="rounded-xl p-5" style={{ background: ACCENT + '10', border: `1px solid ${ACCENT}33` }}>
                    <div className="flex items-center gap-2 mb-2">
                      <ShieldCheck className="w-4 h-4" style={{ color: ACCENT }} />
                      <p className="text-[12px] font-semibold" style={{ color: ACCENT }}>Source-to-pay controls</p>
                    </div>
                    <p className="text-[12.5px] leading-relaxed" style={{ color: colors.ink }}>
                      No purchase order is approved until spend authorization, segregation of duties, the three-way match and sanctions
                      screening all clear. A blocking control holds the order and writes the reason to the ledger.
                    </p>
                  </div>
                </div>

                <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
                  <StatCard label="Open Requisitions" value={dash?.open_requisitions || 0} icon={<ClipboardList className="w-4 h-4" />} accent="#3b82f6" />
                  <StatCard label="Open Purchase Orders" value={dash?.purchase_orders_open || 0} icon={<FileCheck2 className="w-4 h-4" />} accent={ACCENT} />
                  <StatCard label="Awaiting Approval" value={dash?.pending_approval || 0} icon={<Gavel className="w-4 h-4" />} accent="#f59e0b" />
                  <StatCard label="Goods Receipts" value={dash?.goods_receipts || 0} icon={<PackageCheck className="w-4 h-4" />} accent={colors.success} />
                  <StatCard label="Committed Spend" value={dash?.committed_spend || 0} format="currency" icon={<ShoppingCart className="w-4 h-4" />} accent="#ec4899" />
                </div>
              </div>
            )}

            {/* ═══ REQUISITIONS ═══ */}
            {tab === 'requisitions' && (() => {
              const rows = reqs.filter(r => !searchQ || r.item.toLowerCase().includes(searchQ.toLowerCase())
                || (r.requested_by || '').toLowerCase().includes(searchQ.toLowerCase()));
              return rows.length === 0
                ? <EmptyState icon={ClipboardList} title="No requisitions" sub="Internal purchase requests appear here." />
                : (
                  <TableCard minWidth={940}>
                    <table className="w-full text-[12px]">
                      <thead>
                        <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          {['Item', 'Qty', 'Unit price', 'Estimated cost', 'Status', 'Requested by', 'Department', 'Actions'].map(h => (
                            <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map(r => (
                          <tr key={r.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                            <td className="px-4 py-3 font-medium">{r.item}</td>
                            <td className="px-4 py-3 font-mono">{r.quantity}</td>
                            <td className="px-4 py-3 font-mono">{formatCurrency(r.unit_price)}</td>
                            <td className="px-4 py-3 font-mono font-semibold">{formatCurrency(r.estimated_cost)}</td>
                            <td className="px-4 py-3"><Badge status={r.status} /></td>
                            <td className="px-4 py-3">{r.requested_by || <span style={{ color: colors.inkTertiary }}>-</span>}</td>
                            <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{r.department || '-'}</td>
                            <td className="px-4 py-3">
                              <button onClick={() => assessRequisition(r)} disabled={busy === r.id}
                                className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold transition-colors whitespace-nowrap"
                                style={{ background: ACCENT + '18', color: ACCENT }}>
                                {busy === r.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
                                Assess
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </TableCard>
                );
            })()}

            {/* ═══ PURCHASE ORDERS ═══ */}
            {tab === 'purchase-orders' && (() => {
              const rows = pos.filter(p => !searchQ || p.po_number.toLowerCase().includes(searchQ.toLowerCase())
                || p.vendor.toLowerCase().includes(searchQ.toLowerCase()));
              return rows.length === 0
                ? <EmptyState icon={FileCheck2} title="No purchase orders" sub="Issued purchase orders appear here." />
                : (
                  <TableCard minWidth={820}>
                    <table className="w-full text-[12px]">
                      <thead>
                        <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          {['PO number', 'Vendor', 'Total', 'Status', 'Controls'].map(h => (
                            <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map(p => {
                          const pending = ['DRAFT', 'PENDING_APPROVAL'].includes(p.status);
                          return (
                            <tr key={p.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                              <td className="px-4 py-3 font-medium font-mono">{p.po_number}</td>
                              <td className="px-4 py-3">{p.vendor}</td>
                              <td className="px-4 py-3 font-mono font-semibold">{formatCurrency(p.total)}</td>
                              <td className="px-4 py-3"><Badge status={p.status} /></td>
                              <td className="px-4 py-3">
                                <div className="flex items-center gap-1.5">
                                  {pending && (
                                    <button onClick={() => approve(p)} disabled={busy === p.id}
                                      className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold transition-colors"
                                      style={{ background: ACCENT + '18', color: ACCENT }}>
                                      {busy === p.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Gavel className="w-3 h-3" />}
                                      Approve
                                    </button>
                                  )}
                                  <button onClick={() => checkMatch(p)} disabled={busy === p.id}
                                    className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold transition-colors"
                                    style={{ background: colors.canvas, border: `1px solid ${colors.hairline}`, color: colors.inkSubtle }}>
                                    <GitCompareArrows className="w-3 h-3" /> 3-way match
                                  </button>
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </TableCard>
                );
            })()}

            {/* ═══ GOODS RECEIPTS ═══ */}
            {tab === 'goods-receipts' && (() => {
              const poNumber = (id: string) => pos.find(p => p.id === id)?.po_number || id.slice(0, 8);
              const rows = receipts.filter(r => !searchQ || r.receiver.toLowerCase().includes(searchQ.toLowerCase())
                || poNumber(r.purchase_order_id).toLowerCase().includes(searchQ.toLowerCase()));
              return rows.length === 0
                ? <EmptyState icon={PackageCheck} title="No goods receipts" sub="Delivery confirmations appear here." />
                : (
                  <TableCard minWidth={700}>
                    <table className="w-full text-[12px]">
                      <thead>
                        <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          {['Purchase order', 'Receiver', 'Received qty', 'Condition', 'Status'].map(h => (
                            <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map(r => (
                          <tr key={r.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                            <td className="px-4 py-3 font-medium font-mono">{poNumber(r.purchase_order_id)}</td>
                            <td className="px-4 py-3">{r.receiver}</td>
                            <td className="px-4 py-3 font-mono">{r.received_quantity}</td>
                            <td className="px-4 py-3">
                              {r.is_damaged
                                ? <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full" style={{ background: colors.error + '18', color: colors.error }}>Damaged</span>
                                : <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full" style={{ background: colors.success + '18', color: colors.success }}>Good</span>}
                            </td>
                            <td className="px-4 py-3"><Badge status={r.status} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </TableCard>
                );
            })()}

            {/* ═══ VENDORS ═══ */}
            {tab === 'vendors' && (() => {
              const rows = vendors.filter(v => !searchQ || v.vendor.toLowerCase().includes(searchQ.toLowerCase()));
              const riskColor = (v: VendorRow) => {
                const days = v.renewal_date ? Math.round((new Date(v.renewal_date).getTime() - Date.now()) / 86400000) : null;
                const poor = v.performance_score != null && v.performance_score < 70;
                if (poor || (days != null && days <= 30)) return colors.error;
                if ((v.performance_score != null && v.performance_score < 85) || (days != null && days <= 90)) return colors.warning;
                return colors.success;
              };
              return (
                <div className="space-y-4">
                  <div className="rounded-xl p-4 flex items-center gap-2 flex-wrap" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                    <ShieldCheck className="w-4 h-4 shrink-0" style={{ color: ACCENT }} />
                    <span className="text-[12px] font-semibold shrink-0">Screen any vendor name</span>
                    <input type="text" value={screenInput} onChange={e => setScreenInput(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter') screenVendorByName(screenInput); }}
                      placeholder="e.g. a vendor not yet under contract"
                      className="flex-1 min-w-[180px] px-3 py-1.5 rounded-lg border text-[12px] focus:outline-none focus:ring-1"
                      style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }} />
                    <button onClick={() => screenVendorByName(screenInput)} disabled={!screenInput.trim() || busy === `screen:${screenInput.trim()}`}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-md text-[11px] font-semibold transition-colors disabled:opacity-50"
                      style={{ background: ACCENT, color: '#fff' }}>
                      {busy === `screen:${screenInput.trim()}` ? <Loader2 className="w-3 h-3 animate-spin" /> : <ShieldCheck className="w-3 h-3" />}
                      Screen (OFAC)
                    </button>
                  </div>

                  {rows.length === 0
                    ? <EmptyState icon={Building2} title="No vendors" sub="Vendors under contract appear here." />
                    : (
                    <TableCard minWidth={980}>
                      <table className="w-full text-[12px]">
                        <thead>
                          <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                            {['Vendor', 'Service', 'Contract value', 'Renewal', 'Performance', 'Purchase orders', 'Committed spend', 'Sanctions screen'].map(h => (
                              <th key={h} className="text-left px-4 py-3 font-semibold whitespace-nowrap" style={{ color: colors.inkSubtle }}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {rows.map(v => (
                            <tr key={v.vendor} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                              <td className="px-4 py-3 font-medium">
                                <span className="inline-block w-1.5 h-1.5 rounded-full mr-1.5 align-middle" style={{ background: riskColor(v) }} />
                                {v.vendor}
                              </td>
                              <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{v.service_provided || '-'}</td>
                              <td className="px-4 py-3 font-mono">{formatCurrency(v.contract_value)}</td>
                              <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{v.renewal_date ? formatDate(v.renewal_date) : '-'}</td>
                              <td className="px-4 py-3">
                                {v.performance_score != null
                                  ? <span className="font-mono">{v.performance_score.toFixed(0)}<span style={{ color: colors.inkTertiary }}>/100</span></span>
                                  : <span style={{ color: colors.inkTertiary }}>No sheet yet</span>}
                              </td>
                              <td className="px-4 py-3 font-mono">{v.po_count}</td>
                              <td className="px-4 py-3 font-mono font-semibold">{formatCurrency(v.committed_spend)}</td>
                              <td className="px-4 py-3">
                                <button onClick={() => screenVendor(v)} disabled={busy === v.vendor}
                                  className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold transition-colors whitespace-nowrap"
                                  style={{ background: ACCENT + '18', color: ACCENT }}>
                                  {busy === v.vendor ? <Loader2 className="w-3 h-3 animate-spin" /> : <ShieldCheck className="w-3 h-3" />}
                                  Screen (OFAC)
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </TableCard>
                  )}
                </div>
              );
            })()}

            {/* ═══ ANALYTICS ═══ */}
            {tab === 'analytics' && <DomainAnalytics domain="procurement" />}
          </>
        )}
      </div>
    </div>
  );
};

/** One control outcome, rendered in plain English. */
function GateCell({ gate, colors }: { gate: ProcurementGate; colors: Record<string, string> }) {
  const copy = GATE_COPY[gate.code] || { title: humanize(gate.code), ok: 'Cleared.' };
  const c = gate.status === 'PASS' ? colors.success
    : gate.status === 'BLOCK' ? colors.error
      : gate.status === 'ADVISORY' ? colors.warning : colors.inkSubtle;
  const Icon = gate.status === 'PASS' ? CheckCircle2
    : gate.status === 'BLOCK' ? XCircle
      : gate.status === 'ADVISORY' ? AlertTriangle : MinusCircle;
  return (
    <div className="rounded-lg p-2.5" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
      <div className="flex items-center gap-1.5">
        <Icon className="w-3.5 h-3.5" style={{ color: c }} />
        <span className="text-[11.5px] font-semibold" style={{ color: colors.ink }}>{copy.title}</span>
        <span className="ml-auto text-[10px] font-semibold uppercase tracking-wide" style={{ color: c }}>{STATUS_COPY[gate.status] || humanize(gate.status)}</span>
      </div>
      <p className="text-[11px] mt-1 leading-snug" style={{ color: colors.inkSubtle }}>
        {gate.reasons.length ? gate.reasons.join(' ') : copy.ok}
      </p>
    </div>
  );
}

/** One Sourcing Agent verdict field (Yes / No / Unknown), rendered in plain English. */
function AssessCell({ label, ok, colors }: { label: string; ok?: boolean; colors: Record<string, string> }) {
  const c = ok === true ? colors.success : ok === false ? colors.error : colors.inkSubtle;
  const Icon = ok === true ? CheckCircle2 : ok === false ? XCircle : MinusCircle;
  return (
    <div className="rounded-lg p-2.5 flex items-center gap-1.5" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
      <Icon className="w-3.5 h-3.5 shrink-0" style={{ color: c }} />
      <span className="text-[11.5px] font-medium" style={{ color: colors.ink }}>{label}</span>
      <span className="ml-auto text-[10px] font-semibold uppercase tracking-wide" style={{ color: c }}>
        {ok === true ? 'Yes' : ok === false ? 'No' : 'Unknown'}
      </span>
    </div>
  );
}

interface CreatePanelProps {
  open: boolean;
  onClose: () => void;
  onCreated: (msg: string) => void;
  colors: Record<string, string>;
}

/** Small, focus-trapped create dialog. Mirrors components/CreateEntityModal's
 * shell, but posts through the department-specific procurementApi wrapper
 * (api.createRequisition) rather than the generic domain-entity endpoint. */
function NewRequisitionModal({ open, onClose, onCreated, colors }: CreatePanelProps) {
  const [item, setItem] = useState('');
  const [qty, setQty] = useState('1');
  const [price, setPrice] = useState('0');
  const [department, setDepartment] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const titleId = useId();
  const trapRef = useFocusTrap<HTMLDivElement>(open, onClose);

  if (!open) return null;

  const submit = async () => {
    if (!item.trim()) {
      setError('Item description is required');
      announce('Item description is required', 'assertive');
      return;
    }
    setBusy(true); setError('');
    try {
      await api.createRequisition({
        item_description: item.trim(),
        quantity: Math.max(1, Number(qty) || 1),
        unit_price: Math.max(0, Number(price) || 0),
        department: department.trim() || undefined,
      });
      const done = `Requisition "${item.trim()}" created.`;
      announce(done);
      setItem(''); setQty('1'); setPrice('0'); setDepartment('');
      onCreated(done);
      onClose();
    } catch (e: any) {
      const msg = e?.message || 'Create failed';
      setError(msg);
      announce(msg, 'assertive');
    } finally {
      setBusy(false);
    }
  };

  const inputStyle = { background: colors.canvas, border: `1px solid ${colors.hairline}`, color: colors.ink } as React.CSSProperties;
  const labelCls = 'text-[11px] font-semibold block mb-1';
  const fieldCls = 'w-full px-3 py-2 rounded-lg text-[12px] focus:outline-none';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(0,0,0,0.55)' }} onClick={onClose}>
      <div ref={trapRef} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
        className="w-full max-w-md rounded-2xl p-5 space-y-4 max-h-[85vh] overflow-y-auto"
        style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}
        onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h2 id={titleId} className="text-[15px] font-bold" style={{ color: colors.ink }}>New Requisition</h2>
          <button onClick={onClose} aria-label="Close dialog" className="p-1 rounded" style={{ color: colors.inkSubtle }}>
            <X className="w-4 h-4" />
          </button>
        </div>

        <div>
          <label className={labelCls} style={{ color: colors.inkSubtle }}>Item description <span style={{ color: '#ef4444' }}>*</span></label>
          <input type="text" value={item} onChange={e => setItem(e.target.value)} placeholder="e.g. 10x standing desks"
            className={fieldCls} style={inputStyle} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls} style={{ color: colors.inkSubtle }}>Quantity</label>
            <input type="number" min={1} value={qty} onChange={e => setQty(e.target.value)} className={fieldCls} style={inputStyle} />
          </div>
          <div>
            <label className={labelCls} style={{ color: colors.inkSubtle }}>Unit price ($)</label>
            <input type="number" min={0} step="0.01" value={price} onChange={e => setPrice(e.target.value)} className={fieldCls} style={inputStyle} />
          </div>
        </div>
        <div>
          <label className={labelCls} style={{ color: colors.inkSubtle }}>Department</label>
          <input type="text" value={department} onChange={e => setDepartment(e.target.value)} placeholder="Optional"
            className={fieldCls} style={inputStyle} />
        </div>

        {error && <p role="alert" className="text-[11px] font-medium" style={{ color: '#ef4444' }}>{error}</p>}

        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className="px-3 py-2 rounded-lg text-[12px] font-semibold" style={{ background: 'transparent', color: colors.inkSubtle }}>Cancel</button>
          <button onClick={submit} disabled={busy}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-[12px] font-semibold disabled:opacity-50 text-white"
            style={{ background: ACCENT }}>
            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
            Create
          </button>
        </div>
      </div>
    </div>
  );
}

/** Same shell as NewRequisitionModal; posts a vendor plus one optional line
 * item through api.createPurchaseOrder. */
function NewPurchaseOrderModal({ open, onClose, onCreated, colors }: CreatePanelProps) {
  const [vendor, setVendor] = useState('');
  const [poNumber, setPoNumber] = useState('');
  const [desc, setDesc] = useState('');
  const [qty, setQty] = useState('1');
  const [price, setPrice] = useState('0');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const titleId = useId();
  const trapRef = useFocusTrap<HTMLDivElement>(open, onClose);

  if (!open) return null;

  const submit = async () => {
    if (!vendor.trim()) {
      setError('Vendor name is required');
      announce('Vendor name is required', 'assertive');
      return;
    }
    setBusy(true); setError('');
    try {
      const lines = desc.trim()
        ? [{ description: desc.trim(), quantity: Math.max(1, Number(qty) || 1), unit_price: Math.max(0, Number(price) || 0) }]
        : [];
      const created = await api.createPurchaseOrder({
        vendor_name: vendor.trim(),
        po_number: poNumber.trim() || undefined,
        lines,
      });
      const done = `Purchase order ${created.po_number} created for ${vendor.trim()}.`;
      announce(done);
      setVendor(''); setPoNumber(''); setDesc(''); setQty('1'); setPrice('0');
      onCreated(done);
      onClose();
    } catch (e: any) {
      const msg = e?.message || 'Create failed';
      setError(msg);
      announce(msg, 'assertive');
    } finally {
      setBusy(false);
    }
  };

  const inputStyle = { background: colors.canvas, border: `1px solid ${colors.hairline}`, color: colors.ink } as React.CSSProperties;
  const labelCls = 'text-[11px] font-semibold block mb-1';
  const fieldCls = 'w-full px-3 py-2 rounded-lg text-[12px] focus:outline-none';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(0,0,0,0.55)' }} onClick={onClose}>
      <div ref={trapRef} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
        className="w-full max-w-md rounded-2xl p-5 space-y-4 max-h-[85vh] overflow-y-auto"
        style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}
        onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h2 id={titleId} className="text-[15px] font-bold" style={{ color: colors.ink }}>New Purchase Order</h2>
          <button onClick={onClose} aria-label="Close dialog" className="p-1 rounded" style={{ color: colors.inkSubtle }}>
            <X className="w-4 h-4" />
          </button>
        </div>

        <div>
          <label className={labelCls} style={{ color: colors.inkSubtle }}>Vendor <span style={{ color: '#ef4444' }}>*</span></label>
          <input type="text" value={vendor} onChange={e => setVendor(e.target.value)} placeholder="e.g. Meridian Office Supply Co"
            className={fieldCls} style={inputStyle} />
        </div>
        <div>
          <label className={labelCls} style={{ color: colors.inkSubtle }}>PO number</label>
          <input type="text" value={poNumber} onChange={e => setPoNumber(e.target.value)} placeholder="Auto-generated if left blank"
            className={fieldCls} style={inputStyle} />
        </div>
        <div>
          <label className={labelCls} style={{ color: colors.inkSubtle }}>Line item description</label>
          <input type="text" value={desc} onChange={e => setDesc(e.target.value)} placeholder="Optional - e.g. 10x laptop stands"
            className={fieldCls} style={inputStyle} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls} style={{ color: colors.inkSubtle }}>Quantity</label>
            <input type="number" min={1} value={qty} onChange={e => setQty(e.target.value)} className={fieldCls} style={inputStyle} />
          </div>
          <div>
            <label className={labelCls} style={{ color: colors.inkSubtle }}>Unit price ($)</label>
            <input type="number" min={0} step="0.01" value={price} onChange={e => setPrice(e.target.value)} className={fieldCls} style={inputStyle} />
          </div>
        </div>

        {error && <p role="alert" className="text-[11px] font-medium" style={{ color: '#ef4444' }}>{error}</p>}

        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className="px-3 py-2 rounded-lg text-[12px] font-semibold" style={{ background: 'transparent', color: colors.inkSubtle }}>Cancel</button>
          <button onClick={submit} disabled={busy}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-[12px] font-semibold disabled:opacity-50"
            style={{ background: colors.canvas, border: `1px solid ${colors.hairline}`, color: colors.ink }}>
            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
            Create
          </button>
        </div>
      </div>
    </div>
  );
}

export default ProcurementView;
