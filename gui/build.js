#!/usr/bin/env node
// ==============================================================================
// Ziokt Unified GUI Client - Assets Packaging, Bundler & Validation Script
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
  path.join(SRC_DIR, 'manifest.json'),
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

// 3. Build standalone universal app.js bundle (No CORS, No ES module restrictions on file://)
function buildStandaloneAppBundle() {
  const order = [
    'core.js',
    'modules/home.js',
    'modules/chat.js',
    'modules/forum.js',
    'modules/files.js',
    'modules/apps.js',
    'modules/network.js',
    'modules/identity.js',
    'modules/devtools.js',
    'modules/settings.js'
  ];

  let bundle = '// ==============================================================================\n';
  bundle += '// Ziokt Unified Graphical Client - Standalone Universal Application Bundle\n';
  bundle += '// ==============================================================================\n\n';
  bundle += '(function() {\n  "use strict";\n\n';

  for (const rel of order) {
    let content = fs.readFileSync(path.join(SRC_DIR, rel), 'utf8');
    content = content.replace(/^\s*import\s+.*?;?\s*$/gm, '');
    content = content.replace(/^\s*export\s+(default\s+)?(async\s+)?(function|const|let|var)\s+/gm, '$2$3 ');
    content = content.replace(/^\s*export\s*\{[^}]*\};?\s*$/gm, '');
    bundle += `  // --- Module: ${rel} ---\n` + content + `\n\n`;
  }

  const controllerCode = `
  // --- Router & App Controller ---
  const routes = {
    home: { render: renderHome, titleKey: 'nav.home' },
    chat: { render: renderChat, titleKey: 'nav.chat' },
    forum: { render: renderForum, titleKey: 'nav.forum' },
    files: { render: renderFiles, titleKey: 'nav.files' },
    apps: { render: renderApps, titleKey: 'nav.apps' },
    network: { render: renderNetwork, titleKey: 'nav.network' },
    identity: { render: renderIdentity, titleKey: 'nav.identity' },
    devtools: { render: renderDevtools, titleKey: 'nav.devtools' },
    settings: { render: renderSettings, titleKey: 'nav.settings' }
  };

  function getHashTab() {
    const hash = (window.location.hash || '').replace('#', '').trim().toLowerCase();
    return routes[hash] ? hash : null;
  }

  async function initApp() {
    await initI18n();
    setTheme(State.theme);
    setupNavigation();
    setupKeyboardShortcuts();
    setupPwaInstallPrompt();

    const initialTab = getHashTab() || State.currentTab || 'home';
    navigate(initialTab);

    window.addEventListener('hashchange', () => {
      const tab = getHashTab();
      if (tab && tab !== State.currentTab) {
        navigate(tab);
      }
    });

    Events.on('navigate', (tab) => navigate(tab));
    Events.on('language_changed', () => {
      updateNavLabels();
      navigate(State.currentTab);
    });
    Events.on('theme_changed', () => {
      navigate(State.currentTab);
    });

    console.log('[Ziokt GUI] Universal Client Initialized.');
  }

  function navigate(tabName) {
    if (!routes[tabName]) tabName = 'home';
    State.currentTab = tabName;
    if (window.location.hash !== '#' + tabName) {
      history.replaceState(null, '', '#' + tabName);
    }

    const route = routes[tabName];
    const titleEl = document.getElementById('current-page-title');
    if (titleEl) titleEl.textContent = t(route.titleKey);
    document.title = t(route.titleKey) + ' - ' + t('app.title');

    document.querySelectorAll('.nav-item').forEach(item => {
      item.classList.toggle('active', item.dataset.tab === tabName);
    });
    document.querySelectorAll('.bottom-item').forEach(item => {
      item.classList.toggle('active', item.dataset.tab === tabName);
    });

    const container = document.getElementById('content-container');
    if (container) {
      container.innerHTML = '';
      try {
        route.render(container);
      } catch (err) {
        console.error('[Router] Error rendering ' + tabName + ':', err);
        container.innerHTML = '<div style="max-width:800px;margin:40px auto;padding:24px;background:rgba(239,68,68,0.1);border:1px solid var(--accent-red);border-radius:var(--radius-md);"><h3 style="color:var(--accent-red);margin-bottom:8px;">⚠️ 模块加载异常 / Component Render Error</h3><p style="font-size:0.88rem;color:var(--text-main);margin-bottom:12px;">无法加载模块 <strong>' + tabName + '</strong>: ' + (err?.message || err) + '</p><button class="btn btn-secondary btn-sm" onclick="location.hash=\\'#home\\'">返回首页 / Return Home</button></div>';
      }
    }
  }

  function setupNavigation() {
    document.querySelectorAll('.nav-item').forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        navigate(item.dataset.tab);
      });
    });

    document.querySelectorAll('.bottom-item').forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        navigate(item.dataset.tab);
      });
    });

    const quickLang = document.getElementById('quick-lang-btn');
    if (quickLang) {
      quickLang.onclick = () => {
        const next = State.language.startsWith('en') ? 'zh' : 'en';
        setLanguage(next);
      };
    }

    const quickTheme = document.getElementById('quick-theme-btn');
    if (quickTheme) {
      quickTheme.onclick = () => {
        setTheme(State.theme === 'dark' ? 'light' : 'dark');
      };
    }

    const didPill = document.getElementById('user-did-pill');
    if (didPill) {
      didPill.onclick = () => {
        try {
          navigator.clipboard.writeText(State.userDid);
          showToast(t('common.copied') || 'DID 已复制到剪贴板', 'success');
        } catch(e) {
          showToast(State.userDid, 'info');
        }
      };
    }
  }

  function setupPwaInstallPrompt() {
    let deferredPrompt = null;
    window.addEventListener('beforeinstallprompt', (e) => {
      e.preventDefault();
      deferredPrompt = e;
      const btn = document.getElementById('pwa-install-btn');
      if (btn) {
        btn.style.display = 'inline-flex';
        btn.onclick = async () => {
          btn.style.display = 'none';
          deferredPrompt.prompt();
          const choice = await deferredPrompt.userChoice;
          console.log('[PWA] User choice:', choice.outcome);
          deferredPrompt = null;
        };
      }
    });

    window.addEventListener('appinstalled', () => {
      console.log('[PWA] Application successfully installed.');
      showToast('Ziokt 客户端已成功安装到本地设备', 'success');
      const btn = document.getElementById('pwa-install-btn');
      if (btn) btn.style.display = 'none';
    });
  }

  function updateNavLabels() {
    document.querySelectorAll('.nav-item').forEach(item => {
      const key = routes[item.dataset.tab]?.titleKey;
      const labelSpan = item.querySelector('.nav-label');
      if (labelSpan && key) labelSpan.textContent = t(key);
    });
    document.querySelectorAll('.bottom-item').forEach(item => {
      const key = routes[item.dataset.tab]?.titleKey;
      const labelSpan = item.querySelector('.bottom-label');
      if (labelSpan && key) labelSpan.textContent = t(key);
    });
  }

  function setupKeyboardShortcuts() {
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        const modal = document.getElementById('modal-overlay');
        if (modal) modal.style.display = 'none';
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        const term = prompt('全局快捷检索 / 命令 (输入 home, chat, forum, files, apps, network, identity, devtools, settings):');
        if (term && routes[term.toLowerCase()]) {
          navigate(term.toLowerCase());
        }
        return;
      }
      if (['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;
      const num = parseInt(e.key, 10);
      const tabKeys = Object.keys(routes);
      if (num >= 1 && num <= tabKeys.length) {
        navigate(tabKeys[num - 1]);
      }
    });
  }

  // Self bootstrap
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initApp);
  } else {
    initApp();
  }
`;

  bundle += controllerCode + '\n})();\n';
  fs.writeFileSync(path.join(SRC_DIR, 'app.js'), bundle);
  console.log(`  ✓ Built universal standalone app.js (${bundle.length} bytes)`);
}

buildStandaloneAppBundle();

// 4. Copy directory recursively
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

// 5. Also stage into gateway/gui for direct Web Console / Gateway integration
const GATEWAY_GUI_DIR = path.join(__dirname, '..', 'gateway', 'gui');
if (fs.existsSync(GATEWAY_GUI_DIR)) {
  fs.rmSync(GATEWAY_GUI_DIR, { recursive: true, force: true });
}
copyDir(DIST_DIR, GATEWAY_GUI_DIR);
console.log(`>> [Ziokt GUI] Assets synced into gateway/gui/ for /gateway-assets/gui/ serving.`);
