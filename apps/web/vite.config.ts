import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const coreTarget = process.env.VITE_PROXY_TARGET ?? 'http://127.0.0.1:8080';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: coreTarget, changeOrigin: true },
      '/ws': { target: coreTarget.replace(/^http/, 'ws'), ws: true },
    },
  },
});
