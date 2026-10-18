#!/usr/bin/env node
// ==============================================================================
// Ziokt Unified GUI Client - Assets Packaging & Validation Script
// ==============================================================================

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const SRC_DIR = path.join(__dirname, 'src');
const DIST_DIR = path.join(__dirname, 'dist');

console.log('>> [Ziokt GUI] Starting client packaging build...');

// 1. Ensure dist directory
if (fs.existsSync(DIST_DIR)) {
  fs.rmSync(DIST_DIR, { recursive: true, force: true });
}
fs.mkdirSync(DIST_DIR, { recursive: true });

// 2. Validate JSON files
const jsonFiles = [
  path.join(SRC_DIR, 'i18n', 'zh.json'),
  path.join(SRC_DIR, 'i18n', 'en.json'),
  path.join(SRC_DIR, 'i18n', 'zh-CN.json'),
  path.join(SRC_DIR, 'i18n', 'en-US.json'),
  path.join(__dirname, 'package.json')
];

for (const jf of jsonFiles) {
  if (!fs.existsSync(jf)) continue;
  try {
    const content = fs.readFileSync(jf, 'utf8');
    JSON.parse(content);
    console.log(`  ✓ Validated JSON: ${path.relative(__dirname, jf)}`);
  } catch (err) {
    console.error(`  ✕ Invalid JSON in ${jf}:`, err.message);
    process.exit(1);
  }
}

// 3. Copy directory recursively
function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  const entries = fs.readdirSync(src, { withFileTypes: true });
  for (const entry of entries) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copyDir(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

copyDir(SRC_DIR, DIST_DIR);

// Copy downloads if available
const DOWNLOADS_DIR = path.join(__dirname, 'downloads');
if (fs.existsSync(DOWNLOADS_DIR)) {
  copyDir(DOWNLOADS_DIR, path.join(DIST_DIR, 'downloads'));
}

// Sync into Android assets directory (exclude downloads)
const ANDROID_ASSETS_DIR = path.join(__dirname, 'android', 'app', 'src', 'main', 'assets');
if (fs.existsSync(path.dirname(ANDROID_ASSETS_DIR))) {
  if (fs.existsSync(ANDROID_ASSETS_DIR)) {
    fs.rmSync(ANDROID_ASSETS_DIR, { recursive: true, force: true });
  }
  copyDir(SRC_DIR, ANDROID_ASSETS_DIR);
}

const distFiles = fs.readdirSync(DIST_DIR, { recursive: true });
console.log(`>> [Ziokt GUI] Build complete! ${distFiles.length} files staged into dist/`);

// 4. Also stage into gateway/gui for direct Web Console / Gateway integration
const GATEWAY_GUI_DIR = path.join(__dirname, '..', 'gateway', 'gui');
if (fs.existsSync(GATEWAY_GUI_DIR)) {
  fs.rmSync(GATEWAY_GUI_DIR, { recursive: true, force: true });
}
copyDir(DIST_DIR, GATEWAY_GUI_DIR);
console.log(`>> [Ziokt GUI] Assets synced into gateway/gui/ for /gateway-assets/gui/ serving.`);


