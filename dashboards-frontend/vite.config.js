import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 4099,
    // Forward /api/* to the FastAPI backend during dev so the frontend
    // and API appear same-origin.
    proxy: {
      '/api': 'http://localhost:4100',
    },
  },
});
