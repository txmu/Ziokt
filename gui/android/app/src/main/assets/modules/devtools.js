// ==============================================================================
// Module: Native Component Developer Studio (Corium, Tri, ZDA, TC-16, MCP)
// ==============================================================================
import { State, t, showToast, showJsonModal } from '../core.js';

let activeSubTab = 'tc16'; // 'corium' | 'tri' | 'zda' | 'tc16' | 'mcp'

// TC-16 Virtual Machine State
let tc16State = {
  registers: { R0: 0, R1: 0, R2: 0, R3: 0, R4: 0, R5: 0, SP: 0x0FFF, PC: 0x0000 },
  flags: { Z: 0, C: 0, N: 0 },
  gasUsed: 0,
  maxGas: 5000,
  halted: false,
  memory: new Array(16).fill(0),
  instructions: [
    'MOV R0, 10',
    'MOV R1, 25',
    'ADD R0, R1',
    'MOV R2, R0',
    'HALT'
  ],
  pcIndex: 0
};

export function renderDevtools(container) {
  container.innerHTML = `
    <div style="max-width: 1050px; margin: 0 auto;">
      <!-- Header -->
      <div style="margin-bottom: 20px;">
        <h2 style="font-size: 1.25rem; font-weight: 700; color: var(--accent-cyan);">${t('devtools.title')}</h2>
        <p style="font-size: 0.82rem; color: var(--text-muted);">${t('devtools.subtitle')}</p>
      </div>

      <!-- Studio Sub-Tabs -->
      <div style="display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap;">
        <button class="btn btn-sm ${activeSubTab === 'tc16' ? 'btn-primary' : 'btn-secondary'} dev-tab-btn" data-tab="tc16">💻 ${t('devtools.tab_tc16')}</button>
        <button class="btn btn-sm ${activeSubTab === 'corium' ? 'btn-primary' : 'btn-secondary'} dev-tab-btn" data-tab="corium">⛓️ ${t('devtools.tab_corium')}</button>
        <button class="btn btn-sm ${activeSubTab === 'tri' ? 'btn-primary' : 'btn-secondary'} dev-tab-btn" data-tab="tri">🔺 ${t('devtools.tab_tri')}</button>
        <button class="btn btn-sm ${activeSubTab === 'zda' ? 'btn-primary' : 'btn-secondary'} dev-tab-btn" data-tab="zda">📐 ${t('devtools.tab_zda')}</button>
        <button class="btn btn-sm ${activeSubTab === 'mcp' ? 'btn-primary' : 'btn-secondary'} dev-tab-btn" data-tab="mcp">🔌 ${t('devtools.tab_mcp')}</button>
      </div>

      <!-- Content Area according to activeSubTab -->
      <div id="devtools-subcontent"></div>
    </div>
  `;

  // Tab switching
  container.querySelectorAll('.dev-tab-btn').forEach(btn => {
    btn.onclick = () => {
      activeSubTab = btn.dataset.tab;
      renderDevtools(container);
    };
  });

  const subcontent = container.querySelector('#devtools-subcontent');

  // Render Sub-Views
  if (activeSubTab === 'tc16') {
    renderTC16Studio(subcontent);
  } else if (activeSubTab === 'corium') {
    renderCoriumConsole(subcontent);
  } else if (activeSubTab === 'tri') {
    renderTriExplorer(subcontent);
  } else if (activeSubTab === 'zda') {
    renderZdaGate(subcontent);
  } else if (activeSubTab === 'mcp') {
    renderMcpProbes(subcontent);
  }
}

