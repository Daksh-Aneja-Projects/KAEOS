import React from 'react';
import { useTheme } from '../../context/ThemeContext';

interface EmptyStateProps {
  /** Lead icon (an SVG element type, never an emoji). */
  icon: React.ElementType;
  title: string;
  sub: string;
  /** Tighter padding + smaller icon, as Healthcare / Lending / Procurement use. */
  compact?: boolean;
}

/**
 * The one empty-state card the department views share. Every view had grown its
 * own byte-identical copy (Legal, Finance, Sales, Support, ...); encode it once
 * next to StatCard/TableCard so they read as one system and cannot drift.
 */
export function EmptyState({ icon: Icon, title, sub, compact }: EmptyStateProps) {
  const { colors } = useTheme();
  return (
    <div className={`rounded-xl ${compact ? 'p-14' : 'p-16'} text-center`} style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      <Icon className={`${compact ? 'w-11 h-11' : 'w-12 h-12'} mx-auto ${compact ? 'mb-3' : 'mb-4'}`} style={{ color: colors.inkTertiary }} />
      <p className={`${compact ? 'text-[14px]' : 'text-[15px]'} font-medium`} style={{ color: colors.inkSubtle }}>{title}</p>
      <p className="text-[12px] mt-1" style={{ color: colors.inkTertiary }}>{sub}</p>
    </div>
  );
}

export default EmptyState;
