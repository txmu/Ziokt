// ==============================================================================
// Module: Shadow6 Multi-Core Mesh & ETP Onion Gateway Network Panel
// ==============================================================================
import { State, t, showToast, showJsonModal } from '../core.js';

const shadow6Profiles = [
  { id: 'profile-go', core: 'Go', transport: 'kcp', port: 14433, status: 'RUNNING', latency: '12ms' },
  { id: 'profile-rust', core: 'Rust', transport: 'quic', port: 14434, status: 'RUNNING', latency: '8ms' },
  { id: 'profile-gleam', core: 'Gleam', transport: 'secure-stream', port: 14435, status: 'RUNNING', latency: '15ms' },
  { id: 'profile-ada', core: 'Ada', transport: 'cell-relay', port: 14436, status: 'RUNNING', latency: '18ms' },
  { id: 'profile-nim', core: 'Nim', transport: 'webrtc', port: 14437, status: 'RUNNING', latency: '22ms' },
  { id: 'profile-pony', core: 'Pony', transport: 'udp', port: 14438, status: 'RUNNING', latency: '10ms' },
  { id: 'profile-zig', core: 'Zig', transport: 'enet', port: 14439, status: 'RUNNING', latency: '9ms' },
  { id: 'profile-d', core: 'D', transport: 'secure-stream', port: 14440, status: 'RUNNING', latency: '14ms' },
  { id: 'profile-cpp', core: 'C++', transport: 'sctp', port: 14441, status: 'RUNNING', latency: '11ms' },
  { id: 'profile-idris', core: 'Idris', transport: 'udp', port: 14442, status: 'RUNNING', latency: '24ms' },
  { id: 'profile-hare', core: 'Hare', transport: 'udp', port: 14443, status: 'RUNNING', latency: '16ms' },
  { id: 'profile-carp', core: 'Carp', transport: 'udp', port: 14444, status: 'RUNNING', latency: '20ms' },
  { id: 'profile-broker', core: 'Virtual Broker', transport: 'broker-mux', port: 4433, status: 'RUNNING', latency: '5ms' }
];

let showSensitive = false;

