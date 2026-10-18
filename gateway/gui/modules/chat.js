// ==============================================================================
// Module: WATChat End-to-End Encrypted Messenger with Dual UI Switcher
// ==============================================================================
import { State, t, showToast } from '../core.js';

let chatUiMode = localStorage.getItem('watchat_ui_mode') || 'minimalist'; // 'minimalist' | 'classic'
let activeContact = 'genesis-node';
let messagesStore = JSON.parse(localStorage.getItem('watchat_msgs') || 'null') || {
  'genesis-node': [
    { id: 1, sender: 'genesis-node', text: '欢迎加入 Ziokt 端到端加密通讯网络！所有消息均由 XChaCha20-Poly1305 密封。', time: '10:00' },
    { id: 2, sender: 'me', text: '收到！正在测试统一客户端的无缝双 UI 切换。', time: '10:02' },
    { id: 3, sender: 'genesis-node', text: '可在上方随时切换“现代简约版”与“经典丰富版”，加密会话状态实时无损保持。', time: '10:03' }
  ],
  'community-bot': [
    { id: 1, sender: 'community-bot', text: 'Corium 治理委员会 #48 提案已发起，欢迎前往社区论坛参与投票。', time: '09:15' }
  ]
};

export function renderChat(container) {
  const isMinimalist = chatUiMode === 'minimalist';

  container.innerHTML = `
    <div style="height: calc(100vh - var(--topbar-height) - 48px); display: flex; flex-direction: column;">
      <!-- WATChat Sub-Header: Dual UI Switcher -->
      <div style="background: var(--bg-card); border: 1px solid var(--border-subtle); border-radius: var(--radius-md) var(--radius-md) 0 0; padding: 10px 16px; display: flex; justify-content: space-between; align-items: center; border-bottom: none;">
        <div style="display: flex; align-items: center; gap: 10px;">
          <span style="font-weight: 700; color: var(--accent-cyan); font-size: 0.95rem;">💬 ${t('chat.title')}</span>
          <span class="status-badge" style="font-size: 0.7rem; color: var(--accent-green);">
            <span class="status-dot"></span> ${t('chat.encryption_badge')}
          </span>
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 0.78rem; color: var(--text-muted);">${t('chat.dual_ui')}:</span>
          <div style="display: inline-flex; background: var(--bg-input); padding: 2px; border-radius: var(--radius-sm); border: 1px solid var(--border-bright);">
            <button id="toggle-minimalist" class="btn btn-sm ${isMinimalist ? 'btn-primary' : 'btn-secondary'}" style="border:none;">${t('chat.ui_minimalist')}</button>
            <button id="toggle-classic" class="btn btn-sm ${!isMinimalist ? 'btn-primary' : 'btn-secondary'}" style="border:none;">${t('chat.ui_classic')}</button>
          </div>
        </div>
      </div>

      <!-- Main Chat Body -->
      <div class="chat-container" style="border-radius: 0 0 var(--radius-md) var(--radius-md); flex: 1;">
        
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
          <div style="padding: 12px 16px; border-top: 1px solid var(--border-subtle); background: var(--bg-sidebar);">
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
    localStorage.setItem('watchat_ui_mode', 'minimalist');
    showToast('已切换至 WATChat 现代简约版', 'info');
    renderChat(container);
  };

  container.querySelector('#toggle-classic').onclick = () => {
    chatUiMode = 'classic';
    localStorage.setItem('watchat_ui_mode', 'classic');
    showToast('已切换至 WATChat 经典丰富版 (含加密机密与中继状态)', 'info');
    renderChat(container);
  };

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
    localStorage.setItem('watchat_msgs', JSON.stringify(messagesStore));
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
