import { useEffect, useRef, useState } from 'react';

interface CountUpProps {
  value: number;
  decimals?: number;
  /** animation length in ms */
  duration?: number;
  prefix?: string;
  suffix?: string;
  className?: string;
}

function prefersReducedMotion(): boolean {
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
 */
export function CountUp({
  value,
  decimals = 0,
  duration = 900,
  prefix = '',
  suffix = '',
  className,
}: CountUpProps) {
  const [display, setDisplay] = useState(value);
  const displayRef = useRef(value); // latest rendered number, survives re-renders
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (rafRef.current != null) cancelAnimationFrame(rafRef.current);

    const from = displayRef.current;
    const to = Number.isFinite(value) ? value : 0;

    if (from === to || prefersReducedMotion()) {
      displayRef.current = to;
      setDisplay(to);
      return;
    }

    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3); // ease-out cubic
      const current = from + (to - from) * eased;
      displayRef.current = current;
      setDisplay(current);
      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        displayRef.current = to;
        rafRef.current = null;
      }
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
  }, [value, duration]);

  const num = Number.isFinite(display) ? display : 0;
  return (
    <span className={className}>
      {prefix}
      {num.toFixed(decimals)}
      {suffix}
    </span>
  );
}

export default CountUp;
