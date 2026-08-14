import React from 'react';
import { ArrowUpRight, ArrowDownRight } from 'lucide-react';
import { useTheme } from '../../context/ThemeContext';
import { CountUp } from '../CountUp';
import { MiniDonut, type DonutItem } from './MiniDonut';

type StatFormat = 'number' | 'currency' | 'percent';

interface StatCardProps {
  label: string;
  value: number;
  format?: StatFormat;
  decimals?: number;
  /** Signed period-over-period change; sign drives the arrow + color. Same format as value. */
  delta?: number;
  /** Caption next to the delta, e.g. "vs last week". */
  deltaLabel?: string;
  /** Optional lead icon (an SVG element, never an emoji). */
  icon?: React.ReactNode;
  /** Accent color for the icon chip; defaults to theme primary. */
  accent?: string;
  /** Optional inline donut breakdown rendered under the value. */
  donut?: DonutItem[];
  className?: string;
  style?: React.CSSProperties;
}

function affix(format: StatFormat): { prefix: string; suffix: string } {
  if (format === 'currency') return { prefix: '$', suffix: '' };
  if (format === 'percent') return { prefix: '', suffix: '%' };
  return { prefix: '', suffix: '' };
}

/**
 * The canonical KPI tile. A count-up value (never a static number), format-aware
 * prefix/suffix (plain / currency / percent), an optional trend chip whose arrow
 * and color come from the sign of `delta`, an optional lead-icon chip, and an
 * optional inline donut. One tile so every dashboard's KPIs read as one system.
 */
export function StatCard({
  label,
  value,
  format = 'number',
  decimals = 0,
  delta,
  deltaLabel,
  icon,
  accent,
  donut,
  className = '',
  style,
}: StatCardProps) {
  const { colors } = useTheme();
  const { prefix, suffix } = affix(format);
  const chip = accent || colors.primary;
  const up = (delta ?? 0) >= 0;
  const trendColor = up ? colors.success : colors.error;

  return (
    <div
      className={`rounded-xl p-5 ${className}`}
      style={{ background: colors.surface1, border: `1px solid ${colors.hairline}`, ...style }}
    >
      <div className="flex items-start justify-between gap-3">
        <span className="text-[12px] font-medium uppercase tracking-wide" style={{ color: colors.inkSubtle }}>{label}</span>
        {icon && (
          <span
            className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
            style={{ background: chip + '1f', color: chip }}
          >
            {icon}
          </span>
        )}
      </div>

      <div className="mt-2 flex items-baseline gap-2 flex-wrap">
        <CountUp
          value={value}
          decimals={decimals}
          prefix={prefix}
          suffix={suffix}
          className="text-[26px] font-bold tabular-nums leading-none"
        />
        {delta != null && (
          <span
            className="inline-flex items-center gap-0.5 text-[12px] font-semibold px-1.5 py-0.5 rounded-md"
            style={{ background: trendColor + '18', color: trendColor }}
          >
            {up ? <ArrowUpRight className="w-3.5 h-3.5" /> : <ArrowDownRight className="w-3.5 h-3.5" />}
            {prefix}{Math.abs(delta).toLocaleString(undefined, { maximumFractionDigits: decimals })}{suffix}
          </span>
        )}
      </div>

      {deltaLabel && (
        <div className="mt-1 text-[11px]" style={{ color: colors.inkTertiary }}>{deltaLabel}</div>
      )}

      {donut && donut.length > 0 && (
        <div className="mt-4">
          <MiniDonut items={donut} size={80} />
        </div>
      )}
    </div>
  );
}

export default StatCard;
