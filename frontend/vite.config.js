import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': 'https://trace-backend-177290233934.us-central1.run.app' },
  },
})
