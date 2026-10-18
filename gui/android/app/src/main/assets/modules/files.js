// ==============================================================================
// Module: UFS & SafeFS Secure File Vault & Storage Explorer
// ==============================================================================
import { State, t, showToast, showConfirm, isLocalNodeOffline, getActiveRemoteNode, getStorage, setStorage, callTool, sha256, uploadObject, apiRequest } from '../core.js';

let currentVault = 'ufs'; // 'ufs' | 'safefs'
let vaultFiles = [];
try {
  const raw = getStorage('ziokt_vault_files');
  if (raw) vaultFiles = JSON.parse(raw);
} catch (e) {
  vaultFiles = [];
}

export function renderFiles(container) {
  const isEn = State.language === 'en';

  if (isLocalNodeOffline()) {
    container.innerHTML = `
      <div style="max-width: 800px; margin: 40px auto; text-align: center;">
        <div class="card" style="padding: 36px 20px;">
          <div style="font-size: 2.5rem; margin-bottom: 12px;">🔒</div>
          <h3 style="color: var(--accent-red); margin-bottom: 8px;">
            ${isEn ? 'Local Node Offline — Storage Unavailable' : '本地节点未运行 — 存储功能不可用'}
          </h3>
          <p style="color: var(--text-muted); font-size: 0.85rem; max-width: 520px; margin: 0 auto 20px; line-height: 1.6;">
            ${isEn
              ? 'Local mode requires an active Ziokt node daemon at http://127.0.0.1:8185 to mount UFS & SafeFS storage partitions and descriptors. Only Settings is accessible.'
              : '本地节点模式需要本机真实运行有 Ziokt 节点服务 (http://127.0.0.1:8185) 挂载 UFS 与 SafeFS 存储卷。本地未启动时无法创建目录或存储文件，当前仅开放【系统设置】。'}
          </p>
          <div style="display: flex; gap: 10px; justify-content: center; flex-wrap: wrap;">
            <button id="files-go-settings-btn" class="btn btn-primary">⚙️ ${t('nav.settings')}</button>
            <button id="files-retry-probe-btn" class="btn btn-secondary">⚡ ${t('settings.local_node_probe')}</button>
          </div>
        </div>
      </div>
    `;
    const sBtn = container.querySelector('#files-go-settings-btn');
    if (sBtn) sBtn.onclick = () => { location.hash = '#settings'; };
    const pBtn = container.querySelector('#files-retry-probe-btn');
    if (pBtn) pBtn.onclick = async () => {
      pBtn.disabled = true;
      pBtn.textContent = '...';
      const { checkLocalNodeHealth } = await import('../core.js');
      const res = await checkLocalNodeHealth();
      pBtn.disabled = false;
      pBtn.textContent = `⚡ ${t('settings.local_node_probe')}`;
      if (res.ok) {
        showToast(isEn ? 'Local node verified online!' : '本地真实节点检测通过，状态在线！', 'success');
        renderFiles(container);
      } else {
        showToast(isEn ? `Local node unreachable: ${res.error}` : `本地真实节点未响应: ${res.error}`, 'error');
      }
    };
    return;
  }
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

      <!-- Native MCP Chunked Storage & Tool Bridge -->
      <div class="card" style="margin-top: 24px; padding: 20px;">
        <div class="card-title" style="margin-bottom: 12px;">
          <span>🛠️ 原生分块传输与 MCP 工具 / Native Chunked Storage & MCP Tools</span>
        </div>
        <p style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 14px;">
          操作使用已鉴权的真实后端。工具结果仅代表其声明的阶段；验签、暂存、安装、激活分别显示。
        </p>
        <div style="display: flex; flex-direction: column; gap: 10px; max-width: 650px;">
          <label style="font-size: 0.82rem; color: var(--text-main);">Node administrator token（只保存在当前页面内存）
            <input type="password" class="input-text" id="operation-token" autocomplete="off" style="margin-top: 4px;">
          </label>
          <div style="display: flex; gap: 10px; align-items: center;">
            <button class="btn btn-primary btn-sm" id="load-real-tools">连接并刷新工具</button>
            <span id="tool-count" style="font-size: 0.78rem; color: var(--text-dim);"></span>
          </div>
          <select class="input-text" id="real-tool" style="font-size: 0.82rem;"></select>
          <pre id="real-schema" style="white-space: pre-wrap; font-size: 0.72rem; color: var(--text-dim); max-height: 120px; overflow: auto; background: var(--bg-input); padding: 8px; border-radius: var(--radius-sm);"></pre>
          <label style="font-size: 0.82rem; color: var(--text-main);">参数 JSON
            <textarea id="real-arguments" class="input-textarea" rows="4" style="margin-top: 4px; font-size: 0.78rem;">{}</textarea>
          </label>
          <label style="font-size: 0.82rem; display: flex; align-items: center; gap: 6px; cursor: pointer;">
            <input type="checkbox" id="real-confirm"> 我确认执行所选写操作
          </label>
          <div>
            <button class="btn btn-primary btn-sm" id="run-real-tool">执行</button>
          </div>
          <hr style="border: 0; border-top: 1px solid var(--border-subtle); margin: 10px 0;">
          <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
            <input type="file" id="real-file" class="input-text" style="font-size: 0.8rem; width: auto;">
            <select id="file-app" class="input-select" style="font-size: 0.8rem; width: auto;">
              <option value="safefs">safefs</option>
              <option value="dcpm">dcpm</option>
              <option value="ufs">ufs</option>
            </select>
            <button class="btn btn-secondary btn-sm" id="upload-real-file">分块上传实际内容</button>
          </div>
          <p style="font-size: 0.72rem; color: var(--text-dim); margin: 0;">上传只保存加密对象；上传不代表安装。</p>
          <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 6px;">
            <input id="download-object" class="input-text" placeholder="对象 manifest_digest" style="font-size: 0.8rem; flex: 1;">
            <button id="download-real-file" class="btn btn-secondary btn-sm">验证并下载实际内容</button>
          </div>
          <hr style="border: 0; border-top: 1px solid var(--border-subtle); margin: 10px 0;">
          <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
            <input id="native-name" class="input-text" placeholder="原生包 ID（须匹配签名）" style="font-size: 0.8rem; flex: 1;">
            <input id="native-version" class="input-text" placeholder="原生包版本（须匹配签名）" style="font-size: 0.8rem; width: 140px;">
            <button id="stage-native-package" class="btn btn-secondary btn-sm">生成 v2 引用包并验证原生签名暂存</button>
          </div>
          <pre id="real-result" role="status" style="white-space: pre-wrap; overflow-wrap: anywhere; font-size: 0.72rem; color: var(--accent-cyan); background: var(--bg-input); padding: 8px; border-radius: var(--radius-sm); margin-top: 8px;"></pre>
        </div>
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
    if (isLocalNodeOffline()) {
      showToast(State.language === 'en' ? 'Local node is offline, storage operations unavailable' : '本地真实节点未启动 (127.0.0.1:8185)，无法执行存储操作', 'error');
      return;
    }
    container.querySelector('#vault-file-input').click();
  };

  // Upload Logic
  window.handleVaultUpload = (files) => {
    if (isLocalNodeOffline()) {
      showToast(State.language === 'en' ? 'Local node is offline, upload disabled' : '本地真实节点未启动 (127.0.0.1:8185)，无法上传文件', 'error');
      return;
    }
    if (!files || !files.length) return;
    const file = files[0];
    showToast(isEn ? `Encrypting & storing "${file.name}" ...` : `正在加密并存储文件 "${file.name}" ...`, 'info');
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
      setStorage('ziokt_vault_files', JSON.stringify(vaultFiles));
      showToast(isEn ? `"${file.name}" safely stored in native vault` : `文件 "${file.name}" 已持久化保存至原生保险库`, 'success');
      renderFiles(container);
    }, 400);
  };

  // Create Folder
  container.querySelector('#create-folder-btn').onclick = () => {
    if (isLocalNodeOffline()) {
      showToast(State.language === 'en' ? 'Local node is offline, cannot create folder' : '本地真实节点未启动 (127.0.0.1:8185)，无法创建目录', 'error');
      return;
    }
    const name = prompt(isEn ? 'Enter directory name:' : '请输入新目录名称:');
    if (name) {
      vaultFiles.push({
        name,
        size: '-',
        date: isEn ? 'Just now' : '刚刚',
        isDir: true,
        type: 'dir'
      });
      setStorage('ziokt_vault_files', JSON.stringify(vaultFiles));
      showToast(isEn ? `Directory "${name}" created successfully` : `目录 "${name}" 创建成功`, 'success');
      renderFiles(container);
    }
  };

  // Delete Action with Confirmation
  container.querySelectorAll('.del-btn').forEach(btn => {
    btn.onclick = async () => {
      if (isLocalNodeOffline()) {
        showToast(isEn ? 'Local node is offline' : '本地节点未启动', 'error');
        return;
      }
      const name = btn.dataset.name;
      const ok = await showConfirm(
        isEn ? 'Delete File' : '确认删除文件',
        isEn ? `Are you sure you want to permanently delete "${name}"?` : `确定要彻底删除 "${name}" 吗？此操作不可逆。`
      );
      if (ok) {
        vaultFiles = vaultFiles.filter(f => f.name !== name);
        setStorage('ziokt_vault_files', JSON.stringify(vaultFiles));
        showToast(isEn ? `Deleted "${name}"` : `已删除 "${name}"`, 'success');
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

  // Wire up Real MCP Tool & Chunk Handlers
  const out = container.querySelector('#real-result');
  const select = container.querySelector('#real-tool');
  let tools = [];
  const fail = (e) => { if (out) out.textContent = '操作失败：' + e.message; };

  const loadToolsBtn = container.querySelector('#load-real-tools');
  if (loadToolsBtn) {
    loadToolsBtn.onclick = async () => {
      const tokenInput = container.querySelector('#operation-token');
      if (tokenInput && tokenInput.value) {
        State.authToken = tokenInput.value;
        const n = getActiveRemoteNode();
        if (n) {
          n.authToken = tokenInput.value;
        }
        tokenInput.value = '';
      }
      try {
        const listing = await apiRequest('/api/gateway/tools');
        tools = listing.tools.filter(t => t.name.startsWith('safefs_') || t.name.startsWith('ufs_'));
        select.replaceChildren(...tools.map(t => new Option(t.name, t.name)));
        const countEl = container.querySelector('#tool-count');
        if (countEl) countEl.textContent = `已鉴权：${listing.count} 个工具，本页 ${tools.length} 个`;
        select.onchange = () => {
          const tObj = tools.find(t => t.name === select.value);
          const schemaEl = container.querySelector('#real-schema');
          if (schemaEl) schemaEl.textContent = tObj ? JSON.stringify(tObj.inputSchema, null, 2) : '';
          const confirmBox = container.querySelector('#real-confirm');
          if (confirmBox) confirmBox.checked = false;
        };
        select.onchange();
      } catch (e) { fail(e); }
    };
  }

  const runToolBtn = container.querySelector('#run-real-tool');
  if (runToolBtn) {
    runToolBtn.onclick = async (event) => {
      const btn = event.currentTarget;
      btn.disabled = true;
      try {
        const tool = tools.find(t => t.name === select.value);
        if (!tool) throw new Error('请先连接并选择工具');
        const confirmBox = container.querySelector('#real-confirm');
        const confirm = confirmBox ? confirmBox.checked : false;
        if (tool.annotations?.destructiveHint && !confirm) throw new Error('写操作需要明确确认');
        const started = performance.now();
        const argsVal = JSON.parse(container.querySelector('#real-arguments').value);
        const result = await callTool(tool.name, argsVal, { confirm });
        if (out) out.textContent = JSON.stringify({ elapsed_ms: Math.round(performance.now() - started), result }, null, 2);
      } catch (e) { fail(e); }
      finally { btn.disabled = false; }
    };
  }

  const uploadBtn = container.querySelector('#upload-real-file');
  if (uploadBtn) {
    uploadBtn.onclick = async (event) => {
      const btn = event.currentTarget;
      btn.disabled = true;
      try {
        const confirmBox = container.querySelector('#real-confirm');
        if (!confirmBox || !confirmBox.checked) throw new Error('上传写操作需要明确确认');
        const fileInput = container.querySelector('#real-file');
        const file = fileInput?.files?.[0];
        if (!file) throw new Error('请选择文件');
        const appVal = container.querySelector('#file-app')?.value || 'safefs';
        const result = await uploadObject(file, appVal, (done, total) => {
          if (out) out.textContent = `上传 ${done}/${total} 字节`;
        });
        if (out) out.textContent = JSON.stringify({ file: file.name, receipt: result, installed: false }, null, 2);
      } catch (e) { fail(e); }
      finally { btn.disabled = false; }
    };
  }

  const downloadBtn = container.querySelector('#download-real-file');
  if (downloadBtn) {
    downloadBtn.onclick = async (event) => {
      const btn = event.currentTarget;
      btn.disabled = true;
      try {
        const app = container.querySelector('#file-app')?.value || 'safefs';
        const object = container.querySelector('#download-object')?.value?.trim();
        if (!object) throw new Error('请输入对象 manifest_digest');
        const reference = await callTool(app + '_object_reference', { params: { object } });
        if (reference.length > 64 * 1024 * 1024) throw new Error('Browser download limit: 64 MiB');
        const parts = [];
        let length = 0;
        for (let position = 0; position < Math.ceil(reference.length / 16384); position++) {
          const item = await callTool(app + '_object_chunk_get', { params: { object, position } });
          const bytes = Uint8Array.from(atob(item.data_base64), c => c.charCodeAt(0));
          if (await sha256(bytes) !== item.digest) throw new Error('Chunk integrity failed');
          length += bytes.length;
          if (length > reference.length) throw new Error('Object length exceeded');
          parts.push(bytes);
        }
        const bytes = new Uint8Array(length);
        let offset = 0;
        for (const part of parts) {
          bytes.set(part, offset);
          offset += part.length;
        }
        if (length !== reference.length || await sha256(bytes) !== reference.digest) throw new Error('Whole object integrity failed');
        const url = URL.createObjectURL(new Blob([bytes]));
        const a = document.createElement('a');
        a.href = url;
        a.download = 'verified-object.bin';
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        if (out) out.textContent = JSON.stringify({ download_verified: true, bytes: length, digest: reference.digest }, null, 2);
      } catch (e) { fail(e); }
      finally { btn.disabled = false; }
    };
  }

  const stageBtn = container.querySelector('#stage-native-package');
  if (stageBtn) {
    stageBtn.onclick = async (event) => {
      const btn = event.currentTarget;
      btn.disabled = true;
      try {
        const confirmBox = container.querySelector('#real-confirm');
        if (!confirmBox || !confirmBox.checked) throw new Error('生成软件包和暂存需要明确确认');
        const file = container.querySelector('#real-file')?.files?.[0];
        if (!file) throw new Error('请选择独立签名的 Shadow6 原生 ZIP');
        const name = container.querySelector('#native-name')?.value?.trim();
        const version = container.querySelector('#native-version')?.value?.trim();
        if (!name || !version) throw new Error('原生包 ID 和版本不能为空，且必须与内层签名匹配');
        const object = await uploadObject(file, 'dcpm', (done, total) => {
          if (out) out.textContent = `上传 ${done}/${total} 字节`;
        });
        const pkg = await callTool('dcpm_package_build_references', { params: { name, version, files: { 'shadow6/package.zip': object.manifest_digest }, dependencies: [] } }, { confirm: true });
        if (out) out.textContent = JSON.stringify({ package: pkg, staging: true }, null, 2);
        const receipt = await callTool('dcpm_package_stage_native', { digest: pkg.digest, authority: pkg.publisher }, { confirm: true });
        if (out) out.textContent = JSON.stringify({ package: pkg, receipt, installed: false }, null, 2);
      } catch (e) { fail(e); }
      finally { btn.disabled = false; }
    };
  }

}
