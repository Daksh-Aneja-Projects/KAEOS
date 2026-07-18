import { useEffect, useRef } from 'react';
import { useWebSocket } from './useWebSocket';

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
 * `events` filters on substrings of the event payload; omit it to refresh on
 * any tenant event.
 */
export function useLiveRefresh(
  loader: () => void | Promise<void>,
  events?: string[],
) {
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

  return { live: status === 'connected' };
}
