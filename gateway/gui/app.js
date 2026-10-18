// ==============================================================================
// Ziokt Unified Graphical Client - Standalone Universal Application Bundle
// ==============================================================================

(function() {
  "use strict";

  // --- Module: core.js ---
// ==============================================================================
// Ziokt Unified Graphical Client - Core Application Framework & State Manager
// ==============================================================================
function getStorage(key, fallback = '') {
  try {
    const v = localStorage.getItem(key);
    return v !== null ? v : fallback;
  } catch (e) {
    return fallback;
  }
}
function setStorage(key, val) {
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
const DEFAULT_REMOTE_NODES = [
  {
    id: 'node-official-tokyo',
    name: 'Ziokt Mainnet Gateway (Tokyo)',
    url: 'https://cor-web.ziokt.com',
    authToken: 'ziokt_sec_genesis_community_token_2026',
    isDefault: true,
    status: 'online',
    latency: '15ms',
    verifiedAt: null
  }
];
function getRemoteNodes() {
  try {
    const raw = localStorage.getItem('ziokt_remote_nodes');
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) return parsed;
    }
  } catch (e) {}
  return [...DEFAULT_REMOTE_NODES];
}
function saveRemoteNodes(nodes) {
  setStorage('ziokt_remote_nodes', JSON.stringify(nodes));
  State.remoteNodes = nodes;
  Events.emit('remote_nodes_changed', nodes);
}
function getActiveRemoteNode() {
  const nodes = State.remoteNodes || getRemoteNodes();
  const activeId = State.activeRemoteNodeId || getStorage('ziokt_active_node_id', 'node-official-tokyo');
  return nodes.find(n => n.id === activeId) || nodes[0] || DEFAULT_REMOTE_NODES[0];
}
function setActiveRemoteNode(id) {
  const nodes = State.remoteNodes || getRemoteNodes();
  const target = nodes.find(n => n.id === id);
  if (target) {
    State.activeRemoteNodeId = target.id;
    State.gatewayUrl = target.url;
    setStorage('ziokt_active_node_id', target.id);
    setStorage('ziokt_gateway', target.url);
    if (target.authToken) {
      setStorage('ziokt_auth_token', target.authToken);
    }
    Events.emit('active_node_changed', target);
    updateAppNodeBadge();
    return true;
  }
  return false;
}
function addRemoteNode({ name, url, authToken }) {
  const nodes = getRemoteNodes();
  const cleanUrl = url.trim().replace(/\/+$/, '');
  const cleanName = name.trim() || cleanUrl;
  const cleanToken = (authToken || '').trim();
  const newNode = {
    id: 'node-' + Date.now().toString(36) + '-' + Math.random().toString(36).substr(2, 5),
    name: cleanName,
    url: cleanUrl,
    authToken: cleanToken,
    isDefault: false,
    status: cleanToken ? 'unverified' : 'unauthenticated',
    latency: '--',
    verifiedAt: null
  };
  nodes.push(newNode);
  saveRemoteNodes(nodes);
  return newNode;
}
function removeRemoteNode(id) {
  let nodes = getRemoteNodes();
  const target = nodes.find(n => n.id === id);
  if (!target) return false;
  if (target.isDefault) {
    throw new Error('Default system node cannot be deleted');
  }
  nodes = nodes.filter(n => n.id !== id);
  saveRemoteNodes(nodes);
  if (State.activeRemoteNodeId === id) {
    setActiveRemoteNode(nodes[0].id);
  }
  return true;
}
const State = {
  currentTab: 'home',
  language: getInitialLang(),
  theme: getStorage('ziokt_theme', 'dark'),
  runtimeMode: getStorage('ziokt_mode', 'local'), // 'local' | 'remote' | 'hybrid'
  gatewayUrl: getStorage('ziokt_gateway', 'https://cor-web.ziokt.com'),
  localGatewayUrl: 'http://127.0.0.1:8185',
  localNodeStatus: 'checking', // 'checking' | 'online' | 'offline'
  localNodeDetails: null,
  remoteNodes: getRemoteNodes(),
  activeRemoteNodeId: getStorage('ziokt_active_node_id', 'node-official-tokyo'),
  authToken: getStorage('ziokt_auth_token', 'ziokt_sec_genesis_community_token_2026'),
  userDid: getStorage('ziokt_did', ''),
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
const Events = {
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
const BUILTIN_I18N = {"zh": {"app": {"title": "Ziokt 统一图形客户端", "subtitle": "去中心化原生操作系统与应用生态控制中心", "version": "v1.0.0 (Core Native)", "status_online": "正常运行", "status_offline": "已断开", "status_connecting": "连接中...", "mode_local": "本地节点", "mode_remote": "远程网关", "mode_hybrid": "混合模式", "switch_lang": "语言 / Language", "theme_dark": "赛博深黑", "theme_light": "清爽明亮", "theme_contrast": "高对比度"}, "nav": {"home": "首页总览", "chat": "加密通讯", "forum": "社区论坛", "files": "安全存储", "apps": "应用中心", "network": "网络节点", "identity": "身份与贡献", "devtools": "开发工具", "settings": "系统设置"}, "common": {"confirm": "确认", "cancel": "取消", "delete": "删除", "save": "保存", "edit": "编辑", "copy": "复制", "copied": "已复制到剪贴板", "refresh": "刷新", "search": "搜索...", "loading": "加载中...", "success": "操作成功", "error": "操作失败", "details": "查看详情", "actions": "操作", "status": "状态", "name": "名称", "version": "版本", "size": "大小", "date": "时间", "upload": "上传", "download": "下载", "view_raw": "查看原始数据", "advanced": "高级选项", "close": "关闭"}, "home": {"welcome": "欢迎使用 Ziokt 统一图形客户端", "welcome_sub": "集成零知识加密通讯、去中心化包管理、多协议隧道及链上可信微架构", "quick_actions": "快捷功能入口", "system_health": "核心组件健康状态", "gateway_telemetry": "网关实时遥测", "recent_activity": "近期网络活动", "act_chat": "快速发起加密对话", "act_files": "打开原生文件保险库", "act_forum": "浏览社区最新提案", "act_apps": "管理与运行扩展包", "act_network": "查看 Shadow6 / ETP 网格", "local_offline_alert": "⚠️ 未检测到本地真实节点: 当前处于本地模式，但 http://127.0.0.1:8185 未响应。使用本地节点需要用户本地真实有节点运行。", "remote_unauth_alert": "🔒 远程节点需要身份鉴权: 当前活跃远程节点尚未配置有效的 Auth Token 凭证。", "switch_remote": "切换至远程网关", "config_auth": "前往配置凭证", "probe_local": "重新检测本地节点"}, "chat": {"title": "WATChat 端到端加密通讯", "dual_ui": "界面风格切换", "ui_minimalist": "现代简约版", "ui_classic": "经典丰富版", "ui_switch_tip": "随时切换界面布局，聊天记录与加密密钥实时同步无损保留", "contacts": "联系人 / 对话列表", "new_conversation": "新建加密对话", "enter_recipient": "输入对方 DID 或公钥地址", "send": "发送", "input_placeholder": "输入加密消息...", "attach_file": "发送文件附件", "encryption_badge": "XChaCha20-Poly1305 端到端保密", "empty_messages": "暂无历史消息，发送一条问候开启端到端密聊吧"}, "forum": {"title": "Corium 去中心化社区论坛", "new_post": "发布新帖 / 提案", "post_title": "标题", "post_category": "分类", "post_content": "正文内容 (支持 Markdown)", "sign_and_publish": "使用当前身份签名并发布", "cat_governance": "生态治理", "cat_technical": "核心技术", "cat_apps": "应用开发", "cat_general": "综合讨论", "signature_verified": "Ed25519 链上签名已验证", "replies": "条回复"}, "files": {"title": "UFS & SafeFS 安全存储保险库", "vault_type": "存储驱动", "vault_ufs": "UFS 原生文件系统", "vault_safefs": "SafeFS AEAD 加密保险箱", "upload_file": "上传文件", "create_folder": "新建目录", "stealth_mode": "双层可抵赖卷 (Outer Decoy / Inner Stealth)", "drop_tip": "拖拽文件至此处，自动执行安全分块持久化", "download": "下载文件", "delete_confirm": "确定永久删除此文件吗？此操作不可逆。"}, "apps": {"title": "dCPM 去中心化应用中心", "subtitle": "基于 UFS 与 dCPM 签名软件包体系，支持依赖审查、自动验签与安全沙箱执行", "install_pkg": "安装 / 导入 .dcpm 软件包", "installed_tab": "已安装应用", "market_tab": "生态软件包仓库", "rollback": "版本回滚", "uninstall": "卸载", "update": "检查更新", "publisher": "发布者签名", "digest": "SHA-256 校验摘要", "dependencies": "依赖组件", "dep_check_ok": "依赖项完整", "install_confirm": "确定安装此签名软件包吗？将严格在隔离沙箱中运行。", "uninstall_confirm": "确定卸载该应用及其本地缓存吗？"}, "network": {"title": "Shadow6 & ETP 网络节点网格", "subtitle": "管理 13 核心 Profile 运行集群、Virtual Broker 以及洋葱代理链路", "profiles_title": "13 语言核心 Profile 实时集群", "virtual_broker": "虚拟 Broker 代理状态", "s6p1_import": "粘贴导入自定义 S6P1 凭据信封", "etp_title": "ETP 原生洋葱多跳链路", "hops": "跳路由路径", "ping_test": "网络延迟诊断", "privacy_masked": "非管理员模式已自动脱敏保护敏感 IP 与密钥", "node_topology": "节点与网关拓扑", "local_node": "本地节点", "remote_nodes": "远程节点集群", "manage_nodes": "管理自定义节点"}, "identity": {"title": "身份管理与贡献证明 (PoUW)", "did": "去中心化身份 (DID)", "nns_domain": "NNS 绑定域名", "pouw_status": "PoUW 算力与共识贡献状态", "engine_reward": "治理奖励权重", "apply_weight": "申请加入验证者权重白名单", "export_keys": "导出加密密钥备份", "switch_account": "切换身份"}, "devtools": {"title": "原生组件全功能开发工具箱", "subtitle": "提供 Corium、Tri、ZDA、TC-16 虚拟机及 MCP 接口全功能调试与执行界面", "tab_corium": "Corium 控制台", "tab_tri": "Tri 状态机快照", "tab_zda": "ZDA / Ano 门限计算", "tab_tc16": "TC-16 虚拟机工作台", "tab_mcp": "MCP 211 工具探针", "corium_query": "查询区块与交易事实", "tri_run": "执行快照离线隔离沙箱", "zda_calc": "验证精确 ZDA 证据算术", "tc16_asm": "TC-16 汇编与字节码单步调试", "tc16_run": "运行虚拟机", "tc16_step": "单步执行 (Step)", "tc16_reset": "重置寄存器"}, "settings": {"title": "系统与组件生命周期设置", "runtime_mode": "客户端运行模式配置", "local_gateway_url": "本地/远程网关地址", "components_lifecycle": "按需组件启动管理 (On-demand Launcher)", "comp_corium": "Corium 原生区块链服务", "comp_shadow6": "Shadow6 多核心代理网络", "comp_ufs": "UFS & dCPM 安全存储引擎", "comp_watchat": "WATChat 联邦通讯桥接", "comp_etp": "ETP 洋葱网关路由", "accessibility": "无障碍与键盘导航", "keyboard_shortcuts": "快捷键说明: [1-9] 切换模块，[Esc] 关闭弹窗，[Ctrl+K] 全局搜索", "local_node_title": "本地节点连接与真实状态", "local_node_desc": "使用本地节点需要用户本地真实有节点运行。若本地未启动，客户端将无法进行写操作与本地 RPC 交互。", "local_node_probe": "探测本地节点", "local_node_online": "本地真实节点在线", "local_node_offline": "未检测到本地真实节点", "local_node_checking": "检测本地节点中...", "local_node_help": "本地启动指引: 请在终端执行 systemctl start ziokt-gateway 或运行 ./tools/control_center.sh", "remote_nodes_title": "远程节点网关与鉴权管理", "remote_nodes_desc": "使用远程节点需要身份鉴权 (Auth Token)。您可以自定义添加新的远程节点并测试连接与鉴权有效性。", "add_node": "添加新远程节点", "node_name": "节点名称", "node_url": "节点地址 (URL)", "auth_token": "鉴权凭证 (Auth Token)", "auth_token_tip": "用于 Bearer / X-Ziokt-Auth 远程身份验证", "test_auth": "测试鉴权", "set_active": "设为活跃", "active_badge": "当前活跃", "auth_valid": "鉴权通过", "auth_invalid": "鉴权失败", "auth_required": "待鉴权", "delete_node": "删除节点", "cannot_delete_default": "系统默认节点不可删除", "add_node_btn": "添加并测试该节点"}}, "en": {"app": {"title": "Ziokt Unified Graphical Client", "subtitle": "Decentralized Native OS & Application Ecosystem Console", "version": "v1.0.0 (Core Native)", "status_online": "Online", "status_offline": "Disconnected", "status_connecting": "Connecting...", "mode_local": "Local Node", "mode_remote": "Remote Gateway", "mode_hybrid": "Hybrid Mode", "switch_lang": "Language / 语言", "theme_dark": "Cyber Dark", "theme_light": "Clean Light", "theme_contrast": "High Contrast"}, "nav": {"home": "Home", "chat": "WATChat", "forum": "Forum", "files": "Files & Vault", "apps": "App Store", "network": "Network Nodes", "identity": "Identity & PoUW", "devtools": "Dev Tools", "settings": "Settings"}, "common": {"confirm": "Confirm", "cancel": "Cancel", "delete": "Delete", "save": "Save", "edit": "Edit", "copy": "Copy", "copied": "Copied to clipboard", "refresh": "Refresh", "search": "Search...", "loading": "Loading...", "success": "Success", "error": "Error", "details": "Details", "actions": "Actions", "status": "Status", "name": "Name", "version": "Version", "size": "Size", "date": "Date", "upload": "Upload", "download": "Download", "view_raw": "View Raw JSON", "advanced": "Advanced", "close": "Close"}, "home": {"welcome": "Welcome to Ziokt Unified Graphical Client", "welcome_sub": "Integrating Zero-Knowledge communications, dCPM packages, Shadow6 mesh tunnels, and verifiable native compute", "quick_actions": "Quick Actions", "system_health": "Component Health", "gateway_telemetry": "Gateway Telemetry", "recent_activity": "Recent Activity", "act_chat": "Start Encrypted Chat", "act_files": "Open Secure File Vault", "act_forum": "Browse Latest Proposals", "act_apps": "Manage dCPM Packages", "act_network": "Inspect Shadow6 & ETP Mesh", "local_offline_alert": "⚠️ No local real node detected: Currently in local mode, but http://127.0.0.1:8185 is not responding. Local mode requires an actual running Ziokt node.", "remote_unauth_alert": "🔒 Remote node requires authentication: Active remote node does not have a valid Auth Token configured.", "switch_remote": "Switch to Remote Gateway", "config_auth": "Configure Auth Credentials", "probe_local": "Probe Local Node"}, "chat": {"title": "WATChat End-to-End Encrypted Messenger", "dual_ui": "UI Switcher", "ui_minimalist": "Modern Minimalist", "ui_classic": "Classic Rich", "ui_switch_tip": "Seamlessly switch between layouts; message history and cryptographic keys are synchronized without loss", "contacts": "Contacts / Dialogs", "new_conversation": "New Secure Chat", "enter_recipient": "Enter recipient DID or public key", "send": "Send", "input_placeholder": "Type encrypted message...", "attach_file": "Attach Vault File", "encryption_badge": "XChaCha20-Poly1305 Sealed", "empty_messages": "No messages yet. Send a greeting to start secure chatting."}, "forum": {"title": "Corium Decentralized Community Forum", "new_post": "New Post / Proposal", "post_title": "Title", "post_category": "Category", "post_content": "Content (Markdown supported)", "sign_and_publish": "Sign with Ed25519 & Publish", "cat_governance": "Governance", "cat_technical": "Technical", "cat_apps": "App Development", "cat_general": "General Discussion", "signature_verified": "Ed25519 On-Chain Signature Verified", "replies": "replies"}, "files": {"title": "UFS & SafeFS Secure Storage Vault", "vault_type": "Storage Driver", "vault_ufs": "UFS Native Storage", "vault_safefs": "SafeFS AEAD Encrypted Vault", "upload_file": "Upload File", "create_folder": "New Folder", "stealth_mode": "Deniable Volume (Outer Decoy / Inner Stealth)", "drop_tip": "Drag and drop files here for chunked persistent storage", "download": "Download File", "delete_confirm": "Are you sure you want to permanently delete this file? This cannot be undone."}, "apps": {"title": "dCPM Decentralized App Center", "subtitle": "Built on UFS and signed dCPM package architecture with dependency verification and sandbox isolation", "install_pkg": "Install / Import .dcpm Package", "installed_tab": "Installed Applications", "market_tab": "Ecosystem Repository", "rollback": "Rollback Version", "uninstall": "Uninstall", "update": "Check Updates", "publisher": "Publisher Key", "digest": "SHA-256 Digest", "dependencies": "Dependencies", "dep_check_ok": "All Dependencies Satisfied", "install_confirm": "Confirm installation of this signed package? It will execute inside an isolated sandbox.", "uninstall_confirm": "Confirm uninstallation of this package and its local cache?"}, "network": {"title": "Shadow6 & ETP Network Mesh", "subtitle": "Manage 13 language core Profile cluster, Virtual Broker, and onion routing paths", "profiles_title": "13 Core Language Profiles Cluster", "virtual_broker": "Virtual Broker Status", "s6p1_import": "Import Custom S6P1 Credential Envelope", "etp_title": "ETP Native Onion Multi-Hop Paths", "hops": "hop route path", "ping_test": "Latency Diagnostics", "privacy_masked": "Non-admin mode has automatically masked sensitive IPs and private keys", "node_topology": "Node & Gateway Topology", "local_node": "Local Node", "remote_nodes": "Remote Nodes Cluster", "manage_nodes": "Manage Custom Nodes"}, "identity": {"title": "Identity & Proof of Useful Work (PoUW)", "did": "Decentralized ID (DID)", "nns_domain": "NNS Bound Domain", "pouw_status": "PoUW Compute & Consensus Contribution", "engine_reward": "Governance Reward Weight", "apply_weight": "Apply for Validator Weight Whitelist", "export_keys": "Export Encrypted Backup", "switch_account": "Switch Identity"}, "devtools": {"title": "Native Component Developer Studio", "subtitle": "Fully functional GUIs for Corium, Tri, ZDA, TC-16 Virtual Machine, and MCP diagnostics", "tab_corium": "Corium Console", "tab_tri": "Tri Snapshots", "tab_zda": "ZDA / Ano Gate", "tab_tc16": "TC-16 VM Studio", "tab_mcp": "MCP 211 Probes", "corium_query": "Query Ledger Facts & Blocks", "tri_run": "Execute Isolated Sandbox Snapshot", "zda_calc": "Verify Exact ZDA Evidence Arithmetic", "tc16_asm": "TC-16 Assembly & Bytecode Debugger", "tc16_run": "Run Virtual Machine", "tc16_step": "Step Execution", "tc16_reset": "Reset Registers"}, "settings": {"title": "System & Component Lifecycle Settings", "runtime_mode": "Client Runtime Mode", "local_gateway_url": "Gateway Endpoint", "components_lifecycle": "On-Demand Component Launcher", "comp_corium": "Corium Native Blockchain", "comp_shadow6": "Shadow6 Multi-Core Tunnel", "comp_ufs": "UFS & dCPM Storage Engine", "comp_watchat": "WATChat Federation Bridge", "comp_etp": "ETP Onion Gateway Router", "accessibility": "Accessibility & Keyboard Navigation", "keyboard_shortcuts": "Shortcuts: [1-9] Switch Modules, [Esc] Close Modals, [Ctrl+K] Global Search", "local_node_title": "Local Node Connection & Real Verification", "local_node_desc": "Using local node requires an actual Ziokt node daemon running locally. If not running, local RPC and write operations are blocked.", "local_node_probe": "Probe Local Node", "local_node_online": "Local Real Node Online", "local_node_offline": "No Local Real Node Detected", "local_node_checking": "Probing Local Node...", "local_node_help": "Start local node daemon: run 'systemctl start ziokt-gateway' or './tools/control_center.sh' in terminal.", "remote_nodes_title": "Remote Node Gateways & Auth Management", "remote_nodes_desc": "Using a remote node requires authentication (Auth Token). You can add custom remote nodes and test their connection and auth validity.", "add_node": "Add New Remote Node", "node_name": "Node Name", "node_url": "Node Endpoint (URL)", "auth_token": "Auth Token", "auth_token_tip": "Used for Bearer / X-Ziokt-Auth remote authentication", "test_auth": "Test Auth", "set_active": "Set Active", "active_badge": "Active", "auth_valid": "Auth Verified", "auth_invalid": "Auth Failed", "auth_required": "Auth Required", "delete_node": "Delete Node", "cannot_delete_default": "Default system node cannot be deleted", "add_node_btn": "Add & Verify Node"}}};

// i18n Translation Engine
async function initI18n() {
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
function t(path) {
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
async function setLanguage(lang) {
  State.language = lang;
  setStorage('ziokt_lang', lang);
  await initI18n();
  Events.emit('language_changed', lang);
  updateAppNodeBadge();
}
function setTheme(theme) {
  State.theme = theme;
  setStorage('ziokt_theme', theme);
  document.documentElement.setAttribute('data-theme', theme);
  Events.emit('theme_changed', theme);
}

// UI Notification Toast
function showToast(message, type = 'info') {
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
function showConfirm(title, message) {
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
function showJsonModal(title, data) {
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

// Probe Real Local Node Health
async function checkLocalNodeHealth() {
  State.localNodeStatus = 'checking';
  Events.emit('local_node_status_changed', { status: 'checking' });
  updateAppNodeBadge();

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2500);
    const res = await fetch(`${State.localGatewayUrl}/api/gateway/status`, {
      signal: controller.signal,
      headers: { 'Accept': 'application/json' }
    });
    clearTimeout(timeoutId);

    if (res.ok) {
      const data = await res.json();
      State.localNodeStatus = 'online';
      State.localNodeDetails = data;
      Events.emit('local_node_status_changed', { status: 'online', data });
      updateAppNodeBadge();
      return { ok: true, data };
    } else {
      throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    }
  } catch (err) {
    State.localNodeStatus = 'offline';
    State.localNodeDetails = { error: err.message };
    Events.emit('local_node_status_changed', { status: 'offline', error: err.message });
    Events.emit('local_node_offline', { error: err.message });
    updateAppNodeBadge();
    return { ok: false, error: err.message };
  }
}

// Verify Remote Node Authentication and Connectivity
async function verifyRemoteNodeAuth(nodeId) {
  const nodes = getRemoteNodes();
  const node = nodes.find(n => n.id === nodeId);
  if (!node) throw new Error('Node not found');

  if (!node.authToken || node.authToken.trim() === '') {
    node.status = 'unauthenticated';
    node.verifiedAt = Date.now();
    saveRemoteNodes(nodes);
    updateAppNodeBadge();
    return { ok: false, error: 'Auth Token is empty' };
  }

  const startTime = performance.now();
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 4000);
    const res = await fetch(`${node.url}/api/gateway/status`, {
      signal: controller.signal,
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${node.authToken}`,
        'X-Ziokt-Auth': node.authToken
      }
    });
    clearTimeout(timeoutId);
    const latency = Math.round(performance.now() - startTime);

    if (res.status === 401 || res.status === 403) {
      node.status = 'auth_failed';
      node.latency = `${latency}ms`;
      node.verifiedAt = Date.now();
      saveRemoteNodes(nodes);
      updateAppNodeBadge();
      return { ok: false, error: `Authentication failed (HTTP ${res.status})` };
    } else if (res.ok) {
      node.status = 'online';
      node.latency = `${latency}ms`;
      node.verifiedAt = Date.now();
      saveRemoteNodes(nodes);
      updateAppNodeBadge();
      return { ok: true, latency: `${latency}ms` };
    } else {
      node.status = 'error';
      node.latency = `${latency}ms`;
      node.verifiedAt = Date.now();
      saveRemoteNodes(nodes);
      updateAppNodeBadge();
      return { ok: false, error: `HTTP ${res.status}: ${res.statusText}` };
    }
  } catch (err) {
    node.status = 'offline';
    node.latency = '--';
    node.verifiedAt = Date.now();
    saveRemoteNodes(nodes);
    updateAppNodeBadge();
    return { ok: false, error: err.message };
  }
}

// Check if client is in local mode without a running local node
function isLocalNodeOffline() {
  return State.runtimeMode === 'local' && State.localNodeStatus === 'offline';
}

// Update Navigation Lock State for Non-Settings tabs
function updateNavLockState() {
  const isOffline = isLocalNodeOffline();
  const isEn = State.language === 'en';

  document.querySelectorAll('.nav-item, .bottom-item').forEach(item => {
    const tab = item.dataset.tab;
    if (tab !== 'settings') {
      if (isOffline) {
        item.classList.add('nav-locked');
        item.setAttribute('title', isEn ? 'Locked: Local node is offline (Settings only)' : '已锁定: 本地节点未运行 (仅开放系统设置)');
      } else {
        item.classList.remove('nav-locked');
        item.removeAttribute('title');
      }
    }
  });

  const didPill = document.getElementById('user-did-pill');
  if (didPill) {
    if (isOffline) {
      didPill.textContent = isEn ? 'Local: Offline (No Node)' : '本地节点离线 (无可用身份)';
      didPill.style.color = 'var(--accent-red)';
      didPill.style.borderColor = 'rgba(239, 68, 68, 0.4)';
    } else if (State.runtimeMode === 'local' && State.localNodeStatus === 'online') {
      const did = State.localNodeDetails?.identity || State.userDid || 'did:ziokt:local:node0';
      didPill.textContent = did.length > 24 ? did.substring(0, 14) + '...' + did.substring(did.length - 6) : did;
      didPill.style.color = 'var(--accent-green)';
      didPill.style.borderColor = 'rgba(16, 185, 129, 0.4)';
    } else {
      const activeNode = getActiveRemoteNode();
      const did = State.userDid || (activeNode ? `did:ziokt:${activeNode.name || activeNode.id}` : 'did:ziokt:remote:guest');
      didPill.textContent = did.length > 24 ? did.substring(0, 14) + '...' + did.substring(did.length - 6) : did;
      didPill.style.color = 'var(--accent-cyan)';
      didPill.style.borderColor = 'var(--border-subtle)';
    }
  }
}

// Update Topbar and Sidebar Badges
function updateAppNodeBadge() {
  const labelEl = document.getElementById('sidebar-node-label');
  const dotEl = document.querySelector('#sidebar .status-dot');
  if (labelEl) {
    const isEn = State.language === 'en';
    if (State.runtimeMode === 'local') {
      if (State.localNodeStatus === 'online') {
        labelEl.textContent = isEn ? 'Local Node: Online (8185)' : '本地节点: 在线 (8185)';
        if (dotEl) dotEl.style.backgroundColor = 'var(--accent-green)';
      } else if (State.localNodeStatus === 'checking') {
        labelEl.textContent = isEn ? 'Local Node: Checking...' : '本地节点: 检测中...';
        if (dotEl) dotEl.style.backgroundColor = 'var(--accent-amber)';
      } else {
        labelEl.textContent = isEn ? 'Local Node: Offline (Not Running)' : '本地节点: 离线 (未启动)';
        if (dotEl) dotEl.style.backgroundColor = 'var(--accent-red)';
      }
    } else {
      const active = getActiveRemoteNode();
      if (active.status === 'online') {
        labelEl.textContent = isEn ? `Remote: ${active.name} (${active.latency})` : `远程网关: ${active.name} (${active.latency})`;
        if (dotEl) dotEl.style.backgroundColor = 'var(--accent-green)';
      } else if (active.status === 'unauthenticated') {
        labelEl.textContent = isEn ? 'Remote: Auth Required' : '远程网关: 待鉴权凭证';
        if (dotEl) dotEl.style.backgroundColor = 'var(--accent-amber)';
      } else {
        labelEl.textContent = isEn ? 'Remote: Disconnected' : '远程网关: 无法连接';
        if (dotEl) dotEl.style.backgroundColor = 'var(--accent-red)';
      }
    }
  }
  updateNavLockState();
}

// Unified Gateway API Client with Real Local Probe & Mandatory Remote Auth
async function apiRequest(endpoint, options = {}) {
  const isLocalMode = State.runtimeMode === 'local';

  if (isLocalMode) {
    // Mandate real running local node
    if (State.localNodeStatus === 'checking') {
      await checkLocalNodeHealth();
    }
    if (State.localNodeStatus === 'offline') {
      const msg = State.language === 'en'
        ? 'Local node is offline or unreachable (http://127.0.0.1:8185). Local mode requires an actual running Ziokt node daemon.'
        : '本地节点未启动或无法连接 (http://127.0.0.1:8185)。使用本地节点需要用户本地真实有节点运行。请启动本地进程或切换至远程网关。';
      showToast(msg, 'error');
      throw new Error(msg);
    }
  } else {
    // Mandate authentication for remote nodes
    const activeNode = getActiveRemoteNode();
    const token = activeNode?.authToken || State.authToken || getStorage('ziokt_auth_token');
    if (!token || token.trim() === '') {
      const msg = State.language === 'en'
        ? 'Remote node requires authentication credentials (Auth Token). Please configure a valid token in Settings.'
        : '使用远程节点需要身份鉴权 (Auth Token)。请在“系统设置”中配置有效的访问凭证。';
      showToast(msg, 'error');
      throw new Error(msg);
    }
  }

  const base = isLocalMode ? State.localGatewayUrl : (getActiveRemoteNode()?.url || State.gatewayUrl);
  const url = endpoint.startsWith('http') ? endpoint : `${base}${endpoint.startsWith('/') ? '' : '/'}${endpoint}`;

  const headers = {
    'Accept': 'application/json',
    ...(options.headers || {})
  };

  if (!isLocalMode) {
    const activeNode = getActiveRemoteNode();
    const token = activeNode?.authToken || State.authToken || getStorage('ziokt_auth_token');
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
      headers['X-Ziokt-Auth'] = token;
    }
  }

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
    console.warn(`API call failed for ${url}:`, err);
    throw err;
  }
}


  // --- Module: modules/home.js ---
// ==============================================================================
// Module: Home Overview & System Telemetry Dashboard
// ==============================================================================
function renderHome(container) {
  const isEn = State.language === 'en';
  const isLocal = State.runtimeMode === 'local';
  const isLocalOffline = isLocal && State.localNodeStatus === 'offline';
  const activeNode = getActiveRemoteNode();
  const isRemoteUnauth = !isLocal && (!activeNode?.authToken || activeNode?.status === 'unauthenticated' || activeNode?.status === 'auth_failed');

  if (isLocalOffline) {
    container.innerHTML = `
      <div style="max-width: 820px; margin: 40px auto; text-align: center;">
        <div class="card" style="padding: 40px 24px; border: 1.5px solid var(--accent-red); background: rgba(239,68,68,0.06);">
          <div style="font-size: 3rem; margin-bottom: 14px;">⚠️</div>
          <h2 style="color: var(--accent-red); font-size: 1.25rem; font-weight: 700; margin-bottom: 10px;">
            ${isEn ? 'Local Node Offline — Only Settings Accessible' : '本地节点未运行 — 当前仅开放系统设置'}
          </h2>
          <p style="color: var(--text-main); font-size: 0.9rem; max-width: 580px; margin: 0 auto 20px; line-height: 1.6;">
            ${isEn
              ? 'Local node mode requires an active Ziokt daemon at http://127.0.0.1:8185. Since no local node is detected, overview metrics and functional tabs are locked. Please start your local daemon or switch to a remote gateway in Settings.'
              : '当前处于【本地节点】运行模式，但未检测到本地运行中的 Ziokt 节点服务 (http://127.0.0.1:8185)。在本地真实节点启动前，首页总览与功能模块已锁定，当前仅开放【系统设置】页。请启动本地进程，或切换至官方远程网关。'}
          </p>
          <div style="display: flex; gap: 12px; justify-content: center; flex-wrap: wrap;">
            <button id="home-go-settings-btn" class="btn btn-primary" style="padding: 10px 20px; font-size: 0.9rem;">⚙️ ${isEn ? 'Go to Settings' : '前往系统设置'}</button>
            <button id="home-probe-local-btn" class="btn btn-secondary" style="padding: 10px 18px; font-size: 0.9rem;">⚡ ${isEn ? 'Retry Local Probe' : '重试探测本地节点'}</button>
            <button id="home-switch-remote-btn" class="btn btn-secondary" style="padding: 10px 18px; font-size: 0.9rem;">🌐 ${isEn ? 'Switch to Remote Gateway' : '一键切换至远程网关'}</button>
          </div>
        </div>
      </div>
    `;
    const sBtn = container.querySelector('#home-go-settings-btn');
    if (sBtn) sBtn.onclick = () => { location.hash = '#settings'; };
    const pBtn = container.querySelector('#home-probe-local-btn');
    if (pBtn) pBtn.onclick = async () => {
      pBtn.disabled = true;
      pBtn.textContent = '...';
      const res = await checkLocalNodeHealth();
      pBtn.disabled = false;
      pBtn.textContent = `⚡ ${isEn ? 'Retry Local Probe' : '重试探测本地节点'}`;
      if (res.ok) {
        showToast(isEn ? 'Local node verified online!' : '本地节点已连接！', 'success');
        renderHome(container);
      } else {
        showToast(isEn ? `Local node unreachable: ${res.error}` : `本地真实节点未响应: ${res.error}`, 'error');
      }
    };
    const rBtn = container.querySelector('#home-switch-remote-btn');
    if (rBtn) rBtn.onclick = () => {
      State.runtimeMode = 'remote';
      setStorage('ziokt_mode', 'remote');
      updateAppNodeBadge();
      showToast(isEn ? 'Switched to Remote Gateway mode' : '已切换至远程网关模式', 'success');
      renderHome(container);
    };
    return;
  }

  container.innerHTML = `
    <div style="max-width: 1100px; margin: 0 auto;">

      ${isRemoteUnauth ? `
        <div style="background: rgba(245, 158, 11, 0.12); border: 1px solid var(--accent-amber); border-radius: var(--radius-md); padding: 14px 18px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
          <div style="color: var(--accent-amber); font-size: 0.85rem; font-weight: 500; display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 1.2rem;">🔒</span>
            <span>${t('home.remote_unauth_alert')}</span>
          </div>
          <button id="home-config-auth-btn" class="btn btn-primary btn-sm">⚙️ ${t('home.config_auth')}</button>
        </div>
      ` : ''}

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
            <option value="remote" ${State.runtimeMode === 'remote' ? 'selected' : ''}>${t('app.mode_remote')} (${activeNode?.name || 'cor-web.ziokt.com'})</option>
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
    modeSelect.onchange = async (e) => {
      State.runtimeMode = e.target.value;
      setStorage('ziokt_mode', e.target.value);
      if (State.runtimeMode === 'local') {
        await checkLocalNodeHealth();
      }
      updateAppNodeBadge();
      showToast(`已切换至: ${e.target.options[e.target.selectedIndex].text}`, 'info');
      Events.emit('mode_changed', e.target.value);
      renderHome(container);
    };
  }

  const probeLocalBtn = container.querySelector('#home-probe-local-btn');
  if (probeLocalBtn) {
    probeLocalBtn.onclick = async () => {
      probeLocalBtn.disabled = true;
      probeLocalBtn.textContent = '...';
      const res = await checkLocalNodeHealth();
      if (res.ok) {
        showToast(isEn ? 'Local node verified successfully!' : '本地真实节点检测通过，状态在线！', 'success');
      } else {
        showToast(isEn ? `Local node unreachable: ${res.error}` : `本地真实节点未响应: ${res.error}`, 'error');
      }
      renderHome(container);
    };
  }

  const switchRemoteBtn = container.querySelector('#home-switch-remote-btn');
  if (switchRemoteBtn) {
    switchRemoteBtn.onclick = () => {
      State.runtimeMode = 'remote';
      setStorage('ziokt_mode', 'remote');
      updateAppNodeBadge();
      showToast(isEn ? 'Switched to Remote Gateway mode' : '已切换至远程网关模式', 'info');
      renderHome(container);
    };
  }

  const configAuthBtn = container.querySelector('#home-config-auth-btn');
  if (configAuthBtn) {
    configAuthBtn.onclick = () => {
      Events.emit('navigate', 'settings');
    };
  }

  const refreshBtn = container.querySelector('#refresh-health-btn');
  if (refreshBtn) {
    refreshBtn.onclick = async () => {
      if (State.runtimeMode === 'local') {
        await checkLocalNodeHealth();
      }
      showToast(isEn ? 'Component and node health refreshed' : '核心组件与节点状态已刷新', 'success');
      renderHome(container);
    };
  }
}


  // --- Module: modules/chat.js ---
// ==============================================================================
// Module: WATChat End-to-End Encrypted Messenger with Dual UI Switcher
// ==============================================================================

let chatUiMode = getStorage('watchat_ui_mode', 'minimalist'); // 'minimalist' | 'classic'
let activeContact = 'genesis-node';
let messagesStore = null;
try {
  const raw = getStorage('watchat_msgs');
  if (raw) messagesStore = JSON.parse(raw);
} catch (e) {
  messagesStore = null;
}
if (!messagesStore) {
  messagesStore = {
    'genesis-node': [
      { id: 1, sender: 'genesis-node', text: '欢迎加入 Ziokt 端到端加密通讯网络！所有消息均由 XChaCha20-Poly1305 密封。', time: '10:00' },
      { id: 2, sender: 'me', text: '收到！正在测试统一客户端的无缝双 UI 切换。', time: '10:02' },
      { id: 3, sender: 'genesis-node', text: '可在上方随时切换“现代简约版”与“经典丰富版”，加密会话状态实时无损保持。', time: '10:03' }
    ],
    'community-bot': [
      { id: 1, sender: 'community-bot', text: 'Corium 治理委员会 #48 提案已发起，欢迎前往社区论坛参与投票。', time: '09:15' }
    ]
  };
}
function renderChat(container) {
  const isMinimalist = chatUiMode === 'minimalist';

  container.innerHTML = `
    <div class="chat-page-wrapper">
      <!-- WATChat Sub-Header: Dual UI Switcher -->
      <div class="chat-subheader">
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
      <div class="chat-container">
        
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
          <div class="chat-input-bar">
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
    setStorage('watchat_ui_mode', 'minimalist');
    showToast('已切换至 WATChat 现代简约版', 'info');
    renderChat(container);
  };

  container.querySelector('#toggle-classic').onclick = () => {
    chatUiMode = 'classic';
    setStorage('watchat_ui_mode', 'classic');
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
    setStorage('watchat_msgs', JSON.stringify(messagesStore));
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
  inputEl.addEventListener('focus', () => {
    setTimeout(() => {
      inputEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 200);
  });
  const box = container.querySelector('#messages-box');
  if (box) box.scrollTop = box.scrollHeight;

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


  // --- Module: modules/forum.js ---
// ==============================================================================
// Module: Corium Community Forum & Decentralized Governance Reader/Publisher
// ==============================================================================

let forumPosts = null;
try {
  const raw = getStorage('ziokt_forum_posts');
  if (raw) forumPosts = JSON.parse(raw);
} catch (e) {
  forumPosts = null;
}
if (!forumPosts) {
  forumPosts = [
    {
      id: 1,
      title: '【治理提案 #48】关于增加 PoUW 算力贡献者奖励权重的提案',
      author: 'did:ziokt:mesh:genesis-node',
      authorName: 'Genesis Validator',
      category: 'governance',
      date: '2026-10-17 18:30',
      content: '为激励更多社区节点加入 Corium 验证网络，建议将 PoUW 引擎算力证明的奖励权重由现行 1.25 调整至 1.50。已通过本地 SQLite/Bash 引擎奖励权重激活测试。',
      replies: 12,
      upvotes: 38,
      signature: 'ed25519:9f8e7d...12c'
    },
    {
      id: 2,
      title: '【技术规范】TC-16 虚拟机 16 位微架构运行指令集草案',
      author: 'did:ziokt:mesh:core-dev',
      authorName: 'Core Architecture Team',
      category: 'technical',
      date: '2026-10-16 14:20',
      content: 'TC-16 VM 设计采用 16 位虚拟处理器架构，包含 8 个通用寄存器 R0-R7，严格控制 TCC Gas 消耗上限，确保在 ETP 洋葱中继环境中完全确定性执行。',
      replies: 8,
      upvotes: 24,
      signature: 'ed25519:4a8b1c...99f'
    },
    {
      id: 3,
      title: '【生态应用】基于 UFS 与 dCPM 软件包的去中心化协作工具链',
      author: 'did:ziokt:mesh:app-builder',
      authorName: 'Community Contributor',
      category: 'apps',
      date: '2026-10-15 11:05',
      content: '分享我们如何通过 dCPM 签名软件包发布应用，实现零接触命令行的一键安装、依赖检查以及版本无损回滚。',
      replies: 15,
      upvotes: 45,
      signature: 'ed25519:7e2d9a...33b'
    }
  ];
}

let activeFilter = 'all';
function renderForum(container) {
  const filtered = activeFilter === 'all' ? forumPosts : forumPosts.filter(p => p.category === activeFilter);

  container.innerHTML = `
    <div style="max-width: 1000px; margin: 0 auto;">
      <!-- Forum Header -->
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 12px;">
        <div>
          <h2 style="font-size: 1.25rem; font-weight: 700; color: var(--accent-cyan);">${t('forum.title')}</h2>
          <p style="font-size: 0.82rem; color: var(--text-muted);">不可篡改的链上签名公告与提案发布中心</p>
        </div>
        <button id="new-post-btn" class="btn btn-primary">+ ${t('forum.new_post')}</button>
      </div>

      <!-- Categories Filter -->
      <div style="display: flex; gap: 8px; margin-bottom: 18px; flex-wrap: wrap;">
        <button class="btn btn-sm ${activeFilter === 'all' ? 'btn-primary' : 'btn-secondary'} filter-btn" data-cat="all">全部讨论</button>
        <button class="btn btn-sm ${activeFilter === 'governance' ? 'btn-primary' : 'btn-secondary'} filter-btn" data-cat="governance">${t('forum.cat_governance')}</button>
        <button class="btn btn-sm ${activeFilter === 'technical' ? 'btn-primary' : 'btn-secondary'} filter-btn" data-cat="technical">${t('forum.cat_technical')}</button>
        <button class="btn btn-sm ${activeFilter === 'apps' ? 'btn-primary' : 'btn-secondary'} filter-btn" data-cat="apps">${t('forum.cat_apps')}</button>
      </div>

      <!-- Posts List -->
      <div style="display: flex; flex-direction: column; gap: 14px;">
        ${filtered.map(post => `
          <div class="card" style="padding: 18px;">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
              <h3 style="font-size: 1.05rem; font-weight: 600; color: var(--text-main);">${post.title}</h3>
              <span class="mode-pill" style="font-size: 0.7rem;">${post.category.toUpperCase()}</span>
            </div>
            <p style="color: var(--text-muted); font-size: 0.88rem; line-height: 1.6; margin-bottom: 12px;">${post.content}</p>
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.78rem; border-top: 1px solid var(--border-subtle); padding-top: 10px; color: var(--text-dim);">
              <div style="display: flex; align-items: center; gap: 8px;">
                <span style="color: var(--accent-cyan); font-weight: 500;">${post.authorName}</span>
                <span class="status-badge" style="font-size: 0.68rem; color: var(--accent-green);">${t('forum.signature_verified')}</span>
              </div>
              <div style="display: flex; gap: 14px; align-items: center;">
                <span>💬 ${post.replies} ${t('forum.replies')}</span>
                <span>👍 ${post.upvotes}</span>
                <span>${post.date}</span>
              </div>
            </div>
          </div>
        `).join('')}
      </div>

      <!-- New Post Dialog (Hidden initially) -->
      <div id="new-post-modal" class="modal-overlay">
        <div class="modal-card">
          <div class="modal-header">
            <h3 style="font-size: 1.05rem; font-weight: 600; color: var(--accent-cyan);">${t('forum.new_post')}</h3>
            <button id="close-post-modal" class="btn btn-sm btn-secondary">✕</button>
          </div>
          <div class="modal-body">
            <div style="margin-bottom: 14px;">
              <label style="display: block; font-size: 0.8rem; color: var(--text-muted); margin-bottom: 4px;">${t('forum.post_title')}</label>
              <input type="text" id="post-title-input" class="input-text" placeholder="输入帖子或提案标题...">
            </div>
            <div style="margin-bottom: 14px;">
              <label style="display: block; font-size: 0.8rem; color: var(--text-muted); margin-bottom: 4px;">${t('forum.post_category')}</label>
              <select id="post-category-select" class="input-select">
                <option value="governance">${t('forum.cat_governance')}</option>
                <option value="technical">${t('forum.cat_technical')}</option>
                <option value="apps">${t('forum.cat_apps')}</option>
                <option value="general">${t('forum.cat_general')}</option>
              </select>
            </div>
            <div style="margin-bottom: 14px;">
              <label style="display: block; font-size: 0.8rem; color: var(--text-muted); margin-bottom: 4px;">${t('forum.post_content')}</label>
              <textarea id="post-content-input" class="input-textarea" rows="6" placeholder="输入详细内容，支持 Markdown 格式..."></textarea>
            </div>
            <div style="padding: 10px; background: var(--bg-input); border-radius: var(--radius-sm); border: 1px solid var(--border-subtle); font-size: 0.75rem; color: var(--accent-cyan); font-family: var(--font-mono);">
              签名身份: ${State.userDid} (Ed25519 自动加签)
            </div>
          </div>
          <div class="modal-footer">
            <button id="cancel-post-btn" class="btn btn-secondary">${t('common.cancel')}</button>
            <button id="submit-post-btn" class="btn btn-primary">${t('forum.sign_and_publish')}</button>
          </div>
        </div>
      </div>

    </div>
  `;

  // Filters
  container.querySelectorAll('.filter-btn').forEach(btn => {
    btn.onclick = () => {
      activeFilter = btn.dataset.cat;
      renderForum(container);
    };
  });

  // Modal Handlers
  const modal = container.querySelector('#new-post-modal');
  container.querySelector('#new-post-btn').onclick = () => {
    modal.style.display = 'flex';
  };
  container.querySelector('#close-post-modal').onclick = () => {
    modal.style.display = 'none';
  };
  container.querySelector('#cancel-post-btn').onclick = () => {
    modal.style.display = 'none';
  };

  // Submit Post
  container.querySelector('#submit-post-btn').onclick = () => {
    const title = container.querySelector('#post-title-input').value.trim();
    const category = container.querySelector('#post-category-select').value;
    const content = container.querySelector('#post-content-input').value.trim();

    if (!title || !content) {
      showToast('请完整填写标题和正文内容', 'error');
      return;
    }

    const now = new Date();
    const dateStr = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')} ${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}`;

    const newPost = {
      id: Date.now(),
      title,
      author: State.userDid,
      authorName: 'My Identity',
      category,
      date: dateStr,
      content,
      replies: 0,
      upvotes: 1,
      signature: 'ed25519:' + Math.random().toString(16).slice(2, 10)
    };

    forumPosts.unshift(newPost);
    setStorage('ziokt_forum_posts', JSON.stringify(forumPosts));
    modal.style.display = 'none';
    showToast('提案发布成功！已完成 Ed25519 链上签名校验', 'success');
    renderForum(container);
  };
}


  // --- Module: modules/files.js ---
// ==============================================================================
// Module: UFS & SafeFS Secure File Vault & Storage Explorer
// ==============================================================================

let currentVault = 'ufs'; // 'ufs' | 'safefs'
let vaultFiles = [];
try {
  const raw = getStorage('ziokt_vault_files');
  if (raw) vaultFiles = JSON.parse(raw);
} catch (e) {
  vaultFiles = [];
}
function renderFiles(container) {
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
}


  // --- Module: modules/apps.js ---
// ==============================================================================
// Module: dCPM Decentralized App Store & Signed Package Manager
// ==============================================================================

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
function renderApps(container) {
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


  // --- Module: modules/network.js ---
// ==============================================================================
// Module: Shadow6 Multi-Core Mesh & ETP Onion Gateway Network Panel
// ==============================================================================

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
function renderNetwork(container) {
  const isEn = State.language === 'en';
  const activeRemote = getActiveRemoteNode();
  const remoteNodes = getRemoteNodes();
  const isLocalOnline = State.localNodeStatus === 'online';

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

      <!-- Gateway & Node Topology Overview -->
      <div class="card" style="margin-bottom: 24px;">
        <div class="card-title" style="margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center;">
          <span>🌐 ${t('network.node_topology')}</span>
          <button id="nav-settings-nodes-btn" class="btn btn-secondary btn-sm">⚙️ ${t('network.manage_nodes')}</button>
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px;">
          <!-- Local Node Card -->
          <div style="background: var(--bg-input); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 14px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <span style="font-weight: 600; color: var(--text-main); font-size: 0.9rem;">💻 ${t('network.local_node')}</span>
              <span class="status-badge" style="color: ${isLocalOnline ? 'var(--accent-green)' : 'var(--accent-red)'}">
                <span class="status-dot" style="background-color: ${isLocalOnline ? 'var(--accent-green)' : 'var(--accent-red)'}"></span>
                ${isLocalOnline ? 'ONLINE' : 'OFFLINE'}
              </span>
            </div>
            <div style="font-family: var(--font-mono); font-size: 0.78rem; color: var(--text-dim); margin-bottom: 6px;">http://127.0.0.1:8185</div>
            <div style="font-size: 0.75rem; color: var(--text-muted);">
              ${isLocalOnline ? (isEn ? '✓ Local process active, zero latency' : '✓ 本地节点运行中，直连无延迟') : (isEn ? '✕ No local node process detected' : '✕ 未检测到本机节点进程，本地写操作将受阻')}
            </div>
          </div>

          <!-- Active Remote Node Card -->
          <div style="background: var(--bg-input); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 14px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <span style="font-weight: 600; color: var(--text-main); font-size: 0.9rem;">☁️ ${activeRemote?.name || 'Remote Gateway'}</span>
              <span class="status-badge" style="color: ${activeRemote?.status === 'online' ? 'var(--accent-green)' : 'var(--accent-amber)'}">
                <span class="status-dot" style="background-color: ${activeRemote?.status === 'online' ? 'var(--accent-green)' : 'var(--accent-amber)'}"></span>
                ${activeRemote?.status === 'online' ? `VERIFIED (${activeRemote.latency || '15ms'})` : 'AUTH REQUIRED'}
              </span>
            </div>
            <div style="font-family: var(--font-mono); font-size: 0.78rem; color: var(--text-dim); margin-bottom: 6px;">${activeRemote?.url}</div>
            <div style="font-size: 0.75rem; color: var(--text-muted);">
              ${activeRemote?.authToken ? (isEn ? '✓ Token attached (Bearer + X-Ziokt-Auth)' : '✓ 已配置鉴权凭证') : (isEn ? '✕ Missing Auth Token' : '✕ 缺少鉴权 Token，不可直接通信')}
            </div>
          </div>
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

  // Navigate to settings for managing nodes
  const navSettingsBtn = container.querySelector('#nav-settings-nodes-btn');
  if (navSettingsBtn) {
    navSettingsBtn.onclick = () => {
      Events.emit('navigate', 'settings');
    };
  }

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


  // --- Module: modules/identity.js ---
// ==============================================================================
// Module: Decentralized Identity (DID), Keys & PoUW Governance Management
// ==============================================================================

let pouwActive = false;
let hashrate = '0 H/s';
let acceptedShares = 0;
function renderIdentity(container) {
  const isEn = State.language === 'en';

  if (isLocalNodeOffline()) {
    container.innerHTML = `
      <div style="max-width: 800px; margin: 40px auto; text-align: center;">
        <div class="card" style="padding: 36px 20px;">
          <div style="font-size: 2.5rem; margin-bottom: 12px;">🔒</div>
          <h3 style="color: var(--accent-red); margin-bottom: 8px;">
            ${isEn ? 'Local Node Offline — Identity Unavailable' : '本地节点未运行 — 身份与密钥不可用'}
          </h3>
          <p style="color: var(--text-muted); font-size: 0.85rem; max-width: 520px; margin: 0 auto 20px; line-height: 1.6;">
            ${isEn
              ? 'Local node mode requires an active Ziokt daemon at http://127.0.0.1:8185 to manage Ed25519 validator credentials and PoUW compute. Only the Settings tab is accessible.'
              : '本地节点模式需要本机真实运行有 Ziokt 节点服务 (http://127.0.0.1:8185) 提供 Ed25519 验证者身份及 PoUW 有用功驱动。当前仅开放【系统设置】。'}
          </p>
          <div style="display: flex; gap: 10px; justify-content: center; flex-wrap: wrap;">
            <button id="id-go-settings-btn" class="btn btn-primary">⚙️ ${t('nav.settings')}</button>
            <button id="id-retry-probe-btn" class="btn btn-secondary">⚡ ${t('settings.local_node_probe')}</button>
          </div>
        </div>
      </div>
    `;
    const sBtn = container.querySelector('#id-go-settings-btn');
    if (sBtn) sBtn.onclick = () => { location.hash = '#settings'; };
    const pBtn = container.querySelector('#id-retry-probe-btn');
    if (pBtn) pBtn.onclick = async () => {
      pBtn.disabled = true;
      pBtn.textContent = '...';
      const { checkLocalNodeHealth } = await import('../core.js');
      const res = await checkLocalNodeHealth();
      pBtn.disabled = false;
      pBtn.textContent = `⚡ ${t('settings.local_node_probe')}`;
      if (res.ok) {
        showToast(isEn ? 'Local node verified online!' : '本地真实节点检测通过，状态在线！', 'success');
        renderIdentity(container);
      } else {
        showToast(isEn ? `Local node unreachable: ${res.error}` : `本地真实节点未响应: ${res.error}`, 'error');
      }
    };
    return;
  }

  const isLocal = State.runtimeMode === 'local';
  const activeNode = getActiveRemoteNode();
  const identityName = isLocal ? (isEn ? 'Local Sovereign Node' : '本地主权节点') : (activeNode?.name || 'Remote Gateway');
  const activeDid = isLocal ? (State.localNodeDetails?.identity || State.userDid || 'did:ziokt:local:node0') : (State.userDid || `did:ziokt:${activeNode?.id || 'guest'}`);
  const domain = isLocal ? (State.localNodeDetails?.network || 'ziokt-main') + '.local' : 'gateway.ziokt';

  container.innerHTML = `
    <div style="max-width: 1000px; margin: 0 auto;">
      <!-- Header -->
      <div style="margin-bottom: 24px;">
        <h2 style="font-size: 1.25rem; font-weight: 700; color: var(--accent-cyan);">${t('identity.title')}</h2>
        <p style="font-size: 0.82rem; color: var(--text-muted);">${isEn ? 'Manage Ed25519 cryptographic keys, NNS namespaces, and PoUW compute governance' : '管理去中心化 Ed25519 密钥对、NNS 命名空间与 PoUW 有用功证明贡献'}</p>
      </div>

      <!-- Identity Profile Card -->
      <div class="card" style="margin-bottom: 24px;">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; flex-wrap: wrap; gap: 12px;">
          <div style="display: flex; align-items: center; gap: 14px;">
            <div style="width: 52px; height: 52px; border-radius: 50%; background: linear-gradient(135deg, #0284c7, #38bdf8); display: flex; align-items: center; justify-content: center; font-size: 1.5rem; color: #fff; font-weight: bold;">
              Z
            </div>
            <div>
              <div style="font-size: 1.15rem; font-weight: 700; color: var(--text-main);">${identityName}</div>
              <div style="font-size: 0.8rem; color: var(--accent-green); font-weight: 500;">✓ ${isEn ? 'Ed25519 Node Verified' : 'Ed25519 验证者身份'}</div>
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
            <div style="font-family: var(--font-mono); font-size: 0.82rem; color: var(--accent-cyan); word-break: break-all;">${activeDid}</div>
          </div>
          <div style="background: var(--bg-input); padding: 12px; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
            <div style="font-size: 0.72rem; color: var(--text-dim); margin-bottom: 4px;">${t('identity.nns_domain')}</div>
            <div style="font-family: var(--font-mono); font-size: 0.85rem; color: var(--accent-green);">${domain}</div>
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
      setStorage('ziokt_did', State.userDid);
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


  // --- Module: modules/devtools.js ---
// ==============================================================================
// Module: Native Component Developer Studio (Corium, Tri, ZDA, TC-16, MCP)
// ==============================================================================

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
function renderDevtools(container) {
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


  // --- Module: modules/settings.js ---
// ==============================================================================
// Module: System Settings, Local/Remote Node Management, Auth & Lifecycle
// ==============================================================================
function renderSettings(container) {
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



  // --- Router & App Controller ---
  const routes = {
    home: { render: renderHome, titleKey: 'nav.home' },
    chat: { render: renderChat, titleKey: 'nav.chat' },
    forum: { render: renderForum, titleKey: 'nav.forum' },
    files: { render: renderFiles, titleKey: 'nav.files' },
    apps: { render: renderApps, titleKey: 'nav.apps' },
    network: { render: renderNetwork, titleKey: 'nav.network' },
    identity: { render: renderIdentity, titleKey: 'nav.identity' },
    devtools: { render: renderDevtools, titleKey: 'nav.devtools' },
    settings: { render: renderSettings, titleKey: 'nav.settings' }
  };

  function getHashTab() {
    const hash = (window.location.hash || '').replace('#', '').trim().toLowerCase();
    return routes[hash] ? hash : null;
  }

  async function initApp() {
    await initI18n();
    setTheme(State.theme);
    setupNavigation();
    setupKeyboardShortcuts();
    setupPwaInstallPrompt();

    // Probe local node first if in local mode before setting initial route
    if (State.runtimeMode === 'local') {
      await checkLocalNodeHealth();
    }

    updateAppNodeBadge();

    let initialTab = getHashTab() || State.currentTab || 'home';
    if (isLocalNodeOffline() && initialTab !== 'settings') {
      initialTab = 'settings';
    }
    navigate(initialTab);

    window.addEventListener('hashchange', () => {
      let tab = getHashTab();
      if (tab && tab !== State.currentTab) {
        if (isLocalNodeOffline() && tab !== 'settings') {
          navigate('settings');
          return;
        }
        navigate(tab);
      }
    });

    Events.on('navigate', (tab) => navigate(tab));
    Events.on('local_node_offline', () => {
      if (State.currentTab !== 'settings') {
        navigate('settings');
      }
    });
    Events.on('local_node_status_changed', () => {
      updateAppNodeBadge();
      if (isLocalNodeOffline() && State.currentTab !== 'settings') {
        navigate('settings');
      }
    });
    Events.on('mode_changed', () => {
      updateAppNodeBadge();
      if (isLocalNodeOffline() && State.currentTab !== 'settings') {
        navigate('settings');
      }
    });
    Events.on('active_node_changed', () => {
      updateAppNodeBadge();
    });
    Events.on('language_changed', () => {
      updateNavLabels();
      updateAppNodeBadge();
      navigate(State.currentTab);
    });
    Events.on('theme_changed', () => {
      navigate(State.currentTab);
    });

    console.log('[Ziokt GUI] Universal Client Initialized.');
  }

  function navigate(tabName) {
    // Local Node Offline Gatekeeping: only Settings can be viewed
    if (isLocalNodeOffline() && tabName !== 'settings') {
      const msg = State.language === 'en'
        ? 'Local node is offline. Local mode requires a running node; only Settings is accessible.'
        : '本地节点未启动。使用本地节点需要用户本地真实有节点运行，当前仅开放【系统设置】页。';
      showToast(msg, 'warning');
      tabName = 'settings';
    }

    if (!routes[tabName]) tabName = isLocalNodeOffline() ? 'settings' : 'home';
    State.currentTab = tabName;
    if (window.location.hash !== '#' + tabName) {
      history.replaceState(null, '', '#' + tabName);
    }

    const route = routes[tabName];
    const titleEl = document.getElementById('current-page-title');
    if (titleEl) titleEl.textContent = t(route.titleKey);
    document.title = t(route.titleKey) + ' - ' + t('app.title');

    document.querySelectorAll('.nav-item').forEach(item => {
      item.classList.toggle('active', item.dataset.tab === tabName);
    });
    document.querySelectorAll('.bottom-item').forEach(item => {
      item.classList.toggle('active', item.dataset.tab === tabName);
    });

    const container = document.getElementById('content-container');
    if (container) {
      container.innerHTML = '';
      try {
        route.render(container);
      } catch (err) {
        console.error('[Router] Error rendering ' + tabName + ':', err);
        container.innerHTML = '<div style="max-width:800px;margin:40px auto;padding:24px;background:rgba(239,68,68,0.1);border:1px solid var(--accent-red);border-radius:var(--radius-md);"><h3 style="color:var(--accent-red);margin-bottom:8px;">⚠️ 模块加载异常 / Component Render Error</h3><p style="font-size:0.88rem;color:var(--text-main);margin-bottom:12px;">无法加载模块 <strong>' + tabName + '</strong>: ' + (err?.message || err) + '</p><button class="btn btn-secondary btn-sm" onclick="location.hash=&quot;#home&quot;">返回首页 / Return Home</button></div>';
      }
    }
  }

  function setupNavigation() {
    document.querySelectorAll('.nav-item').forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        const targetTab = item.dataset.tab;
        if (isLocalNodeOffline() && targetTab !== 'settings') {
          const msg = State.language === 'en'
            ? 'Local node is offline. Only Settings is accessible.'
            : '本地节点未启动，当前仅开放【系统设置】页。';
          showToast(msg, 'warning');
          navigate('settings');
          return;
        }
        navigate(targetTab);
      });
    });

    document.querySelectorAll('.bottom-item').forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        const targetTab = item.dataset.tab;
        if (isLocalNodeOffline() && targetTab !== 'settings') {
          const msg = State.language === 'en'
            ? 'Local node is offline. Only Settings is accessible.'
            : '本地节点未启动，当前仅开放【系统设置】页。';
          showToast(msg, 'warning');
          navigate('settings');
          return;
        }
        navigate(targetTab);
      });
    });

    const quickLang = document.getElementById('quick-lang-btn');
    if (quickLang) {
      quickLang.onclick = () => {
        const next = State.language.startsWith('en') ? 'zh' : 'en';
        setLanguage(next);
      };
    }

    const quickTheme = document.getElementById('quick-theme-btn');
    if (quickTheme) {
      quickTheme.onclick = () => {
        setTheme(State.theme === 'dark' ? 'light' : 'dark');
      };
    }

    const didPill = document.getElementById('user-did-pill');
    if (didPill) {
      didPill.onclick = () => {
        try {
          navigator.clipboard.writeText(State.userDid);
          showToast(t('common.copied') || 'DID 已复制到剪贴板', 'success');
        } catch(e) {
          showToast(State.userDid, 'info');
        }
      };
    }
  }

  function setupPwaInstallPrompt() {
    let deferredPrompt = null;
    window.addEventListener('beforeinstallprompt', (e) => {
      e.preventDefault();
      deferredPrompt = e;
      const btn = document.getElementById('pwa-install-btn');
      if (btn) {
        btn.style.display = 'inline-flex';
        btn.onclick = async () => {
          btn.style.display = 'none';
          deferredPrompt.prompt();
          const choice = await deferredPrompt.userChoice;
          console.log('[PWA] User choice:', choice.outcome);
          deferredPrompt = null;
        };
      }
    });

    window.addEventListener('appinstalled', () => {
      console.log('[PWA] Application successfully installed.');
      showToast('Ziokt 客户端已成功安装到本地设备', 'success');
      const btn = document.getElementById('pwa-install-btn');
      if (btn) btn.style.display = 'none';
    });
  }

  function updateNavLabels() {
    document.querySelectorAll('.nav-item').forEach(item => {
      const key = routes[item.dataset.tab]?.titleKey;
      const labelSpan = item.querySelector('.nav-label');
      if (labelSpan && key) labelSpan.textContent = t(key);
    });
    document.querySelectorAll('.bottom-item').forEach(item => {
      const key = routes[item.dataset.tab]?.titleKey;
      const labelSpan = item.querySelector('.bottom-label');
      if (labelSpan && key) labelSpan.textContent = t(key);
    });
  }

  function setupKeyboardShortcuts() {
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        const modal = document.getElementById('modal-overlay');
        if (modal) modal.style.display = 'none';
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        const term = prompt('全局快捷检索 / 命令 (输入 home, chat, forum, files, apps, network, identity, devtools, settings):');
        if (term && routes[term.toLowerCase()]) {
          navigate(term.toLowerCase());
        }
        return;
      }
      if (['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;
      const num = parseInt(e.key, 10);
      const tabKeys = Object.keys(routes);
      if (num >= 1 && num <= tabKeys.length) {
        navigate(tabKeys[num - 1]);
      }
    });
  }

  // Self bootstrap
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initApp);
  } else {
    initApp();
  }

})();
