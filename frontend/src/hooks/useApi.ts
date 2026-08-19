/**
 * KAEOS - useParallelApi Hook
 *
 * Not a generic CRUD fetcher. This is the neural interface between
 * the Enterprise Brain backend and the Experience Layer (S4).
 *
 * Every API call in KAEOS carries semantic weight:
 * - It's not "fetching data" - it's querying the Brain's state
 * - Empty != broken. Empty = the Brain hasn't learned this yet
 * - Errors != failure. Errors = a cognitive pathway is interrupted
 */

import { useState, useEffect, useCallback, useRef } from 'react';

/**
 * Multi-source hook for pages that aggregate intelligence from multiple Brain endpoints.
 * This is the norm in KAEOS - the Executive Cockpit queries 4+ endpoints in parallel.
 *
 * @example
 * ```tsx
 * const { results, allLoaded, anyError } = useParallelApi({
 *   health: () => api.getHealth(),
 *   cockpit: () => api.getCockpit(),
 *   feed: () => api.getActivityFeed(15),
 * });
 * ```
 */
export function useParallelApi<T extends Record<string, () => Promise<any>>>(
  fetchers: T
): {
  results: { [K in keyof T]: Awaited<ReturnType<T[K]>> | null };
  loading: boolean;
  allLoaded: boolean;
  anyError: string | null;
  refetchAll: () => void;
} {
  const keys = Object.keys(fetchers) as (keyof T)[];
  const [results, setResults] = useState<Record<string, any>>(
    Object.fromEntries(keys.map(k => [k, null]))
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const fetchersRef = useRef(fetchers);
  fetchersRef.current = fetchers;

  const execute = useCallback(async () => {
    setLoading(true);
    setError(null);
    const settled = await Promise.allSettled(
      keys.map(k => fetchersRef.current[k]())
    );
    const newResults: Record<string, any> = {};
    let firstError: string | null = null;
    settled.forEach((result, i) => {
      if (result.status === 'fulfilled') {
        newResults[keys[i] as string] = result.value;
      } else {
        newResults[keys[i] as string] = null;
        if (!firstError) firstError = result.reason?.message || 'Query failed';
      }
    });
    setResults(newResults);
    setError(firstError);
    setLoading(false);
  }, []);

  useEffect(() => { execute(); }, []);

  return {
    results: results as any,
    loading,
    allLoaded: !loading,
    anyError: error,
    refetchAll: execute,
  };
}
