import {defineConfig} from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: '/',
  plugins: [react()],
  build: {outDir: '../app/static', emptyOutDir: true},
  server: {proxy: {'/api': 'http://127.0.0.1:8000', '/auth': 'http://127.0.0.1:8000'}}
})
