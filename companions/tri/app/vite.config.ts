import path from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

export default defineConfig({
  base: '/tri/',
  server: { host: '127.0.0.1', port: 3000 },
  plugins: [react(), VitePWA({
    registerType: 'autoUpdate',
    includeAssets: ['icon.svg'],
    manifest: {
      name: 'Ziokt Tri Computer', short_name: 'Tri', start_url: '/tri/', scope: '/tri/', display: 'standalone',
      background_color: '#111827', theme_color: '#0891b2', icons: [{ src: 'icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any maskable' }]
    },
    workbox: { globPatterns: ['**/*.{js,css,html,svg,png,woff2}'], navigateFallback: '/tri/index.html', maximumFileSizeToCacheInBytes: 4 * 1024 * 1024 }
  })],
  resolve: { alias: { '@': path.resolve(__dirname, '.') } }
});
