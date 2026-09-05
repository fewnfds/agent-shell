import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

const proxyTarget = process.env.VITE_API_PROXY_TARGET

export default defineConfig({
  base: '/admin/',
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    outDir: '../runtime/frontend_dist',
    emptyOutDir: true,
  },
  server: {
    host: '127.0.0.1',
    strictPort: true,
    ...(proxyTarget
      ? {
          proxy: {
            '/agent-shell': proxyTarget,
            '/compat': proxyTarget,
            '/assistants': proxyTarget,
            '/threads': proxyTarget,
            '/runs': proxyTarget,
            '/store': proxyTarget,
            '/mcp': proxyTarget,
            '/a2a': proxyTarget,
            '/ok': proxyTarget,
            '/info': proxyTarget,
            '/metrics': proxyTarget,
            '/docs': proxyTarget,
            '/openapi.json': proxyTarget,
          },
        }
      : {}),
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
    setupFiles: ['./src/test/setup.ts'],
    testTimeout: 10_000,
  },
})
