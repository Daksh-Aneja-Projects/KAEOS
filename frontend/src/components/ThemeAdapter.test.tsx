import { describe, it, expect } from 'vitest';
import { useState } from 'react';
import { render, fireEvent } from '@testing-library/react';
import ThemeAdapter from './ThemeAdapter';
import { ThemeProvider, useTheme } from '../context/ThemeContext';

/** A child with local state plus the theme toggle, mounted inside ThemeAdapter. */
function Probe() {
  const [count, setCount] = useState(0);
  const { theme, toggle } = useTheme();
  return (
    <div>
      <button onClick={() => setCount(c => c + 1)}>inc</button>
      <button onClick={toggle}>toggle</button>
      <span data-testid="count">{count}</span>
      <span data-testid="theme">{theme}</span>
    </div>
  );
}

/**
 * ThemeAdapter used to return a Fragment in light mode and a div in dark
 * mode, so a theme toggle changed the root element type and React remounted
 * the whole page (all state lost, all effects re-run). These tests pin the
 * fix: one div in both modes, child state survives a toggle.
 */
describe('ThemeAdapter', () => {
  it('keeps child state across a theme toggle (no remount)', () => {
    window.localStorage.removeItem('kaeos-theme');
    const { getByText, getByTestId, container } = render(
      <ThemeProvider>
        <ThemeAdapter>
          <Probe />
        </ThemeAdapter>
      </ThemeProvider>,
    );

    expect(getByTestId('theme').textContent).toBe('dark');
    fireEvent.click(getByText('inc'));
    fireEvent.click(getByText('inc'));
    expect(getByTestId('count').textContent).toBe('2');
    const rootBefore = container.firstElementChild!;
    expect(rootBefore.tagName).toBe('DIV');

    fireEvent.click(getByText('toggle'));

    expect(getByTestId('theme').textContent).toBe('light');
    // Same root element type, and the child kept its state.
    expect(container.firstElementChild!.tagName).toBe('DIV');
    expect(getByTestId('count').textContent).toBe('2');

    fireEvent.click(getByText('toggle')); // and back to dark
    expect(getByTestId('theme').textContent).toBe('dark');
    expect(getByTestId('count').textContent).toBe('2');
  });

  it('is layout-neutral in light mode and scoped in dark mode', () => {
    window.localStorage.setItem('kaeos-theme', 'light');
    const { getByText, container } = render(
      <ThemeProvider>
        <ThemeAdapter>
          <Probe />
        </ThemeAdapter>
      </ThemeProvider>,
    );

    const root = container.firstElementChild as HTMLElement;
    expect(root.tagName).toBe('DIV');
    // Light mode: no dark-mode class (CSS inert) and no generated box.
    expect(root.classList.contains('dark-mode')).toBe(false);
    expect(root.style.display).toBe('contents');

    fireEvent.click(getByText('toggle'));
    expect(root.classList.contains('dark-mode')).toBe(true);
    expect(root.style.display).toBe('');
    window.localStorage.removeItem('kaeos-theme');
  });
});
