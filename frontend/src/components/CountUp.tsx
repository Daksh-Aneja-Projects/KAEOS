import { useLayoutEffect, useRef } from 'react';

interface CountUpProps {
  value: number;
  decimals?: number;
  /** animation length in ms */
  duration?: number;
  prefix?: string;
  suffix?: string;
  className?: string;
}

export function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

/**
 * Count a number up (or down) from its previously rendered value to the new
 * one via requestAnimationFrame with an ease-out curve. A static number reads
 * as a picture; this makes every KPI feel live. Honors prefers-reduced-motion
 * by jumping straight to the final value with no animation.
 *
 * The animation writes el.textContent directly from the rAF loop (same
 * pattern as TwinGraph): zero re-renders per frame instead of one setState
 * per frame across every stat card.
 */
export function CountUp({
  value,
  decimals = 0,
  duration = 900,
  prefix = '',
  suffix = '',
  className,
}: CountUpProps) {
  const spanRef = useRef<HTMLSpanElement | null>(null);
  const shownRef = useRef(value); // latest number written to the DOM, survives re-renders
  const rafRef = useRef<number | null>(null);

  const to = Number.isFinite(value) ? value : 0;

  useLayoutEffect(() => {
    const el = spanRef.current;
    if (!el) return;
    if (rafRef.current != null) cancelAnimationFrame(rafRef.current);

    const fmt = (n: number) => `${prefix}${n.toFixed(decimals)}${suffix}`;
    const from = shownRef.current;

    if (from === to || prefersReducedMotion()) {
      shownRef.current = to;
      el.textContent = fmt(to);
      return;
    }

    // Layout effect runs before paint: rewind the DOM to the old number so
    // the freshly committed final value never flashes for a frame.
    el.textContent = fmt(from);

    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3); // ease-out cubic
      const current = t < 1 ? from + (to - from) * eased : to;
      shownRef.current = current;
      el.textContent = fmt(current);
      rafRef.current = t < 1 ? requestAnimationFrame(tick) : null;
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
  }, [to, duration, prefix, suffix, decimals]);

  // A single string child keeps React owning exactly one text node, so the
  // rAF loop's textContent writes and React's own updates never desync.
  return (
    <span ref={spanRef} className={className}>
      {`${prefix}${to.toFixed(decimals)}${suffix}`}
    </span>
  );
}

export default CountUp;
