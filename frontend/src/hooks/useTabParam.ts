import { useState } from 'react';

/**
 * Tab state seeded from the route-supplied `defaultTab` prop, validated against
 * the view's own tab list so an unrecognised value falls back instead of
 * rendering an empty panel.
 *
 * Ten department views hand-rolled the same validate-or-fall-back check, and it
 * had already drifted: WorkforceView still carries a dead legacy-alias branch,
 * and SupportView's tab bar had lost its roving tabIndex (restored since; it
 * now matches its siblings). This is deliberately a thin
 * wrapper over `useState` - the views keep owning their tab state and call
 * `setTab` directly, so nothing else about them has to change.
 *
 * Note the name is historical: `requested` arrives as a prop from a static
 * route in App.tsx, not from a URL query string. No department view reads
 * `location.search`.
 */
export function useTabParam<T extends string>(
  valid: readonly T[],
  fallback: T,
  requested?: string,
) {
  return useState<T>(() =>
    requested && (valid as readonly string[]).includes(requested) ? (requested as T) : fallback,
  );
}
