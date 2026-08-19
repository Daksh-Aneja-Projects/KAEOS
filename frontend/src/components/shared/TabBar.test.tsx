import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/react';
import TabBar from './TabBar';
import { Activity, BarChart3 } from 'lucide-react';

const TABS = [
  { key: 'overview' as const, label: 'Overview', icon: Activity },
  { key: 'analytics' as const, label: 'Analytics', icon: BarChart3 },
];

/**
 * TabBar replaced three byte-identical tablists (Healthcare, Procurement,
 * Lending). These assertions pin the markup those views used to emit, so a
 * later tidy-up of the class string is caught as the visual change it is.
 */
describe('TabBar', () => {
  it('emits the tablist markup the department views used to inline', () => {
    const { container } = render(
      <TabBar tabs={TABS} value="overview" onChange={() => {}}
        idPrefix="hc" ariaLabel="Healthcare sections" accent="#14b8a6" />,
    );

    const list = container.querySelector('[role="tablist"]')!;
    expect(list.className).toBe('flex gap-1 p-1 rounded-xl overflow-x-auto');
    expect(list.getAttribute('aria-label')).toBe('Healthcare sections');

    const tabs = Array.from(list.querySelectorAll('[role="tab"]'));
    expect(tabs.map(t => t.id)).toEqual(['hc-tab-overview', 'hc-tab-analytics']);
    expect(tabs[0].className).toBe(
      'flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-medium transition-all whitespace-nowrap',
    );
    // Roving tabIndex: only the selected tab is in the tab order.
    expect(tabs.map(t => t.getAttribute('tabindex'))).toEqual(['0', '-1']);
    expect(tabs.map(t => t.getAttribute('aria-selected'))).toEqual(['true', 'false']);
    expect((tabs[0] as HTMLElement).style.color).toBe('rgb(20, 184, 166)');
  });

  it('wraps around on arrow keys and leaves other keys alone', () => {
    const onChange = vi.fn();
    const { container } = render(
      <TabBar tabs={TABS} value="overview" onChange={onChange}
        idPrefix="lnd" ariaLabel="Lending sections" accent="#d97706" />,
    );
    const [first, second] = Array.from(container.querySelectorAll('[role="tab"]'));

    fireEvent.keyDown(first, { key: 'ArrowRight' });
    expect(onChange).toHaveBeenLastCalledWith('analytics');

    fireEvent.keyDown(first, { key: 'ArrowLeft' }); // index 0 wraps to the last
    expect(onChange).toHaveBeenLastCalledWith('analytics');

    fireEvent.keyDown(second, { key: 'Enter' });
    expect(onChange).toHaveBeenCalledTimes(2);
  });
});
