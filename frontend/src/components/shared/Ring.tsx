import { useEffect, useRef, useState } from 'react';
import { useTheme } from '../../context/ThemeContext';
import { prefersReducedMotion } from '../CountUp';

interface RingProps {
  value: number;
  max?: number;
  /** Outer diameter in px. */
  size?: number;
  strokeWidth?: number;
  /** Ring color; defaults to the theme primary. */
  color?: string;
  trackColor?: string;
  /** Accessible name AND the small caption under the center number. */
  label?: string;
  /** Center readout: percent of max (default) or the raw value. */
  center?: 'percent' | 'value' | 'none';
  className?: string;
}

/**
 * A progress ring that draws itself. On mount and whenever `value` changes it
 * tweens the stroke-dashoffset from where it was to the new arc via
 * requestAnimationFrame with an ease-out curve, so the ring visibly fills
 * rather than snapping. prefers-reduced-motion jumps straight to the final arc.
 * Accessible as a progressbar with live value/min/max.
 */
export function Ring({
  value,
  max = 100,
  size = 88,
  strokeWidth = 8,
  color,
  trackColor,
  label,
  center = 'percent',
  className,
}: RingProps) {
  const { colors } = useTheme();
  const target = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0;
  const [frac, setFrac] = useState(target);
  const fracRef = useRef(target); // last drawn fraction, survives re-renders
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    const from = fracRef.current;
    const to = target;
    if (from === to || prefersReducedMotion()) {
      fracRef.current = to;
      setFrac(to);
      return;
    }
    const start = performance.now();
    const duration = 900;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3); // ease-out cubic
      const cur = from + (to - from) * eased;
      fracRef.current = cur;
      setFrac(cur);
      if (t < 1) rafRef.current = requestAnimationFrame(tick);
      else { fracRef.current = to; rafRef.current = null; }
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => { if (rafRef.current != null) cancelAnimationFrame(rafRef.current); };
  }, [target]);

  const r = (size - strokeWidth) / 2;
  const circ = 2 * Math.PI * r;
  const pct = Math.round(target * 100);
  const stroke = color || colors.primary;

  return (
    <div
      className={`relative inline-flex items-center justify-center ${className || ''}`}
      style={{ width: size, height: size }}
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label ? `${label}: ${pct}%` : `${pct}%`}
    >
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none"
          stroke={trackColor || colors.hairline} strokeWidth={strokeWidth}
        />
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none"
          stroke={stroke} strokeWidth={strokeWidth} strokeLinecap="round"
          strokeDasharray={circ}
          strokeDashoffset={circ * (1 - frac)}
        />
      </svg>
      {center !== 'none' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="font-bold tabular-nums leading-none" style={{ fontSize: size * 0.24, color: colors.ink }}>
            {center === 'percent' ? `${Math.round(frac * 100)}%` : Math.round(frac * max).toLocaleString()}
          </span>
          {label && (
            <span className="uppercase tracking-wide mt-1" style={{ fontSize: Math.max(9, size * 0.1), color: colors.inkSubtle }}>
              {label}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

export default Ring;
