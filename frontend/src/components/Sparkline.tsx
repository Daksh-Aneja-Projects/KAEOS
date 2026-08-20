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
  // Hook first, unconditionally: this used to sit below the early return, so a
  // series crossing the 2-point threshold between renders changed hook order.
  const [hover, setHover] = React.useState<number | null>(null);

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

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const rx = ((e.clientX - rect.left) / rect.width) * width;
    let best = 0, bd = Infinity;
    coords.forEach(([x], i) => { const d = Math.abs(x - rx); if (d < bd) { bd = d; best = i; } });
    setHover(best);
  };
  const hp = hover != null ? coords[hover] : null;

  return (
    <svg width={width} height={height} className={className} style={{ overflow: 'visible', cursor: 'crosshair' }}
      onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.28} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gradId})`} />
      <path d={path} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      {/* the present moment, marked — with a live pulse */}
      <circle cx={lastX} cy={lastY} r={2.2} fill={color}>
        <animate attributeName="r" values="2.2;4.5;2.2" dur="1.8s" repeatCount="indefinite" />
        <animate attributeName="opacity" values="1;0.4;1" dur="1.8s" repeatCount="indefinite" />
      </circle>
      {/* hover crosshair + value */}
      {hp && (
        <g>
          <line x1={hp[0]} y1={0} x2={hp[0]} y2={height} stroke={color} strokeOpacity={0.35} strokeWidth={1} />
          <circle cx={hp[0]} cy={hp[1]} r={2.6} fill={color} stroke="#fff" strokeWidth={0.8} />
          <text x={Math.min(hp[0] + 4, width - 2)} y={9} fontSize={9} fill={color} style={{ fontWeight: 700 }}>
            {vals[hover as number] % 1 === 0 ? vals[hover as number] : vals[hover as number].toFixed(2)}
          </text>
        </g>
      )}
    </svg>
  );
}
