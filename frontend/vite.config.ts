import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@vue/devtools-api': fileURLToPath(new URL('./src/shims/devtools-api.ts', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8012', changeOrigin: true },
    },
    headers: {
      'Content-Type': 'text/html; charset=utf-8',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
