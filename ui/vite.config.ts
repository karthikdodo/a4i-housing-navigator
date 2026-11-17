import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';

// `npm run dev` serves the UI on :5173 and forwards API + WebSocket calls to the FastAPI
// server on :8080 (uvicorn api.main:app --port 8080). In production the API serves ui/dist.
const API = process.env.A4I_API_URL ?? 'http://127.0.0.1:8080';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': API,
      '/health': API,
      '/ws': {target: API.replace(/^http/, 'ws'), ws: true},
    },
  },
  build: {chunkSizeWarningLimit: 1500},
});
