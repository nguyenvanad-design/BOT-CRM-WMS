import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import fs from 'fs'

/**
 * Đọc X-API-Key của chatbot từ chatbot/.env (chỉ dùng cho dev proxy) để proxy
 * chèn header phía server — key KHÔNG đi vào bundle trình duyệt.
 */
function chatbotKey(): string {
  try {
    const env = fs.readFileSync(path.resolve(__dirname, '../chatbot/.env'), 'utf-8')
    const m = env.match(/^TOKINARC_API_KEY=(.*)$/m)
    return m ? m[1].trim() : ''
  } catch {
    return ''
  }
}
const CHATBOT_KEY = chatbotKey()
const CHATBOT_TARGET = process.env.VITE_CHATBOT_TARGET || 'http://localhost:8080'

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  build: {
    rollupOptions: {
      output: {
        // Tách vendor lớn ra chunk riêng → giảm bundle chính, cache tốt hơn.
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          charts: ['recharts'],
          query: ['@tanstack/react-query'],
          scan: ['@zxing/library'],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Dev: proxy API sang Django, tránh CORS lúc phát triển.
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      // Dev: proxy /chatbot → chatbot FastAPI, tự chèn X-API-Key.
      '/chatbot': {
        target: CHATBOT_TARGET,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/chatbot/, ''),
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq) => {
            if (CHATBOT_KEY) proxyReq.setHeader('X-API-Key', CHATBOT_KEY)
          })
        },
      },
    },
  },
})
