import React, { createContext, useContext, useState, useEffect } from 'react';

type Theme = 'dark' | 'light';

interface ThemeContextType {
  theme: Theme;
  toggle: () => void;
  colors: typeof darkColors;
}

const darkColors = {
  canvas: '#010102',
  sidebar: '#0a0a0b',
  surface1: '#0f1011',
  surface2: '#141516',
  surface3: '#18191a',
  hairline: '#23252a',
  hairlineStrong: '#34343a',
  primary: '#5e6ad2',
  primaryHover: '#828fff',
  ink: '#f7f8f8',
  inkMuted: '#d0d6e0',
  inkSubtle: '#8a8f98',
  inkTertiary: '#62666d',
  success: '#27a644',
  warning: '#f5a623',
  error: '#e5534b',
  info: '#539bf5',
  cardBg: '#0f1011',
  navActive: 'rgba(94,106,210,0.12)',
  navActiveText: '#828fff',
  inputBg: '#141516',
};

const lightColors = {
  canvas: '#F8F9FB',
  sidebar: '#F0F1F4',
  surface1: '#FFFFFF',
  surface2: '#F5F6F8',
  surface3: '#EDEEF1',
  hairline: '#D8DAE0',
  hairlineStrong: '#C4C7CE',
  primary: '#5e6ad2',
  primaryHover: '#4F5ABF',
  ink: '#0F172A',
  inkMuted: '#1E293B',
  inkSubtle: '#475569',
  inkTertiary: '#64748B',
  success: '#15803d',
  warning: '#b45309',
  error: '#dc2626',
  info: '#2563eb',
  cardBg: '#FFFFFF',
  navActive: 'rgba(94,106,210,0.10)',
  navActiveText: '#4F5ABF',
  inputBg: '#EFF0F3',
};

// M7.14: the theme tokens that ALSO exist as CSS custom properties in
// index.css's @theme block. Those literals are the static dark defaults
// (Tailwind needs literal values at build time, and they style the first
// paint before React mounts); the provider writes the live values over them
// on documentElement, so every var(--color-*) rule and Tailwind token
// utility (bg-canvas, text-ink, hover:bg-surface2...) follows the JS theme.
// One runtime source of truth: this file. JS-only tokens (sidebar, cardBg,
// navActive, navActiveText, inputBg) have no CSS counterpart and stay JS;
// CSS-only vars (--color-surface-4, --color-hairline-tertiary,
// --color-primary-focus, spacing, fonts) stay CSS.
const CSS_TOKEN_VARS: [keyof typeof darkColors, string][] = [
  ['canvas', '--color-canvas'],
  ['surface1', '--color-surface-1'],
  ['surface2', '--color-surface-2'],
  ['surface3', '--color-surface-3'],
  ['hairline', '--color-hairline'],
  ['hairlineStrong', '--color-hairline-strong'],
  ['primary', '--color-primary'],
  ['primaryHover', '--color-primary-hover'],
  ['ink', '--color-ink'],
  ['inkMuted', '--color-ink-muted'],
  ['inkSubtle', '--color-ink-subtle'],
  ['inkTertiary', '--color-ink-tertiary'],
  ['success', '--color-success'],
  ['warning', '--color-warning'],
  ['error', '--color-error'],
  ['info', '--color-info'],
];

const ThemeContext = createContext<ThemeContextType>({
  theme: 'dark',
  toggle: () => {},
  colors: darkColors,
});

export const useTheme = () => useContext(ThemeContext);

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = localStorage.getItem('kaeos-theme');
    return (saved as Theme) || 'dark';
  });

  const toggle = () => {
    setTheme(prev => {
      const next = prev === 'dark' ? 'light' : 'dark';
      localStorage.setItem('kaeos-theme', next);
      return next;
    });
  };

  const colors = theme === 'dark' ? darkColors : lightColors;

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    // Publish the live token values as CSS custom properties (M7.14): inline
    // styles on the root outrank the @theme defaults in index.css, so CSS
    // and Tailwind utilities switch with the theme instead of staying dark.
    for (const [key, cssVar] of CSS_TOKEN_VARS) {
      document.documentElement.style.setProperty(cssVar, colors[key]);
    }
    document.body.style.backgroundColor = colors.canvas;
    document.body.style.color = colors.ink;
  }, [theme, colors]);

  return (
    <ThemeContext.Provider value={{ theme, toggle, colors }}>
      {children}
    </ThemeContext.Provider>
  );
};