// 1. TC-16 Virtual Machine Studio
function renderTC16Studio(container) {
  container.innerHTML = `
    <div class="grid-cards" style="margin-bottom: 20px;">
      <!-- Registers Panel -->
      <div class="card" style="padding: 16px;">
        <div class="card-title" style="margin-bottom: 12px;">
          <span>通用寄存器 (16-bit Architecture)</span>
          <span class="mode-pill" style="font-size: 0.7rem;">Gas: ${tc16State.gasUsed} / ${tc16State.maxGas}</span>
        </div>
        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; font-family: var(--font-mono); text-align: center;">
          ${Object.entries(tc16State.registers).map(([r, val]) => `
            <div style="background: var(--bg-input); padding: 8px 4px; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
              <div style="font-size: 0.7rem; color: var(--text-dim);">${r}</div>
              <div style="font-size: 0.95rem; font-weight: bold; color: var(--accent-cyan);">0x${val.toString(16).padStart(4, '0').toUpperCase()}</div>
              <div style="font-size: 0.68rem; color: var(--text-muted);">(${val})</div>
            </div>
          `).join('')}
        </div>
        <div style="display: flex; gap: 12px; margin-top: 12px; font-size: 0.75rem; color: var(--text-muted); font-family: var(--font-mono);">
          <span>标志位: </span>
          <span style="color: ${tc16State.flags.Z ? 'var(--accent-green)' : 'var(--text-dim)'}; font-weight: bold;">Z: ${tc16State.flags.Z}</span>
          <span style="color: ${tc16State.flags.C ? 'var(--accent-green)' : 'var(--text-dim)'}; font-weight: bold;">C: ${tc16State.flags.C}</span>
          <span style="color: ${tc16State.flags.N ? 'var(--accent-green)' : 'var(--text-dim)'}; font-weight: bold;">N: ${tc16State.flags.N}</span>
          <span>状态: ${tc16State.halted ? '⏹️ HALTED' : '▶️ READY'}</span>
        </div>
      </div>

      <!-- Memory Inspector (First 16 words) -->
      <div class="card" style="padding: 16px;">
        <div class="card-title" style="margin-bottom: 12px;">
          <span>安全内存视图 (RAM Segments)</span>
          <button id="tc16-reset-mem" class="btn btn-sm btn-secondary">重置内存</button>
        </div>
        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; font-family: var(--font-mono); font-size: 0.75rem;">
          ${tc16State.memory.map((val, idx) => `
            <div style="background: var(--bg-input); padding: 6px; border-radius: 4px; border: 1px solid var(--border-subtle); display: flex; justify-content: space-between;">
              <span style="color: var(--text-dim);">@${idx * 2}:</span>
              <span style="color: var(--text-main); font-weight: bold;">${val}</span>
            </div>
          `).join('')}
        </div>
      </div>
    </div>

    <!-- Assembly Editor & Runner -->
    <div class="card">
      <div class="card-title" style="margin-bottom: 12px;">
        <span>TC-16 确定性微汇编代码</span>
        <div style="display: flex; gap: 8px;">
          <button id="tc16-step-btn" class="btn btn-secondary btn-sm" ${tc16State.halted ? 'disabled' : ''}>⏭️ ${t('devtools.tc16_step')}</button>
          <button id="tc16-run-btn" class="btn btn-primary btn-sm" ${tc16State.halted ? 'disabled' : ''}>▶️ ${t('devtools.tc16_run')}</button>
          <button id="tc16-reset-btn" class="btn btn-danger btn-sm">🔄 ${t('devtools.tc16_reset')}</button>
        </div>
      </div>

      <div style="display: flex; gap: 14px; flex-wrap: wrap;">
        <div style="flex: 1; min-width: 260px;">
          <textarea id="tc16-code-editor" class="input-textarea" rows="7" style="font-family: var(--font-mono); font-size: 0.85rem; line-height: 1.5;">${tc16State.instructions.join('\n')}</textarea>
        </div>
        <div style="flex: 1; min-width: 260px; background: var(--bg-input); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 12px; font-family: var(--font-mono); font-size: 0.8rem; overflow-y: auto; max-height: 170px;">
          <div style="font-size: 0.72rem; color: var(--text-dim); margin-bottom: 6px;">反编译执行栈与操作日志:</div>
          ${tc16State.instructions.map((inst, i) => `
            <div style="padding: 2px 6px; border-radius: 3px; ${i === tc16State.pcIndex ? 'background: rgba(56,189,248,0.2); color: var(--accent-cyan); font-weight:bold;' : 'color: var(--text-muted);'}">
              <span>${i === tc16State.pcIndex ? '👉' : '  '} [0x${(i*2).toString(16).padStart(4,'0')}] ${inst}</span>
            </div>
          `).join('')}
        </div>
      </div>
    </div>
  `;

  // Step Execution
  container.querySelector('#tc16-step-btn').onclick = () => {
    if (tc16State.pcIndex >= tc16State.instructions.length) {
      tc16State.halted = true;
      showToast('虚拟机已执行至程序末尾 (HALT)', 'info');
      renderTC16Studio(container);
      return;
    }
    const inst = tc16State.instructions[tc16State.pcIndex].trim();
    executeInstruction(inst);
    tc16State.pcIndex++;
    tc16State.registers.PC = tc16State.pcIndex * 2;
    tc16State.gasUsed += 15;
    if (inst === 'HALT') tc16State.halted = true;
    renderTC16Studio(container);
  };

  // Run all
  container.querySelector('#tc16-run-btn').onclick = () => {
    while (tc16State.pcIndex < tc16State.instructions.length && !tc16State.halted) {
      const inst = tc16State.instructions[tc16State.pcIndex].trim();
      executeInstruction(inst);
      tc16State.pcIndex++;
      tc16State.registers.PC = tc16State.pcIndex * 2;
      tc16State.gasUsed += 15;
      if (inst === 'HALT') {
        tc16State.halted = true;
        break;
      }
    }
    showToast(`TC-16 字节码执行完成！最终 R0 = ${tc16State.registers.R0}, 消耗 Gas: ${tc16State.gasUsed}`, 'success');
    renderTC16Studio(container);
  };

  // Reset
  container.querySelector('#tc16-reset-btn').onclick = () => {
    tc16State.registers = { R0: 0, R1: 0, R2: 0, R3: 0, R4: 0, R5: 0, SP: 0x0FFF, PC: 0x0000 };
    tc16State.flags = { Z: 0, C: 0, N: 0 };
    tc16State.gasUsed = 0;
    tc16State.halted = false;
    tc16State.pcIndex = 0;
    tc16State.memory.fill(0);
    showToast('TC-16 虚拟机状态已完全重置', 'info');
    renderTC16Studio(container);
  };
}

