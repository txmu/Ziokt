// ==============================================================================
// Module: dCPM Decentralized App Store & Signed Package Manager
// ==============================================================================
import { State, t, showToast, showConfirm, showJsonModal } from '../core.js';

let packages = [
  {
    id: 'ziokt-core',
    name: 'Ziokt Core Runtime',
    version: '1.0.8',
    prevVersion: '1.0.7',
    publisher: 'ed25519:4a8f9b...12c',
    size: '12.4 MB',
    status: 'installed',
    digest: 'sha256:4a8f9b8c7d6e5f4a3b2c1d0e9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a',
    dependencies: ['etp-onion-gateway >= 2.0.0'],
    description: 'Ziokt 原生微架构核心运行时，提供去中心化事件总线、状态共识与安全执行环境。'
  },
  {
    id: 'tc16-vm-isa',
    name: 'TC-16 Virtual Machine ISA',
    version: '1.0.2',
    prevVersion: '1.0.1',
    publisher: 'ed25519:7b1e2c...90f',
    size: '4.8 MB',
    status: 'installed',
    digest: 'sha256:7b1e2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b',
    dependencies: ['ziokt-core >= 1.0.0'],
    description: '16位确定性微虚拟机指令集包，支持隔离环境中的可信计算与 Gas 算力控制。'
  },
  {
    id: 'etp-onion-gateway',
    name: 'ETP Native Onion Gateway',
    version: '2.1.0',
    prevVersion: '2.0.8',
    publisher: 'ed25519:91df3e...44a',
    size: '8.2 MB',
    status: 'installed',
    digest: 'sha256:91df3e2a1b0c9d8e7f6a5b4c3d2e1f0a4a8f9b8c7d6e5f4a3b2c1d0e9f8a7b6c',
    dependencies: [],
    description: 'ETP 洋葱多跳原生网关路由包，实现抗审查与高匿名性的端到端数据传输。'
  },
  {
    id: 'shadow6-broker',
    name: 'Shadow6 Virtual Broker Mesh',
    version: '3.4.1',
    prevVersion: '3.4.0',
    publisher: 'ed25519:6c5d4e...88a',
    size: '18.5 MB',
    status: 'installed',
    digest: 'sha256:6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a91df3e2a1b0c9d8e7f6a5b4c3d2e1f',
    dependencies: ['ziokt-core >= 1.0.0'],
    description: 'Shadow6 虚拟 Broker 代理与 13 语言核心 Profile 集群运行容器。'
  },
  {
    id: 'safefs-crypto',
    name: 'SafeFS AEAD Storage Driver',
    version: '1.1.0',
    prevVersion: '1.0.9',
    publisher: 'ed25519:1a2b3c...55d',
    size: '3.6 MB',
    status: 'available',
    digest: 'sha256:1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b',
    dependencies: ['ziokt-core >= 1.0.0'],
    description: '高级 AEAD 加密文件保险箱驱动程序，提供外层诱饵卷与内层隐蔽卷的可抵赖存储能力。'
  }
];

let activeTab = 'installed'; // 'installed' | 'market'

