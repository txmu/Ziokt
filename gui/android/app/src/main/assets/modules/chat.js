// ==============================================================================
// Module: WATChat End-to-End Encrypted Messenger with Dual UI Switcher
// ==============================================================================
import { State, t, showToast, getStorage, setStorage } from '../core.js';

let chatUiMode = getStorage('watchat_ui_mode', 'classic'); // 'minimalist' | 'classic'
let isChatLoggedIn = getStorage('watchat_logged_in', 'false') === 'true';
let activeContact = 'genesis-node';
let isVoiceRecording = false;
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
      { id: 1, sender: 'genesis-node', text: '欢迎加入 Ziokt 腕聊端到端加密通讯网络！所有消息均由 XChaCha20-Poly1305 密封。', time: '10:00' },
      { id: 2, sender: 'me', text: '收到！经典丰富版已直接复刻腕聊原生界面架构。', time: '10:02' },
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
    if (!isMinimalist) {
      // Replicate exact Login UI from WATChat-code.zip
      container.innerHTML = `
        <div class="chat-page-wrapper watchat-classic-root">
          <div class="chat-login-container login-classic">
            <div class="chat-login-card login-box">
              
              <!-- Dual UI Switcher at top of Login Page -->
              <div class="chat-login-switcher-bar" style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #2b383f; padding-bottom: 10px; margin-bottom: 12px;">
                <div style="font-size: 0.8rem; font-weight: 700; color: #45d483; display: flex; align-items: center; gap: 6px;">
                  <span>腕聊</span>
                  <span style="font-size: 0.68rem; color: #07140d; background: #45d483; padding: 1px 6px; border-radius: 6px; font-weight: 800;">经典版</span>
                </div>
                <div class="dual-ui-toggle-group">
                  <button id="toggle-minimalist" class="btn btn-sm btn-secondary" style="border:none; padding: 3px 8px; font-size: 0.75rem;">${t('chat.ui_minimalist')}</button>
                  <button id="toggle-classic" class="btn btn-sm btn-primary" style="border:none; background: #45d483; color: #07140d; font-weight: 700; padding: 3px 8px; font-size: 0.75rem;">${t('chat.ui_classic')}</button>
                </div>
              </div>

              <!-- Replicated Login Form -->
              <form id="chat-login-form">
                <h1 style="font-size: 28px; margin: 0; color: #f4f7f8; font-weight: 800;">腕聊</h1>
                <p style="color: #9fb0b8; margin: 5px 0 14px; font-size: 14px;">登录你的账户</p>
                <input id="chat-username" autocomplete="username" maxlength="24" placeholder="用户名" aria-label="用户名" required value="admin" class="input-text">
                <input id="chat-passphrase" type="password" autocomplete="current-password" maxlength="64" placeholder="密码" aria-label="密码" required value="123456789012" class="input-text">
                <button type="submit" id="chat-login-btn">进入</button>
                <output id="loginError" class="error" aria-live="polite" style="color: #ff7d7d; font-size: 13px; margin-top: 8px; display: block;"></output>
              </form>

              <div style="margin-top: 14px; font-size: 0.72rem; color: #9fb0b8; display: flex; justify-content: space-between; align-items: center;">
                <span>DID: did:ziokt:mesh:genesis-node</span>
                <span style="color: #45d483; border: 1px solid rgba(69,212,131,0.3); padding: 2px 6px; border-radius: 8px;">XChaCha20-Poly1305</span>
              </div>
            </div>
          </div>
        </div>
      `;
    } else {
      // Modern Minimalist Login View
      container.innerHTML = `
        <div class="chat-page-wrapper">
          <div class="chat-login-container login-minimalist">
            <div class="chat-login-card">
              <div class="chat-login-switcher-bar">
                <div style="font-size: 0.8rem; font-weight: 600; color: var(--text-muted); display: flex; align-items: center; gap: 6px;">
                  <span>💬 WATChat</span>
                  <span class="mode-pill" style="font-size: 0.7rem; color: var(--accent-cyan);">${t('chat.dual_ui')}</span>
                </div>
                <div class="dual-ui-toggle-group">
                  <button id="toggle-minimalist" class="btn btn-sm btn-primary" style="border:none;">${t('chat.ui_minimalist')}</button>
                  <button id="toggle-classic" class="btn btn-sm btn-secondary" style="border:none;">${t('chat.ui_classic')}</button>
                </div>
              </div>

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
                <span class="mode-pill">${t('chat.ui_minimalist')}</span>
              </div>
            </div>
          </div>
        </div>
      `;
    }

    // Dual UI Handlers on Login Page
    container.querySelector('#toggle-minimalist').onclick = () => {
      chatUiMode = 'minimalist';
      setStorage('watchat_ui_mode', 'minimalist');
      showToast(t('chat.ui_minimalist'), 'info');
      renderChat(container);
    };

    container.querySelector('#toggle-classic').onclick = () => {
      chatUiMode = 'classic';
      setStorage('watchat_ui_mode', 'classic');
      showToast('已切换至腕聊经典丰富版', 'info');
      renderChat(container);
    };

    // Login Form Submit
    container.querySelector('#chat-login-form').onsubmit = (e) => {
      e.preventDefault();
      isChatLoggedIn = true;
      setStorage('watchat_logged_in', 'true');
      showToast('腕聊已进入会话', 'success');
      renderChat(container);
    };

    return;
  }

  // 2. Logged-in Chat Room
  if (!isMinimalist) {
    // Replicate exact 腕聊 UI from WATChat-code.zip
    container.innerHTML = `
      <div class="chat-page-wrapper watchat-classic-root">
        <div class="chat-classic-app">
          
          <!-- Replicated Header from WATChat-code.zip -->
          <header class="chat-classic-header">
            <button id="chat-back-btn" class="chat-classic-head-btn" aria-label="返回" title="返回联系人">‹</button>
            <strong id="chat-peer-title">${activeContact === 'genesis-node' ? 'Genesis Node' : 'Community Bot'}</strong>
            <span class="online">● 在线</span>
            <span style="font-size: 0.65rem; color: #45d483; font-family: var(--font-mono); border: 1px solid rgba(69,212,131,0.3); padding: 1px 6px; border-radius: 6px; margin: 0 4px;">XChaCha20-Poly1305</span>
            
            <!-- Dual UI Switcher in Header -->
            <div class="dual-ui-toggle-group" style="margin: 0 4px;">
              <button id="toggle-minimalist" class="btn btn-sm btn-secondary" style="border:none; padding: 2px 8px; font-size: 0.72rem;">${t('chat.ui_minimalist')}</button>
              <button id="toggle-classic" class="btn btn-sm btn-primary" style="border:none; background: #45d483; color: #07140d; font-weight: 700; padding: 2px 8px; font-size: 0.72rem;">${t('chat.ui_classic')}</button>
            </div>

            <!-- Header Action Buttons from WATChat-code.zip: 管 (Admin) & 退 (Logout) -->
            <button id="chat-admin-btn" class="chat-classic-head-btn btn-text-badge" aria-label="管理用户" title="管理用户">管</button>
            <button id="chat-logout-btn" class="chat-classic-head-btn btn-text-badge" aria-label="退出" title="${t('chat.logout_btn')}">退</button>
          </header>

          <!-- Admin Drawer from WATChat-code.zip -->
          <section id="chat-admin-panel" style="display: none; background: #192126; border-bottom: 1px solid #2b383f; padding: 12px; font-size: 13px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <h2 style="font-size: 15px; margin: 0; color: #45d483;">用户与联系人 (腕聊)</h2>
              <button id="chat-close-admin-btn" style="background: transparent; border: 0; color: #9fb0b8; font-size: 16px; cursor: pointer;">✕</button>
            </div>
            <p style="color: #9fb0b8; margin: 0 0 8px; font-size: 12px;">点选某用户，再勾选其可聊天联系人；端到端双向密钥生效。</p>
            <div style="display: flex; gap: 6px; flex-wrap: wrap;">
              <button type="button" class="user-chip active" style="padding: 4px 10px; background: #45d483; color: #07140d; font-weight: 700; border: 0; border-radius: 8px;">Genesis Node (主节点)</button>
              <button type="button" class="user-chip" style="padding: 4px 10px; background: #101417; color: #f4f7f8; border: 1px solid #2b383f; border-radius: 8px;">Community Bot</button>
            </div>
          </section>

          <!-- Body: Contacts List + Messages + 5-Column Composer -->
          <div class="chat-container" style="display: flex; flex: 1; min-height: 0; background: #101417; overflow: hidden; border: none;">
            
            <!-- Replicated Sidebar Contacts List -->
            <aside class="chat-sidebar" style="width: 260px; background: #101417; border-right: 1px solid #2b383f; display: flex; flex-direction: column;">
              <div style="padding: 8px; border-bottom: 1px solid #2b383f;">
                <input type="text" id="contact-search" class="input-text" placeholder="搜索联系人…" style="width: 100%; min-height: 38px; border: 1px solid #2b383f; background: #192126; color: #f4f7f8; border-radius: 9px; padding: 0 8px; font-size: 13px;">
              </div>
              <div id="contact-list" class="list" style="flex: 1; overflow-y: auto; padding: 8px;">
                <div class="contact chat-classic-contact ${activeContact === 'genesis-node' ? 'active' : ''}" data-id="genesis-node">
                  <span class="avatar chat-classic-avatar">G</span>
                  <div style="flex: 1; overflow: hidden;">
                    <div style="font-weight: 700; font-size: 14px; color: #f4f7f8; display: flex; justify-content: space-between;">
                      <span>Genesis Node</span>
                      <span style="font-size: 11px; color: #9fb0b8;">10:03</span>
                    </div>
                    <div style="font-size: 12px; color: #9fb0b8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">双 UI 架构测试中...</div>
                  </div>
                </div>

                <div class="contact chat-classic-contact ${activeContact === 'community-bot' ? 'active' : ''}" data-id="community-bot">
                  <span class="avatar chat-classic-avatar" style="background: #246b49; color: #fff;">C</span>
                  <div style="flex: 1; overflow: hidden;">
                    <div style="font-weight: 700; font-size: 14px; color: #f4f7f8; display: flex; justify-content: space-between;">
                      <span>Community Bot</span>
                      <span style="font-size: 11px; color: #9fb0b8;">09:15</span>
                    </div>
                    <div style="font-size: 12px; color: #9fb0b8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">#48 提案已发布</div>
                  </div>
                </div>
              </div>
              <div style="padding: 8px; border-top: 1px solid #2b383f;">
                <button id="add-contact-btn" style="width: 100%; min-height: 40px; border: 0; background: #45d483; color: #07140d; font-weight: 700; border-radius: 9px; cursor: pointer;">+ ${t('chat.new_conversation')}</button>
              </div>
            </aside>

            <!-- Replicated Messages Area + Composer -->
            <div class="chat-main" style="flex: 1; display: flex; flex-direction: column; min-height: 0; background: #101417; overflow: hidden;">
              
              <!-- Messages -->
              <div id="messages-box" class="messages chat-classic-messages">
                ${(messagesStore[activeContact] || []).map(m => `
                  <article class="message chat-classic-msg ${m.sender === 'me' ? 'mine' : ''}">
                    <div>${m.text}</div>
                    <time>${m.time}</time>
                  </article>
                `).join('')}
              </div>

              <!-- Replicated 5-Column Composer: 图 / 视 / 音 / 消息… / 发 -->
              <div class="chat-input-bar chat-classic-composer">
                <button id="attach-vault-btn" class="media-button chat-classic-media-btn" type="button" aria-label="发送图片" title="从保险库/本地发送图片与附件">图</button>
                <button id="video-attach-btn" class="media-button chat-classic-media-btn" type="button" aria-label="发送视频" title="发送视频附件">视</button>
                <button id="voice-record-btn" class="media-button chat-classic-media-btn ${isVoiceRecording ? 'recording' : ''}" type="button" aria-label="录制语音" title="录制语音消息">${isVoiceRecording ? '停' : '音'}</button>
                <input type="text" id="chat-input" class="chat-classic-input" maxlength="1000" enterkeyhint="send" autocomplete="off" placeholder="消息…" aria-label="消息">
                <button type="submit" id="chat-send-btn" class="media-button chat-classic-media-btn" aria-label="发送" style="background:#45d483; color:#07140d; font-weight:800;">发</button>
              </div>

            </div>

          </div>
        </div>
      </div>
    `;
  } else {
    // Modern Minimalist Chat View
    container.innerHTML = `
      <div class="chat-page-wrapper">
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
              <button id="toggle-minimalist" class="btn btn-sm btn-primary" style="border:none;">${t('chat.ui_minimalist')}</button>
              <button id="toggle-classic" class="btn btn-sm btn-secondary" style="border:none;">${t('chat.ui_classic')}</button>
            </div>
            <button id="chat-logout-btn" class="btn btn-secondary btn-sm" title="${t('chat.logout_btn')}" style="padding: 4px 8px; font-size: 0.75rem;">🔒 ${t('chat.logout_btn')}</button>
          </div>
        </div>

        <div class="chat-container">
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

          <div class="chat-main">
            <div style="padding: 12px 16px; border-bottom: 1px solid var(--border-subtle); display: flex; justify-content: space-between; align-items: center; background: var(--bg-sidebar);">
              <div>
                <div style="font-weight: 600; font-size: 0.95rem; color: var(--text-main);">${activeContact === 'genesis-node' ? 'Genesis Node (Node #0)' : 'Community Bot'}</div>
                <div style="font-size: 0.72rem; color: var(--accent-cyan); font-family: var(--font-mono);">did:ziokt:mesh:${activeContact}</div>
              </div>
            </div>

            <div id="messages-box" class="chat-messages">
              ${(messagesStore[activeContact] || []).map(m => `
                <div class="chat-bubble ${m.sender === 'me' ? 'bubble-mine' : 'bubble-theirs'}">
                  <div>${m.text}</div>
                  <div style="font-size: 0.65rem; text-align: right; margin-top: 4px; opacity: 0.75;">${m.time}</div>
                </div>
              `).join('')}
            </div>

            <div class="chat-input-bar">
              <div style="display: flex; gap: 10px;">
                <input type="text" id="chat-input" class="input-text" placeholder="${t('chat.input_placeholder')}" style="flex: 1;">
                <button id="chat-send-btn" class="btn btn-primary">${t('chat.send')}</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

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
    showToast('已切换至腕聊经典丰富版', 'info');
    renderChat(container);
  };

  // Logout / Lock Session Handler
  const logoutBtn = container.querySelector('#chat-logout-btn');
  if (logoutBtn) {
    logoutBtn.onclick = () => {
      isChatLoggedIn = false;
      setStorage('watchat_logged_in', 'false');
      showToast('已锁定会话并返回登录页', 'info');
      renderChat(container);
    };
  }

  // Admin button handler (Classic mode)
  const adminBtn = container.querySelector('#chat-admin-btn');
  const adminPanel = container.querySelector('#chat-admin-panel');
  if (adminBtn && adminPanel) {
    adminBtn.onclick = () => {
      adminPanel.style.display = adminPanel.style.display === 'none' ? 'block' : 'none';
    };
    const closeAdminBtn = container.querySelector('#chat-close-admin-btn');
    if (closeAdminBtn) closeAdminBtn.onclick = () => { adminPanel.style.display = 'none'; };
  }

  // Contact Switcher
  container.querySelectorAll('.contact-item, .chat-classic-contact').forEach(item => {
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

  // Classic Bar Attachment ("图")
  const attachBtn = container.querySelector('#attach-vault-btn');
  if (attachBtn) {
    attachBtn.onclick = () => {
      const filename = prompt('输入图片或 UFS/SafeFS 附件文件名发送 (例如: PHOTO.jpg 或 WELCOME.txt):', 'PHOTO.jpg');
      if (filename) {
        inputEl.value = `[图: ${filename} | ufs://${filename}]`;
        doSend();
      }
    };
  }

  // Classic Bar Video ("视")
  const videoBtn = container.querySelector('#video-attach-btn');
  if (videoBtn) {
    videoBtn.onclick = () => {
      const filename = prompt('输入视频附件名称发送 (例如: clip.mp4):', 'clip.mp4');
      if (filename) {
        inputEl.value = `[视: ${filename}]`;
        doSend();
      }
    };
  }

  // Classic Bar Voice ("音")
  const voiceBtn = container.querySelector('#voice-record-btn');
  if (voiceBtn) {
    voiceBtn.onclick = () => {
      if (!isVoiceRecording) {
        isVoiceRecording = true;
        showToast('正在录音… 再次点击发送', 'info');
        renderChat(container);
      } else {
        isVoiceRecording = false;
        inputEl.value = `[音: 语音 3秒]`;
        doSend();
        showToast('语音已发送', 'success');
      }
    };
  }
}
