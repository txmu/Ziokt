// ==============================================================================
// Module: WATChat End-to-End Encrypted Messenger with Dual UI Switcher
// ==============================================================================
import { State, t, showToast, getStorage, setStorage } from '../core.js';

let chatUiMode = getStorage('watchat_ui_mode', 'minimalist'); // 'minimalist' | 'classic'
let isChatLoggedIn = getStorage('watchat_logged_in', 'false') === 'true';
let activeContact = 'genesis-node';
let messagesStore = null;
try {
  const raw = getStorage('watchat_msgs');
  if (raw) messagesStore = JSON.parse(raw);
} catch (e) {
  messagesStore = null;
}
if (!messagesStore) {
  messagesStore = {
    'genesis-node': [
      { id: 1, sender: 'genesis-node', text: '欢迎加入 Ziokt 端到端加密通讯网络！所有消息均由 XChaCha20-Poly1305 密封。', time: '10:00' },
      { id: 2, sender: 'me', text: '收到！正在测试统一客户端的无缝双 UI 切换。', time: '10:02' },
      { id: 3, sender: 'genesis-node', text: '可在上方随时切换“现代简约版”与“经典丰富版”，加密会话状态实时无损保持。', time: '10:03' }
    ],
    'community-bot': [
      { id: 1, sender: 'community-bot', text: 'Corium 治理委员会 #48 提案已发起，欢迎前往社区论坛参与投票。', time: '09:15' }
    ]
  };
}

