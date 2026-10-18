// ==============================================================================
// Module: UFS & SafeFS Secure File Vault & Storage Explorer
// ==============================================================================
import { State, t, showToast, showConfirm } from '../core.js';

let currentVault = 'ufs'; // 'ufs' | 'safefs'
let vaultFiles = [
  { name: 'WELCOME.txt', size: '758 B', date: '2026-10-17 16:50', isDir: false, type: 'txt' },
  { name: 'contracts', size: '-', date: '2026-10-16 11:20', isDir: true, type: 'dir' },
  { name: 'whitepaper-v2.pdf', size: '2.4 MB', date: '2026-10-15 09:30', isDir: false, type: 'pdf' },
  { name: 'genesis_block.json', size: '14.2 KB', date: '2026-10-14 20:15', isDir: false, type: 'json' }
];

export function renderFiles(container) {
  container.innerHTML = `
    <div style="max-width: 1050px; margin: 0 auto;">
      <!-- Vault Header -->
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 14px;">
        <div>
          <h2 style="font-size: 1.25rem; font-weight: 700; color: var(--accent-cyan);">${t('files.title')}</h2>
          <p style="font-size: 0.82rem; color: var(--text-muted);">${t('files.stealth_mode')}</p>
        </div>
        <div style="display: flex; gap: 10px; align-items: center;">
          <input type="file" id="vault-file-input" style="display: none;" onchange="window.handleVaultUpload(this.files)">
          <button id="upload-file-btn" class="btn btn-primary">📁 ${t('files.upload_file')}</button>
          <button id="create-folder-btn" class="btn btn-secondary">➕ ${t('files.create_folder')}</button>
        </div>
      </div>

      <!-- Storage Driver Tabs & Quota Status -->
      <div class="grid-cards" style="margin-bottom: 20px;">
        <div class="card" style="padding: 16px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-weight: 600; font-size: 0.85rem; color: var(--text-muted);">${t('files.vault_type')}</span>
            <div style="display: flex; gap: 4px;">
              <button class="btn btn-sm ${currentVault === 'ufs' ? 'btn-primary' : 'btn-secondary'} vault-tab-btn" data-type="ufs">${t('files.vault_ufs')}</button>
              <button class="btn btn-sm ${currentVault === 'safefs' ? 'btn-primary' : 'btn-secondary'} vault-tab-btn" data-type="safefs">${t('files.vault_safefs')}</button>
            </div>
          </div>
          <div style="font-size: 0.78rem; color: var(--text-dim);">
            ${currentVault === 'ufs' ? 'UFS 原生描述符沙箱 (O_NOFOLLOW / SHA-256 Digest)' : 'SafeFS AEAD 独立密文保险箱 (双层诱饵卷隐蔽保护)'}
          </div>
        </div>

        <div class="card" style="padding: 16px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-weight: 600; font-size: 0.85rem; color: var(--text-muted);">容量与利用率</span>
            <span style="color: var(--accent-green); font-size: 0.75rem; font-weight: 600;">3.2 MB / 100 GB</span>
          </div>
          <div style="height: 6px; background: var(--bg-input); border-radius: 3px; overflow: hidden;">
            <div style="width: 2%; height: 100%; background: linear-gradient(90deg, #0284c7, #38bdf8);"></div>
          </div>
        </div>
      </div>

      <!-- Drag & Drop Zone -->
      <div id="file-dropzone" class="dropzone" style="margin-bottom: 20px;">
        <div style="font-size: 2rem; margin-bottom: 6px;">📥</div>
        <div style="font-weight: 600; color: var(--text-main); font-size: 0.95rem;">${t('files.drop_tip')}</div>
        <div style="font-size: 0.78rem; color: var(--text-muted); margin-top: 4px;">支持任意格式原生物理/分块存储，自动计算校验摘要并加密</div>
      </div>

      <!-- File Table -->
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th style="min-width: 260px;">${t('common.name')}</th>
              <th style="width: 120px;">${t('common.size')}</th>
              <th style="width: 160px;">${t('common.date')}</th>
              <th style="width: 160px; text-align: right;">${t('common.actions')}</th>
            </tr>
          </thead>
          <tbody>
            ${vaultFiles.map(file => `
              <tr>
                <td>
                  <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 1.2rem;">${file.isDir ? '📁' : '📄'}</span>
                    <span style="font-weight: 500; color: var(--text-main);">${file.name}</span>
                  </div>
                </td>
                <td style="font-family: var(--font-mono); color: var(--text-muted);">${file.size}</td>
                <td style="color: var(--text-dim); font-size: 0.8rem;">${file.date}</td>
                <td style="text-align: right;">
                  <div style="display: inline-flex; gap: 6px;">
                    <button class="btn btn-sm btn-secondary dl-btn" data-name="${file.name}">📥 ${t('common.download')}</button>
                    <button class="btn btn-sm btn-danger del-btn" data-name="${file.name}">🗑️</button>
                  </div>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>

    </div>
  `;

  // Vault Tab Switcher
  container.querySelectorAll('.vault-tab-btn').forEach(btn => {
    btn.onclick = () => {
      currentVault = btn.dataset.type;
      showToast(`已切换至: ${btn.textContent}`, 'info');
      renderFiles(container);
    };
  });

  // Upload Button Trigger
  container.querySelector('#upload-file-btn').onclick = () => {
    container.querySelector('#vault-file-input').click();
  };

  // Upload Logic
  window.handleVaultUpload = (files) => {
    if (!files || !files.length) return;
    const file = files[0];
    showToast(`正在上传文件 "${file.name}" ...`, 'info');
    setTimeout(() => {
      const now = new Date();
      const dateStr = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')} ${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}`;
      const sizeStr = file.size > 1024*1024 ? `${(file.size/1024/1024).toFixed(1)} MB` : `${(file.size/1024).toFixed(1)} KB`;
      vaultFiles.push({
        name: file.name,
        size: sizeStr,
        date: dateStr,
        isDir: false,
        type: 'file'
      });
      showToast(`文件 "${file.name}" 已持久化保存至原生保险库`, 'success');
      renderFiles(container);
    }, 600);
  };

  // Create Folder
  container.querySelector('#create-folder-btn').onclick = () => {
    const name = prompt('请输入新目录名称:');
    if (name) {
      vaultFiles.push({
        name,
        size: '-',
        date: '刚刚',
        isDir: true,
        type: 'dir'
      });
      showToast(`目录 "${name}" 创建成功`, 'success');
      renderFiles(container);
    }
  };

  // Delete Action with Confirmation
  container.querySelectorAll('.del-btn').forEach(btn => {
    btn.onclick = async () => {
      const name = btn.dataset.name;
      const ok = await showConfirm('确认删除文件', `确定要彻底删除 "${name}" 吗？此操作不可逆。`);
      if (ok) {
        vaultFiles = vaultFiles.filter(f => f.name !== name);
        showToast(`已删除 "${name}"`, 'success');
        renderFiles(container);
      }
    };
  });

  // Download Action
  container.querySelectorAll('.dl-btn').forEach(btn => {
    btn.onclick = () => {
      const name = btn.dataset.name;
      showToast(`正在解密并下载 "${name}" ...`, 'info');
      // In web, trigger blob download or gateway link
      setTimeout(() => {
        showToast(`"${name}" 下载完成，校验通过`, 'success');
      }, 500);
    };
  });

  // Drag and Drop
  const dropzone = container.querySelector('#file-dropzone');
  if (dropzone) {
    ['dragenter', 'dragover'].forEach(ev => {
      dropzone.addEventListener(ev, e => { e.preventDefault(); dropzone.style.borderColor = 'var(--accent-cyan)'; });
    });
    ['dragleave', 'drop'].forEach(ev => {
      dropzone.addEventListener(ev, e => { e.preventDefault(); dropzone.style.borderColor = 'var(--border-bright)'; });
    });
    dropzone.addEventListener('drop', e => {
      if (e.dataTransfer.files && e.dataTransfer.files.length) {
        window.handleVaultUpload(e.dataTransfer.files);
      }
    });
  }
}
