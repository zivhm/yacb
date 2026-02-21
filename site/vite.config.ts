import { defineConfig } from 'vite'
import path from 'path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@root-assets': path.resolve(__dirname, '../assets'),
    },
  },
  server: {
    fs: {
      allow: ['..'],
    },
  },
})
