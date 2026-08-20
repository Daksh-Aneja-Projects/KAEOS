import { useEffect, useRef, useState } from 'react';
import { ShieldCheck, Crosshair, AlertTriangle, Activity, RefreshCw } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { request } from '../api/client';
import { CountUp, prefersReducedMotion } from '../components/CountUp';
import { useVisiblePoll } from '../hooks/useLiveRefresh';

/**
 * Governance Proving Ground — the Assurance Score (gate catch-rate).
 *
 * The north-star safe-autonomy-rate measures how much ran clean; it never proves
 * the gates would STOP a bad action. This page fires a versioned battery of
 * KNOWN-BAD actions at the live gates and shows how many were caught — a firing
 * range for the governance layer. Living, not a screenshot: projectiles launch,
 * hit the gate wall, and deflect in real time (rAF), respecting reduced-motion.
 */

interface AttackResult {
  id: string; name: string; category: string;
  department: string; severity: 'CRIT' | 'HIGH' | 'MED'; gate: string; caught: boolean;
}
interface BatteryRun {
  battery_version: string; total: number; caught: number; escaped_count: number;
  escaped: AttackResult[]; assurance_score: number | null; perfect: boolean;
  results: AttackResult[]; note: string;
}

const DANGER = '#e5484d';       // CRIT accent (semantic; theme-independent)

export default function ProvingGround() {
  const { colors } = useTheme();
  const [run, setRun] = useState<BatteryRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = async () => {
    setRefreshing(true);
    try {
      setRun(await request<BatteryRun>('/proving-ground/run'));
      setError(null);
    } catch (e) {
      setError((e as Error)?.message || 'Failed to run the proving ground');
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => { load(); }, []);
  useVisiblePoll(load, 20000); // live-refresh convention

  const scorePct = run?.assurance_score != null ? Math.round(run.assurance_score * 100) : null;
  const sevColor = (s: string) => (s === 'CRIT' ? DANGER : s === 'HIGH' ? colors.warning : colors.inkTertiary);

  return (
    <div className="h-full flex flex-col gap-4" style={{ color: colors.ink }}>
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-[26px] font-semibold tracking-tight" style={{ letterSpacing: '-0.6px' }}>
            Governance Proving Ground
          </h1>
          <p className="text-[13px] mt-1 max-w-[720px]" style={{ color: colors.inkSubtle }}>
            We continuously fire a battery of known-bad actions at the live gates and
            measure how many are stopped. The Assurance Score is that catch-rate: proof
            the governance blocks bad actions, not just that clean runs passed.
          </p>
        </div>
        <button
          onClick={load}
          className="shrink-0 inline-flex items-center gap-2 rounded-lg px-3 py-2 text-[12px] font-medium"
          style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.inkSubtle }}
        >
          <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} /> Re-run battery
        </button>
      </div>

      {error && (
        <div className="rounded-lg px-4 py-3 text-[13px]" style={{ background: colors.surface2, border: `1px solid ${DANGER}`, color: colors.ink }}>
          {error}
        </div>
      )}

      {/* Hero: score ring + live firing range */}
      <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-4 min-h-0">
        <ScorePanel run={run} scorePct={scorePct} colors={colors} />
        <FiringRange run={run} colors={colors} sevColor={sevColor} />
      </div>

      {/* Per-attack catch grid */}
      <div className="rounded-xl min-h-0 flex-1 overflow-auto" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        <div className="px-4 py-3 sticky top-0" style={{ background: colors.surface1, borderBottom: `1px solid ${colors.hairline}` }}>
          <span className="text-[12px] font-semibold" style={{ color: colors.inkSubtle }}>
            THE BATTERY {run ? `· ${run.total} known-bad actions` : ''}
          </span>
        </div>
        <div className="p-3 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2">
          {(run?.results ?? []).map((a, i) => (
            <AttackCard key={a.id} a={a} i={i} colors={colors} sevColor={sevColor} />
          ))}
        </div>
      </div>
    </div>
  );
}

