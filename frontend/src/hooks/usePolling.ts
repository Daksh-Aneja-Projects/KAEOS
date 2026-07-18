/**
 * KAEOS - usePolling Hook
 * 
 * The Enterprise Brain's heartbeat. Certain pages need to stay alive
 * with the Brain's cognitive loop - OODA, Signals, Activity Feed,
 * Debates. These aren't static dashboards; they're live neural streams.
 * 
 * This hook provides:
 * - Configurable polling interval
 * - Auto-pause when tab is hidden (saves Brain queries)
 * - Graceful degradation on consecutive failures
 * - Freshness indicator (how stale is the intelligence?)
 */

import { useState, useEffect, useCallback, useRef } from 'react';

export interface PollingState<T> {
  /** Latest intelligence from the Brain */
  data: T | null;
  /** Initial load in progress */
  loading: boolean;
  /** Last query failed */
  error: string | null;
  /** No intelligence available */
  empty: boolean;
  /** Stream is actively polling */
  isLive: boolean;
  /** Seconds since last successful update */
  staleness: number;
  /** Manually trigger a refresh */
  refresh: () => void;
  /** Pause the live stream */
  pause: () => void;
  /** Resume the live stream */
  resume: () => void;
}

export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number = 30000,
  options?: {
    emptyCheck?: (data: T) => boolean;
    /** Max consecutive failures before pausing */
    maxRetries?: number;
    /** Pause polling when document is hidden */
    pauseOnHidden?: boolean;
  }
): PollingState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isLive, setIsLive] = useState(true);
  const [lastSuccess, setLastSuccess] = useState<number>(Date.now());
  const [staleness, setStaleness] = useState(0);
  
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const failCount = useRef(0);
  const maxRetries = options?.maxRetries ?? 5;
  const pauseOnHidden = options?.pauseOnHidden ?? true;

  const isEmpty = useCallback((d: T | null): boolean => {
    if (d === null) return true;
    if (options?.emptyCheck) return options.emptyCheck(d);
    if (Array.isArray(d)) return d.length === 0;
    if (typeof d === 'object' && d !== null) {
      const obj = d as any;
      if ('events' in obj && Array.isArray(obj.events)) return obj.events.length === 0;
      if ('total' in obj && obj.total === 0) return true;
    }
    return false;
  }, [options?.emptyCheck]);

  const execute = useCallback(async () => {
    try {
      const result = await fetcherRef.current();
      setData(result);
      setError(null);
      setLastSuccess(Date.now());
      failCount.current = 0;
    } catch (err: any) {
      failCount.current++;
      setError(err?.message || 'Stream interrupted');
      // Auto-pause after too many consecutive failures
      if (failCount.current >= maxRetries) {
        setIsLive(false);
      }
    } finally {
      setLoading(false);
    }
  }, [maxRetries]);

  // Start/stop polling
  useEffect(() => {
    if (isLive) {
      execute(); // Initial fetch
      intervalRef.current = setInterval(execute, intervalMs);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [isLive, intervalMs, execute]);

  // Staleness tracker
  useEffect(() => {
    const timer = setInterval(() => {
      setStaleness(Math.floor((Date.now() - lastSuccess) / 1000));
    }, 1000);
    return () => clearInterval(timer);
  }, [lastSuccess]);

  // Pause on tab hidden
  useEffect(() => {
    if (!pauseOnHidden) return;
    const handleVisibility = () => {
      if (document.hidden) {
        if (intervalRef.current) clearInterval(intervalRef.current);
      } else if (isLive) {
        execute();
        intervalRef.current = setInterval(execute, intervalMs);
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);
    return () => document.removeEventListener('visibilitychange', handleVisibility);
  }, [isLive, intervalMs, execute, pauseOnHidden]);

  return {
    data,
    loading,
    error,
    empty: !loading && isEmpty(data),
    isLive,
    staleness,
    refresh: execute,
    pause: () => setIsLive(false),
    resume: () => { failCount.current = 0; setIsLive(true); },
  };
}
