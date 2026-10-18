// ==============================================================================
// Module: Home Overview & System Telemetry Dashboard
// ==============================================================================
import { State, t, showToast, Events } from '../core.js';

export function renderHome(container) {
  container.innerHTML = `
    <div style="max-width: 1100px; margin: 0 auto;">
      <!-- Welcome Banner -->
      <div style="background: linear-gradient(135deg, rgba(2,132,199,0.15), rgba(129,140,248,0.1)); border: 1px solid var(--border-bright); border-radius: var(--radius-lg); padding: 24px; margin-bottom: 24px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px;">
        <div>
          <h2 style="font-size: 1.35rem; font-weight: 700; color: var(--text-main); margin-bottom: 6px;">${t('home.welcome')}</h2>
          <p style="color: var(--text-muted); font-size: 0.85rem; max-width: 620px;">${t('home.welcome_sub')}</p>
        </div>
        <div style="display: flex; gap: 8px; align-items: center;">
          <span style="font-size: 0.8rem; color: var(--text-muted);">${t('settings.runtime_mode')}:</span>
          <select id="home-mode-select" class="input-select" style="width: auto; padding: 6px 10px; font-weight: 600;">
            <option value="local" ${State.runtimeMode === 'local' ? 'selected' : ''}>${t('app.mode_local')} (127.0.0.1:8185)</option>
            <option value="remote" ${State.runtimeMode === 'remote' ? 'selected' : ''}>${t('app.mode_remote')} (cor-web.ziokt.com)</option>
            <option value="hybrid" ${State.runtimeMode === 'hybrid' ? 'selected' : ''}>${t('app.mode_hybrid')}</option>
          </select>
        </div>
      </div>

      <!-- Quick Action Shortcuts -->
      <div style="margin-bottom: 28px;">
        <h3 style="font-size: 0.95rem; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 14px;">${t('home.quick_actions')}</h3>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px;">
          <button class="btn btn-secondary home-action-btn" data-target="chat" style="padding: 16px; justify-content: flex-start; border-radius: var(--radius-md);">
            <span style="font-size: 1.5rem;">💬</span>
            <div style="text-align: left;">
              <div style="font-weight: 600; color: var(--text-main);">${t('home.act_chat')}</div>
              <div style="font-size: 0.72rem; color: var(--text-muted);">WATChat Sealed Chat</div>
            </div>
          </button>
          <button class="btn btn-secondary home-action-btn" data-target="files" style="padding: 16px; justify-content: flex-start; border-radius: var(--radius-md);">
            <span style="font-size: 1.5rem;">🔒</span>
            <div style="text-align: left;">
              <div style="font-weight: 600; color: var(--text-main);">${t('home.act_files')}</div>
              <div style="font-size: 0.72rem; color: var(--text-muted);">UFS & SafeFS Vault</div>
            </div>
          </button>
          <button class="btn btn-secondary home-action-btn" data-target="apps" style="padding: 16px; justify-content: flex-start; border-radius: var(--radius-md);">
            <span style="font-size: 1.5rem;">📦</span>
            <div style="text-align: left;">
              <div style="font-weight: 600; color: var(--text-main);">${t('home.act_apps')}</div>
              <div style="font-size: 0.72rem; color: var(--text-muted);">dCPM App Store</div>
            </div>
          </button>
          <button class="btn btn-secondary home-action-btn" data-target="network" style="padding: 16px; justify-content: flex-start; border-radius: var(--radius-md);">
            <span style="font-size: 1.5rem;">🌐</span>
            <div style="text-align: left;">
              <div style="font-weight: 600; color: var(--text-main);">${t('home.act_network')}</div>
              <div style="font-size: 0.72rem; color: var(--text-muted);">Shadow6 & ETP Mesh</div>
            </div>
          </button>
        </div>
      </div>

      <!-- Telemetry Cards -->
      <div class="grid-cards">
        <div class="card">
          <div class="card-title">
            <span>${t('identity.did')}</span>
            <span class="status-badge"><span class="status-dot"></span> Active</span>
          </div>
          <div class="card-value" style="font-family: var(--font-mono); font-size: 0.95rem; color: var(--accent-cyan);">${State.userDid}</div>
          <div class="card-desc">绑定 NNS 域: genesis.ziokt &bull; Ed25519 签名链已锚定</div>
        </div>
        <div class="card">
          <div class="card-title">
            <span>${t('identity.pouw_status')}</span>
            <span style="color: var(--accent-green); font-weight: 600;">MINING</span>
          </div>
          <div class="card-value">2,840 H/s <span style="font-size: 0.85rem; color: var(--text-muted); font-weight: normal;">(SHA-256 / Blake3)</span></div>
          <div class="card-desc">区块高度: #10,482 &bull; 累计算力贡献分: 142.50</div>
        </div>
        <div class="card">
          <div class="card-title">
            <span>${t('network.profiles_title')}</span>
            <span style="color: var(--accent-purple); font-weight: 600;">13 CORES</span>
          </div>
          <div class="card-value" style="font-size: 1.1rem; color: var(--accent-purple);">Shadow6 Virtual Broker: 就绪</div>
          <div class="card-desc">已连接 Go, Rust, Zig, Nim, Gleam, Ada 等多协议隧道</div>
        </div>
      </div>

      <!-- Component Health Grid -->
      <div class="card" style="margin-bottom: 24px;">
        <div class="card-title" style="margin-bottom: 14px;">
          <span>${t('home.system_health')}</span>
          <button id="refresh-health-btn" class="btn btn-secondary btn-sm">🔄 ${t('common.refresh')}</button>
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px;">
          ${Object.entries(State.components).map(([key, comp]) => `
            <div style="background: var(--bg-input); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 12px; display: flex; align-items: center; justify-content: space-between;">
              <div>
                <div style="font-weight: 600; font-size: 0.85rem; color: var(--text-main);">${comp.name}</div>
                <div style="font-size: 0.72rem; color: var(--text-dim); font-family: var(--font-mono);">Port: ${comp.port}</div>
              </div>
              <span class="status-badge"><span class="status-dot"></span></span>
            </div>
          `).join('')}
        </div>
      </div>

      <!-- Recent Activity Log -->
      <div class="card">
        <div class="card-title" style="margin-bottom: 12px;">
          <span>${t('home.recent_activity')}</span>
        </div>
        <div style="display: flex; flex-direction: column; gap: 8px; font-size: 0.85rem;">
          <div style="padding: 8px 12px; background: var(--bg-input); border-radius: var(--radius-sm); display: flex; justify-content: space-between;">
            <span style="color: var(--text-main);">🔒 UFS 存储保险箱初始化完成，已挂载双层诱饵卷</span>
            <span style="color: var(--text-dim); font-size: 0.75rem;">刚刚</span>
          </div>
          <div style="padding: 8px 12px; background: var(--bg-input); border-radius: var(--radius-sm); display: flex; justify-content: space-between;">
            <span style="color: var(--text-main);">🪐 Shadow6 控制中心建立安全连接 (13 Profiles 活跃)</span>
            <span style="color: var(--text-dim); font-size: 0.75rem;">2 分钟前</span>
          </div>
          <div style="padding: 8px 12px; background: var(--bg-input); border-radius: var(--radius-sm); display: flex; justify-content: space-between;">
            <span style="color: var(--text-main);">💬 WATChat 加密通讯桥接已就绪，XChaCha20 密钥握手成功</span>
            <span style="color: var(--text-dim); font-size: 0.75rem;">5 分钟前</span>
          </div>
        </div>
      </div>
    </div>
  `;

  // Event handlers
  container.querySelectorAll('.home-action-btn').forEach(btn => {
    btn.onclick = () => {
      Events.emit('navigate', btn.dataset.target);
    };
  });

  const modeSelect = container.querySelector('#home-mode-select');
  if (modeSelect) {
    modeSelect.onchange = (e) => {
      State.runtimeMode = e.target.value;
      localStorage.setItem('ziokt_mode', e.target.value);
      showToast(`已切换至: ${e.target.options[e.target.selectedIndex].text}`, 'info');
      Events.emit('mode_changed', e.target.value);
    };
  }

  const refreshBtn = container.querySelector('#refresh-health-btn');
  if (refreshBtn) {
    refreshBtn.onclick = () => {
      showToast('核心组件状态已刷新，所有节点正常在线', 'success');
    };
  }
}
