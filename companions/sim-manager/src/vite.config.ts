import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';
export default defineConfig({
 plugins:[react(),VitePWA({registerType:'prompt',scope:'/sim/',base:'/sim/',includeAssets:['icon-192.png','icon-512.png','notification-worker.js'],manifest:{id:'/sim/',name:'Ziokt SIM Manager',short_name:'SIM Manager',start_url:'/sim/',scope:'/sim/',display:'standalone',theme_color:'#4f46e5',background_color:'#ffffff',icons:[{src:'icon-192.png',sizes:'192x192',type:'image/png',purpose:'any maskable'},{src:'icon-512.png',sizes:'512x512',type:'image/png',purpose:'any maskable'}]},workbox:{importScripts:['notification-worker.js'],globPatterns:['**/*.{js,css,html,png,svg}'],navigateFallback:'/sim/index.html',navigateFallbackDenylist:[/^\/api\//,/^\/uploads\//],runtimeCaching:[]}})],
 base:'/sim/',build:{minify:true,sourcemap:false}
});
