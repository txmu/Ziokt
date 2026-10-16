import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';
const base=process.env.SIM_BASE_PATH||'/sim/';
if(!/^\/(?:[a-zA-Z0-9_-]+\/)*$/.test(base))throw Error('INVALID_SIM_BASE_PATH');
export default defineConfig({
 plugins:[react(),VitePWA({registerType:'prompt',scope:base,base,includeAssets:['icon-192.png','icon-512.png','notification-worker.js'],manifest:{id:base,name:'Ziokt SIM Manager',short_name:'SIM Manager',start_url:base,scope:base,display:'standalone',theme_color:'#4f46e5',background_color:'#ffffff',icons:[{src:'icon-192.png',sizes:'192x192',type:'image/png',purpose:'any maskable'},{src:'icon-512.png',sizes:'512x512',type:'image/png',purpose:'any maskable'}]},workbox:{importScripts:['notification-worker.js'],globPatterns:['**/*.{js,css,html,png,svg}'],navigateFallback:base+'index.html',navigateFallbackDenylist:[/^\/api\//,/^\/uploads\//],runtimeCaching:[]}})],
 base,build:{minify:true,sourcemap:false}
});
