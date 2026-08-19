/**
 * Department-scoped RBAC helpers.
 *
 * A user may carry a `department` scope (set by an admin, delivered in the
 * login JWT). Scoped users only see their own department's operational
 * surfaces; org-wide users (department = null) see everything. Cross-domain
 * aggregates (Dashboard, Org Pulse, Analytics, Reality Experience, My Work)
 * are NEVER hidden: correlating signal across departments is the product's IP.
 * Mirrors backend app/core/tenant.py require_department.
 */

export const DEPARTMENTS = [
  'hr', 'finance', 'legal', 'sales', 'support', 'operations', 'engineering',
  // Regulated verticals — each mounts a first-class backend surface gated by
  // require_department(<slug>) in app/main.py.
  'healthcare', 'lending', 'procurement',
] as const;

export type DepartmentSlug = typeof DEPARTMENTS[number];

export const DEPARTMENT_LABELS: Record<DepartmentSlug, string> = {
  hr: 'Human Resources',
  finance: 'Finance',
  legal: 'Legal & Compliance',
  sales: 'Sales & CRM',
  support: 'Customer Support',
  operations: 'Operations',
  engineering: 'Engineering & IT Ops',
  healthcare: 'Healthcare',
  lending: 'Lending & Credit',
  procurement: 'Procurement',
};

/**
 * THE department accent palette. Single source of truth: the sidebar context
 * indicator (App.tsx), the icon tiles (DomainIcon), the department dashboards
 * and the vertical views all read these values. Do not re-declare a hex for a
 * department anywhere else - four hand-synced copies had already drifted
 * (finance/support swapped, operations and engineering each a third colour).
 */
export const DEPARTMENT_COLORS: Record<DepartmentSlug, string> = {
  hr: '#22c55e',
  finance: '#ec4899',
  legal: '#6366f1',
  sales: '#f59e0b',
  support: '#3b82f6',
  operations: '#ef4444',
  // cyan, not legal's indigo: the Neural Map colours nodes by department and
  // two departments sharing a hue makes the graph unreadable.
  engineering: '#06b6d4',
  healthcare: '#14b8a6',
  lending: '#d97706',
  procurement: '#8b5cf6',
};

/**
 * Can a user with `userDepartment` scope see the surface belonging to
 * department `slug`?
 * - Org-wide users (null/undefined scope) see every department.
 * - A missing/unknown slug means the surface is not department-specific.
 * - Otherwise only the user's own department is visible.
 */
export function canSeeDepartment(
  userDepartment: string | null | undefined,
  slug: string | null | undefined,
): boolean {
  if (!userDepartment) return true;
  if (!slug) return true;
  return userDepartment === slug;
}
