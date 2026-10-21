#!/usr/bin/env node
// ==============================================================================
// Ziokt Unified GUI Client - Assets Packaging, Bundler & Validation Script
// ==============================================================================

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { execSync } from 'child_process';
import {createHash} from 'node:crypto';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const SRC_DIR = path.join(__dirname, 'src');
const DIST_DIR = path.join(__dirname, 'dist');

console.log('>> [Ziokt GUI] Starting client packaging build...');

// 1. Ensure dist directory
if (!process.argv.includes('--bundle-only') && fs.existsSync(DIST_DIR)) {
  fs.rmSync(DIST_DIR, { recursive: true, force: true });
}
if (!process.argv.includes('--bundle-only')) fs.mkdirSync(DIST_DIR, { recursive: true });

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
    '../../ziokt/web/application-client.js',
    'core.js',
    'private-offline.js',
    'modules/home.js',
    'modules/chat.js',
    'modules/forum.js',
    'modules/files.js',
    'modules/apps.js',
    'modules/content.js',
    'modules/ecosystem.js',
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
    content = content.replace(/^\s*import\b[\s\S]*?from\s*['"][^'"]+['"];?\s*$/gm, '');
    content = content.replace(/^\s*import\b.*?;?\s*$/gm, '');
    content = content.replace(/^\s*export\s+(default\s+)?(async\s+)?(function|const|let|var|class)\s+/gm, (m, p1, p2, p3) => (p2 || '') + p3 + ' ');
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
    library: { render: renderLibrary, titleKey: 'nav.library' },
    netnews: { render: renderNetnews, titleKey: 'nav.netnews' },
    ecosystem: { render: renderEcosystem, titleKey: 'nav.ecosystem' },
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

    // Probe local node first if in local mode before setting initial route
    if (State.runtimeMode === 'local') {
      await checkLocalNodeHealth();
    }

    updateAppNodeBadge();

    let initialTab = getHashTab() || State.currentTab || 'home';
    if (isLocalNodeOffline() && !canUseWithoutLocalNode(initialTab)) {
      initialTab = 'settings';
    }
    navigate(initialTab);

    window.addEventListener('hashchange', () => {
      let tab = getHashTab();
      if (tab && tab !== State.currentTab) {
        if (isLocalNodeOffline() && !canUseWithoutLocalNode(tab)) {
          navigate('settings');
          return;
        }
        navigate(tab);
      }
    });

    Events.on('navigate', (tab) => navigate(tab));
    Events.on('local_node_offline', () => {
      if (!canUseWithoutLocalNode(State.currentTab)) {
        navigate('settings');
      }
    });
    Events.on('local_node_status_changed', () => {
      updateAppNodeBadge();
      if (isLocalNodeOffline() && !canUseWithoutLocalNode(State.currentTab)) {
        navigate('settings');
      }
    });
    Events.on('mode_changed', () => {
      updateAppNodeBadge();
      if (isLocalNodeOffline() && !canUseWithoutLocalNode(State.currentTab)) {
        navigate('settings');
      }
    });
    Events.on('active_node_changed', () => {
      updateAppNodeBadge();
    });
    Events.on('language_changed', () => {
      updateNavLabels();
      updateAppNodeBadge();
      navigate(State.currentTab);
    });
    Events.on('theme_changed', () => {
      navigate(State.currentTab);
    });

    console.log('[Ziokt GUI] Universal Client Initialized.');
  }

  function navigate(tabName) {
    // Local Node Offline Gatekeeping: only Settings can be viewed
    if (isLocalNodeOffline() && !canUseWithoutLocalNode(tabName)) {
      const msg = State.language === 'en'
        ? 'Local node is offline. Local mode requires a running node; only Settings is accessible.'
        : '本地节点未启动。使用本地节点需要用户本地真实有节点运行，当前仅开放【系统设置】页。';
      showToast(msg, 'warning');
      tabName = 'settings';
    }

    if (!routes[tabName]) tabName = isLocalNodeOffline() ? 'settings' : 'home';
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
        container.innerHTML = '<div style="max-width:800px;margin:40px auto;padding:24px;background:rgba(239,68,68,0.1);border:1px solid var(--accent-red);border-radius:var(--radius-md);"><h3 style="color:var(--accent-red);margin-bottom:8px;">⚠️ 模块加载异常 / Component Render Error</h3><p style="font-size:0.88rem;color:var(--text-main);margin-bottom:12px;">无法加载模块 <strong>' + tabName + '</strong>: ' + (err?.message || err) + '</p><button class="btn btn-secondary btn-sm" onclick="location.hash=&quot;#home&quot;">返回首页 / Return Home</button></div>';
      }
    }
  }

  function setupNavigation() {
    document.querySelectorAll('.nav-item').forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        const targetTab = item.dataset.tab;
        if (isLocalNodeOffline() && !canUseWithoutLocalNode(targetTab)) {
          const msg = State.language === 'en'
            ? 'Local node is offline. Only Settings is accessible.'
            : '本地节点未启动，当前仅开放【系统设置】页。';
          showToast(msg, 'warning');
          navigate('settings');
          return;
        }
        navigate(targetTab);
      });
    });

    document.querySelectorAll('.bottom-item').forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        const targetTab = item.dataset.tab;
        if (isLocalNodeOffline() && !canUseWithoutLocalNode(targetTab)) {
          const msg = State.language === 'en'
            ? 'Local node is offline. Only Settings is accessible.'
            : '本地节点未启动，当前仅开放【系统设置】页。';
          showToast(msg, 'warning');
          navigate('settings');
          return;
        }
        navigate(targetTab);
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

  const appPath = path.join(SRC_DIR, 'app.js');
  fs.writeFileSync(appPath, bundle);

  try {
    execSync(`node -c "${appPath}"`, { stdio: 'pipe' });
    console.log(`  ✓ Validated JS syntax of standalone app.js with Node.js V8 engine`);
  } catch (err) {
    console.error(`  ✕ Syntax error in bundled app.js:`, err.stderr ? err.stderr.toString() : err.message);
    process.exit(1);
  }

  console.log(`  ✓ Built universal standalone app.js (${bundle.length} bytes)`);
}

