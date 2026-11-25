import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:8848', changeOrigin: true } },
  },
  build: {
    outDir: '../web',        // 构建产物直接给 Python 后端托管
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
  },
})
