import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

import { styleBaselinePlugin } from './scripts/style-baseline-plugin.ts'

const proxyTarget = process.env.VITE_API_PROXY_TARGET
const frontendRoot = fileURLToPath(new URL('.', import.meta.url))

export default defineConfig({
  base: '/admin/',
  plugins: [styleBaselinePlugin(frontendRoot), vue()],
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
            '/api': proxyTarget,
            '/v1': proxyTarget,
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
