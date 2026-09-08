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
 */
export function useEnterprisePanel<T>(loader: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // The loader lives in a ref so `load` is stable and the mount effect below
  // runs once, not once per render.
  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const load = useCallback(async () => {
    try {
      const d = await loaderRef.current();
      setData(d); setError(null); setNotice(null);
    } catch (e: any) {
      if (e instanceof ApiError && (e.status === 402 || e.status === 403)) setNotice(e.message);
      else setError(e?.message || 'The request failed.');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);
  useVisiblePoll(load, 15000);
  return { data, error, notice, loading, reload: load };
}
