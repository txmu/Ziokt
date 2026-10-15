'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(path.resolve(__dirname, fs.existsSync(path.resolve(__dirname, '../ci/browser/node_modules/playwright'))
  ? '../ci/browser/node_modules/playwright' : '../.runtime/browser/node_modules/playwright'));
const { spawn } = require('node:child_process');

(async () => {
  const app = path.resolve(__dirname, '../companions/tri/app');
  const server = spawn(process.execPath, [path.join(app, 'node_modules/vite/bin/vite.js'), 'preview', '--host', '127.0.0.1', '--strictPort', '--port', '4173'], { cwd: app, stdio: ['ignore', 'pipe', 'pipe'] });
  let output = '';
  server.stdout.on('data', chunk => output += chunk);
  server.stderr.on('data', chunk => output += chunk);
  let browser;
  try {
    for (let i = 0; i < 100 && !output.includes('4173'); i++) await new Promise(resolve => setTimeout(resolve, 100));
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext();
    const external = [];
    context.on('request', request => { if (!request.url().startsWith('http://127.0.0.1:4173/')) external.push(request.url()); });
    const page = await context.newPage();
    await page.goto('http://127.0.0.1:4173/tri/', { waitUntil: 'networkidle', timeout: 30000 });
    await page.getByText('Ternary Computer Simulator', { exact: true }).waitFor({ timeout: 15000 });
    if (external.length) throw new Error('Tri app attempted an external network request');
    const manifest = await page.evaluate(async () => {
      const response = await fetch('/tri/manifest.webmanifest');
      return response.json();
    });
    if (manifest.display !== 'standalone' || manifest.scope !== '/tri/') throw new Error('Tri install manifest is incomplete');
    await page.evaluate(async () => { await navigator.serviceWorker.ready; });
    await context.setOffline(true);
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.getByText('Ternary Computer Simulator', { exact: true }).waitFor({ timeout: 10000 });
    console.log('Tri PWA online, manifest, offline shell and no-external-request checks passed');
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
