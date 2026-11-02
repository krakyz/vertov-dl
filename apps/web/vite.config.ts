import { defineConfig } from 'vite';

const target = process.env.MEDIA_API_TARGET || 'http://127.0.0.1:47831';
const proxy = {
  '/api': { target, changeOrigin: false },
  '/healthz': { target, changeOrigin: false },
};

export default defineConfig({
  server: {
    host: '127.0.0.1', port: 5173, strictPort: true, proxy,
  },
  preview: { host: '127.0.0.1', port: 5173, strictPort: true, proxy },
});
