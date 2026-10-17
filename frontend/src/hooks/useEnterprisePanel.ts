import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../api/client';
import { useVisiblePoll } from './useLiveRefresh';

/**
 * Load an Enterprise-gated panel's data, treating 402/403 as a governance
 * notice rather than an error: a 402 means the capability is not enabled
 * on this deployment, a 403 means this principal (a viewer, or an agent key
 * on a console-only view) may not see it. Both render as a calm sentence
 * from the backend, never a red error with a pointless retry.
 *
 * Extracted from GovernedExecution.tsx (its original, page-local `usePanel`)
 * so a second Enterprise page (Object Explorer, F13) does not duplicate the
 * same non-trivial 402/403 handling - fix once where every caller routes
 * through.
 *
 * `error` is only set while there is nothing to show. A failed refresh after
 * data has loaded is reported as `staleError` instead, so a page keeps the
 * last loaded figures (and anything the user typed) and shows a small banner.
 * Polling stops for good once a 402 or 403 arrives: the answer will not change
 * on its own, and every poll would repeat the plan-upgrade prompt.
 */
export function useEnterprisePanel<T>(loader: () => Promise<T>, opts?: { poll?: boolean }) {
  const poll = opts?.poll !== false;
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [staleError, setStaleError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // The loader lives in a ref so `load` is stable and the mount effect below
  // runs once, not once per render.
  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const hasData = useRef(false);
  const gated = useRef(false);
  const load = useCallback(async () => {
    try {
      const d = await loaderRef.current();
      hasData.current = true; gated.current = false;
      setData(d); setError(null); setStaleError(null); setNotice(null);
    } catch (e: any) {
      if (e instanceof ApiError && (e.status === 402 || e.status === 403)) {
        gated.current = true;
        setNotice(e.message || 'This is not available to you on this deployment.');
      } else {
        const msg = e?.message || 'The request failed.';
        if (hasData.current) setStaleError(msg); else setError(msg);
      }
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);
  useVisiblePoll(() => { if (!gated.current) return load(); }, poll ? 15000 : undefined);
  return { data, error, staleError, notice, loading, reload: load };
}