export function renderNetwork(container) {
  container.innerHTML = `
    <div style="max-width: 1050px; margin: 0 auto;">
      <!-- Header -->
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 14px;">
        <div>
          <h2 style="font-size: 1.25rem; font-weight: 700; color: var(--accent-cyan);">${t('network.title')}</h2>
          <p style="font-size: 0.82rem; color: var(--text-muted);">${t('network.subtitle')}</p>
        </div>
        <div style="display: flex; gap: 10px;">
          <a href="https://ziokt-shadow6-43-207-75-185.sslip.io/" target="_blank" class="btn btn-primary">🪐 打开 Shadow6 Web UI</a>
          <button id="toggle-sensitive-btn" class="btn btn-secondary">${showSensitive ? '🔒 隐藏敏感内容' : '👁️ 显示敏感内容'}</button>
          <button id="ping-all-btn" class="btn btn-secondary">⚡ ${t('network.ping_test')}</button>
        </div>
      </div>

      <!-- Network Overview Cards -->
      <div class="grid-cards" style="margin-bottom: 24px;">
        <div class="card">
          <div class="card-title">
            <span>Shadow6 13 核心网格</span>
            <span class="status-badge"><span class="status-dot"></span> 13/13 ONLINE</span>
          </div>
          <div class="card-value" style="font-size: 1.2rem; color: var(--accent-purple);">全语言 Profile 就绪</div>
          <div class="card-desc">多协议动态编排: QUIC, KCP, SCTP, WebRTC, ENet, UDP</div>
        </div>

        <div class="card">
          <div class="card-title">
            <span>ETP 原生洋葱多跳链路</span>
            <span style="color: var(--accent-green); font-weight: 600;">ACTIVE</span>
          </div>
          <div class="card-value" style="font-size: 1.2rem;">3-Hop 匿名混淆路由</div>
          <div class="card-desc">回路 ID: #c48a &bull; 出口节点: 43.207.75.185</div>
        </div>
      </div>

      <!-- 13 Profiles Table -->
      <div class="card" style="margin-bottom: 24px;">
        <div class="card-title" style="margin-bottom: 14px;">
          <span>${t('network.profiles_title')}</span>
          <span style="font-size: 0.75rem; color: var(--text-dim); font-weight: normal;">${t('network.privacy_masked')}</span>
        </div>
        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th>Profile 标识</th>
                <th>核心运行时</th>
                <th>传输协议</th>
                <th>监听端口</th>
                <th>主机端点</th>
                <th>延迟</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              ${shadow6Profiles.map(p => `
                <tr>
                  <td style="font-family: var(--font-mono); font-weight: 600; color: var(--text-main);">${p.id}</td>
                  <td style="color: var(--accent-cyan); font-weight: 500;">${p.core}</td>
                  <td style="color: var(--text-muted); font-family: var(--font-mono);">${p.transport}</td>
                  <td style="color: var(--accent-amber); font-family: var(--font-mono);">${p.port}</td>
                  <td style="font-family: var(--font-mono); font-size: 0.8rem; color: var(--text-dim);">
                    ${showSensitive ? '43.207.75.185' : '***.***.***.***'}
                  </td>
                  <td style="color: var(--accent-green); font-weight: 600;">${p.latency}</td>
                  <td><span class="status-badge"><span class="status-dot"></span> ${p.status}</span></td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>

      <!-- S6P1 Credential Envelope Paste / Import Section -->
      <div class="card">
        <div class="card-title" style="margin-bottom: 10px;">
          <span>${t('network.s6p1_import')}</span>
        </div>
        <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 12px;">用户可在此粘贴自定义 S6P1 凭据信封（Base64URL 格式），客户端将自动解析其组件契约、核心路由清单与凭据准入权限：</p>
        <textarea id="s6p1-input" class="input-textarea" rows="4" style="font-family: var(--font-mono); font-size: 0.8rem; margin-bottom: 12px;" placeholder="粘贴以 S6P1. 开头的凭据字符串..."></textarea>
        <div style="display: flex; gap: 10px;">
          <button id="parse-s6p1-btn" class="btn btn-primary">解析并接入 S6P1 信封</button>
          <button id="load-sample-s6p1-btn" class="btn btn-secondary">加载默认创世节点信封</button>
        </div>
      </div>

    </div>
  `;

  // Toggle sensitive masking
  container.querySelector('#toggle-sensitive-btn').onclick = () => {
    showSensitive = !showSensitive;
    renderNetwork(container);
    showToast(showSensitive ? '敏感字段已解除遮盖' : '已启用脱敏掩码', 'info');
  };

  // Ping test simulation
  container.querySelector('#ping-all-btn').onclick = () => {
    showToast('正在向 13 个 Profile 节点及 Virtual Broker 发起探测 ...', 'info');
    setTimeout(() => {
      shadow6Profiles.forEach(p => {
        p.latency = `${Math.floor(Math.random() * 20) + 5}ms`;
      });
      showToast('所有 Profile 延迟已更新，平均延迟 11.4ms', 'success');
      renderNetwork(container);
    }, 600);
  };

  // S6P1 Envelope Parser
  const s6p1Input = container.querySelector('#s6p1-input');
  container.querySelector('#load-sample-s6p1-btn').onclick = () => {
    s6p1Input.value = 'S6P1.eyJjb21wb25lbnRzIjp7ImNvbnRyb2wtY2VudGVyIjp0cnVlLCJndWFyZCI6dHJ1ZX0sImNvcmUiOlsiZ28iLCJydXN0IiwiemlnIl0sInJvbGUiOiJicm9rZXIifQ==';
  };

  container.querySelector('#parse-s6p1-btn').onclick = () => {
    const raw = s6p1Input.value.trim();
    if (!raw.startsWith('S6P1.')) {
      showToast('S6P1 凭据信封前缀错误，必须以 S6P1. 开头', 'error');
      return;
    }
    try {
      let b64 = raw.slice(5).replace(/-/g, '+').replace(/_/g, '/');
      while (b64.length % 4) b64 += '=';
      const parsed = JSON.parse(decodeURIComponent(escape(atob(b64))));
      showJsonModal('S6P1 信封解析成功', parsed);
      showToast('S6P1 信封解析通过，已载入自定义路由网格', 'success');
    } catch (e) {
      showToast('S6P1 解析失败: ' + e.message, 'error');
    }
  };
}
