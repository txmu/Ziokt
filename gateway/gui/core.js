// ==============================================================================
// Ziokt Unified Graphical Client - Core Application Framework & State Manager
// ==============================================================================

export function getStorage(key, fallback = '') {
  try {
    const v = localStorage.getItem(key);
    return v !== null ? v : fallback;
  } catch (e) {
    return fallback;
  }
}

export function setStorage(key, val) {
  try {
    localStorage.setItem(key, val);
  } catch (e) {
    console.warn(`Failed to set storage for ${key}:`, e);
  }
}

function getInitialLang() {
  const raw = getStorage('ziokt_lang') || (typeof navigator !== 'undefined' ? navigator.language : 'zh') || 'zh';
  return raw.toLowerCase().startsWith('en') ? 'en' : 'zh';
}

export const State = {
  currentTab: 'home',
  language: getInitialLang(),
  theme: getStorage('ziokt_theme', 'dark'),
  runtimeMode: getStorage('ziokt_mode', 'local'), // 'local' | 'remote' | 'hybrid'
  gatewayUrl: getStorage('ziokt_gateway', 'https://cor-web.ziokt.com'),
  localGatewayUrl: 'http://127.0.0.1:8185',
  userDid: getStorage('ziokt_did', 'did:ziokt:800a3e4c08b13a41b41632a2bd8f0065'),
  components: {
    corium: { name: 'Corium Blockchain', status: 'online', port: 8545 },
    shadow6: { name: 'Shadow6 Mesh Cluster', status: 'online', port: 8186 },
    ufs: { name: 'UFS & dCPM Storage', status: 'online', port: 8184 },
    watchat: { name: 'WATChat Bridge', status: 'online', port: 8181 },
    etp: { name: 'ETP Onion Gateway', status: 'online', port: 9050 }
  },
  i18nData: {},
  events: {}
};

// Event Bus
export const Events = {
  on(event, callback) {
    if (!State.events[event]) State.events[event] = [];
    State.events[event].push(callback);
  },
  emit(event, data) {
    if (State.events[event]) {
      State.events[event].forEach(cb => cb(data));
    }
  }
};

