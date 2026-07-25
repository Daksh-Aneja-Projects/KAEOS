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
};

// Matches the accent colors used for the department context indicator in App.tsx.
export const DEPARTMENT_COLORS: Record<DepartmentSlug, string> = {
  hr: '#22c55e',
  finance: '#ec4899',
  legal: '#6366f1',
  sales: '#f59e0b',
  support: '#3b82f6',
  operations: '#ef4444',
  engineering: '#6366f1',
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
