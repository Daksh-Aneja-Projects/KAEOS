import React from 'react';
import { useTheme } from '../../context/ThemeContext';

export interface TabSpec<T extends string> {
  key: T;
  label: string;
  icon: React.ElementType;
}

interface TabBarProps<T extends string> {
  tabs: TabSpec<T>[];
  value: T;
  onChange: (key: T) => void;
  /** Prefix for each tab's DOM id, e.g. "hc" gives `hc-tab-overview`. */
  idPrefix: string;
  /** Accessible name for the tablist, e.g. "Healthcare sections". */
  ariaLabel: string;
  /** Text color of the selected tab. */
  accent: string;
}

/**
 * The pill tablist shared verbatim by the Healthcare, Procurement and Lending
 * views, including the roving-tabIndex arrow-key behaviour a tablist owes its
 * keyboard users.
 *
 * Scope note: only those three. The other seven department views look similar
 * but are NOT the same markup - Engineering drops the icon and uses a different
 * pill size, Workforce paints the selected tab with `colors.primary`, Support
 * wraps instead of scrolling and handles keys on the container, Operations adds
 * `aria-controls`, Finance/Sales add `shrink-0` and color each tab
 * individually. Widening this component to cover them would mean a prop per
 * difference, which is worse than the duplication it removes.
 */
export function TabBar<T extends string>({
  tabs, value, onChange, idPrefix, ariaLabel, accent,
}: TabBarProps<T>) {
  const { colors } = useTheme();

  const moveTab = (e: React.KeyboardEvent, i: number) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const next = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
    onChange(next.key);
    document.getElementById(`${idPrefix}-tab-${next.key}`)?.focus();
  };

  return (
    <div className="flex gap-1 p-1 rounded-xl overflow-x-auto" role="tablist" aria-label={ariaLabel}
      style={{ background: colors.surface1 }}>
      {tabs.map((t, i) => (
        <button key={t.key} id={`${idPrefix}-tab-${t.key}`} role="tab" aria-selected={value === t.key}
          tabIndex={value === t.key ? 0 : -1} onClick={() => onChange(t.key)} onKeyDown={e => moveTab(e, i)}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-medium transition-all whitespace-nowrap"
          style={{
            background: value === t.key ? colors.canvas : 'transparent',
            color: value === t.key ? accent : colors.inkSubtle,
            boxShadow: value === t.key ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
          }}>
          <t.icon className="w-3.5 h-3.5" />
          {t.label}
        </button>
      ))}
    </div>
  );
}

export default TabBar;