export const BUILTIN_I18N = {"zh": {"app": {"title": "Ziokt 统一图形客户端", "subtitle": "去中心化原生操作系统与应用生态控制中心", "version": "v1.0.0 (Core Native)", "status_online": "正常运行", "status_offline": "已断开", "status_connecting": "连接中...", "mode_local": "本地节点", "mode_remote": "远程网关", "mode_hybrid": "混合模式", "switch_lang": "语言 / Language", "theme_dark": "赛博深黑", "theme_light": "清爽明亮", "theme_contrast": "高对比度"}, "nav": {"home": "首页总览", "chat": "加密通讯", "forum": "社区论坛", "files": "安全存储", "apps": "应用中心", "network": "网络节点", "identity": "身份与贡献", "devtools": "开发工具", "settings": "系统设置"}, "common": {"confirm": "确认", "cancel": "取消", "delete": "删除", "save": "保存", "edit": "编辑", "copy": "复制", "copied": "已复制到剪贴板", "refresh": "刷新", "search": "搜索...", "loading": "加载中...", "success": "操作成功", "error": "操作失败", "details": "查看详情", "actions": "操作", "status": "状态", "name": "名称", "version": "版本", "size": "大小", "date": "时间", "upload": "上传", "download": "下载", "view_raw": "查看原始数据", "advanced": "高级选项", "close": "关闭"}, "home": {"welcome": "欢迎使用 Ziokt 统一图形客户端", "welcome_sub": "集成零知识加密通讯、去中心化包管理、多协议隧道及链上可信微架构", "quick_actions": "快捷功能入口", "system_health": "核心组件健康状态", "gateway_telemetry": "网关实时遥测", "recent_activity": "近期网络活动", "act_chat": "快速发起加密对话", "act_files": "打开原生文件保险库", "act_forum": "浏览社区最新提案", "act_apps": "管理与运行扩展包", "act_network": "查看 Shadow6 / ETP 网格"}, "chat": {"title": "WATChat 端到端加密通讯", "dual_ui": "界面风格切换", "ui_minimalist": "现代简约版", "ui_classic": "经典丰富版", "ui_switch_tip": "随时切换界面布局，聊天记录与加密密钥实时同步无损保留", "contacts": "联系人 / 对话列表", "new_conversation": "新建加密对话", "enter_recipient": "输入对方 DID 或公钥地址", "send": "发送", "input_placeholder": "输入加密消息...", "attach_file": "发送文件附件", "encryption_badge": "XChaCha20-Poly1305 端到端保密", "empty_messages": "暂无历史消息，发送一条问候开启端到端密聊吧"}, "forum": {"title": "Corium 去中心化社区论坛", "new_post": "发布新帖 / 提案", "post_title": "标题", "post_category": "分类", "post_content": "正文内容 (支持 Markdown)", "sign_and_publish": "使用当前身份签名并发布", "cat_governance": "生态治理", "cat_technical": "核心技术", "cat_apps": "应用开发", "cat_general": "综合讨论", "signature_verified": "Ed25519 链上签名已验证", "replies": "条回复"}, "files": {"title": "UFS & SafeFS 安全存储保险库", "vault_type": "存储驱动", "vault_ufs": "UFS 原生文件系统", "vault_safefs": "SafeFS AEAD 加密保险箱", "upload_file": "上传文件", "create_folder": "新建目录", "stealth_mode": "双层可抵赖卷 (Outer Decoy / Inner Stealth)", "drop_tip": "拖拽文件至此处，自动执行安全分块持久化", "download": "下载文件", "delete_confirm": "确定永久删除此文件吗？此操作不可逆。"}, "apps": {"title": "dCPM 去中心化应用中心", "subtitle": "基于 UFS 与 dCPM 签名软件包体系，支持依赖审查、自动验签与安全沙箱执行", "install_pkg": "安装 / 导入 .dcpm 软件包", "installed_tab": "已安装应用", "market_tab": "生态软件包仓库", "rollback": "版本回滚", "uninstall": "卸载", "update": "检查更新", "publisher": "发布者签名", "digest": "SHA-256 校验摘要", "dependencies": "依赖组件", "dep_check_ok": "依赖项完整", "install_confirm": "确定安装此签名软件包吗？将严格在隔离沙箱中运行。", "uninstall_confirm": "确定卸载该应用及其本地缓存吗？"}, "network": {"title": "Shadow6 & ETP 网络节点网格", "subtitle": "管理 13 核心 Profile 运行集群、Virtual Broker 以及洋葱代理链路", "profiles_title": "13 语言核心 Profile 实时集群", "virtual_broker": "虚拟 Broker 代理状态", "s6p1_import": "粘贴导入自定义 S6P1 凭据信封", "etp_title": "ETP 原生洋葱多跳链路", "hops": "跳路由路径", "ping_test": "网络延迟诊断", "privacy_masked": "非管理员模式已自动脱敏保护敏感 IP 与密钥"}, "identity": {"title": "身份管理与贡献证明 (PoUW)", "did": "去中心化身份 (DID)", "nns_domain": "NNS 绑定域名", "pouw_status": "PoUW 算力与共识贡献状态", "engine_reward": "治理奖励权重", "apply_weight": "申请加入验证者权重白名单", "export_keys": "导出加密密钥备份", "switch_account": "切换身份"}, "devtools": {"title": "原生组件全功能开发工具箱", "subtitle": "提供 Corium、Tri、ZDA、TC-16 虚拟机及 MCP 接口全功能调试与执行界面", "tab_corium": "Corium 控制台", "tab_tri": "Tri 状态机快照", "tab_zda": "ZDA / Ano 门限计算", "tab_tc16": "TC-16 虚拟机工作台", "tab_mcp": "MCP 211 工具探针", "corium_query": "查询区块与交易事实", "tri_run": "执行快照离线隔离沙箱", "zda_calc": "验证精确 ZDA 证据算术", "tc16_asm": "TC-16 汇编与字节码单步调试", "tc16_run": "运行虚拟机", "tc16_step": "单步执行 (Step)", "tc16_reset": "重置寄存器"}, "settings": {"title": "系统与组件生命周期设置", "runtime_mode": "客户端运行模式配置", "local_gateway_url": "本地/远程网关地址", "components_lifecycle": "按需组件启动管理 (On-demand Launcher)", "comp_corium": "Corium 原生区块链服务", "comp_shadow6": "Shadow6 多核心代理网络", "comp_ufs": "UFS & dCPM 安全存储引擎", "comp_watchat": "WATChat 联邦通讯桥接", "comp_etp": "ETP 洋葱网关路由", "accessibility": "无障碍与键盘导航", "keyboard_shortcuts": "快捷键说明: [1-9] 切换模块，[Esc] 关闭弹窗，[Ctrl+K] 全局搜索"}}, "en": {"app": {"title": "Ziokt Unified Graphical Client", "subtitle": "Decentralized Native OS & Application Ecosystem Console", "version": "v1.0.0 (Core Native)", "status_online": "Online", "status_offline": "Disconnected", "status_connecting": "Connecting...", "mode_local": "Local Node", "mode_remote": "Remote Gateway", "mode_hybrid": "Hybrid Mode", "switch_lang": "Language / 语言", "theme_dark": "Cyber Dark", "theme_light": "Clean Light", "theme_contrast": "High Contrast"}, "nav": {"home": "Home", "chat": "WATChat", "forum": "Forum", "files": "Files & Vault", "apps": "App Store", "network": "Network Nodes", "identity": "Identity & PoUW", "devtools": "Dev Tools", "settings": "Settings"}, "common": {"confirm": "Confirm", "cancel": "Cancel", "delete": "Delete", "save": "Save", "edit": "Edit", "copy": "Copy", "copied": "Copied to clipboard", "refresh": "Refresh", "search": "Search...", "loading": "Loading...", "success": "Success", "error": "Error", "details": "Details", "actions": "Actions", "status": "Status", "name": "Name", "version": "Version", "size": "Size", "date": "Date", "upload": "Upload", "download": "Download", "view_raw": "View Raw JSON", "advanced": "Advanced", "close": "Close"}, "home": {"welcome": "Welcome to Ziokt Unified Graphical Client", "welcome_sub": "Integrating Zero-Knowledge communications, dCPM packages, Shadow6 mesh tunnels, and verifiable native compute", "quick_actions": "Quick Actions", "system_health": "Component Health", "gateway_telemetry": "Gateway Telemetry", "recent_activity": "Recent Activity", "act_chat": "Start Encrypted Chat", "act_files": "Open Secure File Vault", "act_forum": "Browse Latest Proposals", "act_apps": "Manage dCPM Packages", "act_network": "Inspect Shadow6 & ETP Mesh"}, "chat": {"title": "WATChat End-to-End Encrypted Messenger", "dual_ui": "UI Switcher", "ui_minimalist": "Modern Minimalist", "ui_classic": "Classic Rich", "ui_switch_tip": "Seamlessly switch between layouts; message history and cryptographic keys are synchronized without loss", "contacts": "Contacts / Dialogs", "new_conversation": "New Secure Chat", "enter_recipient": "Enter recipient DID or public key", "send": "Send", "input_placeholder": "Type encrypted message...", "attach_file": "Attach Vault File", "encryption_badge": "XChaCha20-Poly1305 Sealed", "empty_messages": "No messages yet. Send a greeting to start secure chatting."}, "forum": {"title": "Corium Decentralized Community Forum", "new_post": "New Post / Proposal", "post_title": "Title", "post_category": "Category", "post_content": "Content (Markdown supported)", "sign_and_publish": "Sign with Ed25519 & Publish", "cat_governance": "Governance", "cat_technical": "Technical", "cat_apps": "App Development", "cat_general": "General Discussion", "signature_verified": "Ed25519 On-Chain Signature Verified", "replies": "replies"}, "files": {"title": "UFS & SafeFS Secure Storage Vault", "vault_type": "Storage Driver", "vault_ufs": "UFS Native Storage", "vault_safefs": "SafeFS AEAD Encrypted Vault", "upload_file": "Upload File", "create_folder": "New Folder", "stealth_mode": "Deniable Volume (Outer Decoy / Inner Stealth)", "drop_tip": "Drag and drop files here for chunked persistent storage", "download": "Download File", "delete_confirm": "Are you sure you want to permanently delete this file? This cannot be undone."}, "apps": {"title": "dCPM Decentralized App Center", "subtitle": "Built on UFS and signed dCPM package architecture with dependency verification and sandbox isolation", "install_pkg": "Install / Import .dcpm Package", "installed_tab": "Installed Applications", "market_tab": "Ecosystem Repository", "rollback": "Rollback Version", "uninstall": "Uninstall", "update": "Check Updates", "publisher": "Publisher Key", "digest": "SHA-256 Digest", "dependencies": "Dependencies", "dep_check_ok": "All Dependencies Satisfied", "install_confirm": "Confirm installation of this signed package? It will execute inside an isolated sandbox.", "uninstall_confirm": "Confirm uninstallation of this package and its local cache?"}, "network": {"title": "Shadow6 & ETP Network Mesh", "subtitle": "Manage 13 language core Profile cluster, Virtual Broker, and onion routing paths", "profiles_title": "13 Core Language Profiles Cluster", "virtual_broker": "Virtual Broker Status", "s6p1_import": "Import Custom S6P1 Credential Envelope", "etp_title": "ETP Native Onion Multi-Hop Paths", "hops": "hop route path", "ping_test": "Latency Diagnostics", "privacy_masked": "Non-admin mode has automatically masked sensitive IPs and private keys"}, "identity": {"title": "Identity & Proof of Useful Work (PoUW)", "did": "Decentralized ID (DID)", "nns_domain": "NNS Bound Domain", "pouw_status": "PoUW Compute & Consensus Contribution", "engine_reward": "Governance Reward Weight", "apply_weight": "Apply for Validator Weight Whitelist", "export_keys": "Export Encrypted Backup", "switch_account": "Switch Identity"}, "devtools": {"title": "Native Component Developer Studio", "subtitle": "Fully functional GUIs for Corium, Tri, ZDA, TC-16 Virtual Machine, and MCP diagnostics", "tab_corium": "Corium Console", "tab_tri": "Tri Snapshots", "tab_zda": "ZDA / Ano Gate", "tab_tc16": "TC-16 VM Studio", "tab_mcp": "MCP 211 Probes", "corium_query": "Query Ledger Facts & Blocks", "tri_run": "Execute Isolated Sandbox Snapshot", "zda_calc": "Verify Exact ZDA Evidence Arithmetic", "tc16_asm": "TC-16 Assembly & Bytecode Debugger", "tc16_run": "Run Virtual Machine", "tc16_step": "Step Execution", "tc16_reset": "Reset Registers"}, "settings": {"title": "System & Component Lifecycle Settings", "runtime_mode": "Client Runtime Mode", "local_gateway_url": "Gateway Endpoint", "components_lifecycle": "On-Demand Component Launcher", "comp_corium": "Corium Native Blockchain", "comp_shadow6": "Shadow6 Multi-Core Tunnel", "comp_ufs": "UFS & dCPM Storage Engine", "comp_watchat": "WATChat Federation Bridge", "comp_etp": "ETP Onion Gateway Router", "accessibility": "Accessibility & Keyboard Navigation", "keyboard_shortcuts": "Shortcuts: [1-9] Switch Modules, [Esc] Close Modals, [Ctrl+K] Global Search"}}};

