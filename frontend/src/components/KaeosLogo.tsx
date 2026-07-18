import React from 'react';

/**
 * KAEOS mark: the enterprise twin in miniature.
 * A bright core (the Company Brain) with seven orbiting nodes (the seven
 * department brains) joined into one living network - the product's hero
 * visual as its identity.
 */
export default function KaeosLogo({ className = 'w-4 h-4', color = 'currentColor' }: {
  className?: string;
  color?: string;
}) {
  const nodes = Array.from({ length: 7 }, (_, i) => {
    const a = (i / 7) * 2 * Math.PI - Math.PI / 2;
    return { x: 12 + Math.cos(a) * 8.2, y: 12 + Math.sin(a) * 8.2 };
  });
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      {/* spokes: every department connected to the brain */}
      {nodes.map((n, i) => (
        <line key={`s${i}`} x1="12" y1="12" x2={n.x} y2={n.y}
          stroke={color} strokeWidth="1" opacity="0.55" />
      ))}
      {/* orbit links between neighbouring departments */}
      {nodes.map((n, i) => {
        const m = nodes[(i + 1) % 7];
        return (
          <line key={`o${i}`} x1={n.x} y1={n.y} x2={m.x} y2={m.y}
            stroke={color} strokeWidth="0.8" opacity="0.3" />
        );
      })}
      {/* department nodes */}
      {nodes.map((n, i) => (
        <circle key={`n${i}`} cx={n.x} cy={n.y} r="1.7" fill={color} />
      ))}
      {/* the Company Brain core */}
      <circle cx="12" cy="12" r="3.1" fill={color} />
      <circle cx="12" cy="12" r="4.6" stroke={color} strokeWidth="0.9" opacity="0.35" />
    </svg>
  );
}
