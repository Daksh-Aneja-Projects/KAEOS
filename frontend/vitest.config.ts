import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Test harness for the frontend (previously there were zero tests).
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
});