// i18n Translation Engine
export async function initI18n() {
  const lang = State.language.toLowerCase().startsWith('en') ? 'en' : 'zh';
  if (typeof BUILTIN_I18N !== 'undefined' && BUILTIN_I18N[lang]) {
    State.i18nData = Object.assign({}, BUILTIN_I18N[lang]);
  }
  try {
    const res = await fetch(`i18n/${lang}.json`);
    if (res.ok) {
      const data = await res.json();
      State.i18nData = Object.assign({}, State.i18nData, data);
    }
  } catch (e) {
    // Built-in dictionaries active
  }
}

export function t(path) {
  const parts = path.split('.');
  let curr = State.i18nData;
  for (const p of parts) {
    if (curr && curr[p] !== undefined) {
      curr = curr[p];
    } else {
      return path;
    }
  }
  return curr;
}

export async function setLanguage(lang) {
  State.language = lang;
  setStorage('ziokt_lang', lang);
  await initI18n();
  Events.emit('language_changed', lang);
}

export function setTheme(theme) {
  State.theme = theme;
  setStorage('ziokt_theme', theme);
  document.documentElement.setAttribute('data-theme', theme);
  Events.emit('theme_changed', theme);
}

// UI Notification Toast
export function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${type === 'success' ? '✓' : type === 'error' ? '✕' : 'ℹ'}</span> <span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 250);
  }, 3500);
}

