import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    rollupOptions: {
      output: {
        // Stable vendor groups get their own long-lived chunks so an app
        // deploy does not invalidate 200 kB of unchanged framework code.
        // Keep react/react-dom/react-router in ONE chunk: they share module
        // state (the React dispatcher, the router context) and must never be
        // duplicated across chunks.
        manualChunks(id: string) {
          if (/\/node_modules\/(react|react-dom|react-router|scheduler)\//.test(id)) return 'react';
        },
      },
    },
  },
  server: {
    port: 5174,
    strictPort: true,
    host: true,
  }
})
