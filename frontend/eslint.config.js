import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
  },
  {
    files: ['**/*.{ts,tsx}'],
    rules: {
      '@typescript-eslint/no-explicit-any': 'warn',

      // ── At error: clean today, keep them that way ──────────────────────
      // rules-of-hooks caught a real shipped bug (Sparkline useState after
      // an early return); it must never be turned off again.
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/static-components': 'error',
      '@typescript-eslint/no-unused-expressions': 'error',
      'no-empty': 'error',

      // ── At warn: real signal, but fixing every hit is repo-wide churn ──
      // (counts at time of re-enable; ratchet to error as they hit zero)
      // ~130 hits, almost all dead lucide-react imports. Underscore-prefix
      // names to mark intentionally-unused values.
      '@typescript-eslint/no-unused-vars': ['warn', {
        argsIgnorePattern: '^_',
        varsIgnorePattern: '^_',
        caughtErrorsIgnorePattern: '^_',
      }],
      // 58 hits: mostly load-on-mount effects calling state setters.
      'react-hooks/set-state-in-effect': 'warn',
      // 17 hits: ref.current read during render in several views.
      'react-hooks/refs': 'warn',
      // 5 hits: the intentional force-sim pattern (TwinGraph, Topology,
      // useWebSocket) mutates sim state from handlers and rAF loops.
      'react-hooks/immutability': 'warn',
      // 6 hits: the deliberate live-clock idiom (Date.now() for "Xs ago"
      // labels and uptime meters, re-rendered by tick state).
      'react-hooks/purity': 'warn',
      // 21 hits: mixed component/helper exports; HMR-quality only.
      'react-refresh/only-export-components': 'warn',
    }
  }
])
