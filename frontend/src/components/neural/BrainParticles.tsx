import React, { useEffect, useRef } from 'react';

/**
 * The living company brain: a canvas particle cluster. Points drift inside a
 * sphere-ish boundary and link to near neighbors, so the brain reads as a
 * dense, breathing knowledge graph rather than a static badge.
 * Respects prefers-reduced-motion (renders one static frame).
 */
export default function BrainParticles({
  size,
  color,
  accent,
  density = 64,
  className,
}: {
  size: number;
  color: string;
  /** Larger, brighter highlight nodes scattered through the cluster. */
  accent?: string;
  density?: number;
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    ctx.scale(dpr, dpr);

    const R = size / 2;
    // Hash-scattered points (no visible spiral arms); motion supplies the life.
    const hash = (n: number) => {
      const x = Math.sin(n * 127.1 + 311.7) * 43758.5453;
      return x - Math.floor(x);
    };
    const pts = Array.from({ length: density }, (_, i) => {
      const a = hash(i) * Math.PI * 2;
      const r = R * 0.85 * Math.sqrt(hash(i + 999));
      const va = hash(i + 500) * Math.PI * 2;
      return {
        x: R + Math.cos(a) * r,
        y: R + Math.sin(a) * r,
        vx: Math.cos(va) * 0.16,
        vy: Math.sin(va) * 0.16,
        big: hash(i + 77) > 0.9,
      };
    });

    const LINK_DIST = R * 0.34;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let raf = 0;

    const draw = () => {
      ctx.clearRect(0, 0, size, size);
      // Links first, under the points.
      for (let i = 0; i < pts.length; i++) {
        for (let j = i + 1; j < pts.length; j++) {
          const dx = pts[i].x - pts[j].x, dy = pts[i].y - pts[j].y;
          const d = Math.hypot(dx, dy);
          if (d < LINK_DIST) {
            ctx.globalAlpha = 0.28 * (1 - d / LINK_DIST);
            ctx.strokeStyle = color;
            ctx.lineWidth = 0.6;
            ctx.beginPath();
            ctx.moveTo(pts[i].x, pts[i].y);
            ctx.lineTo(pts[j].x, pts[j].y);
            ctx.stroke();
          }
        }
      }
      ctx.globalAlpha = 1;
      for (const p of pts) {
        ctx.fillStyle = p.big && accent ? accent : color;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.big ? 2.4 : 1.4, 0, Math.PI * 2);
        ctx.fill();
        if (p.big && accent) {
          ctx.globalAlpha = 0.25;
          ctx.beginPath();
          ctx.arc(p.x, p.y, 5, 0, Math.PI * 2);
          ctx.fill();
          ctx.globalAlpha = 1;
        }
      }
    };

    const step = () => {
      for (const p of pts) {
        p.x += p.vx;
        p.y += p.vy;
        // Soft spherical boundary: nudge back toward center past 88% radius.
        const dx = p.x - R, dy = p.y - R;
        const d = Math.hypot(dx, dy);
        if (d > R * 0.88) {
          p.vx -= (dx / d) * 0.02;
          p.vy -= (dy / d) * 0.02;
        }
      }
      draw();
      raf = requestAnimationFrame(step);
    };

    draw();
    if (!reduced) raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [size, color, density]);

  return (
    <canvas
      ref={canvasRef}
      className={className}
      style={{ width: size, height: size, display: 'block' }}
      aria-hidden="true"
    />
  );
}
