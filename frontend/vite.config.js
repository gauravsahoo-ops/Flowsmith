import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 500,
    rollupOptions: {
      output: {
        // Rolldown-native chunk groups. The `\0`-prefixed Vite virtual
        // modules (preload helper + modulepreload polyfill) must sit in
        // their own tiny chunk: the entry chunk statically imports the
        // helper for React.lazy() routes, and if it is merged into
        // vendor-monaco the whole 4.3 MB Monaco chunk gets modulepreloaded
        // on first paint. High priority so no vendor group captures them.
        advancedChunks: {
          groups: [
            {
              name: 'vite-runtime',
              test: (id) => id.includes('vite/preload-helper') || id.includes('vite/modulepreload-polyfill'),
              priority: 100,
            },
            {
              name: 'vendor-react',
              test: /node_modules[\\/](react|react-dom|react-router|react-router-dom|zustand)[\\/]/,
              priority: 50,
            },
            {
              name: 'vendor-monaco',
              test: /node_modules[\\/](monaco-editor|@monaco-editor)[\\/]/,
              priority: 40,
            },
            {
              name: 'vendor-flow',
              test: /node_modules[\\/]@xyflow[\\/]/,
              priority: 40,
            },
            {
              // Split remaining third-party deps out of the main chunk
              // to keep the initial bundle lean.
              name: 'vendor-misc',
              test: /node_modules/,
            },
          ],
        },
      },
    },
  },
  test: {
    include: ['src/**/*.{test,spec}.{js,jsx,ts,tsx}'],
    exclude: ['tests/**', 'node_modules/**'],
    environment: 'node',
  },
})
