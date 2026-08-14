import { request } from '../http';

/**
 * Super-admin OPERATOR CONSOLE — cross-tenant fleet reads.
 *
 * Every /ops route is gated by the platform ADMIN_SECRET (X-Admin-Secret
 * header), NOT the tenant JWT: a customer's token proves who they are, never
 * that they may act platform-wide (see backend app/core/admin.py). The secret
 * is supplied per call and lives only in the operator's session memory; it is
 * never persisted to disk here and never logged. `request()` already threads a
 * `headers` option through to fetch, so no transport change is needed.
 *
 * A wrong secret returns 403 (not 401), so it never trips http's session-expiry
 * reload — the console shows a clean inline error and fails closed instead.
 */

const secret = (s: string) => ({ headers: { 'X-Admin-Secret': s } });

export interface OpsOverview {
  tenant_count: number;
  active_tenants: number;
  total_executions: number;
  /** null (not 0) when no executions in the window — honesty contract. */
  blended_safe_autonomy_rate: number | null;
  plan_distribution: Record<string, number>;
  note: string | null;
}

export interface OpsTenant {
  id: string;
  name: string;
  plan: string;
  is_active: boolean;
  created_at: string | null;
  agent_count: number;
  execution_count: number;
}

export interface OpsTenantsResponse {
  count: number;
  tenants: OpsTenant[];
}

export interface OpsTenantDetail {
  id: string;
  name: string;
  plan: string;
  is_active: boolean;
  created_at: string | null;
  entitlements: string[];
  usage: Record<string, any>;
  health: {
    agent_count: number;
    execution_count: number;
    safe_autonomy_rate: number | null;
  };
}

export const opsApi = {
  opsOverview: (adminSecret: string) =>
    request<OpsOverview>('/ops/overview', secret(adminSecret)),
  opsTenants: (adminSecret: string) =>
    request<OpsTenantsResponse>('/ops/tenants', secret(adminSecret)),
  opsTenantDetail: (tenantId: string, adminSecret: string) =>
    request<OpsTenantDetail>(`/ops/tenants/${encodeURIComponent(tenantId)}`, secret(adminSecret)),
};