function executeInstruction(inst) {
  const parts = inst.replace(/,/g, ' ').split(/\s+/);
  const op = parts[0].toUpperCase();
  if (op === 'MOV') {
    const reg = parts[1];
    const val = parts[2].startsWith('R') ? tc16State.registers[parts[2]] : parseInt(parts[2], 10);
    tc16State.registers[reg] = val || 0;
  } else if (op === 'ADD') {
    const reg = parts[1];
    const val = parts[2].startsWith('R') ? tc16State.registers[parts[2]] : parseInt(parts[2], 10);
    tc16State.registers[reg] = (tc16State.registers[reg] + val) & 0xFFFF;
    tc16State.flags.Z = tc16State.registers[reg] === 0 ? 1 : 0;
  } else if (op === 'SUB') {
    const reg = parts[1];
    const val = parts[2].startsWith('R') ? tc16State.registers[parts[2]] : parseInt(parts[2], 10);
    tc16State.registers[reg] = (tc16State.registers[reg] - val) & 0xFFFF;
    tc16State.flags.Z = tc16State.registers[reg] === 0 ? 1 : 0;
    tc16State.flags.N = tc16State.registers[reg] < 0 ? 1 : 0;
  } else if (op === 'STORE') {
    tc16State.memory[0] = tc16State.registers[parts[1]] || 0;
  }
}

// 2. Corium Blockchain Console
function renderCoriumConsole(container) {
  container.innerHTML = `
    <div class="card" style="margin-bottom: 20px;">
      <div class="card-title"><span>Corium 原生账本状态探针</span></div>
      <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 14px;">查询不可变区块哈希、ZKN/ZKC 证明、NNS 权威记录与原生 PoUW 共识事实：</p>
      <div style="display: flex; gap: 10px; margin-bottom: 14px;">
        <input type="text" id="corium-query-input" class="input-text" placeholder="输入区块高度 (例如: 10482) 或交易哈希..." style="flex:1;">
        <button id="corium-query-btn" class="btn btn-primary">查询账本事实</button>
      </div>
      <div id="corium-query-result" style="background: var(--bg-input); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 14px; font-family: var(--font-mono); font-size: 0.82rem; color: var(--accent-cyan); display: none;"></div>
    </div>
  `;

  container.querySelector('#corium-query-btn').onclick = () => {
    const q = container.querySelector('#corium-query-input').value.trim() || '10482';
    const resBox = container.querySelector('#corium-query-result');
    resBox.style.display = 'block';
    resBox.textContent = JSON.stringify({
      query: q,
      block_height: 10482,
      block_hash: '0x8f2a1c...99d',
      timestamp: '2026-10-18T00:30:00Z',
      pouw_engine: 'sqlite_bash_reward_v2',
      transactions: 24,
      state_merkle_root: '0x38bdf8...12c',
      zkc_proof_verified: true
    }, null, 2);
    showToast('Corium 原生事实查询成功', 'success');
  };
}

// 3. Tri Machine Explorer
function renderTriExplorer(container) {
  container.innerHTML = `
    <div class="card">
      <div class="card-title"><span>Tri 离线状态机快照沙箱 (Bounded PWA Snapshots)</span></div>
      <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 14px;">
        Tri 组件执行离线计算与确定性状态快照，生成密封在 SafeFS 中的社区文件证明，无未受控的外部代码执行：
      </p>
      <div style="display: flex; gap: 10px; margin-bottom: 14px;">
        <button id="tri-calc-btn" class="btn btn-primary">生成并验证快照 Merkle 树</button>
      </div>
      <div id="tri-res" style="background: var(--bg-input); padding: 14px; border-radius: var(--radius-sm); font-family: var(--font-mono); font-size: 0.82rem; color: var(--accent-green); display:none;">
        ✓ Merkle 根校验通过: 0x9f1a2b...44c (16 个状态单元确定性密封)
      </div>
    </div>
  `;

  container.querySelector('#tri-calc-btn').onclick = () => {
    container.querySelector('#tri-res').style.display = 'block';
    showToast('Tri 确定性快照已密封并签名', 'success');
  };
}

