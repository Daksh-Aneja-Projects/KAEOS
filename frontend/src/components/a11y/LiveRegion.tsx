import { useEffect, useState } from 'react';

/**
 * Screen-reader announcement host.
 *
 * A single visually-hidden ARIA live region mounted once at the app root.
 * Any code (toasts, async errors, save confirmations) calls `announce(msg)`
 * without prop-drilling a context; the message is read out by assistive tech.
 *
 * Two politeness levels: 'polite' (default, waits for a pause) and
 * 'assertive' (interrupts, for errors). We keep two separate regions so a
 * polite message can't clobber an assertive one.
 */

type Politeness = 'polite' | 'assertive';

const listeners = new Set<(p: Politeness, msg: string) => void>();

/** Announce a message to screen-reader users. Safe to call from anywhere. */
export function announce(message: string, politeness: Politeness = 'polite'): void {
  const msg = (message ?? '').trim();
  if (!msg) return;
  listeners.forEach((fn) => fn(politeness, msg));
}

export function LiveRegionHost() {
  const [polite, setPolite] = useState('');
  const [assertive, setAssertive] = useState('');

  useEffect(() => {
    const fn = (p: Politeness, msg: string) => {
      const set = p === 'assertive' ? setAssertive : setPolite;
      // Clear first so an identical consecutive message still fires a change.
      set('');
      requestAnimationFrame(() => set(msg));
    };
    listeners.add(fn);
    return () => { listeners.delete(fn); };
  }, []);

  return (
    <>
      <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">{polite}</div>
      <div className="sr-only" role="alert" aria-live="assertive" aria-atomic="true">{assertive}</div>
    </>
  );
}