buildStandaloneAppBundle();
// The shell version changes only when its fixed assets change.
const shellAssets=['index.html','app.js','bootstrap.js','style.css','manifest.json','icons/icon-192.png','icons/icon-512.png','icons/icon.svg','i18n/zh.json','i18n/en.json','i18n/zh-CN.json','i18n/en-US.json'];
const shellHash=createHash('sha256');for(const name of shellAssets){shellHash.update(name+'\0');shellHash.update(fs.readFileSync(path.join(SRC_DIR,name)));}
const workerPath=path.join(SRC_DIR,'sw.js'),workerTemplate=fs.readFileSync(workerPath,'utf8').replace(/const CACHE_NAME = '[^']+';/,"const CACHE_NAME = 'ziokt-gui-shell-v2-build';");shellHash.update(workerTemplate);fs.writeFileSync(workerPath,workerTemplate.replace(/const CACHE_NAME = '[^']+';/,"const CACHE_NAME = 'ziokt-gui-shell-v2-"+shellHash.digest('hex').slice(0,20)+"';"));
if (process.argv.includes('--bundle-only')) process.exit(0);

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

// Sync into Android assets directory (exclude downloads)
const ANDROID_ASSETS_DIR = path.join(__dirname, 'android', 'app', 'src', 'main', 'assets');
if (fs.existsSync(path.dirname(ANDROID_ASSETS_DIR))) {
  if (fs.existsSync(ANDROID_ASSETS_DIR)) {
    fs.rmSync(ANDROID_ASSETS_DIR, { recursive: true, force: true });
  }
  copyDir(DIST_DIR, ANDROID_ASSETS_DIR);
}

const distFiles = fs.readdirSync(DIST_DIR, { recursive: true });
console.log(`>> [Ziokt GUI] Build complete! ${distFiles.length} files staged into dist/`);

// 5. Also stage into gateway/gui for direct Web Console / Gateway integration
const GATEWAY_GUI_DIR = path.join(__dirname, '..', 'gateway', 'gui');
fs.mkdirSync(GATEWAY_GUI_DIR, { recursive: true });
copyDir(DIST_DIR, GATEWAY_GUI_DIR);
console.log(`>> [Ziokt GUI] Assets synced into gateway/gui/ for /gateway-assets/gui/ serving.`);
