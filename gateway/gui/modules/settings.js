// ==============================================================================
// Module: System Settings, Local/Remote Node Management, Auth & Lifecycle
// ==============================================================================
import {
  State,
  t,
  showToast,
  showConfirm,
  setLanguage,
  setTheme,
  Events,
  setStorage,
  getRemoteNodes,
  getActiveRemoteNode,
  setActiveRemoteNode,
  addRemoteNode,
  removeRemoteNode,
  checkLocalNodeHealth,
  verifyRemoteNodeAuth,
  updateAppNodeBadge
} from '../core.js';

export function renderSettings(container) {
  if (!container) return;
  const isEn = State.language === 'en';
  const comps = State.components || {};
  const remoteNodes = getRemoteNodes();
  const activeNode = getActiveRemoteNode();

  const isLocal = State.runtimeMode === 'local';
  const isLocalOnline = State.localNodeStatus === 'online';
  const isLocalChecking = State.localNodeStatus === 'checking';

  container.innerHTML = `
    <div style="max-width: 950px; margin: 0 auto;">
      ${isLocal && !isLocalOnline ? `
        <!-- Local Node Required Top Warning Banner -->
        <div style="background: rgba(239, 68, 68, 0.12); border: 1.5px solid var(--accent-red); border-radius: var(--radius-md); padding: 18px 20px; margin-bottom: 24px;">
          <div style="display: flex; align-items: flex-start; gap: 14px;">
            <span style="font-size: 1.8rem; line-height: 1;">⚠️</span>
            <div style="flex: 1;">
              <h3 style="color: var(--accent-red); margin-bottom: 6px; font-size: 1.05rem; font-weight: 700;">
                ${isEn ? 'Local Node Required — Only Settings Accessible' : '本地真实节点未运行 — 当前仅开放系统设置'}
              </h3>
              <p style="color: var(--text-main); font-size: 0.85rem; line-height: 1.6; margin-bottom: 12px;">
                ${isEn
                  ? 'You are currently in Local Node Mode, but no Ziokt daemon is detected at http://127.0.0.1:8185. All other tabs (Home, Chat, Files, Apps, Identity, etc.) are locked until a real node is verified, or until you switch to a remote gateway.'
                  : '当前客户端处于【本地节点】模式，但未在本地检测到运行中的 Ziokt 节点服务 (http://127.0.0.1:8185)。在本地真实节点启动前，总览、聊天、文件存储、身份等其他选项卡已锁定。您可以启动本地节点后重试探测，或在此直接切换至远程网关。'}
              </p>
              <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                <button id="settings-probe-top-btn" class="btn btn-primary btn-sm">⚡ ${isEn ? 'Probe Local Node (8185)' : '立即探测本地节点 (8185)'}</button>
                <button id="settings-switch-remote-top-btn" class="btn btn-secondary btn-sm">🌐 ${isEn ? 'One-Click Switch to Remote Gateway' : '一键切换至远程网关'}</button>
              </div>
            </div>
          </div>
        </div>
      ` : ''}

      <!-- Header -->
      <div style="margin-bottom: 24px;">
        <h2 style="font-size: 1.25rem; font-weight: 700; color: var(--accent-cyan);">${t('settings.title')}</h2>
        <p style="font-size: 0.82rem; color: var(--text-muted);">${isEn ? 'Configure local/remote node topology, authentication credentials, component lifecycle, themes and accessibility' : '配置本地/远程节点拓扑、身份鉴权凭证、组件按需生命周期、外观主题与无障碍交互'}</p>
      </div>

      <!-- Runtime Mode Selection -->
      <div class="card" style="margin-bottom: 20px;">
        <div class="card-title" style="margin-bottom: 14px;">
          <span>${t('settings.runtime_mode')}</span>
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; margin-bottom: 12px;">
          <div>
            <label style="display: block; font-size: 0.78rem; color: var(--text-muted); margin-bottom: 6px;">${isEn ? 'Runtime Mode' : '客户端运行模式'}</label>
            <select id="setting-mode-select" class="input-select">
              <option value="local" ${State.runtimeMode === 'local' ? 'selected' : ''}>${t('app.mode_local')} (${isEn ? 'Local Private Environment' : '纯本地私有节点环境'})</option>
              <option value="remote" ${State.runtimeMode === 'remote' ? 'selected' : ''}>${t('app.mode_remote')} (${isEn ? 'Remote Gateway Node' : '连接远程主网关'})</option>
              <option value="hybrid" ${State.runtimeMode === 'hybrid' ? 'selected' : ''}>${t('app.mode_hybrid')} (${isEn ? 'Local Storage + Remote Relay' : '本地存储 + 远程共识中继'})</option>
            </select>
          </div>
          <div>
            <label style="display: block; font-size: 0.78rem; color: var(--text-muted); margin-bottom: 6px;">${isEn ? 'Active Gateway Endpoint' : '当前生效网关端点'}</label>
            <input type="text" id="setting-gateway-input" class="input-text" value="${isLocal ? State.localGatewayUrl : (activeNode?.url || State.gatewayUrl)}">
          </div>
        </div>
        <div style="font-size: 0.78rem; color: var(--text-dim); line-height: 1.5;">
          ${isLocal
            ? (isEn ? '💡 Local mode routes all RPC and transactions directly to localhost. A real running Ziokt node is required.' : '💡 本地模式将所有 RPC 与交互直接打入本地主机。本机必须真实运行有 Ziokt 节点服务。')
            : (isEn ? '💡 Remote mode routes traffic through an authenticated cloud gateway. Authentication token is mandatory.' : '💡 远程模式通过云端可信网关中继访问，必须配置有效的访问鉴权 Token。')}
        </div>
      </div>

      <!-- Local Node Real Probe & Health (Mandatory for Local Mode) -->
      <div class="card" style="margin-bottom: 20px; border-left: 4px solid ${isLocalOnline ? 'var(--accent-green)' : (isLocalChecking ? 'var(--accent-amber)' : 'var(--accent-red)')};">
        <div class="card-title" style="margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center;">
          <span>${t('settings.local_node_title')}</span>
          <span class="status-badge" style="color: ${isLocalOnline ? 'var(--accent-green)' : (isLocalChecking ? 'var(--accent-amber)' : 'var(--accent-red)')};">
            <span class="status-dot" style="background-color: ${isLocalOnline ? 'var(--accent-green)' : (isLocalChecking ? 'var(--accent-amber)' : 'var(--accent-red)')};"></span>
            ${isLocalChecking ? t('settings.local_node_checking') : (isLocalOnline ? t('settings.local_node_online') : t('settings.local_node_offline'))}
          </span>
        </div>
        <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 14px;">${t('settings.local_node_desc')}</p>
        
        <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 14px;">
          <input type="text" id="setting-local-url-input" class="input-text" style="max-width: 300px; font-family: var(--font-mono); font-size: 0.85rem;" value="${State.localGatewayUrl}">
          <button id="probe-local-node-btn" class="btn btn-secondary btn-sm">⚡ ${t('settings.local_node_probe')}</button>
          ${isLocalOnline ? `<span style="font-size: 0.78rem; color: var(--accent-green);">✓ HTTP 200 OK (${State.localNodeDetails?.network || 'ziokt-main'})</span>` : ''}
        </div>

        ${!isLocalOnline && !isLocalChecking ? `
          <div style="background: rgba(239, 68, 68, 0.08); border: 1px dashed rgba(239, 68, 68, 0.4); border-radius: var(--radius-sm); padding: 12px; font-size: 0.78rem; color: var(--accent-red);">
            <strong>${isEn ? 'Notice:' : '节点未就绪提示:'}</strong> ${t('settings.local_node_help')}
          </div>
        ` : ''}
      </div>

      <!-- Remote Node Gateways & Auth Management -->
      <div class="card" style="margin-bottom: 20px;">
        <div class="card-title" style="margin-bottom: 12px;">
          <span>${t('settings.remote_nodes_title')}</span>
          <span style="font-size: 0.72rem; color: var(--accent-purple); font-weight: normal;">${isEn ? 'Custom Endpoints & Auth Tokens' : '支持多节点切换与鉴权配置'}</span>
        </div>
        <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 16px;">${t('settings.remote_nodes_desc')}</p>

        <!-- Configured Nodes List -->
        <div style="display: flex; flex-direction: column; gap: 12px; margin-bottom: 20px;">
          ${remoteNodes.map(node => {
            const isActive = node.id === activeNode?.id;
            const hasToken = !!(node.authToken && node.authToken.trim());
            const statusColor = node.status === 'online' ? 'var(--accent-green)' : (node.status === 'unauthenticated' ? 'var(--accent-amber)' : (node.status === 'auth_failed' ? 'var(--accent-red)' : 'var(--text-dim)'));
            const statusText = node.status === 'online' ? `${t('settings.auth_valid')} (${node.latency || '15ms'})` : (node.status === 'unauthenticated' ? t('settings.auth_required') : (node.status === 'auth_failed' ? t('settings.auth_invalid') : (node.status === 'offline' ? t('app.status_offline') : '未验证')));

            return `
              <div style="background: var(--bg-input); border: 1px solid ${isActive ? 'var(--accent-cyan)' : 'var(--border-subtle)'}; border-radius: var(--radius-sm); padding: 14px 16px;">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 10px; margin-bottom: 10px;">
                  <div>
                    <div style="display: flex; align-items: center; gap: 8px;">
                      <span style="font-weight: 600; font-size: 0.92rem; color: var(--text-main);">${node.name}</span>
                      ${isActive ? `<span class="badge" style="background: rgba(2,132,199,0.2); color: var(--accent-cyan); font-size: 0.68rem; padding: 2px 6px; border-radius: 4px;">${t('settings.active_badge')}</span>` : ''}
                      ${node.isDefault ? `<span class="badge" style="background: rgba(147,51,234,0.15); color: var(--accent-purple); font-size: 0.68rem; padding: 2px 6px; border-radius: 4px;">${isEn ? 'System Default' : '官方默认'}</span>` : ''}
                    </div>
                    <div style="font-size: 0.78rem; font-family: var(--font-mono); color: var(--text-dim); margin-top: 3px;">${node.url}</div>
                  </div>
                  <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 0.75rem; color: ${statusColor}; font-weight: 600;">● ${statusText}</span>
                    <button class="btn btn-secondary btn-sm test-node-btn" data-id="${node.id}" title="${t('settings.test_auth')}">⚡ ${t('settings.test_auth')}</button>
                    ${!isActive ? `<button class="btn btn-primary btn-sm activate-node-btn" data-id="${node.id}">${t('settings.set_active')}</button>` : ''}
                    ${!node.isDefault ? `<button class="btn btn-danger btn-sm delete-node-btn" data-id="${node.id}" title="${t('settings.delete_node')}">🗑️</button>` : ''}
                  </div>
                </div>

                <!-- Auth Token row -->
                <div style="display: flex; gap: 10px; align-items: center; margin-top: 8px;">
                  <span style="font-size: 0.72rem; color: var(--text-muted); flex-shrink: 0;">${t('settings.auth_token')}:</span>
                  <input type="password" class="input-text node-token-input" data-id="${node.id}" value="${node.authToken || ''}" placeholder="${t('settings.auth_token_tip')}" style="font-size: 0.78rem; font-family: var(--font-mono); height: 30px; padding: 4px 8px;">
                  <button class="btn btn-secondary btn-sm save-token-btn" data-id="${node.id}" style="height: 30px; padding: 2px 10px; font-size: 0.75rem;">${t('common.save')}</button>
                </div>
              </div>
            `;
          }).join('')}
        </div>

        <!-- Add Custom Remote Node Form -->
        <div style="border-top: 1px solid var(--border-subtle); padding-top: 16px;">
          <h4 style="font-size: 0.88rem; font-weight: 600; color: var(--text-main); margin-bottom: 12px;">+ ${t('settings.add_node')}</h4>
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-bottom: 12px;">
            <div>
              <label style="display: block; font-size: 0.75rem; color: var(--text-muted); margin-bottom: 4px;">${t('settings.node_name')}</label>
              <input type="text" id="new-node-name" class="input-text" placeholder="e.g. 自建私有网关 / Private Cloud Gateway">
            </div>
            <div>
              <label style="display: block; font-size: 0.75rem; color: var(--text-muted); margin-bottom: 4px;">${t('settings.node_url')}</label>
              <input type="text" id="new-node-url" class="input-text" placeholder="https://gateway.example.com">
            </div>
            <div>
              <label style="display: block; font-size: 0.75rem; color: var(--text-muted); margin-bottom: 4px;">${t('settings.auth_token')}</label>
              <input type="password" id="new-node-token" class="input-text" placeholder="ziokt_sec_...">
            </div>
          </div>
          <button id="add-node-btn" class="btn btn-primary btn-sm">+ ${t('settings.add_node_btn')}</button>
        </div>
      </div>

      <!-- On-Demand Component Launcher -->
      <div class="card" style="margin-bottom: 20px;">
        <div class="card-title" style="margin-bottom: 12px;">
          <span>${t('settings.components_lifecycle')}</span>
          <span style="font-size: 0.72rem; color: var(--accent-cyan); font-weight: normal;">${isEn ? 'On-demand loading to save system overhead' : '按需独立加载，避免强制全量开销'}</span>
        </div>
        <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 14px;">${isEn ? 'The client does not mandate all daemon processes to run permanently. You can toggle local background microservices freely:' : '客户端无需强制常驻所有服务，您可以根据使用场景自由启闭本地后台进程：'}</p>
        
        <div style="display: flex; flex-direction: column; gap: 10px;">
          ${Object.entries(comps).map(([key, comp]) => {
            const status = (comp?.status || 'offline').toLowerCase();
            const isOnline = status === 'online';
            return `
            <div style="background: var(--bg-input); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 12px 16px; display: flex; justify-content: space-between; align-items: center;">
              <div>
                <div style="font-weight: 600; font-size: 0.9rem; color: var(--text-main);">${comp?.name || key}</div>
                <div style="font-size: 0.75rem; color: var(--text-dim); font-family: var(--font-mono);">${isEn ? 'Local Port' : '本地端口'}: ${comp?.port || 'N/A'} &bull; ${isEn ? 'Status' : '状态'}: <span style="color:${isOnline ? 'var(--accent-green)' : 'var(--accent-red)'}">${status.toUpperCase()}</span></div>
              </div>
              <button class="btn btn-sm ${isOnline ? 'btn-danger' : 'btn-primary'} toggle-comp-btn" data-key="${key}">
                ${isOnline ? (isEn ? '⏹️ Stop Service' : '⏹️ 停止服务') : (isEn ? '▶️ Start Service' : '▶️ 启动服务')}
              </button>
            </div>
            `;
          }).join('')}
        </div>
      </div>

      <!-- Theme & Language -->
      <div class="grid-cards" style="margin-bottom: 20px;">
        <div class="card">
          <div class="card-title"><span>${isEn ? 'Appearance Theme' : '外观主题'}</span></div>
          <div style="display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap;">
            <button class="btn btn-sm ${State.theme === 'dark' ? 'btn-primary' : 'btn-secondary'} theme-btn" data-theme="dark">🌙 ${t('app.theme_dark')}</button>
            <button class="btn btn-sm ${State.theme === 'light' ? 'btn-primary' : 'btn-secondary'} theme-btn" data-theme="light">☀️ ${t('app.theme_light')}</button>
            <button class="btn btn-sm ${State.theme === 'contrast' ? 'btn-primary' : 'btn-secondary'} theme-btn" data-theme="contrast">⚡ ${t('app.theme_contrast')}</button>
          </div>
        </div>

        <div class="card">
          <div class="card-title"><span>语言 / Language</span></div>
          <div style="display: flex; gap: 8px; margin-top: 10px;">
            <button class="btn btn-sm ${State.language === 'zh' ? 'btn-primary' : 'btn-secondary'} lang-btn" data-lang="zh">🇨🇳 简体中文</button>
            <button class="btn btn-sm ${State.language === 'en' ? 'btn-primary' : 'btn-secondary'} lang-btn" data-lang="en">🇬🇧 English</button>
          </div>
        </div>
      </div>

      <!-- Accessibility & Keyboard Shortcuts -->
      <div class="card" style="margin-bottom: 20px;">
        <div class="card-title" style="margin-bottom: 10px;">
          <span>${t('settings.accessibility')}</span>
        </div>
        <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 12px;">${t('settings.keyboard_shortcuts')}</p>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 8px; font-size: 0.78rem; font-family: var(--font-mono); color: var(--accent-cyan);">
          <div>[1] ${isEn ? 'Home Overview' : '首页总览'}</div>
          <div>[2] ${isEn ? 'WATChat Comms' : 'WATChat 通讯'}</div>
          <div>[3] ${isEn ? 'Community Forum' : '社区论坛'}</div>
          <div>[4] ${isEn ? 'Safe Storage' : '安全存储'}</div>
          <div>[5] ${isEn ? 'App Store' : '应用中心'}</div>
          <div>[6] ${isEn ? 'Mesh Nodes' : '网络节点'}</div>
          <div>[7] ${isEn ? 'Identity & Stake' : '身份与贡献'}</div>
          <div>[8] ${isEn ? 'Dev Tools' : '开发工具'}</div>
          <div>[9] ${isEn ? 'System Settings' : '系统设置'}</div>
        </div>
      </div>

      <!-- Danger Zone / Cache Clearing -->
      <div class="card" style="border-color: rgba(239, 68, 68, 0.4);">
        <div class="card-title" style="color: var(--accent-red); margin-bottom: 8px;">
          <span>${isEn ? 'Danger Zone / Cache Reset' : '危险操作 / 缓存清理'}</span>
        </div>
        <p style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 12px;">${isEn ? 'Reset local client cache and session state. On-chain ciphertext in UFS/SafeFS will not be deleted:' : '重置本地缓存、断开网关会话，但不会删除您存储在 UFS/SafeFS 中的链上物理密文：'}</p>
        <button id="clear-cache-btn" class="btn btn-danger btn-sm">${isEn ? 'Clear Local Cache & Reset Session' : '清除客户端本地缓存并重置会话'}</button>
      </div>

    </div>
  `;

  // Runtime Mode Switcher
  const modeSelect = container.querySelector('#setting-mode-select');
  if (modeSelect) {
    modeSelect.onchange = async (e) => {
      State.runtimeMode = e.target.value;
      setStorage('ziokt_mode', e.target.value);
      if (State.runtimeMode === 'local') {
        await checkLocalNodeHealth();
      }
      updateAppNodeBadge();
      showToast(isEn ? `Runtime mode switched to ${e.target.value.toUpperCase()}` : `客户端运行模式已切换为: ${e.target.value.toUpperCase()}`, 'info');
      renderSettings(container);
    };
  }

  // Gateway input listener
  const gwInput = container.querySelector('#setting-gateway-input');
  if (gwInput) {
    gwInput.onchange = (e) => {
      const val = e.target.value.trim();
      if (State.runtimeMode === 'local') {
        State.localGatewayUrl = val;
      } else {
        State.gatewayUrl = val;
        setStorage('ziokt_gateway', val);
      }
      showToast(isEn ? 'Endpoint saved' : '端点已更新', 'success');
    };
  }

  // Top Offline Banner Buttons
  const topProbeBtn = container.querySelector('#settings-probe-top-btn');
  if (topProbeBtn) {
    topProbeBtn.onclick = async () => {
      topProbeBtn.disabled = true;
      topProbeBtn.textContent = '...';
      const res = await checkLocalNodeHealth();
      topProbeBtn.disabled = false;
      topProbeBtn.textContent = `⚡ ${isEn ? 'Probe Local Node (8185)' : '立即探测本地节点 (8185)'}`;
      if (res.ok) {
        showToast(isEn ? 'Local node verified online!' : '本地真实节点检测通过，状态在线！', 'success');
      } else {
        showToast(isEn ? `Local node unreachable: ${res.error}` : `本地真实节点未响应: ${res.error}`, 'error');
      }
      renderSettings(container);
    };
  }
  const topSwitchBtn = container.querySelector('#settings-switch-remote-top-btn');
  if (topSwitchBtn) {
    topSwitchBtn.onclick = () => {
      State.runtimeMode = 'remote';
      setStorage('ziokt_mode', 'remote');
      updateAppNodeBadge();
      showToast(isEn ? 'Switched to Remote Gateway mode' : '已切换至远程网关模式', 'success');
      renderSettings(container);
    };
  }

  // Local Node Probe Button
  const probeLocalBtn = container.querySelector('#probe-local-node-btn');
  const localUrlInput = container.querySelector('#setting-local-url-input');
  if (probeLocalBtn) {
    probeLocalBtn.onclick = async () => {
      if (localUrlInput) {
        State.localGatewayUrl = localUrlInput.value.trim();
      }
      probeLocalBtn.disabled = true;
      probeLocalBtn.textContent = isEn ? 'Probing...' : '正在探测...';
      const res = await checkLocalNodeHealth();
      probeLocalBtn.disabled = false;
      probeLocalBtn.textContent = `⚡ ${t('settings.local_node_probe')}`;
      if (res.ok) {
        showToast(isEn ? 'Local node verified successfully!' : '本地真实节点检测通过，状态在线！', 'success');
      } else {
        showToast(isEn ? `Local node unreachable: ${res.error}` : `本地真实节点未响应: ${res.error}`, 'error');
      }
      renderSettings(container);
    };
  }

  // Remote Node - Test Auth
  container.querySelectorAll('.test-node-btn').forEach(btn => {
    btn.onclick = async () => {
      const id = btn.dataset.id;
      btn.disabled = true;
      btn.textContent = '...';
      const res = await verifyRemoteNodeAuth(id);
      btn.disabled = false;
      btn.textContent = `⚡ ${t('settings.test_auth')}`;
      if (res.ok) {
        showToast(isEn ? `Node auth verified! Latency: ${res.latency}` : `节点鉴权成功！延迟: ${res.latency}`, 'success');
      } else {
        showToast(isEn ? `Auth failed: ${res.error}` : `节点鉴权未通过: ${res.error}`, 'error');
      }
      renderSettings(container);
    };
  });

  // Remote Node - Activate Node
  container.querySelectorAll('.activate-node-btn').forEach(btn => {
    btn.onclick = () => {
      const id = btn.dataset.id;
      setActiveRemoteNode(id);
      showToast(isEn ? 'Active node updated' : '当前生效远程节点已切换', 'success');
      renderSettings(container);
    };
  });

  // Remote Node - Save Token
  container.querySelectorAll('.save-token-btn').forEach(btn => {
    btn.onclick = () => {
      const id = btn.dataset.id;
      const input = container.querySelector(`.node-token-input[data-id="${id}"]`);
      if (input) {
        const val = input.value.trim();
        const nodes = getRemoteNodes();
        const target = nodes.find(n => n.id === id);
        if (target) {
          target.authToken = val;
          setStorage('ziokt_remote_nodes', JSON.stringify(nodes));
          if (State.activeRemoteNodeId === id) {
            setStorage('ziokt_auth_token', val);
            State.authToken = val;
          }
          showToast(isEn ? 'Auth token saved for node' : '节点鉴权凭证已保存', 'success');
          renderSettings(container);
        }
      }
    };
  });

  // Remote Node - Delete Node
  container.querySelectorAll('.delete-node-btn').forEach(btn => {
    btn.onclick = async () => {
      const id = btn.dataset.id;
      const ok = await showConfirm(
        isEn ? 'Delete Remote Node' : '删除远程节点',
        isEn ? 'Are you sure you want to remove this custom remote node?' : '确定要删除此自定义远程节点吗？'
      );
      if (ok) {
        try {
          removeRemoteNode(id);
          showToast(isEn ? 'Remote node removed' : '远程节点已删除', 'success');
          renderSettings(container);
        } catch (e) {
          showToast(e.message, 'error');
        }
      }
    };
  });

  // Add Custom Remote Node
  const addBtn = container.querySelector('#add-node-btn');
  if (addBtn) {
    addBtn.onclick = async () => {
      const nameInput = container.querySelector('#new-node-name');
      const urlInput = container.querySelector('#new-node-url');
      const tokenInput = container.querySelector('#new-node-token');

      const name = nameInput.value.trim();
      const url = urlInput.value.trim();
      const token = tokenInput.value.trim();

      if (!url) {
        showToast(isEn ? 'Node URL is required' : '节点 URL 不能为空', 'error');
        return;
      }
      if (!url.startsWith('http://') && !url.startsWith('https://')) {
        showToast(isEn ? 'URL must start with http:// or https://' : '节点 URL 必须以 http:// 或 https:// 开头', 'error');
        return;
      }
      if (!token) {
        showToast(isEn ? 'Auth Token is required for remote node' : '使用远程节点必须配置鉴权凭证 (Auth Token)', 'error');
        return;
      }

      const newNode = addRemoteNode({ name: name || url, url, authToken: token });
      showToast(isEn ? 'Custom remote node added, testing authentication...' : '自定义远程节点已添加，正在测试鉴权...', 'info');

      // Immediate verify
      const res = await verifyRemoteNodeAuth(newNode.id);
      if (res.ok) {
        showToast(isEn ? 'New node authenticated and ready!' : '新节点鉴权成功，随时可切换使用！', 'success');
      } else {
        showToast(isEn ? `Node added but auth failed: ${res.error}` : `节点已添加，但鉴权未通过: ${res.error}`, 'error');
      }
      renderSettings(container);
    };
  }

  // Component Toggles
  container.querySelectorAll('.toggle-comp-btn').forEach(btn => {
    btn.onclick = () => {
      const key = btn.dataset.key;
      const comp = State.components[key];
      if (comp) {
        comp.status = comp.status === 'online' ? 'offline' : 'online';
        showToast(isEn ? `${comp.name} status updated: ${comp.status.toUpperCase()}` : `${comp.name} 状态已更新为: ${comp.status.toUpperCase()}`, comp.status === 'online' ? 'success' : 'info');
        renderSettings(container);
      }
    };
  });

  // Theme Toggles
  container.querySelectorAll('.theme-btn').forEach(btn => {
    btn.onclick = () => {
      setTheme(btn.dataset.theme);
      showToast(isEn ? `Theme switched to: ${btn.textContent}` : `主题已切换为: ${btn.textContent}`, 'info');
      renderSettings(container);
    };
  });

  // Language Toggles
  container.querySelectorAll('.lang-btn').forEach(btn => {
    btn.onclick = async () => {
      await setLanguage(btn.dataset.lang);
      showToast(`Language switched to: ${btn.textContent}`, 'info');
      renderSettings(container);
    };
  });

  // Clear Cache
  const clearBtn = container.querySelector('#clear-cache-btn');
  if (clearBtn) {
    clearBtn.onclick = async () => {
      const ok = await showConfirm(
        isEn ? 'Reset Confirmation' : '重置确认',
        isEn ? 'Are you sure you want to clear all local sessions and caches? The app will reset to defaults.' : '确定要清空本地所有会话与缓存吗？应用将恢复初始设置。'
      );
      if (ok) {
        try { localStorage.clear(); } catch(e) {}
        showToast(isEn ? 'Cache cleared, resetting client...' : '缓存已清空，正在重置客户端...', 'success');
        setTimeout(() => location.reload(), 800);
      }
    };
  }
}