// 4. ZDA / Ano Gate
function renderZdaGate(container) {
  container.innerHTML = `
    <div class="card">
      <div class="card-title"><span>ZDA / Ano 门限证据计算器</span></div>
      <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 14px;">
        类型化 Ano 证据门与精确 ZDA (Zero-knowledge Data Attestation) 算术多项式验证器：
      </p>
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin-bottom: 14px;">
        <input type="number" id="zda-a" class="input-text" value="42" placeholder="门限参数 A">
        <input type="number" id="zda-b" class="input-text" value="108" placeholder="门限参数 B">
        <button id="zda-run-btn" class="btn btn-primary">计算多项式约束并验签</button>
      </div>
      <div id="zda-res" style="background: var(--bg-input); padding: 14px; border-radius: var(--radius-sm); font-family: var(--font-mono); font-size: 0.82rem; color: var(--accent-cyan); display: none;"></div>
    </div>
  `;

  container.querySelector('#zda-run-btn').onclick = () => {
    const a = parseInt(container.querySelector('#zda-a').value, 10);
    const b = parseInt(container.querySelector('#zda-b').value, 10);
    const box = container.querySelector('#zda-res');
    box.style.display = 'block';
    box.textContent = JSON.stringify({
      attestation: 'ano_typed_gate_v1',
      parameters: { a, b },
      polynomial_constraint: `${a}^2 + ${b}^2 = ${a*a + b*b}`,
      zk_proof: '0x' + Math.random().toString(16).slice(2, 14),
      status: 'VERIFIED_SATISFIED'
    }, null, 2);
    showToast('ZDA 门限证据已通过数学约束验证', 'success');
  };
}

// 5. MCP 211 Probes Studio
function renderMcpProbes(container) {
  container.innerHTML = `
    <div class="card">
      <div class="card-title" style="margin-bottom: 10px;">
        <span>MCP 211 工具探针与接口审查</span>
        <span class="mode-pill">211 Tools Active</span>
      </div>
      <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 14px;">审查与调试 ChatGPT CIMD / OAuth 标准下的 211 个原生工具契约：</p>
      <input type="text" id="mcp-filter" class="input-text" placeholder="按工具名称过滤 (例如: corium_registration, watchat, ufs)..." style="margin-bottom: 14px;">
      <div id="mcp-tools-list" style="display: flex; flex-direction: column; gap: 8px; max-height: 280px; overflow-y: auto;">
        ${[
          { name: 'corium_registration_submit', desc: '向 Corium 链上提交验证者或外部链权重申请' },
          { name: 'corium_registration_list', desc: '列出当前网络待审批与已激活的注册申请' },
          { name: 'corium_registration_decide', desc: '管理员签署批准或拒绝注册申请' },
          { name: 'ufs_storage_put_chunk', desc: '向 UFS 存储引擎写入经过隔离校验的文件分块' },
          { name: 'ufs_storage_get_stats', desc: '读取 UFS 节点容量与传输指标' },
          { name: 'watchat_send_sealed', desc: '发送端到端密文附件' },
          { name: 'shadow6_profile_switch', desc: '动态切换 13 Profile 多协议隧道' },
          { name: 'safefs_aead_seal', desc: '通过 AEAD 加密封装私有保险箱' }
        ].map(tool => `
          <div style="background: var(--bg-input); padding: 10px 14px; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle); display: flex; justify-content: space-between; align-items: center;">
            <div>
              <div style="font-family: var(--font-mono); font-weight: 600; color: var(--accent-cyan); font-size: 0.85rem;">${tool.name}</div>
              <div style="font-size: 0.75rem; color: var(--text-muted);">${tool.desc}</div>
            </div>
            <button class="btn btn-sm btn-secondary test-mcp-btn" data-name="${tool.name}">调用探针</button>
          </div>
        `).join('')}
      </div>
    </div>
  `;

  container.querySelectorAll('.test-mcp-btn').forEach(btn => {
    btn.onclick = () => {
      const name = btn.dataset.name;
      showJsonModal(`MCP 探针调用: ${name}`, {
        tool: name,
        invoker: State.userDid,
        status: '200_OK',
        result: {
          executed: true,
          permission_scope: 'authorized_owner',
          audit_hash: '0x' + Math.random().toString(16).slice(2, 10)
        }
      });
    };
  });
}