export function renderApps(container) {
  const filtered = activeTab === 'installed' 
    ? packages.filter(p => p.status === 'installed')
    : packages;

  container.innerHTML = `
    <div style="max-width: 1050px; margin: 0 auto;">
      <!-- Header -->
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 14px;">
        <div>
          <h2 style="font-size: 1.25rem; font-weight: 700; color: var(--accent-cyan);">${t('apps.title')}</h2>
          <p style="font-size: 0.82rem; color: var(--text-muted);">${t('apps.subtitle')}</p>
        </div>
        <div style="display: flex; gap: 10px;">
          <input type="file" id="dcpm-package-upload" style="display:none;" accept=".dcpm,application/octet-stream">
          <button id="import-pkg-btn" class="btn btn-primary">📤 ${t('apps.install_pkg')}</button>
          <button id="check-updates-btn" class="btn btn-secondary">🔄 ${t('apps.update')}</button>
        </div>
      </div>

      <!-- Navigation Tabs -->
      <div style="display: flex; gap: 8px; margin-bottom: 20px;">
        <button class="btn btn-sm ${activeTab === 'installed' ? 'btn-primary' : 'btn-secondary'} app-tab-btn" data-tab="installed">${t('apps.installed_tab')} (${packages.filter(p=>p.status==='installed').length})</button>
        <button class="btn btn-sm ${activeTab === 'market' ? 'btn-primary' : 'btn-secondary'} app-tab-btn" data-tab="market">${t('apps.market_tab')} (${packages.length})</button>
      </div>

      <!-- Packages Cards Grid -->
      <div style="display: flex; flex-direction: column; gap: 16px;">
        ${filtered.map(pkg => `
          <div class="card" style="padding: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; flex-wrap: wrap; gap: 10px;">
              <div>
                <div style="display: flex; align-items: center; gap: 10px;">
                  <h3 style="font-size: 1.1rem; font-weight: 600; color: var(--text-main);">${pkg.name}</h3>
                  <span class="mode-pill" style="font-size: 0.72rem; color: var(--accent-cyan);">v${pkg.version}</span>
                  ${pkg.status === 'installed' ? `<span class="status-badge" style="font-size: 0.7rem; color: var(--accent-green);"><span class="status-dot"></span> 已就绪</span>` : `<span class="mode-pill" style="color:var(--text-dim);border-color:var(--border-subtle);">未安装</span>`}
                </div>
                <div style="font-family: var(--font-mono); font-size: 0.75rem; color: var(--text-dim); margin-top: 4px;">ID: ${pkg.id} &bull; ${pkg.size}</div>
              </div>
              <div style="display: flex; gap: 8px; align-items: center;">
                <button class="btn btn-sm btn-secondary view-manifest-btn" data-id="${pkg.id}">📜 校验摘要</button>
                ${pkg.status === 'installed' ? `
                  <button class="btn btn-sm btn-secondary rollback-btn" data-id="${pkg.id}">⏪ ${t('apps.rollback')}</button>
                  <button class="btn btn-sm btn-danger uninstall-btn" data-id="${pkg.id}">🗑️ ${t('apps.uninstall')}</button>
                ` : `
                  <button class="btn btn-sm btn-primary install-btn" data-id="${pkg.id}">📥 安装</button>
                `}
              </div>
            </div>

            <p style="color: var(--text-muted); font-size: 0.88rem; line-height: 1.5; margin-bottom: 14px;">${pkg.description}</p>

            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.78rem; border-top: 1px solid var(--border-subtle); padding-top: 10px; color: var(--text-dim); flex-wrap: wrap; gap: 8px;">
              <div>
                <span>发布签名: </span>
                <span style="font-family: var(--font-mono); color: var(--accent-cyan);">${pkg.publisher}</span>
              </div>
              <div>
                <span>依赖要求: </span>
                <span style="color: var(--accent-green); font-weight: 500;">${pkg.dependencies.length ? pkg.dependencies.join(', ') : '无独立外部依赖'}</span>
              </div>
            </div>
          </div>
        `).join('')}
      </div>

    </div>
  `;

  // Tab switching
  container.querySelectorAll('.app-tab-btn').forEach(btn => {
    btn.onclick = () => {
      activeTab = btn.dataset.tab;
      renderApps(container);
    };
  });

  // Import / Upload .dcpm Package
  const uploadInput = container.querySelector('#dcpm-package-upload');
  container.querySelector('#import-pkg-btn').onclick = () => {
    uploadInput.click();
  };
  uploadInput.onchange = (e) => {
    if (!e.target.files.length) return;
    const file = e.target.files[0];
    showToast(`正在验签并导入 "${file.name}" ...`, 'info');
    setTimeout(() => {
      const newPkg = {
        id: file.name.replace(/\.dcpm$/, ''),
        name: `User App (${file.name})`,
        version: '1.0.0',
        prevVersion: '0.9.0',
        publisher: 'ed25519:user-custom...88c',
        size: `${(file.size / 1024).toFixed(1)} KB`,
        status: 'installed',
        digest: 'sha256:' + Math.random().toString(16).slice(2, 10),
        dependencies: [],
        description: '用户通过 dCPM 客户端上传的已签名应用程序扩展。'
      };
      packages.unshift(newPkg);
      showToast(`软件包 "${file.name}" 验签通过，沙箱挂载成功！`, 'success');
      renderApps(container);
    }, 800);
  };

  // Check Updates
  container.querySelector('#check-updates-btn').onclick = () => {
    showToast('已向 dCPM 生态源查询，所有核心软件包均处于最新签名版本', 'success');
  };

  // View Manifest Modal
  container.querySelectorAll('.view-manifest-btn').forEach(btn => {
    btn.onclick = () => {
      const pkg = packages.find(p => p.id === btn.dataset.id);
      showJsonModal(`dCPM 软件包契约: ${pkg.name}`, {
        package_id: pkg.id,
        version: pkg.version,
        sha256_digest: pkg.digest,
        publisher_key: pkg.publisher,
        dependencies: pkg.dependencies,
        isolation_policy: 'confined_tcc_sandbox'
      });
    };
  });

  // Rollback Action
  container.querySelectorAll('.rollback-btn').forEach(btn => {
    btn.onclick = async () => {
      const pkg = packages.find(p => p.id === btn.dataset.id);
      const ok = await showConfirm('版本回滚确认', `确定将 "${pkg.name}" 从 v${pkg.version} 回滚至上一版本 v${pkg.prevVersion} 吗？`);
      if (ok) {
        showToast(`正在安全恢复上一状态快照 ...`, 'info');
        setTimeout(() => {
          pkg.version = pkg.prevVersion;
          showToast(`已成功回滚至 v${pkg.version}`, 'success');
          renderApps(container);
        }, 600);
      }
    };
  });

  // Uninstall Action
  container.querySelectorAll('.uninstall-btn').forEach(btn => {
    btn.onclick = async () => {
      const pkg = packages.find(p => p.id === btn.dataset.id);
      const ok = await showConfirm('卸载应用确认', `确定卸载 "${pkg.name}" 及其本地运行时缓存吗？`);
      if (ok) {
        pkg.status = 'available';
        showToast(`"${pkg.name}" 已卸载并清除沙箱缓存`, 'success');
        renderApps(container);
      }
    };
  });

  // Install Action
  container.querySelectorAll('.install-btn').forEach(btn => {
    btn.onclick = async () => {
      const pkg = packages.find(p => p.id === btn.dataset.id);
      const ok = await showConfirm('安装确认', `确定安装 "${pkg.name}" (v${pkg.version}) 吗？将严格在隔离沙箱中执行。`);
      if (ok) {
        showToast(`正在拉取并校验依赖项 ...`, 'info');
        setTimeout(() => {
          pkg.status = 'installed';
          showToast(`"${pkg.name}" 安装成功`, 'success');
          renderApps(container);
        }, 700);
      }
    };
  });
}
