import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ThemeProvider, useTheme } from './ThemeContext';

function Toggler() {
  const { theme, toggle } = useTheme();
  return <button onClick={toggle}>theme:{theme}</button>;
}

const rootVar = (name: string) =>
  document.documentElement.style.getPropertyValue(name);

beforeEach(() => localStorage.clear());

// M7.14: the provider is the runtime source of truth for the theme tokens.
// It must publish them as the CSS custom properties index.css declares in
// @theme, so var(--color-*) rules and Tailwind token utilities follow the
// theme instead of staying pinned to the dark literals.
describe('ThemeProvider CSS custom properties', () => {
  it('writes the dark token values onto documentElement on mount', () => {
    render(<ThemeProvider><Toggler /></ThemeProvider>);
    expect(screen.getByText('theme:dark')).toBeInTheDocument();
    expect(rootVar('--color-canvas')).toBe('#010102');
    expect(rootVar('--color-ink')).toBe('#f7f8f8');
    expect(rootVar('--color-surface-2')).toBe('#141516');
    expect(rootVar('--color-hairline-strong')).toBe('#34343a');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  });

  it('rewrites the vars and data-theme when the theme toggles', () => {
    render(<ThemeProvider><Toggler /></ThemeProvider>);
    fireEvent.click(screen.getByText('theme:dark'));

    expect(screen.getByText('theme:light')).toBeInTheDocument();
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    expect(rootVar('--color-canvas')).toBe('#F8F9FB');
    expect(rootVar('--color-ink')).toBe('#0F172A');
    expect(rootVar('--color-primary-hover')).toBe('#4F5ABF');
    // Shared brand primary is identical in both palettes.
    expect(rootVar('--color-primary')).toBe('#5e6ad2');
    // And back.
    fireEvent.click(screen.getByText('theme:light'));
    expect(rootVar('--color-canvas')).toBe('#010102');
  });
});
