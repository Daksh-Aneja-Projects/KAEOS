import { request } from '../http';

/* ─── Response shapes (bound to app/procurement/api/v1/router.py) ─── */

export interface ProcurementDashboard {
  open_requisitions: number;
  purchase_orders_open: number;
  pending_approval: number;
  goods_receipts: number;
  committed_spend: number;
}

export interface RequisitionRow {
  id: string;
  item: string;
  quantity: number;
  unit_price: number;
  estimated_cost: number;
  status: string;               // DRAFT | PENDING_APPROVAL | APPROVED | ORDERED | RECEIVED | CANCELLED
  requested_by: string | null;
  department: string | null;
}

export interface PurchaseOrderRow {
  id: string;
  po_number: string;
  vendor: string;
  vendor_id: string | null;
  total: number;
  status: string;
}

export interface GoodsReceiptRow {
  id: string;
  purchase_order_id: string;
  receiver: string;
  received_quantity: number;
  is_damaged: boolean;
  status: string;
}

export interface VendorRow {
  vendor: string;
  vendor_id: string | null;
  service_provided: string | null;
  contract_value: number;
  renewal_date: string | null;      // ISO date, or null if not on file
  performance_score: number | null; // 0-100, null if no performance sheet yet (honesty contract)
  po_count: number;
  committed_spend: number;
}

/**
 * Result of routing a requisition or PO through the gated 7-gate pipeline
 * (compliance -> fairness -> confidence/HITL -> debate -> execute -> audit).
 * ``status`` mirrors app.agents.runtime.AgentExecutor.execute_skill: one of
 * SUCCESS_CLEAN | PENDING_HITL | BLOCKED_COMPLIANCE | BLOCKED_FAIRNESS |
 * BLOCKED_DEBATE | ESCALATED_DEBATE | HUMAN_OVERRIDDEN | FAILED_ACTUATION |
 * FAILED_AUDIT. The frontend translates it to plain English - never render it
 * raw.
 */
export interface GatedRunResult {
  status: string;
  execution_id?: string;
  reason?: string;
}

/** Sourcing Agent's parsed verdict on a requisition (present when status is SUCCESS_CLEAN). */
export interface SourcingAssessment extends GatedRunResult {
  assessment?: {
    compliant?: boolean;
    price_reasonable?: boolean;
    recommend_po?: boolean;
    flags?: string[];
  };
}

/** Spend Guard Agent's advisory read on a PO: the same four gates the approval
 * endpoint enforces, plus a gated plain-English recommendation. Read-only -
 * it never approves or blocks the PO itself. */
export interface SpendGuardResult {
  po_id: string;
  gates: ProcurementGate[];
  blocking_controls: string[];
  safe_to_approve: boolean;
  gated: GatedRunResult;
  rationale?: {
    safe_to_approve?: boolean;
    blocking_controls?: string[];
    recommendation?: string;
  };
}

/** One source-to-pay control outcome (spend-auth, SoD, three-way match, OFAC). */
export interface ProcurementGate {
  code: string;                 // SPEND_AUTHORIZATION | SEGREGATION_OF_DUTIES | THREE_WAY_MATCH | OFAC_SANCTIONS | PO_STATE
  status: string;               // PASS | BLOCK | ADVISORY | NOT_APPLICABLE
  blocking: boolean;
  reasons: string[];            // plain-English findings
}

/** Normalized result of an approval attempt — approved or fail-closed, both carry gates. */
export interface ApprovalOutcome {
  approved: boolean;
  po_id?: string;
  po_number?: string;
  status?: string;
  gates: ProcurementGate[];
  message?: string;
}

export interface ThreeWayMatch {
  po_id: string;
  invoice_count: number;
  matches: {
    invoice_id: string;
    invoice_number: string;
    status: string;             // MATCHED | EXCEPTION | PENDING_RECEIPT | NO_PO
    po_matched: boolean;
    receipt_matched: boolean;
    reasons: string[];
  }[];
}

const q = (status?: string) => (status ? `?status=${encodeURIComponent(status)}` : '');

export const procurementApi = {
  getProcurementDashboard: () => request<ProcurementDashboard>('/procurement/dashboard'),

  getRequisitions: (status?: string) =>
    request<RequisitionRow[]>(`/procurement/requisitions${q(status)}`),
  createRequisition: (body: Record<string, any>) =>
    request<any>('/procurement/requisitions', { method: 'POST', body: JSON.stringify(body) }),

  getPurchaseOrders: (status?: string) =>
    request<PurchaseOrderRow[]>(`/procurement/purchase-orders${q(status)}`),
  createPurchaseOrder: (body: Record<string, any>) =>
    request<any>('/procurement/purchase-orders', { method: 'POST', body: JSON.stringify(body) }),

  /**
   * Approve a PO through the four-control gate chain. Returns a normalized
   * outcome for BOTH a clean approval and a fail-closed block, so the caller can
   * render the same four-gate story either way. A block arrives as a 409 whose
   * detail the shared request() serializes to a JSON string; recover it here.
   * ponytail: parse-recovers the transport's stringified detail — drop if
   * request() ever surfaces structured errors.
   */
  approvePurchaseOrder: async (
    poId: string,
    body?: { approver_limit?: number; sanctions_list?: any[]; requester?: string; receiver?: string },
  ): Promise<ApprovalOutcome> => {
    try {
      const r = await request<{ po_id: string; po_number: string; status: string; gates: ProcurementGate[] }>(
        `/procurement/purchase-orders/${poId}/approve`, { method: 'POST', body: JSON.stringify(body || {}) });
      return { approved: true, ...r };
    } catch (e: any) {
      try {
        const parsed = JSON.parse(e?.message ?? '');
        if (parsed && Array.isArray(parsed.gates)) {
          return { approved: false, message: parsed.message, gates: parsed.gates };
        }
      } catch { /* not a gate-block payload */ }
      throw e; // a genuine error (404 / 500 / network) — let the view surface it
    }
  },

  getGoodsReceipts: (poId?: string) =>
    request<GoodsReceiptRow[]>(`/procurement/goods-receipts${poId ? `?po_id=${encodeURIComponent(poId)}` : ''}`),
  createGoodsReceipt: (body: Record<string, any>) =>
    request<any>('/procurement/goods-receipts', { method: 'POST', body: JSON.stringify(body) }),

  getThreeWayMatch: (poId: string) => request<ThreeWayMatch>(`/procurement/three-way-match/${poId}`),

  getProcurementVendors: () => request<VendorRow[]>('/procurement/vendors'),
  screenVendor: (vendorName: string, sanctionsList?: any[]) =>
    request<ProcurementGate>('/procurement/vendors/screen', {
      method: 'POST', body: JSON.stringify({ vendor_name: vendorName, sanctions_list: sanctionsList ?? null }),
    }),

  /** Sourcing Agent: gated policy-fit + price-reasonableness read on a
   * requisition, before a PO is raised. Advisory - writes nothing. */
  assessRequisition: (requestId: string) =>
    request<SourcingAssessment>(`/procurement/requisitions/${requestId}/assess`, { method: 'POST' }),

  /** Spend Guard Agent: the same four control gates the approval endpoint
   * enforces, plus a gated plain-English recommendation for the approver.
   * Read-only - meant to run alongside (not instead of) approvePurchaseOrder. */
  guardPurchaseOrder: (
    poId: string,
    body?: { approver_limit?: number; sanctions_list?: any[] },
  ) => request<SpendGuardResult>(`/procurement/purchase-orders/${poId}/guard`, {
    method: 'POST', body: JSON.stringify(body || {}),
  }),
};
