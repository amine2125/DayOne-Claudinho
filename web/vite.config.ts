import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      // Single source of truth: the registry templates used by the Python pipeline.
      '@schema': path.resolve(__dirname, '../schema'),
    },
  },
  publicDir: path.resolve(__dirname, 'public'),
  server: { fs: { allow: ['..'] } },
})
