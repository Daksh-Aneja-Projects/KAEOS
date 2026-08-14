import { useTheme } from '../../context/ThemeContext';
import { CountUp } from '../CountUp';

export const DONUT_PALETTE = ['#6366f1', '#22c55e', '#f59e0b', '#3b82f6', '#ef4444', '#a855f7'];

export interface DonutItem {
  label: string;
  value: number;
}

interface MiniDonutProps {
  items: DonutItem[];
  /** Outer diameter in px (Finance used 96, HR 80). */
  size?: number;
  /** Word under the center total. */
  centerLabel?: string;
  className?: string;
}

/**
 * The Finance and HR dashboards each carried a byte-for-byte copy of this
 * donut. One shared component now: a conic-gradient ring with a count-up total
 * in the hole and a percentage legend. Colors come from the theme; the ring
 * segments use DONUT_PALETTE.
 */
export function MiniDonut({ items, size = 96, centerLabel = 'total', className }: MiniDonutProps) {
  const { colors } = useTheme();
  const total = items.reduce((s, i) => s + i.value, 0);
  let acc = 0;
  const segs = items.map((it, idx) => {
    const start = (acc / (total || 1)) * 360;
    acc += it.value;
    const end = (acc / (total || 1)) * 360;
    return `${DONUT_PALETTE[idx % DONUT_PALETTE.length]} ${start}deg ${end}deg`;
  });
  const hole = Math.round(size * 0.125); // inset of the center disc

  return (
    <div className={`flex items-center gap-4 ${className || ''}`}>
      <div
        className="rounded-full shrink-0 relative"
        style={{ width: size, height: size, background: total > 0 ? `conic-gradient(${segs.join(', ')})` : colors.canvas }}
      >
        <div
          className="absolute rounded-full flex flex-col items-center justify-center"
          style={{ inset: hole, background: colors.surface1 }}
        >
          <CountUp value={total} className="text-[16px] font-bold leading-none tabular-nums" />
          <span className="text-[11px] uppercase tracking-wide mt-0.5" style={{ color: colors.inkSubtle }}>{centerLabel}</span>
        </div>
      </div>
      <div className="flex-1 min-w-0 space-y-1.5">
        {items.map((it, idx) => (
          <div key={it.label} className="flex items-center gap-1.5 text-[11px]">
            <span className="w-2 h-2 rounded-full shrink-0" style={{ background: DONUT_PALETTE[idx % DONUT_PALETTE.length] }} />
            <span className="truncate" style={{ color: colors.inkSubtle }}>{it.label}</span>
            <span className="font-mono ml-auto pl-2" style={{ color: colors.ink }}>{it.value.toLocaleString()}</span>
            <span className="w-8 text-right shrink-0" style={{ color: colors.inkSubtle }}>{total ? Math.round((it.value / total) * 100) : 0}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default MiniDonut;