function ScorePanel({ run, scorePct, colors }: { run: BatteryRun | null; scorePct: number | null; colors: any }) {
  const ok = run?.perfect ?? false;
  const ring = scorePct ?? 0;
  const R = 76, C = 2 * Math.PI * R;
  const color = ok ? colors.success : colors.warning;
  return (
    <div className="rounded-xl p-5 flex flex-col items-center justify-center gap-3" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      <div className="relative" style={{ width: 180, height: 180 }}>
        <svg width={180} height={180} className="-rotate-90">
          <circle cx={90} cy={90} r={R} fill="none" stroke={colors.hairline} strokeWidth={10} />
          <circle
            cx={90} cy={90} r={R} fill="none" stroke={color} strokeWidth={10} strokeLinecap="round"
            strokeDasharray={C} strokeDashoffset={C - (ring / 100) * C}
            style={{ transition: prefersReducedMotion() ? 'none' : 'stroke-dashoffset 1s cubic-bezier(0.22,1,0.36,1)' }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <div className="text-[40px] font-semibold leading-none" style={{ color: colors.ink, letterSpacing: '-1px' }}>
            {scorePct == null ? '—' : <><CountUp value={scorePct} />%</>}
          </div>
          <div className="text-[11px] mt-1 font-medium" style={{ color: colors.inkTertiary }}>ASSURANCE SCORE</div>
        </div>
      </div>
      <div className="inline-flex items-center gap-2 text-[13px] font-medium" style={{ color: ok ? colors.success : colors.warning }}>
        <ShieldCheck size={16} />
        {run ? `${run.caught} of ${run.total} known-bad actions caught` : 'Running battery…'}
      </div>
      {run && run.escaped_count > 0 && (
        <div className="text-[12px] text-center" style={{ color: colors.warning }}>
          {run.escaped_count} escaped — a gate has regressed.
        </div>
      )}
      <div className="text-[11px] text-center mt-1" style={{ color: colors.inkTertiary }}>
        Complements safe-autonomy-rate · battery {run?.battery_version ?? '—'}
      </div>
    </div>
  );
}

/** Live rAF firing range: each known-bad action is a projectile launched at the
 *  gate wall and deflected on contact. Static shield when reduced-motion is set. */
function FiringRange({ run, colors, sevColor }: { run: BatteryRun | null; colors: any; sevColor: (s: string) => string }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const results = run?.results;

  useEffect(() => {
    const canvas = canvasRef.current, wrap = wrapRef.current;
    if (!canvas || !wrap || !results || results.length === 0) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let raf = 0, running = true;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const resize = () => {
      const w = wrap.clientWidth, h = wrap.clientHeight;
      canvas.width = w * dpr; canvas.height = h * dpr;
      canvas.style.width = `${w}px`; canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const ro = new ResizeObserver(resize); ro.observe(wrap);

    type P = { x: number; y: number; vx: number; caught: boolean; sev: string; t: number; life: number };
    const reduced = prefersReducedMotion();
    const spawn = (i: number): P => {
      const a = results[i % results.length];
      const h = wrap.clientHeight || 260;
      return { x: 8, y: 30 + Math.random() * (h - 60), vx: 1.6 + Math.random() * 1.4, caught: a.caught, sev: a.severity, t: 0, life: 0 };
    };
    let projectiles: P[] = reduced ? [] : results.map((_, i) => spawn(i));
    const bursts: { x: number; y: number; t: number; color: string }[] = [];

    const draw = () => {
      const w = wrap.clientWidth, h = wrap.clientHeight;
      const wallX = w * 0.66;
      ctx.clearRect(0, 0, w, h);

      // Gate wall (the governance shield)
      const grad = ctx.createLinearGradient(wallX - 20, 0, wallX + 6, 0);
      grad.addColorStop(0, 'rgba(39,166,68,0)');
      grad.addColorStop(1, 'rgba(39,166,68,0.18)');
      ctx.fillStyle = grad; ctx.fillRect(wallX - 20, 0, 26, h);
      ctx.strokeStyle = colors.success; ctx.globalAlpha = 0.8;
      ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(wallX, 8); ctx.lineTo(wallX, h - 8); ctx.stroke();
      ctx.globalAlpha = 1;

      if (!reduced) {
        for (const p of projectiles) {
          p.x += p.vx; p.t += 1;
          if (p.x >= wallX && p.life === 0) {
            p.life = 1;
            bursts.push({ x: wallX, y: p.y, t: 0, color: p.caught ? colors.success : DANGER });
            if (p.caught) { p.vx = -(1.2 + Math.random()); } // deflected back
          }
          if (p.life > 0) { p.life += 1; p.x += p.vx; p.y += (Math.random() - 0.5) * 1.4; }
          // color by severity before the wall; green tail after a catch
          ctx.fillStyle = p.life > 0 && p.caught ? colors.success : sevColor(p.sev);
          ctx.globalAlpha = 0.9;
          ctx.beginPath(); ctx.arc(p.x, p.y, 2.6, 0, Math.PI * 2); ctx.fill();
          ctx.globalAlpha = 0.25;
          ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(p.x - p.vx * 6, p.y); ctx.strokeStyle = ctx.fillStyle as string; ctx.lineWidth = 2; ctx.stroke();
          ctx.globalAlpha = 1;
        }
        // recycle off-screen projectiles
        projectiles = projectiles.map((p, i) => (p.x < -20 || p.x > w + 20 || p.life > 90) ? spawn(i) : p);
        // bursts
        for (const b of bursts) {
          b.t += 1;
          const r = b.t * 0.9, alpha = Math.max(0, 1 - b.t / 26);
          ctx.strokeStyle = b.color; ctx.globalAlpha = alpha * 0.8;
          ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(b.x, b.y, r, 0, Math.PI * 2); ctx.stroke();
          ctx.globalAlpha = 1;
        }
        for (let i = bursts.length - 1; i >= 0; i--) if (bursts[i].t > 26) bursts.splice(i, 1);
      } else {
        // Reduced motion: the SAME story, told without movement. Each known-bad
        // action is drawn as a spent shot - a severity-coloured trail from the
        // left edge ending at the wall, with a deflection tick where the gates
        // turned it back. The previous fallback drew a bare column of dots at
        // the wall, which left the panel reading as an empty box: a
        // reduced-motion user got no picture of what had happened at all.
        results.forEach((a, i) => {
          const y = 24 + ((i + 0.5) / results.length) * (h - 48);
          ctx.strokeStyle = sevColor(a.severity);
          ctx.globalAlpha = 0.4;
          ctx.lineWidth = 2;
          ctx.beginPath(); ctx.moveTo(10, y); ctx.lineTo(wallX - 7, y); ctx.stroke();
          ctx.globalAlpha = 1;
          ctx.fillStyle = a.caught ? colors.success : DANGER;
          ctx.beginPath(); ctx.arc(wallX - 7, y, 3.2, 0, Math.PI * 2); ctx.fill();
          if (a.caught) {
            // deflected: the shot bounces back off the shield
            ctx.strokeStyle = colors.success; ctx.globalAlpha = 0.55;
            ctx.lineWidth = 1.5;
            ctx.beginPath(); ctx.moveTo(wallX - 9, y); ctx.lineTo(wallX - 26, y - 6); ctx.stroke();
            ctx.globalAlpha = 1;
          }
        });
      }

      if (running) raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => { running = false; cancelAnimationFrame(raf); ro.disconnect(); };
  }, [results, colors]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div ref={wrapRef} className="relative rounded-xl overflow-hidden min-h-[240px]" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      <canvas ref={canvasRef} className="absolute inset-0" />
      <div className="absolute top-3 left-4 flex items-center gap-2 text-[12px] font-semibold pointer-events-none" style={{ color: colors.inkSubtle }}>
        <Crosshair size={14} /> KNOWN-BAD ACTIONS
      </div>
      <div className="absolute top-3 right-4 flex items-center gap-2 text-[12px] font-semibold pointer-events-none" style={{ color: colors.success }}>
        THE GATES <ShieldCheck size={14} />
      </div>
    </div>
  );
}

function AttackCard({ a, i, colors, sevColor }: { a: AttackResult; i: number; colors: any; sevColor: (s: string) => string }) {
  const reduced = prefersReducedMotion();
  return (
    <div
      className="rounded-lg p-3 flex items-start gap-3"
      style={{
        background: colors.surface2, border: `1px solid ${colors.hairline}`,
        animation: reduced ? 'none' : `pgIn 420ms cubic-bezier(0.22,1,0.36,1) both`,
        animationDelay: `${Math.min(i * 45, 700)}ms`,
      }}
    >
      <div className="mt-0.5 shrink-0">
        {a.caught
          ? <ShieldCheck size={18} style={{ color: colors.success }} />
          : <AlertTriangle size={18} style={{ color: colors.warning }} />}
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-medium leading-snug" style={{ color: colors.ink }}>{a.name}</div>
        <div className="text-[11px] mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5" style={{ color: colors.inkTertiary }}>
          <span className="inline-flex items-center gap-1">
            <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ background: sevColor(a.severity) }} />
            {a.severity}
          </span>
          <span>· {a.department}</span>
          <span>· caught by <span style={{ color: colors.inkSubtle }}>{a.gate}</span></span>
        </div>
      </div>
      <div className="shrink-0 text-[11px] font-semibold self-center inline-flex items-center gap-1"
           style={{ color: a.caught ? colors.success : colors.warning }}>
        <Activity size={12} /> {a.caught ? 'CAUGHT' : 'ESCAPED'}
      </div>
      <style>{`@keyframes pgIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}`}</style>
    </div>
  );
}
