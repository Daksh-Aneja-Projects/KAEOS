import React from 'react';
import { useTheme } from '../context/ThemeContext';

/**
 * ThemeAdapter wraps legacy page components (which use hardcoded light-mode
 * Tailwind classes like bg-white, text-gray-900, border-gray-100) and injects
 * CSS overrides so they render correctly in dark mode.
 */
export default function ThemeAdapter({ children }: { children: React.ReactNode }) {
  const { theme, colors } = useTheme();

  if (theme === 'light') {
    return <>{children}</>;
  }

  // Dark mode - override Tailwind light-mode colors via scoped CSS
  return (
    <div className="theme-adapter dark-mode h-full">
      <style>{`
        .dark-mode { color: ${colors.ink}; }
        /* Backgrounds */
        .dark-mode .bg-white { background: ${colors.surface1} !important; }
        .dark-mode .bg-gray-50,
        .dark-mode .bg-gray-100 { background: ${colors.surface2} !important; }
        .dark-mode .bg-gray-50\\/50 { background: ${colors.surface2} !important; }
        .dark-mode .bg-gray-900,
        .dark-mode .bg-gray-800 { background: ${colors.surface3} !important; color: ${colors.ink} !important; }
        .dark-mode .bg-\\[\\#FAFAFA\\] { background: ${colors.surface1} !important; } /* Topology canvas */
        
        /* Text */
        .dark-mode .text-gray-900,
        .dark-mode .text-gray-800,
        .dark-mode .text-\\[\\#1d1d1f\\],
        .dark-mode .text-gray-700 { color: ${colors.ink} !important; }
        .dark-mode .text-gray-600,
        .dark-mode .text-gray-500 { color: ${colors.inkMuted} !important; }
        .dark-mode .text-gray-400 { color: ${colors.inkSubtle} !important; }
        .dark-mode .text-gray-300 { color: ${colors.inkTertiary} !important; }
        
        /* Borders */
        .dark-mode .border-gray-100 { border-color: ${colors.hairline} !important; }
        .dark-mode .border-gray-200,
        .dark-mode .border-\\[\\#E5E5EA\\] { border-color: ${colors.hairlineStrong} !important; }
        .dark-mode .divide-gray-100 > * + * { border-color: ${colors.hairline} !important; }
        .dark-mode .border-b { border-color: ${colors.hairline}; }
        
        /* Inputs */
        .dark-mode input,
        .dark-mode textarea,
        .dark-mode select {
          background: ${colors.surface2} !important;
          border-color: ${colors.hairlineStrong} !important;
          color: ${colors.ink} !important;
        }
        .dark-mode input::placeholder,
        .dark-mode textarea::placeholder { color: ${colors.inkSubtle} !important; }
        
        /* Table headers */
        .dark-mode thead tr { background: ${colors.surface2} !important; }
        .dark-mode th { color: ${colors.inkMuted} !important; }
        
        /* Hover states */
        .dark-mode .hover\\:bg-gray-50\\/50:hover,
        .dark-mode .hover\\:bg-gray-200:hover,
        .dark-mode .hover\\:bg-gray-50:hover { background: ${colors.surface3} !important; }
        
        /* Card shadows */
        .dark-mode .premium-shadow { box-shadow: 0 1px 3px rgba(0,0,0,0.4), 0 0 0 1px ${colors.hairline} !important; }
        
        /* SVG text & lines in Topology */
        .dark-mode svg text[fill="#1d1d1f"] { fill: ${colors.ink} !important; }
        .dark-mode svg text[fill="#9CA3AF"] { fill: ${colors.inkSubtle} !important; }
        .dark-mode svg text[fill="#4338CA"] { fill: #828fff !important; } /* primary hover */
        .dark-mode svg text[fill="#059669"] { fill: #4ade80 !important; } /* success */
        .dark-mode svg text[fill="#4b5563"] { fill: ${colors.inkMuted} !important; }
        .dark-mode svg line[stroke="#E5E5EA"] { stroke: ${colors.hairlineStrong} !important; }
        .dark-mode svg polygon[fill="#D1D5DB"] { fill: ${colors.hairlineStrong} !important; }
        
        /* Colored badge backgrounds - soften in dark mode */
        .dark-mode .bg-emerald-50 { background: rgba(5,150,105,0.1) !important; }
        .dark-mode .bg-emerald-100 { background: rgba(5,150,105,0.15) !important; }
        .dark-mode .bg-blue-50 { background: rgba(37,99,235,0.12) !important; }
        .dark-mode .bg-blue-100 { background: rgba(37,99,235,0.15) !important; }
        .dark-mode .bg-amber-50 { background: rgba(217,119,6,0.1) !important; }
        .dark-mode .bg-amber-100 { background: rgba(217,119,6,0.15) !important; }
        .dark-mode .bg-red-50 { background: rgba(225,29,72,0.1) !important; border-color: rgba(225,29,72,0.2) !important; }
        .dark-mode .bg-red-100 { background: rgba(225,29,72,0.15) !important; }
        .dark-mode .bg-indigo-50 { background: rgba(67,56,202,0.1) !important; }
        .dark-mode .bg-indigo-100 { background: rgba(67,56,202,0.15) !important; }
        .dark-mode .bg-purple-50 { background: rgba(124,58,237,0.1) !important; }
        .dark-mode .bg-purple-100 { background: rgba(124,58,237,0.15) !important; }
        
        /* Filter pills */
        .dark-mode .bg-gray-100.text-gray-600 { background: ${colors.surface2} !important; color: ${colors.inkMuted} !important; }
        .dark-mode .hover\\:bg-gray-200.text-gray-600:hover { background: ${colors.surface3} !important; }
        
        /* Ring focus */
        .dark-mode .focus\\:ring-indigo-500:focus,
        .dark-mode .focus\\:ring-purple-500:focus { --tw-ring-color: ${colors.primary}; }
        .dark-mode .focus\\:ring-amber-500:focus { --tw-ring-color: ${colors.warning}; }
      `}</style>
      {children}
    </div>
  );
}
