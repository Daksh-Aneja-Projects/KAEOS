import { useEffect, useRef } from 'react';
import { useWebSocket } from './useWebSocket';

/**
 * Poll `loader` on a timer, paused while the tab is hidden and re-fired on
 * return - so a backgrounded tab burns no queries and is never stale when the
 * user looks back at it. Omit `intervalMs` to do nothing.
 *
 * Reach for THIS when a page only needs a timer. `useLiveRefresh` wraps it and
 * also refreshes on tenant WebSocket events, but every `useWebSocket()` call
 * opens its own socket, so adopting the bigger hook purely to get the
 * visibility guard would cost a connection per call site.
 */
export function useVisiblePoll(loader: () => void | Promise<void>, intervalMs?: number) {
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    if (!intervalMs) return;
    let id: ReturnType<typeof setInterval> | null = null;
    const stop = () => { if (id) { clearInterval(id); id = null; } };
    const start = () => { stop(); id = setInterval(() => void loaderRef.current(), intervalMs); };
    const onVisibility = () => {
      if (document.hidden) stop();
      else { void loaderRef.current(); start(); }
    };
    if (!document.hidden) start();
    document.addEventListener('visibilitychange', onVisibility);
    return () => { stop(); document.removeEventListener('visibilitychange', onVisibility); };
  }, [intervalMs]);
}

/**
 * Re-run a page's loader whenever the backend says something happened.
 *
 * Before this, ~40 of the app's data pages fetched once on mount and then
 * rotted until the user clicked one of the 13 manual refresh buttons - the
 * user WAS the refresh mechanism. The tenant WebSocket already broadcasts
 * every activity event; this just listens.
 *
 *   const loadData = async () => { ...setState... };
 *   useEffect(() => { loadData(); }, []);
 *   useLiveRefresh(loadData);
 *
 * It deliberately drives an EXISTING loader rather than owning the fetch:
 * these views set several pieces of state per load, so a hook that owned the
 * data would not fit them - and a hook that does not fit its call sites is
 * dead code, however elegant.
 *
 * `opts` may be a bare `events` array (substring filter on the event payload;
 * omit to refresh on any tenant event) or an options object. Pass
 * `{ intervalMs }` to ALSO poll on a timer - the dashboards that must feel live
 * even when the WebSocket is quiet use this. The timer pauses while the tab is
 * hidden and re-fires on return, so a backgrounded tab never burns queries.
 */
export function useLiveRefresh(
  loader: () => void | Promise<void>,
  opts?: string[] | { events?: string[]; intervalMs?: number },
) {
  const events = Array.isArray(opts) ? opts : opts?.events;
  const intervalMs = Array.isArray(opts) ? undefined : opts?.intervalMs;
  const { lastMessage, status } = useWebSocket();

  // Hold the newest loader without making it a dependency: callers pass inline
  // closures, which would otherwise re-fire on every render.
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    if (!lastMessage) return;
    if (events?.length) {
      const blob = JSON.stringify(lastMessage).toUpperCase();
      if (!events.some(e => blob.includes(e.toUpperCase()))) return;
    }
    void loaderRef.current();
  }, [lastMessage, events]);

  // Interval refresh, paused while the tab is hidden.
  useVisiblePoll(loader, intervalMs);

  return { live: status === 'connected' };
}
