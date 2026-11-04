import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

// The backend's routes. Vite forwards them, so the browser (or the phone via
// the tunnel) only ever talks to one origin. 127.0.0.1, not localhost:
// uvicorn listens on IPv4 only and Node may resolve localhost to IPv6.
const API_ROUTES = ['/auth', '/chat', '/approve', '/threads', '/transcribe']
// ASSIST_API_TARGET points the proxy elsewhere when port 8000 is taken
const API_TARGET = process.env.ASSIST_API_TARGET ?? 'http://127.0.0.1:8000'
const proxy = Object.fromEntries(API_ROUTES.map((route) => [route, API_TARGET]))

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'favicon.ico', 'apple-touch-icon-180x180.png'],
      manifest: {
        name: 'Assist',
        short_name: 'Assist',
        description: 'A voice assistant for your notes, calendar and email.',
        display: 'standalone',
        start_url: '/',
        theme_color: '#FAFAF8',
        background_color: '#FAFAF8',
        icons: [
          { src: 'pwa-64x64.png', sizes: '64x64', type: 'image/png' },
          { src: 'pwa-192x192.png', sizes: '192x192', type: 'image/png' },
          { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png' },
          { src: 'maskable-icon-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        // App shell only: the built files. No runtimeCaching, so API calls
        // always go to the network and are never stored.
        globPatterns: ['**/*.{js,css,html,svg,png,ico}'],
        navigateFallback: 'index.html',
        navigateFallbackDenylist: API_ROUTES.map((route) => new RegExp(`^${route}`)),
      },
      // The tunnel serves the dev server, so the phone needs the worker there too
      devOptions: { enabled: true },
    }),
  ],
  server: {
    proxy,
    // Quick tunnels get a random *.trycloudflare.com name
    allowedHosts: ['.trycloudflare.com'],
  },
  preview: { proxy },
})
