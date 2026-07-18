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
  success: '#16a34a',
  warning: '#d97706',
  error: '#dc2626',
  info: '#2563eb',
  cardBg: '#FFFFFF',
  navActive: 'rgba(94,106,210,0.10)',
  navActiveText: '#4F5ABF',
  inputBg: '#EFF0F3',
};

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
    document.body.style.backgroundColor = colors.canvas;
    document.body.style.color = colors.ink;
  }, [theme, colors]);

  return (
    <ThemeContext.Provider value={{ theme, toggle, colors }}>
      {children}
    </ThemeContext.Provider>
  );
};
