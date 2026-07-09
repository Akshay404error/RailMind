import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Proxies /api/* to the FastAPI backend during development, so the
// dashboard can call same-origin '/api/...' paths without needing CORS
// configured on the backend. Adjust the target if uvicorn is running on
// a different port.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
