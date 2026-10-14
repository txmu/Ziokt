import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: '/gp-simanager/', 
  build: {
    minify: false // Termux 环境下依然建议关闭混淆，加快速度
  }
});
