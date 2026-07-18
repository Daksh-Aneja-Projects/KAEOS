import React, { useEffect, useRef, useState } from 'react';

/**
 * A number that shows when it changed.
 *
 * Motion should mean something. The twin proved the app can animate; the rest
 * of the UI redrew silently, so a value arriving from the backend looked
 * identical to a value that had been sitting there for an hour. This flashes
 * once, briefly, on an actual change - and never on first paint.
 */
export default function LiveValue({
  value,
  className = '',
  style,
  flashColor = '#22c55e',
}: {
  value: string | number;
  className?: string;
  style?: React.CSSProperties;
  flashColor?: string;
}) {
  const [flash, setFlash] = useState(false);
  const prev = useRef(value);
  const mounted = useRef(false);

  useEffect(() => {
    if (!mounted.current) {           // first paint is not a change
      mounted.current = true;
      prev.current = value;
      return;
    }
    if (prev.current === value) return;
    prev.current = value;
    setFlash(true);
    const t = setTimeout(() => setFlash(false), 900);
    return () => clearTimeout(t);
  }, [value]);

  return (
    <span
      className={className}
      style={{
        ...style,
        transition: 'color 250ms ease, text-shadow 250ms ease',
        ...(flash ? { color: flashColor, textShadow: `0 0 12px ${flashColor}66` } : {}),
      }}
    >
      {value}
    </span>
  );
}