export function renderChat(container) {
  const isMinimalist = chatUiMode === 'minimalist';

  // 1. WATChat Login Screen with Dual UI Switcher
  if (!isChatLoggedIn) {
    container.innerHTML = `
      <div class="chat-page-wrapper">
        <div class="chat-login-container ${isMinimalist ? 'login-minimalist' : 'login-classic'}">
          <div class="chat-login-card">
            
            <!-- Dual UI Switcher on Login Page -->
            <div class="chat-login-switcher-bar">
              <div style="font-size: 0.8rem; font-weight: 600; color: var(--text-muted); display: flex; align-items: center; gap: 6px;">
                <span>💬 WATChat</span>
                <span class="mode-pill" style="font-size: 0.7rem; color: var(--accent-cyan);">${t('chat.dual_ui')}</span>
              </div>
              <div class="dual-ui-toggle-group">
                <button id="toggle-minimalist" class="btn btn-sm ${isMinimalist ? 'btn-primary' : 'btn-secondary'}" style="border:none;">${t('chat.ui_minimalist')}</button>
                <button id="toggle-classic" class="btn btn-sm ${!isMinimalist ? 'btn-primary' : 'btn-secondary'}" style="border:none;">${t('chat.ui_classic')}</button>
              </div>
            </div>

            <!-- Login Header & Encryption Badge -->
            <div style="text-align: center; margin: 16px 0 20px 0;">
              <div style="font-size: 2.2rem; margin-bottom: 8px;">🔐</div>
              <h2 style="font-size: 1.25rem; font-weight: 700; color: var(--text-main); margin-bottom: 4px;">${t('chat.login_title')}</h2>
              <p style="font-size: 0.8rem; color: var(--text-muted);">${t('chat.login_desc')}</p>
              <div style="margin-top: 8px;">
                <span class="status-badge" style="font-size: 0.72rem; color: var(--accent-green); background: rgba(16,185,129,0.12); padding: 4px 10px; border-radius: 12px; border: 1px solid rgba(16,185,129,0.3);">
                  <span class="status-dot"></span> XChaCha20-Poly1305
                </span>
              </div>
            </div>

            <!-- Classic Telemetry Panel (Only shown in Classic mode) -->
            ${!isMinimalist ? `
              <div class="chat-classic-telemetry-box">
                <div style="font-size: 0.75rem; font-weight: 600; color: var(--accent-cyan); margin-bottom: 6px; font-family: var(--font-mono);">${t('chat.classic_telemetry')}</div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; font-size: 0.7rem; color: var(--text-muted); font-family: var(--font-mono);">
                  <div>• ${t('chat.ratchet_status')}</div>
                  <div>• ${t('chat.cipher_info')}</div>
                  <div style="grid-column: 1 / -1;">• ${t('chat.onion_route')}</div>
                </div>
              </div>
            ` : ''}

            <!-- Login Credentials Form -->
            <form id="chat-login-form" style="display: flex; flex-direction: column; gap: 12px; margin-top: 16px;">
              <div>
                <label style="display: block; font-size: 0.78rem; font-weight: 600; color: var(--text-muted); margin-bottom: 4px;">
                  ${t('common.name')} / DID
                </label>
                <input type="text" id="chat-username" class="input-text" value="Genesis Node (Node #0)" placeholder="${t('chat.username_placeholder')}" style="width: 100%;">
              </div>

              <div>
                <label style="display: block; font-size: 0.78rem; font-weight: 600; color: var(--text-muted); margin-bottom: 4px;">
                  ${t('settings.auth_token')} / Passphrase
                </label>
                <input type="password" id="chat-passphrase" class="input-text" value="●●●●●●●●●●●●" placeholder="${t('chat.passphrase_placeholder')}" style="width: 100%;">
              </div>

              <button type="submit" id="chat-login-btn" class="btn btn-primary" style="width: 100%; padding: 10px; margin-top: 6px; font-weight: 600;">
                🚀 ${t('chat.login_btn')}
              </button>
            </form>

            <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 16px; font-size: 0.75rem; color: var(--text-dim);">
              <span>DID: did:ziokt:mesh:genesis-node</span>
              <span class="mode-pill">${isMinimalist ? t('chat.ui_minimalist') : t('chat.ui_classic')}</span>
            </div>

          </div>
        </div>
      </div>
    `;

    // Dual UI Switcher Handlers on Login Page
    container.querySelector('#toggle-minimalist').onclick = () => {
      chatUiMode = 'minimalist';
      setStorage('watchat_ui_mode', 'minimalist');
      showToast(t('chat.ui_minimalist'), 'info');
      renderChat(container);
    };

    container.querySelector('#toggle-classic').onclick = () => {
      chatUiMode = 'classic';
      setStorage('watchat_ui_mode', 'classic');
      showToast(t('chat.ui_classic'), 'info');
      renderChat(container);
    };

    // Login Form Submit
    container.querySelector('#chat-login-form').onsubmit = (e) => {
      e.preventDefault();
      isChatLoggedIn = true;
      setStorage('watchat_logged_in', 'true');
      showToast('WATChat 已登录并建立加密会话', 'success');
      renderChat(container);
    };

    return;
  }

  // 2. Active Chat Conversation Room
  container.innerHTML = `
    <div class="chat-page-wrapper">
      <!-- WATChat Sub-Header: Dual UI Switcher & Session Controls -->
      <div class="chat-subheader">
        <div style="display: flex; align-items: center; gap: 10px;">
          <span style="font-weight: 700; color: var(--accent-cyan); font-size: 0.95rem;">💬 ${t('chat.title')}</span>
          <span class="status-badge" style="font-size: 0.7rem; color: var(--accent-green);">
            <span class="status-dot"></span> XChaCha20-Poly1305
          </span>
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 0.78rem; color: var(--text-muted);">${t('chat.dual_ui')}:</span>
          <div class="dual-ui-toggle-group">
            <button id="toggle-minimalist" class="btn btn-sm ${isMinimalist ? 'btn-primary' : 'btn-secondary'}" style="border:none;">${t('chat.ui_minimalist')}</button>
            <button id="toggle-classic" class="btn btn-sm ${!isMinimalist ? 'btn-primary' : 'btn-secondary'}" style="border:none;">${t('chat.ui_classic')}</button>
          </div>
          <button id="chat-logout-btn" class="btn btn-secondary btn-sm" title="${t('chat.logout_btn')}" style="padding: 4px 8px; font-size: 0.75rem;">🔒 ${t('chat.logout_btn')}</button>
        </div>
      </div>

      <!-- Main Chat Body -->
      <div class="chat-container">
        
        <!-- Sidebar Contacts -->
        <div class="chat-sidebar">
          <div style="padding: 12px; border-bottom: 1px solid var(--border-subtle);">
            <input type="text" id="contact-search" class="input-text" placeholder="${t('common.search')}" style="padding: 6px 10px; font-size: 0.8rem;">
          </div>
          <div id="contact-list" style="flex: 1; overflow-y: auto;">
            <div class="contact-item ${activeContact === 'genesis-node' ? 'active' : ''}" data-id="genesis-node" style="padding: 12px 14px; border-bottom: 1px solid var(--border-subtle); cursor: pointer; display: flex; align-items: center; gap: 10px;">
              <div style="width: 36px; height: 36px; border-radius: 50%; background: linear-gradient(135deg, #0284c7, #38bdf8); display: flex; align-items: center; justify-content: center; font-weight: bold; color: #fff;">G</div>
              <div style="flex: 1; overflow: hidden;">
                <div style="font-weight: 600; font-size: 0.85rem; color: var(--text-main); display: flex; justify-content: space-between;">
                  <span>Genesis Node</span>
                  <span style="font-size: 0.7rem; color: var(--text-dim);">10:03</span>
                </div>
                <div style="font-size: 0.75rem; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">双 UI 架构测试中...</div>
              </div>
            </div>

            <div class="contact-item ${activeContact === 'community-bot' ? 'active' : ''}" data-id="community-bot" style="padding: 12px 14px; border-bottom: 1px solid var(--border-subtle); cursor: pointer; display: flex; align-items: center; gap: 10px;">
              <div style="width: 36px; height: 36px; border-radius: 50%; background: linear-gradient(135deg, #818cf8, #a855f7); display: flex; align-items: center; justify-content: center; font-weight: bold; color: #fff;">C</div>
              <div style="flex: 1; overflow: hidden;">
                <div style="font-weight: 600; font-size: 0.85rem; color: var(--text-main); display: flex; justify-content: space-between;">
                  <span>Community Bot</span>
                  <span style="font-size: 0.7rem; color: var(--text-dim);">09:15</span>
                </div>
                <div style="font-size: 0.75rem; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">#48 提案已发布</div>
              </div>
            </div>
          </div>
          <div style="padding: 10px; border-top: 1px solid var(--border-subtle);">
            <button id="add-contact-btn" class="btn btn-secondary btn-sm" style="width: 100%;">+ ${t('chat.new_conversation')}</button>
          </div>
        </div>

        <!-- Chat Content Area -->
        <div class="chat-main">
          <!-- Active Conversation Header -->
          <div style="padding: 12px 16px; border-bottom: 1px solid var(--border-subtle); display: flex; justify-content: space-between; align-items: center; background: var(--bg-sidebar);">
            <div>
              <div style="font-weight: 600; font-size: 0.95rem; color: var(--text-main);">${activeContact === 'genesis-node' ? 'Genesis Node (Node #0)' : 'Community Bot'}</div>
              <div style="font-size: 0.72rem; color: var(--accent-cyan); font-family: var(--font-mono);">did:ziokt:mesh:${activeContact}</div>
            </div>
            ${!isMinimalist ? `
              <!-- Classic View Telemetry Toolbar -->
              <div style="display: flex; gap: 8px; font-size: 0.75rem; color: var(--text-muted);">
                <span class="mode-pill" style="color:var(--accent-green);border-color:rgba(16,185,129,0.3);background:rgba(16,185,129,0.15);">Ratchet: Active</span>
                <span class="mode-pill">Cipher: XChaCha20</span>
                <span class="mode-pill">Relay: Onion ETP</span>
              </div>
            ` : ''}
          </div>

          <!-- Message Bubbles -->
          <div id="messages-box" class="chat-messages">
            ${(messagesStore[activeContact] || []).map(m => `
              <div class="chat-bubble ${m.sender === 'me' ? 'bubble-mine' : 'bubble-theirs'}">
                ${!isMinimalist && m.sender !== 'me' ? `<div style="font-size:0.68rem;color:var(--accent-cyan);margin-bottom:3px;font-family:var(--font-mono);">${m.sender}</div>` : ''}
                <div>${m.text}</div>
                <div style="font-size: 0.65rem; text-align: right; margin-top: 4px; opacity: 0.75;">${m.time}</div>
              </div>
            `).join('')}
          </div>

          <!-- Input Bar -->
          <div class="chat-input-bar">
            ${!isMinimalist ? `
              <!-- Classic Rich Bar with Attachment & Code Trigger -->
              <div style="display: flex; gap: 6px; margin-bottom: 8px;">
                <button id="attach-vault-btn" class="btn btn-secondary btn-sm" title="从保险库附加文件">📎 ${t('chat.attach_file')}</button>
                <button id="emoji-quick-btn" class="btn btn-secondary btn-sm">😀 表情</button>
                <button id="clear-chat-btn" class="btn btn-secondary btn-sm">🗑️ 清空记录</button>
              </div>
            ` : ''}
            <div style="display: flex; gap: 10px;">
              <input type="text" id="chat-input" class="input-text" placeholder="${t('chat.input_placeholder')}" style="flex: 1;">
              <button id="chat-send-btn" class="btn btn-primary">${t('chat.send')}</button>
            </div>
          </div>

        </div>

      </div>
    </div>
  `;

  // UI Switch Handlers
  container.querySelector('#toggle-minimalist').onclick = () => {
    chatUiMode = 'minimalist';
    setStorage('watchat_ui_mode', 'minimalist');
    showToast('已切换至 WATChat 现代简约版', 'info');
    renderChat(container);
  };

  container.querySelector('#toggle-classic').onclick = () => {
    chatUiMode = 'classic';
    setStorage('watchat_ui_mode', 'classic');
    showToast('已切换至 WATChat 经典丰富版 (含加密机密与中继状态)', 'info');
    renderChat(container);
  };

  // Logout / Lock Session Handler
  const logoutBtn = container.querySelector('#chat-logout-btn');
  if (logoutBtn) {
    logoutBtn.onclick = () => {
      isChatLoggedIn = false;
      setStorage('watchat_logged_in', 'false');
      showToast('已锁定会话并返回 WATChat 登录页', 'info');
      renderChat(container);
    };
  }

  // Contact Switcher
  container.querySelectorAll('.contact-item').forEach(item => {
    item.onclick = () => {
      activeContact = item.dataset.id;
      renderChat(container);
    };
  });

  // Send Message Logic
  const inputEl = container.querySelector('#chat-input');
  const sendBtn = container.querySelector('#chat-send-btn');
  const doSend = () => {
    const text = inputEl.value.trim();
    if (!text) return;
    if (!messagesStore[activeContact]) messagesStore[activeContact] = [];
    
    const now = new Date();
    const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
    messagesStore[activeContact].push({
      id: Date.now(),
      sender: 'me',
      text,
      time: timeStr
    });
    setStorage('watchat_msgs', JSON.stringify(messagesStore));
    inputEl.value = '';
    
    // Auto-scroll
    renderChat(container);
    const box = container.querySelector('#messages-box');
    if (box) box.scrollTop = box.scrollHeight;
  };

  sendBtn.onclick = doSend;
  inputEl.onkeydown = (e) => {
    if (e.key === 'Enter') doSend();
  };
  inputEl.addEventListener('focus', () => {
    setTimeout(() => {
      inputEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 200);
  });
  const box = container.querySelector('#messages-box');
  if (box) box.scrollTop = box.scrollHeight;

  // Add Contact Prompt
  const addBtn = container.querySelector('#add-contact-btn');
  if (addBtn) {
    addBtn.onclick = () => {
      const recipient = prompt(t('chat.enter_recipient'));
      if (recipient) {
        messagesStore[recipient] = [
          { id: Date.now(), sender: recipient, text: '端到端加密握手已建立。', time: '刚刚' }
        ];
        activeContact = recipient;
        renderChat(container);
        showToast('已建立新会话', 'success');
      }
    };
  }

  // Classic Bar Attachment
  const attachBtn = container.querySelector('#attach-vault-btn');
  if (attachBtn) {
    attachBtn.onclick = () => {
      const filename = prompt('输入 UFS 或 SafeFS 文件名作为附件发送 (例如: WELCOME.txt):', 'WELCOME.txt');
      if (filename) {
        inputEl.value = `[Vault Attachment: ${filename} | ufs://${filename}]`;
        doSend();
      }
    };
  }
}
