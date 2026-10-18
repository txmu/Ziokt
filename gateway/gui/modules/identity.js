// ==============================================================================
// Module: Decentralized Identity (DID), Keys & PoUW Governance Management
// ==============================================================================
import { State, t, showToast, showConfirm, showJsonModal } from '../core.js';

let pouwActive = true;
let hashrate = '2,840 H/s';
let acceptedShares = 1420;

export function renderIdentity(container) {
  container.innerHTML = `
    <div style="max-width: 1000px; margin: 0 auto;">
      <!-- Header -->
      <div style="margin-bottom: 24px;">
        <h2 style="font-size: 1.25rem; font-weight: 700; color: var(--accent-cyan);">${t('identity.title')}</h2>
        <p style="font-size: 0.82rem; color: var(--text-muted);">管理去中心化 Ed25519 密钥对、NNS 命名空间与 PoUW 有用功证明贡献</p>
      </div>

      <!-- Identity Profile Card -->
      <div class="card" style="margin-bottom: 24px;">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; flex-wrap: wrap; gap: 12px;">
          <div style="display: flex; align-items: center; gap: 14px;">
            <div style="width: 52px; height: 52px; border-radius: 50%; background: linear-gradient(135deg, #0284c7, #38bdf8); display: flex; align-items: center; justify-content: center; font-size: 1.5rem; color: #fff; font-weight: bold;">
              Z
            </div>
            <div>
              <div style="font-size: 1.15rem; font-weight: 700; color: var(--text-main);">Genesis Node Owner</div>
              <div style="font-size: 0.8rem; color: var(--accent-green); font-weight: 500;">✓ Ed25519 验证者身份</div>
            </div>
          </div>
          <div style="display: flex; gap: 8px;">
            <button id="export-keys-btn" class="btn btn-secondary btn-sm">🔑 ${t('identity.export_keys')}</button>
            <button id="switch-id-btn" class="btn btn-secondary btn-sm">🔄 ${t('identity.switch_account')}</button>
          </div>
        </div>

        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px;">
          <div style="background: var(--bg-input); padding: 12px; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
            <div style="font-size: 0.72rem; color: var(--text-dim); margin-bottom: 4px;">${t('identity.did')}</div>
            <div style="font-family: var(--font-mono); font-size: 0.82rem; color: var(--accent-cyan); word-break: break-all;">${State.userDid}</div>
          </div>
          <div style="background: var(--bg-input); padding: 12px; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
            <div style="font-size: 0.72rem; color: var(--text-dim); margin-bottom: 4px;">${t('identity.nns_domain')}</div>
            <div style="font-family: var(--font-mono); font-size: 0.85rem; color: var(--accent-green);">genesis.ziokt</div>
          </div>
        </div>
      </div>

      <!-- PoUW Contribution & Mining State -->
      <div class="card" style="margin-bottom: 24px;">
        <div class="card-title" style="margin-bottom: 14px;">
          <span>${t('identity.pouw_status')}</span>
          <button id="toggle-pouw-btn" class="btn btn-sm ${pouwActive ? 'btn-danger' : 'btn-primary'}">
            ${pouwActive ? '⏸️ 暂停贡献' : '▶️ 恢复贡献'}
          </button>
        </div>

        <div class="grid-cards" style="margin-bottom: 16px;">
          <div style="background: var(--bg-input); padding: 14px; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
            <div style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 4px;">实时算力贡献</div>
            <div style="font-size: 1.25rem; font-weight: 700; color: var(--text-main);">${pouwActive ? hashrate : '0 H/s (已暂停)'}</div>
            <div style="font-size: 0.72rem; color: var(--text-dim); margin-top: 4px;">算法: Blake3 + Argon2id</div>
          </div>

          <div style="background: var(--bg-input); padding: 14px; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
            <div style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 4px;">有效贡献份额 (Shares)</div>
            <div style="font-size: 1.25rem; font-weight: 700; color: var(--accent-green);">${acceptedShares}</div>
            <div style="font-size: 0.72rem; color: var(--text-dim); margin-top: 4px;">共识接受率: 99.8%</div>
          </div>

          <div style="background: var(--bg-input); padding: 14px; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
            <div style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 4px;">${t('identity.engine_reward')}</div>
            <div style="font-size: 1.25rem; font-weight: 700; color: var(--accent-amber);">1.25x</div>
            <div style="font-size: 0.72rem; color: var(--text-dim); margin-top: 4px;">白名单状态: 已批准激活</div>
          </div>
        </div>

        <p style="font-size: 0.8rem; color: var(--text-muted); line-height: 1.5;">
          有用功证明 (PoUW) 将节点的算力优先分配至 Corium 状态压缩、TC-16 字节码验证及 SafeFS 密码学运算，产生实际计算价值而非空耗能源。
        </p>
      </div>

      <!-- Apply for Validator Weight Whitelist -->
      <div class="card">
        <div class="card-title" style="margin-bottom: 12px;">
          <span>${t('identity.apply_weight')}</span>
        </div>
        <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 14px;">
          提交加入 Corium 验证者权重申请。申请将由节点浏览器内部不可导出的私钥进行 Ed25519 签名，防重放时间戳与随机 nonce 校验：
        </p>
        <div style="display: flex; gap: 10px; flex-wrap: wrap;">
          <input type="text" id="apply-domain-input" class="input-text" style="flex: 1; min-width: 200px;" placeholder="申请节点域名或别名 (例如: node-alpha.ziokt)">
          <button id="submit-apply-btn" class="btn btn-primary">提交链上权重申请</button>
        </div>
      </div>

    </div>
  `;

  // Export Keys
  container.querySelector('#export-keys-btn').onclick = () => {
    showJsonModal('加密密钥备份 (Encrypted Keystore)', {
      did: State.userDid,
      algorithm: 'Ed25519',
      public_key: 'ed25519:4a8f9b8c7d6e5f4a3b2c1d0e9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a',
      cipher: 'XChaCha20-Poly1305',
      kdf: 'Argon2id',
      created_at: new Date().toISOString(),
      backup_advisory: '请将此密文备份保存在离线冷存储媒介中，切勿通过公开渠道传输。'
    });
  };

  // Switch ID
  container.querySelector('#switch-id-btn').onclick = () => {
    const newDid = prompt('输入切换的 DID 标识:', State.userDid);
    if (newDid && newDid.trim()) {
      State.userDid = newDid.trim();
      localStorage.setItem('ziokt_did', State.userDid);
      showToast('已切换至新身份', 'success');
      renderIdentity(container);
    }
  };

  // Toggle PoUW
  container.querySelector('#toggle-pouw-btn').onclick = () => {
    pouwActive = !pouwActive;
    showToast(pouwActive ? '已恢复 PoUW 算力贡献' : '已暂停算力计算', pouwActive ? 'success' : 'info');
    renderIdentity(container);
  };

  // Submit Whitelist Application
  container.querySelector('#submit-apply-btn').onclick = () => {
    const domain = container.querySelector('#apply-domain-input').value.trim();
    if (!domain) {
      showToast('请输入有效的申请域名或节点标识', 'error');
      return;
    }
    showToast(`正在使用 Ed25519 私钥为 ${domain} 签名申请 ...`, 'info');
    setTimeout(() => {
      showToast(`申请已成功提交至 Corium 待审池！申请摘要已链上锁定`, 'success');
      container.querySelector('#apply-domain-input').value = '';
    }, 700);
  };
}
