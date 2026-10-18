// ==============================================================================
// Ziokt Unified Graphical Client - Application Controller & Router
// ==============================================================================
import { State, Events, initI18n, t, setTheme, setLanguage, showToast, showJsonModal } from './core.js';
import { renderHome } from './modules/home.js';
import { renderChat } from './modules/chat.js';
import { renderForum } from './modules/forum.js';
import { renderFiles } from './modules/files.js';
import { renderApps } from './modules/apps.js';
import { renderNetwork } from './modules/network.js';
import { renderIdentity } from './modules/identity.js';
import { renderDevtools } from './modules/devtools.js';
import { renderSettings } from './modules/settings.js';

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

export async function initApp() {
  // 1. Initialize i18n and theme
  await initI18n();
  setTheme(State.theme);

  // 2. Setup Navigation Handlers
  setupNavigation();

  // 3. Setup Keyboard Navigation Accessibility
  setupKeyboardShortcuts();

  // 4. Initial Navigation
  navigate(State.currentTab || 'home');

  // 5. Global Event Listeners
  Events.on('navigate', (tab) => navigate(tab));
  Events.on('language_changed', () => {
    updateNavLabels();
    navigate(State.currentTab);
  });
  Events.on('theme_changed', () => {
    navigate(State.currentTab);
  });

  console.log('Ziokt GUI Client initialized successfully.');
}

function navigate(tabName) {
  if (!routes[tabName]) tabName = 'home';
  State.currentTab = tabName;

  // Update Page Title
  const route = routes[tabName];
  const titleEl = document.getElementById('current-page-title');
  if (titleEl) titleEl.textContent = t(route.titleKey);
  document.title = `${t(route.titleKey)} - ${t('app.title')}`;

  // Update Active Nav states
  document.querySelectorAll('.nav-item').forEach(item => {
    item.classList.toggle('active', item.dataset.tab === tabName);
  });
  document.querySelectorAll('.bottom-item').forEach(item => {
    item.classList.toggle('active', item.dataset.tab === tabName);
  });

  // Render Target Module
  const container = document.getElementById('content-container');
  if (container) {
    container.innerHTML = '';
    route.render(container);
  }
}

function setupNavigation() {
  // Desktop Sidebar clicks
  document.querySelectorAll('.nav-item').forEach(item => {
    item.onclick = (e) => {
      e.preventDefault();
      navigate(item.dataset.tab);
    };
  });

  // Mobile Bottom Bar clicks
  document.querySelectorAll('.bottom-item').forEach(item => {
    item.onclick = (e) => {
      e.preventDefault();
      navigate(item.dataset.tab);
    };
  });

  // Quick DID click
  const didPill = document.getElementById('user-did-pill');
  if (didPill) {
    didPill.onclick = () => {
      navigator.clipboard.writeText(State.userDid);
      showToast(`${t('common.copied')}: ${State.userDid}`, 'success');
    };
  }

  // Quick Language Toggle
  const quickLang = document.getElementById('quick-lang-btn');
  if (quickLang) {
    quickLang.onclick = () => {
      setLanguage(State.language === 'zh' ? 'en' : 'zh');
    };
  }

  // Quick Theme Toggle
  const quickTheme = document.getElementById('quick-theme-btn');
  if (quickTheme) {
    quickTheme.onclick = () => {
      setTheme(State.theme === 'dark' ? 'light' : 'dark');
    };
  }
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
    // Esc closes modal
    if (e.key === 'Escape') {
      const modal = document.getElementById('modal-overlay');
      if (modal) modal.style.display = 'none';
      return;
    }

    // Ctrl+K opens Quick Command Palette
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      const term = prompt('全局快捷检索 / 命令 (输入 home, chat, forum, files, apps, network, identity, devtools, settings):');
      if (term && routes[term.toLowerCase()]) {
        navigate(term.toLowerCase());
      }
      return;
    }

    // Numbers 1-9 switch tabs (when not typing in an input)
    if (['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;
    const num = parseInt(e.key, 10);
    const tabKeys = Object.keys(routes);
    if (num >= 1 && num <= tabKeys.length) {
      navigate(tabKeys[num - 1]);
    }
  });
}

// Global bootstrap
window.addEventListener('DOMContentLoaded', initApp);
