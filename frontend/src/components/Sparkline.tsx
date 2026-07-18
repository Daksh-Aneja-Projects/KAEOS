import React from 'react';

/**
 * A tiny trend line.
 *
 * The product's claim is that it learns - agents earn autonomy over time - but
 * every screen showed a single snapshot. "57%" is a status. "57%, and rising"
 * is the thesis. This renders the second one.
 */
export default function Sparkline({
  points,
  color = '#22c55e',
  width = 120,
  height = 28,
  className = '',
}: {
  points: (number | null)[];
  color?: string;
  width?: number;
  height?: number;
  className?: string;
}) {
  const vals = points.filter((p): p is number => p !== null && !isNaN(p));
  if (vals.length < 2) return null;

  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const pad = 2;

  const coords = vals.map((v, i) => {
    const x = pad + (i / (vals.length - 1)) * (width - pad * 2);
    const y = height - pad - ((v - min) / span) * (height - pad * 2);
    return [x, y] as const;
  });

  const path = coords.map(([x, y], i) => `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
  const area = `${path} L ${coords[coords.length - 1][0].toFixed(1)} ${height} L ${coords[0][0].toFixed(1)} ${height} Z`;
  const [lastX, lastY] = coords[coords.length - 1];
  const gradId = `spark-${color.replace('#', '')}`;

  return (
    <svg width={width} height={height} className={className} aria-hidden="true">
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.28} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gradId})`} />
      <path d={path} fill="none" stroke={color} strokeWidth={1.5}
        strokeLinejoin="round" strokeLinecap="round" />
      {/* the present moment, marked */}
      <circle cx={lastX} cy={lastY} r={2.2} fill={color} />
    </svg>
  );
}
