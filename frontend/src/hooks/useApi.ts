/**
 * KAEOS - useApi Hook
 * 
 * Not a generic CRUD fetcher. This is the neural interface between
 * the Enterprise Brain backend and the Experience Layer (S4).
 * 
 * Every API call in KAEOS carries semantic weight:
 * - It's not "fetching data" - it's querying the Brain's state
 * - Empty != broken. Empty = the Brain hasn't learned this yet
 * - Errors != failure. Errors = a cognitive pathway is interrupted
 * 
 * Built-in states map to the Brain's cognitive states:
 * - loading  → Brain is reasoning
 * - data     → Brain has intelligence to share
 * - empty    → Brain has no knowledge in this domain yet
 * - error    → A neural pathway is interrupted
 */

import { useState, useEffect, useCallback, useRef } from 'react';

export interface ApiState<T> {
  /** The intelligence returned by the Brain */
  data: T | null;
  /** Brain is currently reasoning / computing */
  loading: boolean;
  /** A cognitive pathway failed */
  error: string | null;
  /** Brain has no knowledge in this domain - not an error, a state */
  empty: boolean;
  /** Re-query the Brain */
  refetch: () => void;
  /** Timestamp of last successful query */
  lastUpdated: Date | null;
}

/**
 * Core hook for querying the Enterprise Brain.
 * 
 * @param fetcher - Async function that queries a Brain endpoint
 * @param options - Configuration for the query behavior
 * 
 * @example
 * ```tsx
 * const { data, loading, empty } = useApi(
 *   () => api.getBrainOverview(),
 *   { emptyCheck: (d) => d.enterprise_iq === 0 }
 * );
 * ```
 */
export function useApi<T>(
  fetcher: () => Promise<T>,
  options?: {
    /** Custom empty-state check. Default: checks for null, [], or {total: 0} */
    emptyCheck?: (data: T) => boolean;
    /** Dependencies that trigger re-fetch */
    deps?: any[];
    /** Don't fetch on mount - wait for manual trigger */
    lazy?: boolean;
  }
): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(!options?.lazy);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const isEmpty = useCallback((d: T | null): boolean => {
    if (d === null || d === undefined) return true;
    if (options?.emptyCheck) return options.emptyCheck(d);
    if (Array.isArray(d)) return d.length === 0;
    if (typeof d === 'object' && d !== null) {
      // Check common response patterns: { total: 0 }, { items: [] }
      const obj = d as any;
      if ('total' in obj && obj.total === 0) return true;
      // Check if all array properties are empty
      const arrayProps = Object.values(obj).filter(Array.isArray);
      if (arrayProps.length > 0 && arrayProps.every(arr => (arr as any[]).length === 0)) return true;
    }
    return false;
  }, [options?.emptyCheck]);

  const execute = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetcherRef.current();
      setData(result);
      setLastUpdated(new Date());
    } catch (err: any) {
      const message = err?.message || 'Neural pathway interrupted';
      setError(message);
      // Don't clear existing data on refetch errors - preserve last known state
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!options?.lazy) {
      execute();
    }
  }, [...(options?.deps || [])]);

  return {
    data,
    loading,
    error,
    empty: !loading && isEmpty(data),
    refetch: execute,
    lastUpdated,
  };
}

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
