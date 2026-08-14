import React from 'react';
import { useTheme } from '../../context/ThemeContext';

interface TableCardProps {
  /** Intrinsic width of the table content; below this the card scrolls horizontally instead of clipping. */
  minWidth?: number;
  className?: string;
  style?: React.CSSProperties;
  children: React.ReactNode;
}

/**
 * The one place the "wide table that scrolls instead of clipping" pattern lives.
 *
 * Every dense grid in KAEOS re-invented the same three-layer sandwich
 * (rounded-xl overflow-hidden > overflow-x-auto > min-w-[...]); see
 * ProvenanceLedger.tsx. Diverging copies drift: one forgets overflow-hidden and
 * the rounded corners bleed, another drops the min-width and the columns crush.
 * Encode it once. The outer surface clips to the radius, the middle layer owns
 * the horizontal scroll, and the inner layer holds the content at its natural
 * width so narrow viewports scroll rather than cut columns off.
 */
export function TableCard({ minWidth = 720, className = '', style, children }: TableCardProps) {
  const { colors } = useTheme();
  return (
    <div
      className={`rounded-xl overflow-hidden ${className}`}
      style={{ background: colors.surface1, border: `1px solid ${colors.hairline}`, ...style }}
    >
      <div className="overflow-x-auto">
        <div style={{ minWidth }}>{children}</div>
      </div>
    </div>
  );
}

export default TableCard;