// Confirmation Dialog Modal (Promise-based)
export function showConfirm(title, message) {
  return new Promise((resolve) => {
    const overlay = document.getElementById('modal-overlay');
    const titleEl = document.getElementById('modal-title');
    const bodyEl = document.getElementById('modal-body');
    const footerEl = document.getElementById('modal-footer');
    
    titleEl.textContent = title;
    bodyEl.innerHTML = `<p style="line-height:1.6;color:var(--text-main);">${message}</p>`;
    footerEl.innerHTML = `
      <button class="btn btn-secondary" id="modal-cancel">${t('common.cancel')}</button>
      <button class="btn btn-primary" id="modal-ok">${t('common.confirm')}</button>
    `;
    
    overlay.style.display = 'flex';
    
    const cleanup = () => {
      overlay.style.display = 'none';
      document.getElementById('modal-cancel')?.removeEventListener('click', onCancel);
      document.getElementById('modal-ok')?.removeEventListener('click', onOk);
    };
    
    const onCancel = () => { cleanup(); resolve(false); };
    const onOk = () => { cleanup(); resolve(true); };
    
    document.getElementById('modal-cancel').addEventListener('click', onCancel);
    document.getElementById('modal-ok').addEventListener('click', onOk);
  });
}

// Raw JSON View Modal
export function showJsonModal(title, data) {
  const overlay = document.getElementById('modal-overlay');
  const titleEl = document.getElementById('modal-title');
  const bodyEl = document.getElementById('modal-body');
  const footerEl = document.getElementById('modal-footer');
  
  titleEl.textContent = title;
  const jsonStr = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
  bodyEl.innerHTML = `<pre style="background:var(--bg-input);padding:14px;border-radius:6px;font-family:var(--font-mono);font-size:0.8rem;color:var(--accent-cyan);overflow:auto;max-height:55vh;white-space:pre-wrap;">${jsonStr}</pre>`;
  footerEl.innerHTML = `
    <button class="btn btn-secondary" id="modal-copy">${t('common.copy')}</button>
    <button class="btn btn-primary" id="modal-close">${t('common.close')}</button>
  `;
  overlay.style.display = 'flex';
  
  document.getElementById('modal-copy').onclick = () => {
    navigator.clipboard.writeText(jsonStr);
    showToast(t('common.copied'), 'success');
  };
  document.getElementById('modal-close').onclick = () => {
    overlay.style.display = 'none';
  };
}

// Unified Gateway API Client
export async function apiRequest(endpoint, options = {}) {
  const base = State.runtimeMode === 'local' ? State.localGatewayUrl : State.gatewayUrl;
  const url = endpoint.startsWith('http') ? endpoint : `${base}${endpoint.startsWith('/') ? '' : '/'}${endpoint}`;
  
  const headers = {
    'Accept': 'application/json',
    ...(options.headers || {})
  };

  try {
    const res = await fetch(url, { ...options, headers });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    }
    const contentType = res.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      return await res.json();
    }
    return await res.text();
  } catch (err) {
    // If local mode failed, try fallback or notify
    console.warn(`API call failed for ${url}:`, err);
    throw err;
  }
}
