import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Vite config for the ShopMind dashboard.
// The dev server proxies backend routes so the frontend can call
// same-origin paths if desired; the API client currently uses the
// absolute backend URL (http://localhost:8000).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/webhooks': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
});
