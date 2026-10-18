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
  if (key === 'ziokt_auth_token') return '';
  try {
    const v = localStorage.getItem(key);
    return v !== null ? v : fallback;
  } catch (e) {
    return fallback;
  }
}
function setStorage(key, val) {
  if (key === 'ziokt_auth_token') { State.authToken = val; return; }
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

const nodeSecrets = new Map();
try { localStorage.removeItem('ziokt_auth_token'); const old = JSON.parse(localStorage.getItem('ziokt_remote_nodes') || '[]'); localStorage.setItem('ziokt_remote_nodes', JSON.stringify(old.map(({authToken, ...n}) => n))); } catch (_) {}
const DEFAULT_REMOTE_NODES = [
  {
    id: 'node-official-tokyo',
    name: 'Ziokt Mainnet Gateway (Tokyo)',
    url: (typeof location !== 'undefined' && ['app.ziokt.com','cor-web.ziokt.com'].includes(location.hostname)) ? location.origin : 'https://app.ziokt.com',
    authToken: '',
    isDefault: true,
    status: 'unverified',
    latency: '--',
    verifiedAt: null
  }
];
function getRemoteNodes() {
  try {
    const raw = localStorage.getItem('ziokt_remote_nodes');
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) return parsed.map(n => ({...n,authToken: nodeSecrets.get(n.id) || '',status:'unverified'}));
    }
  } catch (e) {}
  return [...DEFAULT_REMOTE_NODES];
}
function saveRemoteNodes(nodes) {
  nodes.forEach(n => nodeSecrets.set(n.id, n.authToken || ''));
  setStorage('ziokt_remote_nodes', JSON.stringify(nodes.map(({authToken, ...n}) => n)));
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
  runtimeMode: getStorage('ziokt_mode', typeof location !== 'undefined' && location.protocol === 'https:' ? 'remote' : 'local'), // 'local' | 'remote' | 'hybrid'
  gatewayUrl: getStorage('ziokt_gateway', 'https://cor-web.ziokt.com'),
  localGatewayUrl: 'http://127.0.0.1:8185',
  localNodeStatus: 'checking', // 'checking' | 'online' | 'offline'
  localNodeDetails: null,
  remoteNodes: getRemoteNodes(),
  activeRemoteNodeId: getStorage('ziokt_active_node_id', 'node-official-tokyo'),
  authToken: '',
  userDid: getStorage('ziokt_did', ''),
  components: {
    corium: { name: 'Corium Blockchain', status: 'unverified', port: 8545 },
    shadow6: { name: 'Shadow6 Mesh Cluster', status: 'unverified', port: 8186 },
    ufs: { name: 'UFS & dCPM Storage', status: 'unverified', port: 8184 },
    watchat: { name: 'WATChat Bridge', status: 'unverified', port: 8181 },
    etp: { name: 'ETP Onion Gateway', status: 'unverified', port: 9050 }
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
const BUILTIN_I18N = {"zh": {"app": {"title": "Ziokt 统一图形客户端", "subtitle": "去中心化原生操作系统与应用生态控制中心", "version": "v1.0.0 (Core Native)", "status_online": "正常运行", "status_offline": "已断开", "status_connecting": "连接中...", "mode_local": "本地节点", "mode_remote": "远程网关", "mode_hybrid": "混合模式", "switch_lang": "语言 / Language", "theme_dark": "赛博深黑", "theme_light": "清爽明亮", "theme_contrast": "高对比度"}, "nav": {"home": "首页总览", "chat": "加密通讯", "forum": "社区论坛", "files": "安全存储", "apps": "应用中心", "network": "网络节点", "identity": "身份与贡献", "devtools": "开发工具", "settings": "系统设置"}, "common": {"confirm": "确认", "cancel": "取消", "delete": "删除", "save": "保存", "edit": "编辑", "copy": "复制", "copied": "已复制到剪贴板", "refresh": "刷新", "search": "搜索...", "loading": "加载中...", "success": "操作成功", "error": "操作失败", "details": "查看详情", "actions": "操作", "status": "状态", "name": "名称", "version": "版本", "size": "大小", "date": "时间", "upload": "上传", "download": "下载", "view_raw": "查看原始数据", "advanced": "高级选项", "close": "关闭"}, "home": {"welcome": "欢迎使用 Ziokt 统一图形客户端", "welcome_sub": "集成零知识加密通讯、去中心化包管理、多协议隧道及链上可信微架构", "quick_actions": "快捷功能入口", "system_health": "核心组件健康状态", "gateway_telemetry": "网关实时遥测", "recent_activity": "近期网络活动", "act_chat": "快速发起加密对话", "act_files": "打开原生文件保险库", "act_forum": "浏览社区最新提案", "act_apps": "管理与运行扩展包", "act_network": "查看 Shadow6 / ETP 网格", "local_offline_alert": "⚠️ 未检测到本地真实节点: 当前处于本地模式，但 http://127.0.0.1:8185 未响应。使用本地节点需要用户本地真实有节点运行。", "remote_unauth_alert": "🔒 远程节点需要身份鉴权: 当前活跃远程节点尚未配置有效的 Auth Token 凭证。", "switch_remote": "切换至远程网关", "config_auth": "前往配置凭证", "probe_local": "重新检测本地节点"}, "chat": {"title": "WATChat 端到端加密通讯", "dual_ui": "界面风格切换", "ui_minimalist": "现代简约版", "ui_classic": "经典丰富版", "ui_switch_tip": "随时切换界面布局，聊天记录与加密密钥实时同步无损保留", "contacts": "联系人 / 对话列表", "new_conversation": "新建加密对话", "enter_recipient": "输入对方 DID 或公钥地址", "send": "发送", "input_placeholder": "输入加密消息...", "attach_file": "发送文件附件", "encryption_badge": "XChaCha20-Poly1305 端到端保密", "empty_messages": "暂无历史消息，发送一条问候开启端到端密聊吧"}, "forum": {"title": "Corium 去中心化社区论坛", "new_post": "发布新帖 / 提案", "post_title": "标题", "post_category": "分类", "post_content": "正文内容 (支持 Markdown)", "sign_and_publish": "使用当前身份签名并发布", "cat_governance": "生态治理", "cat_technical": "核心技术", "cat_apps": "应用开发", "cat_general": "综合讨论", "signature_verified": "Ed25519 链上签名已验证", "replies": "条回复"}, "files": {"title": "UFS & SafeFS 安全存储保险库", "vault_type": "存储驱动", "vault_ufs": "UFS 原生文件系统", "vault_safefs": "SafeFS AEAD 加密保险箱", "upload_file": "上传文件", "create_folder": "新建目录", "stealth_mode": "双层可抵赖卷 (Outer Decoy / Inner Stealth)", "drop_tip": "拖拽文件至此处，自动执行安全分块持久化", "download": "下载文件", "delete_confirm": "确定永久删除此文件吗？此操作不可逆。"}, "apps": {"title": "dCPM 去中心化应用中心", "subtitle": "基于 UFS 与 dCPM 签名软件包体系，支持依赖审查、自动验签与安全沙箱执行", "install_pkg": "安装 / 导入 .dcpm 软件包", "installed_tab": "已安装应用", "market_tab": "生态软件包仓库", "rollback": "版本回滚", "uninstall": "卸载", "update": "检查更新", "publisher": "发布者签名", "digest": "SHA-256 校验摘要", "dependencies": "依赖组件", "dep_check_ok": "依赖项完整", "install_confirm": "确定安装此签名软件包吗？将严格在隔离沙箱中运行。", "uninstall_confirm": "确定卸载该应用及其本地缓存吗？"}, "network": {"title": "Shadow6 & ETP 网络节点网格", "subtitle": "管理 13 核心 Profile 运行集群、Virtual Broker 以及洋葱代理链路", "profiles_title": "13 语言核心 Profile 实时集群", "virtual_broker": "虚拟 Broker 代理状态", "s6p1_import": "粘贴导入自定义 S6P1 凭据信封", "etp_title": "ETP 原生洋葱多跳链路", "hops": "跳路由路径", "ping_test": "网络延迟诊断", "privacy_masked": "非管理员模式已自动脱敏保护敏感 IP 与密钥", "node_topology": "节点与网关拓扑", "local_node": "本地节点", "remote_nodes": "远程节点集群", "manage_nodes": "管理自定义节点"}, "identity": {"title": "身份管理与贡献证明 (PoUW)", "did": "去中心化身份 (DID)", "nns_domain": "NNS 绑定域名", "pouw_status": "PoUW 算力与共识贡献状态", "engine_reward": "治理奖励权重", "apply_weight": "申请加入验证者权重白名单", "export_keys": "导出加密密钥备份", "switch_account": "切换身份"}, "devtools": {"title": "原生组件全功能开发工具箱", "subtitle": "提供 Corium、Tri、ZDA、TC-16 虚拟机及 MCP 接口全功能调试与执行界面", "tab_corium": "Corium 控制台", "tab_tri": "Tri 状态机快照", "tab_zda": "ZDA / Ano 门限计算", "tab_tc16": "TC-16 虚拟机工作台", "tab_mcp": "MCP 211 工具探针", "corium_query": "查询区块与交易事实", "tri_run": "执行快照离线隔离沙箱", "zda_calc": "验证精确 ZDA 证据算术", "tc16_asm": "TC-16 汇编与字节码单步调试", "tc16_run": "运行虚拟机", "tc16_step": "单步执行 (Step)", "tc16_reset": "重置寄存器"}, "settings": {"title": "系统与组件生命周期设置", "runtime_mode": "客户端运行模式配置", "local_gateway_url": "本地/远程网关地址", "components_lifecycle": "按需组件启动管理 (On-demand Launcher)", "comp_corium": "Corium 原生区块链服务", "comp_shadow6": "Shadow6 多核心代理网络", "comp_ufs": "UFS & dCPM 安全存储引擎", "comp_watchat": "WATChat 联邦通讯桥接", "comp_etp": "ETP 洋葱网关路由", "accessibility": "无障碍与键盘导航", "keyboard_shortcuts": "快捷键说明: [1-9] 切换模块，[Esc] 关闭弹窗，[Ctrl+K] 全局搜索", "local_node_title": "本地节点连接与真实状态", "local_node_desc": "使用本地节点需要用户本地真实有节点运行。若本地未启动，客户端将无法进行写操作与本地 RPC 交互。", "local_node_probe": "探测本地节点", "local_node_online": "本地真实节点在线", "local_node_offline": "未检测到本地真实节点", "local_node_checking": "检测本地节点中...", "local_node_help": "本地启动指引: 请在终端执行 systemctl start ziokt-gateway 或运行 ./tools/control_center.sh", "remote_nodes_title": "远程节点网关与鉴权管理", "remote_nodes_desc": "使用远程节点需要身份鉴权 (Auth Token)。您可以自定义添加新的远程节点并测试连接与鉴权有效性。", "add_node": "添加新远程节点", "node_name": "节点名称", "node_url": "节点地址 (URL)", "auth_token": "鉴权凭证 (Auth Token)", "auth_token_tip": "用于 Bearer / X-Ziokt-Auth 远程身份验证", "test_auth": "测试鉴权", "set_active": "设为活跃", "active_badge": "当前活跃", "auth_valid": "鉴权通过", "auth_invalid": "鉴权失败", "auth_required": "待鉴权", "delete_node": "删除节点", "cannot_delete_default": "系统默认节点不可删除", "add_node_btn": "添加并测试该节点"}}, "en": {"app": {"title": "Ziokt Unified Graphical Client", "subtitle": "Decentralized Native OS & Application Ecosystem Console", "version": "v1.0.0 (Core Native)", "status_online": "Online", "status_offline": "Disconnected", "status_connecting": "Connecting...", "mode_local": "Local Node", "mode_remote": "Remote Gateway", "mode_hybrid": "Hybrid Mode", "switch_lang": "Language / 语言", "theme_dark": "Cyber Dark", "theme_light": "Clean Light", "theme_contrast": "High Contrast"}, "nav": {"home": "Home", "chat": "WATChat", "forum": "Forum", "files": "Files & Vault", "apps": "App Store", "network": "Network Nodes", "identity": "Identity & PoUW", "devtools": "Dev Tools", "settings": "Settings"}, "common": {"confirm": "Confirm", "cancel": "Cancel", "delete": "Delete", "save": "Save", "edit": "Edit", "copy": "Copy", "copied": "Copied to clipboard", "refresh": "Refresh", "search": "Search...", "loading": "Loading...", "success": "Success", "error": "Error", "details": "Details", "actions": "Actions", "status": "Status", "name": "Name", "version": "Version", "size": "Size", "date": "Date", "upload": "Upload", "download": "Download", "view_raw": "View Raw JSON", "advanced": "Advanced", "close": "Close"}, "home": {"welcome": "Welcome to Ziokt Unified Graphical Client", "welcome_sub": "Integrating Zero-Knowledge communications, dCPM packages, Shadow6 mesh tunnels, and verifiable native compute", "quick_actions": "Quick Actions", "system_health": "Component Health", "gateway_telemetry": "Gateway Telemetry", "recent_activity": "Recent Activity", "act_chat": "Start Encrypted Chat", "act_files": "Open Secure File Vault", "act_forum": "Browse Latest Proposals", "act_apps": "Manage dCPM Packages", "act_network": "Inspect Shadow6 & ETP Mesh", "local_offline_alert": "⚠️ No local real node detected: Currently in local mode, but http://127.0.0.1:8185 is not responding. Local mode requires an actual running Ziokt node.", "remote_unauth_alert": "🔒 Remote node requires authentication: Active remote node does not have a valid Auth Token configured.", "switch_remote": "Switch to Remote Gateway", "config_auth": "Configure Auth Credentials", "probe_local": "Probe Local Node"}, "chat": {"title": "WATChat End-to-End Encrypted Messenger", "dual_ui": "UI Switcher", "ui_minimalist": "Modern Minimalist", "ui_classic": "Classic Rich", "ui_switch_tip": "Seamlessly switch between layouts; message history and cryptographic keys are synchronized without loss", "contacts": "Contacts / Dialogs", "new_conversation": "New Secure Chat", "enter_recipient": "Enter recipient DID or public key", "send": "Send", "input_placeholder": "Type encrypted message...", "attach_file": "Attach Vault File", "encryption_badge": "XChaCha20-Poly1305 Sealed", "empty_messages": "No messages yet. Send a greeting to start secure chatting."}, "forum": {"title": "Corium Decentralized Community Forum", "new_post": "New Post / Proposal", "post_title": "Title", "post_category": "Category", "post_content": "Content (Markdown supported)", "sign_and_publish": "Sign with Ed25519 & Publish", "cat_governance": "Governance", "cat_technical": "Technical", "cat_apps": "App Development", "cat_general": "General Discussion", "signature_verified": "Ed25519 On-Chain Signature Verified", "replies": "replies"}, "files": {"title": "UFS & SafeFS Secure Storage Vault", "vault_type": "Storage Driver", "vault_ufs": "UFS Native Storage", "vault_safefs": "SafeFS AEAD Encrypted Vault", "upload_file": "Upload File", "create_folder": "New Folder", "stealth_mode": "Deniable Volume (Outer Decoy / Inner Stealth)", "drop_tip": "Drag and drop files here for chunked persistent storage", "download": "Download File", "delete_confirm": "Are you sure you want to permanently delete this file? This cannot be undone."}, "apps": {"title": "dCPM Decentralized App Center", "subtitle": "Built on UFS and signed dCPM package architecture with dependency verification and sandbox isolation", "install_pkg": "Install / Import .dcpm Package", "installed_tab": "Installed Applications", "market_tab": "Ecosystem Repository", "rollback": "Rollback Version", "uninstall": "Uninstall", "update": "Check Updates", "publisher": "Publisher Key", "digest": "SHA-256 Digest", "dependencies": "Dependencies", "dep_check_ok": "All Dependencies Satisfied", "install_confirm": "Confirm installation of this signed package? It will execute inside an isolated sandbox.", "uninstall_confirm": "Confirm uninstallation of this package and its local cache?"}, "network": {"title": "Shadow6 & ETP Network Mesh", "subtitle": "Manage 13 language core Profile cluster, Virtual Broker, and onion routing paths", "profiles_title": "13 Core Language Profiles Cluster", "virtual_broker": "Virtual Broker Status", "s6p1_import": "Import Custom S6P1 Credential Envelope", "etp_title": "ETP Native Onion Multi-Hop Paths", "hops": "hop route path", "ping_test": "Latency Diagnostics", "privacy_masked": "Non-admin mode has automatically masked sensitive IPs and private keys", "node_topology": "Node & Gateway Topology", "local_node": "Local Node", "remote_nodes": "Remote Nodes Cluster", "manage_nodes": "Manage Custom Nodes"}, "identity": {"title": "Identity & Proof of Useful Work (PoUW)", "did": "Decentralized ID (DID)", "nns_domain": "NNS Bound Domain", "pouw_status": "PoUW Compute & Consensus Contribution", "engine_reward": "Governance Reward Weight", "apply_weight": "Apply for Validator Weight Whitelist", "export_keys": "Export Encrypted Backup", "switch_account": "Switch Identity"}, "devtools": {"title": "Native Component Developer Studio", "subtitle": "Fully functional GUIs for Corium, Tri, ZDA, TC-16 Virtual Machine, and MCP diagnostics", "tab_corium": "Corium Console", "tab_tri": "Tri Snapshots", "tab_zda": "ZDA / Ano Gate", "tab_tc16": "TC-16 VM Studio", "tab_mcp": "MCP Tool Catalog", "corium_query": "Query Ledger Facts & Blocks", "tri_run": "Execute Isolated Sandbox Snapshot", "zda_calc": "Verify Exact ZDA Evidence Arithmetic", "tc16_asm": "TC-16 Assembly & Bytecode Debugger", "tc16_run": "Run Virtual Machine", "tc16_step": "Step Execution", "tc16_reset": "Reset Registers"}, "settings": {"title": "System & Component Lifecycle Settings", "runtime_mode": "Client Runtime Mode", "local_gateway_url": "Gateway Endpoint", "components_lifecycle": "On-Demand Component Launcher", "comp_corium": "Corium Native Blockchain", "comp_shadow6": "Shadow6 Multi-Core Tunnel", "comp_ufs": "UFS & dCPM Storage Engine", "comp_watchat": "WATChat Federation Bridge", "comp_etp": "ETP Onion Gateway Router", "accessibility": "Accessibility & Keyboard Navigation", "keyboard_shortcuts": "Shortcuts: [1-9] Switch Modules, [Esc] Close Modals, [Ctrl+K] Global Search", "local_node_title": "Local Node Connection & Real Verification", "local_node_desc": "Using local node requires an actual Ziokt node daemon running locally. If not running, local RPC and write operations are blocked.", "local_node_probe": "Probe Local Node", "local_node_online": "Local Real Node Online", "local_node_offline": "No Local Real Node Detected", "local_node_checking": "Probing Local Node...", "local_node_help": "Start local node daemon: run 'systemctl start ziokt-gateway' or './tools/control_center.sh' in terminal.", "remote_nodes_title": "Remote Node Gateways & Auth Management", "remote_nodes_desc": "Using a remote node requires authentication (Auth Token). You can add custom remote nodes and test their connection and auth validity.", "add_node": "Add New Remote Node", "node_name": "Node Name", "node_url": "Node Endpoint (URL)", "auth_token": "Auth Token", "auth_token_tip": "Used for Bearer / X-Ziokt-Auth remote authentication", "test_auth": "Test Auth", "set_active": "Set Active", "active_badge": "Active", "auth_valid": "Auth Verified", "auth_invalid": "Auth Failed", "auth_required": "Auth Required", "delete_node": "Delete Node", "cannot_delete_default": "Default system node cannot be deleted", "add_node_btn": "Add & Verify Node"}}};

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
      Events.emit('local_node_status_changed', { status: 'unverified', data });
      updateAppNodeBadge();
      return { ok: true, data };
    } else {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.error || `HTTP ${res.status}: ${res.statusText}`);
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
    const res = await fetch(`${node.url}/api/gateway/tools`, {
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
  if (!endpoint.startsWith('/') || endpoint.startsWith('//')) throw new Error('Same gateway relative path required');
  const url = `${base}${endpoint}`;

  const headers = {
    'Accept': 'application/json',
    ...(options.headers || {})
  };

  {
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
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.error || `HTTP ${res.status}: ${res.statusText}`);
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

// Real GUI operations share the server's typed MCP authorization, audit and idempotency.
async function callTool(name, arguments_, {confirm = false, key = crypto.randomUUID()} = {}) {
  const result = await apiRequest('/api/gateway/tools/call', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name, arguments: arguments_, confirm, idempotency_key: key})
  });
  const text = (result.content || []).filter(c => c.type === 'text').map(c => c.text).join('\n');
  if (result.isError) throw new Error(text || 'Tool execution failed');
  if (result.structuredContent) return result.structuredContent;
  try { return JSON.parse(text); } catch (_) { return {text}; }
}
async function sha256(bytes) {
  return 'sha256:' + Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), b => b.toString(16).padStart(2, '0')).join('');
}
async function uploadObject(file, app, progress = () => {}) {
  if (file.size > 64 * 1024 * 1024) throw new Error('Browser upload limit: 64 MiB per file');
  const bytes = new Uint8Array(await file.arrayBuffer());
  const digest = await sha256(bytes), upload = crypto.randomUUID();
  await callTool(app+'_object_begin', {params:{upload, size: bytes.length, digest, ttl: 3600}}, {confirm:true,key:upload+'-begin'});
  try {
    for (let start=0, position=0; start<bytes.length; start+=16384, position++) {
      const chunk=bytes.slice(start,start+16384);
      const data_base64=btoa(String.fromCharCode(...chunk));
      await callTool(app+'_object_chunk_put', {params:{upload,position,digest:await sha256(chunk),data_base64}}, {confirm:true,key:upload+'-chunk-'+position});
      progress(Math.min(start+16384,bytes.length),bytes.length);
    }
    const result=await callTool(app+'_object_finish',{params:{upload}},{confirm:true,key:upload+'-finish'});
    if (result.digest!==digest || result.length!==bytes.length) throw new Error('Final object receipt differs from uploaded content');
    return result;
  } catch (error) {
    // An ambiguous finish result retains its upload lease; inspect object.status before manual release.
    throw new Error('Upload '+upload+': '+error.message);
  }
}
async function renderToolPanel(container, title, filter, fileOperations = false) {
  container.innerHTML = `<div class="card"><a href="https://app.ziokt.com/downloads/" target="_blank" rel="noopener">各平台软件下载 / Downloads</a><h2></h2><p>操作使用已鉴权的真实后端。工具结果仅代表其声明的阶段；验签、暂存、安装、激活分别显示。</p>
    <label>Node administrator token（只保存在当前页面内存）<input type="password" class="input-text" id="operation-token" autocomplete="off"></label>
    <button class="btn btn-primary" id="load-real-tools">连接并刷新工具</button><p id="tool-count"></p>
    <select class="input-text" id="real-tool"></select><pre id="real-schema" style="white-space:pre-wrap"></pre>
    <label>参数 JSON<textarea id="real-arguments" class="input-textarea" rows="7">{}</textarea></label>
    <label><input type="checkbox" id="real-confirm"> 我确认执行所选写操作</label>
    <button class="btn btn-primary" id="run-real-tool">执行</button>
    ${fileOperations ? '<hr><input type="file" id="real-file"><select id="file-app"><option>safefs</option><option>dcpm</option><option>ufs</option></select><button class="btn btn-secondary" id="upload-real-file">分块上传实际内容</button><p>上传只保存加密对象；上传不代表安装。</p><input id=download-object class=input-text placeholder="对象 manifest_digest"><button id=download-real-file class="btn btn-secondary">验证并下载实际内容</button><hr><input id=native-name class=input-text placeholder="原生包 ID（须匹配签名）"><input id=native-version class=input-text placeholder="原生包版本（须匹配签名）"><button id=stage-native-package class="btn btn-secondary">生成 v2 引用包并验证原生签名暂存</button>' : ''}
    <pre id="real-result" role="status" style="white-space:pre-wrap;overflow-wrap:anywhere"></pre></div>`;
  container.querySelector('h2').textContent=title;
  const out=container.querySelector('#real-result'), select=container.querySelector('#real-tool');
  let tools=[];
  const fail=e=>{out.textContent='操作失败：'+e.message;};
  container.querySelector('#load-real-tools').onclick=async()=>{
    const token=container.querySelector('#operation-token');
    if(token.value) {State.authToken=token.value;const n=getActiveRemoteNode();if(n){n.authToken=token.value;nodeSecrets.set(n.id,token.value);}token.value='';}
    try {
      const listing=await apiRequest('/api/gateway/tools');tools=listing.tools.filter(t=>filter(t.name));
      select.replaceChildren(...tools.map(t=>new Option(t.name,t.name)));
      container.querySelector('#tool-count').textContent=`已鉴权：${listing.count} 个工具，本页 ${tools.length} 个`;
      select.onchange=()=>{const t=tools.find(t=>t.name===select.value);container.querySelector('#real-schema').textContent=t?JSON.stringify(t.inputSchema,null,2):'';container.querySelector('#real-confirm').checked=false;};select.onchange();
    }catch(e){fail(e);}
  };
  container.querySelector('#run-real-tool').onclick=async(event)=>{
    const btn=event.currentTarget;btn.disabled=true;
    try {
      const tool=tools.find(t=>t.name===select.value);if(!tool)throw new Error('请先连接并选择工具');
      const confirm=container.querySelector('#real-confirm').checked;
      if(tool.annotations.destructiveHint&&!confirm)throw new Error('写操作需要明确确认');
      const started=performance.now();
      const result=await callTool(tool.name,JSON.parse(container.querySelector('#real-arguments').value),{confirm});
      out.textContent=JSON.stringify({elapsed_ms:Math.round(performance.now()-started),result},null,2);
    }catch(e){fail(e);}finally{btn.disabled=false;}
  };
  if(fileOperations)container.querySelector('#upload-real-file').onclick=async(event)=>{
    const btn=event.currentTarget;btn.disabled=true;
    try{
      if(!container.querySelector('#real-confirm').checked)throw new Error('上传写操作需要明确确认');
      const file=container.querySelector('#real-file').files[0];if(!file)throw new Error('请选择文件');
      const result=await uploadObject(file,container.querySelector('#file-app').value,(done,total)=>{out.textContent=`上传 ${done}/${total} 字节`;});
      out.textContent=JSON.stringify({file:file.name,receipt:result,installed:false},null,2);
    }catch(e){fail(e);}finally{btn.disabled=false;}
  };
  if(fileOperations)container.querySelector('#download-real-file').onclick=async(event)=>{
    const btn=event.currentTarget;btn.disabled=true;
    try{
      const app=container.querySelector('#file-app').value,object=container.querySelector('#download-object').value.trim();
      const reference=await callTool(app+'_object_reference',{params:{object}});
      if(reference.length>64*1024*1024)throw new Error('Browser download limit: 64 MiB');
      const parts=[];let length=0;
      for(let position=0;position<Math.ceil(reference.length/16384);position++){
        const item=await callTool(app+'_object_chunk_get',{params:{object,position}});
        const bytes=Uint8Array.from(atob(item.data_base64),c=>c.charCodeAt(0));
        if(await sha256(bytes)!==item.digest)throw new Error('Chunk integrity failed');
        length+=bytes.length;if(length>reference.length)throw new Error('Object length exceeded');parts.push(bytes);
      }
      const bytes=new Uint8Array(length);let offset=0;for(const part of parts){bytes.set(part,offset);offset+=part.length;}
      if(length!==reference.length||await sha256(bytes)!==reference.digest)throw new Error('Whole object integrity failed');
      const url=URL.createObjectURL(new Blob([bytes]));const a=document.createElement('a');a.href=url;a.download='verified-object.bin';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      out.textContent=JSON.stringify({download_verified:true,bytes:length,digest:reference.digest},null,2);
    }catch(e){fail(e);}finally{btn.disabled=false;}
  };
  if(fileOperations)container.querySelector('#stage-native-package').onclick=async(event)=>{
    const btn=event.currentTarget;btn.disabled=true;
    try{
      if(!container.querySelector('#real-confirm').checked)throw new Error('生成软件包和暂存需要明确确认');
      const file=container.querySelector('#real-file').files[0];if(!file)throw new Error('请选择独立签名的 Shadow6 原生 ZIP');
      const name=container.querySelector('#native-name').value.trim(),version=container.querySelector('#native-version').value.trim();
      if(!name||!version)throw new Error('原生包 ID 和版本不能为空，且必须与内层签名匹配');
      const object=await uploadObject(file,'dcpm',(done,total)=>{out.textContent=`上传 ${done}/${total} 字节`;});
      const pkg=await callTool('dcpm_package_build_references',{params:{name,version,files:{'shadow6/package.zip':object.manifest_digest},dependencies:[]}},{confirm:true});
      out.textContent=JSON.stringify({package:pkg,staging:true},null,2);
      const receipt=await callTool('dcpm_package_stage_native',{digest:pkg.digest,authority:pkg.publisher},{confirm:true});
      out.textContent=JSON.stringify({package:pkg,receipt,installed:false},null,2);
    }catch(e){fail(e);}finally{btn.disabled=false;}
  };

}


  // --- Module: modules/home.js ---
function renderHome(container) {
  return renderToolPanel(container, '节点实时总览', n => /status|components|stats/.test(n), false);
}


  // --- Module: modules/chat.js ---
// ==============================================================================
// Module: WATChat End-to-End Encrypted Messenger with Dual UI Switcher
// ==============================================================================

let chatUiMode = getStorage('watchat_ui_mode', 'classic'); // 'minimalist' | 'classic'
let isChatLoggedIn = getStorage('watchat_logged_in', 'false') === 'true';
let activeContact = 'genesis-node';
let isVoiceRecording = false;
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
      { id: 1, sender: 'genesis-node', text: '欢迎加入 Ziokt 腕聊端到端加密通讯网络！所有消息均由 XChaCha20-Poly1305 密封。', time: '10:00' },
      { id: 2, sender: 'me', text: '收到！经典丰富版已直接复刻腕聊原生界面架构。', time: '10:02' },
      { id: 3, sender: 'genesis-node', text: '可在上方随时切换“现代简约版”与“经典丰富版”，加密会话状态实时无损保持。', time: '10:03' }
    ],
    'community-bot': [
      { id: 1, sender: 'community-bot', text: 'Corium 治理委员会 #48 提案已发起，欢迎前往社区论坛参与投票。', time: '09:15' }
    ]
  };
}
function renderChat(container) {
  const isMinimalist = chatUiMode === 'minimalist';

  // 1. WATChat Login Screen with Dual UI Switcher
  if (!isChatLoggedIn) {
    if (!isMinimalist) {
      // Replicate exact Login UI from WATChat-code.zip
      container.innerHTML = `
        <div class="chat-page-wrapper watchat-classic-root">
          <div class="chat-login-container login-classic">
            <div class="chat-login-card login-box">
              
              <!-- Dual UI Switcher at top of Login Page -->
              <div class="chat-login-switcher-bar" style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #2b383f; padding-bottom: 10px; margin-bottom: 12px;">
                <div style="font-size: 0.8rem; font-weight: 700; color: #45d483; display: flex; align-items: center; gap: 6px;">
                  <span>腕聊</span>
                  <span style="font-size: 0.68rem; color: #07140d; background: #45d483; padding: 1px 6px; border-radius: 6px; font-weight: 800;">经典版</span>
                </div>
                <div class="dual-ui-toggle-group">
                  <button id="toggle-minimalist" class="btn btn-sm btn-secondary" style="border:none; padding: 3px 8px; font-size: 0.75rem;">${t('chat.ui_minimalist')}</button>
                  <button id="toggle-classic" class="btn btn-sm btn-primary" style="border:none; background: #45d483; color: #07140d; font-weight: 700; padding: 3px 8px; font-size: 0.75rem;">${t('chat.ui_classic')}</button>
                </div>
              </div>

              <!-- Replicated Login Form -->
              <form id="chat-login-form">
                <h1 style="font-size: 28px; margin: 0; color: #f4f7f8; font-weight: 800;">腕聊</h1>
                <p style="color: #9fb0b8; margin: 5px 0 14px; font-size: 14px;">登录你的账户</p>
                <input id="chat-username" autocomplete="username" maxlength="24" placeholder="用户名" aria-label="用户名" required class="input-text">
                <input id="chat-passphrase" type="password" autocomplete="current-password" maxlength="64" placeholder="密码" aria-label="密码" required class="input-text">
                <button type="submit" id="chat-login-btn">进入</button>
                <output id="loginError" class="error" aria-live="polite" style="color: #ff7d7d; font-size: 13px; margin-top: 8px; display: block;"></output>
              </form>

              <div style="margin-top: 14px; font-size: 0.72rem; color: #9fb0b8; display: flex; justify-content: space-between; align-items: center;">
                <span>DID: did:ziokt:mesh:genesis-node</span>
                <span style="color: #45d483; border: 1px solid rgba(69,212,131,0.3); padding: 2px 6px; border-radius: 8px;">XChaCha20-Poly1305</span>
              </div>
            </div>
          </div>
        </div>
      `;
    } else {
      // Modern Minimalist Login View
      container.innerHTML = `
        <div class="chat-page-wrapper">
          <div class="chat-login-container login-minimalist">
            <div class="chat-login-card">
              <div class="chat-login-switcher-bar">
                <div style="font-size: 0.8rem; font-weight: 600; color: var(--text-muted); display: flex; align-items: center; gap: 6px;">
                  <span>💬 WATChat</span>
                  <span class="mode-pill" style="font-size: 0.7rem; color: var(--accent-cyan);">${t('chat.dual_ui')}</span>
                </div>
                <div class="dual-ui-toggle-group">
                  <button id="toggle-minimalist" class="btn btn-sm btn-primary" style="border:none;">${t('chat.ui_minimalist')}</button>
                  <button id="toggle-classic" class="btn btn-sm btn-secondary" style="border:none;">${t('chat.ui_classic')}</button>
                </div>
              </div>

              <div style="text-align: center; margin: 16px 0 20px 0;">
                <div style="font-size: 2.2rem; margin-bottom: 8px;">🔐</div>
                <h2 style="font-size: 1.25rem; font-weight: 700; color: var(--text-main); margin-bottom: 4px;">${t('chat.login_title')}</h2>
                <p style="font-size: 0.8rem; color: var(--text-muted);">${t('chat.login_desc')}</p>
                <div style="margin-top: 8px;">
                  <span class="status-badge" style="font-size: 0.72rem; color: var(--accent-green); background: rgba(16,185,129,0.12); padding: 4px 10px; border-radius: 12px; border: 1px solid rgba(16,185,129,0.3);">
                    <span class="status-dot"></span> XChaCha20-Poly1305
                  </span>
                </div>
              </div>

              <form id="chat-login-form" style="display: flex; flex-direction: column; gap: 12px; margin-top: 16px;">
                <div>
                  <label style="display: block; font-size: 0.78rem; font-weight: 600; color: var(--text-muted); margin-bottom: 4px;">
                    ${t('common.name')} / DID
                  </label>
                  <input type="text" id="chat-username" class="input-text" value="Genesis Node (Node #0)" placeholder="${t('chat.username_placeholder')}" style="width: 100%;">
                </div>
                <div>
                  <label style="display: block; font-size: 0.78rem; font-weight: 600; color: var(--text-muted); margin-bottom: 4px;">
                    ${t('settings.auth_token')} / Passphrase
                  </label>
                  <input type="password" id="chat-passphrase" class="input-text" value="●●●●●●●●●●●●" placeholder="${t('chat.passphrase_placeholder')}" style="width: 100%;">
                </div>
                <button type="submit" id="chat-login-btn" class="btn btn-primary" style="width: 100%; padding: 10px; margin-top: 6px; font-weight: 600;">
                  🚀 ${t('chat.login_btn')}
                </button>
              </form>

              <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 16px; font-size: 0.75rem; color: var(--text-dim);">
                <span>DID: did:ziokt:mesh:genesis-node</span>
                <span class="mode-pill">${t('chat.ui_minimalist')}</span>
              </div>
            </div>
          </div>
        </div>
      `;
    }

    // Dual UI Handlers on Login Page
    container.querySelector('#toggle-minimalist').onclick = () => {
      chatUiMode = 'minimalist';
      setStorage('watchat_ui_mode', 'minimalist');
      showToast(t('chat.ui_minimalist'), 'info');
      renderChat(container);
    };

    container.querySelector('#toggle-classic').onclick = () => {
      chatUiMode = 'classic';
      setStorage('watchat_ui_mode', 'classic');
      showToast('已切换至腕聊经典丰富版', 'info');
      renderChat(container);
    };

    // Login Form Submit
    container.querySelector('#chat-login-form').onsubmit = (e) => {
      e.preventDefault();
      isChatLoggedIn = true;
      setStorage('watchat_logged_in', 'true');
      showToast('腕聊已进入会话', 'success');
      renderChat(container);
    };

    return;
  }

  // 2. Logged-in Chat Room
  if (!isMinimalist) {
    // Replicate exact 腕聊 UI from WATChat-code.zip
    container.innerHTML = `
      <div class="chat-page-wrapper watchat-classic-root">
        <div class="chat-classic-app">
          
          <!-- Replicated Header from WATChat-code.zip -->
          <header class="chat-classic-header">
            <button id="chat-back-btn" class="chat-classic-head-btn" aria-label="返回" title="返回联系人">‹</button>
            <strong id="chat-peer-title">${activeContact === 'genesis-node' ? 'Genesis Node' : 'Community Bot'}</strong>
            <span class="online">● 在线</span>
            <span style="font-size: 0.65rem; color: #45d483; font-family: var(--font-mono); border: 1px solid rgba(69,212,131,0.3); padding: 1px 6px; border-radius: 6px; margin: 0 4px;">XChaCha20-Poly1305</span>
            
            <!-- Dual UI Switcher in Header -->
            <div class="dual-ui-toggle-group" style="margin: 0 4px;">
              <button id="toggle-minimalist" class="btn btn-sm btn-secondary" style="border:none; padding: 2px 8px; font-size: 0.72rem;">${t('chat.ui_minimalist')}</button>
              <button id="toggle-classic" class="btn btn-sm btn-primary" style="border:none; background: #45d483; color: #07140d; font-weight: 700; padding: 2px 8px; font-size: 0.72rem;">${t('chat.ui_classic')}</button>
            </div>

            <!-- Header Action Buttons from WATChat-code.zip: 管 (Admin) & 退 (Logout) -->
            <button id="chat-admin-btn" class="chat-classic-head-btn btn-text-badge" aria-label="管理用户" title="管理用户">管</button>
            <button id="chat-logout-btn" class="chat-classic-head-btn btn-text-badge" aria-label="退出" title="${t('chat.logout_btn')}">退</button>
          </header>

          <!-- Admin Drawer from WATChat-code.zip -->
          <section id="chat-admin-panel" style="display: none; background: #192126; border-bottom: 1px solid #2b383f; padding: 12px; font-size: 13px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <h2 style="font-size: 15px; margin: 0; color: #45d483;">用户与联系人 (腕聊)</h2>
              <button id="chat-close-admin-btn" style="background: transparent; border: 0; color: #9fb0b8; font-size: 16px; cursor: pointer;">✕</button>
            </div>
            <p style="color: #9fb0b8; margin: 0 0 8px; font-size: 12px;">点选某用户，再勾选其可聊天联系人；端到端双向密钥生效。</p>
            <div style="display: flex; gap: 6px; flex-wrap: wrap;">
              <button type="button" class="user-chip active" style="padding: 4px 10px; background: #45d483; color: #07140d; font-weight: 700; border: 0; border-radius: 8px;">Genesis Node (主节点)</button>
              <button type="button" class="user-chip" style="padding: 4px 10px; background: #101417; color: #f4f7f8; border: 1px solid #2b383f; border-radius: 8px;">Community Bot</button>
            </div>
          </section>

          <!-- Body: Contacts List + Messages + 5-Column Composer -->
          <div class="chat-container" style="display: flex; flex: 1; min-height: 0; background: #101417; overflow: hidden; border: none;">
            
            <!-- Replicated Sidebar Contacts List -->
            <aside class="chat-sidebar" style="width: 260px; background: #101417; border-right: 1px solid #2b383f; display: flex; flex-direction: column;">
              <div style="padding: 8px; border-bottom: 1px solid #2b383f;">
                <input type="text" id="contact-search" class="input-text" placeholder="搜索联系人…" style="width: 100%; min-height: 38px; border: 1px solid #2b383f; background: #192126; color: #f4f7f8; border-radius: 9px; padding: 0 8px; font-size: 13px;">
              </div>
              <div id="contact-list" class="list" style="flex: 1; overflow-y: auto; padding: 8px;">
                <div class="contact chat-classic-contact ${activeContact === 'genesis-node' ? 'active' : ''}" data-id="genesis-node">
                  <span class="avatar chat-classic-avatar">G</span>
                  <div style="flex: 1; overflow: hidden;">
                    <div style="font-weight: 700; font-size: 14px; color: #f4f7f8; display: flex; justify-content: space-between;">
                      <span>Genesis Node</span>
                      <span style="font-size: 11px; color: #9fb0b8;">10:03</span>
                    </div>
                    <div style="font-size: 12px; color: #9fb0b8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">双 UI 架构测试中...</div>
                  </div>
                </div>

                <div class="contact chat-classic-contact ${activeContact === 'community-bot' ? 'active' : ''}" data-id="community-bot">
                  <span class="avatar chat-classic-avatar" style="background: #246b49; color: #fff;">C</span>
                  <div style="flex: 1; overflow: hidden;">
                    <div style="font-weight: 700; font-size: 14px; color: #f4f7f8; display: flex; justify-content: space-between;">
                      <span>Community Bot</span>
                      <span style="font-size: 11px; color: #9fb0b8;">09:15</span>
                    </div>
                    <div style="font-size: 12px; color: #9fb0b8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">#48 提案已发布</div>
                  </div>
                </div>
              </div>
              <div style="padding: 8px; border-top: 1px solid #2b383f;">
                <button id="add-contact-btn" style="width: 100%; min-height: 40px; border: 0; background: #45d483; color: #07140d; font-weight: 700; border-radius: 9px; cursor: pointer;">+ ${t('chat.new_conversation')}</button>
              </div>
            </aside>

            <!-- Replicated Messages Area + Composer -->
            <div class="chat-main" style="flex: 1; display: flex; flex-direction: column; min-height: 0; background: #101417; overflow: hidden;">
              
              <!-- Messages -->
              <div id="messages-box" class="messages chat-classic-messages">
                ${(messagesStore[activeContact] || []).map(m => `
                  <article class="message chat-classic-msg ${m.sender === 'me' ? 'mine' : ''}">
                    <div>${m.text}</div>
                    <time>${m.time}</time>
                  </article>
                `).join('')}
              </div>

              <!-- Replicated 5-Column Composer: 图 / 视 / 音 / 消息… / 发 -->
              <div class="chat-input-bar chat-classic-composer">
                <button id="attach-vault-btn" class="media-button chat-classic-media-btn" type="button" aria-label="发送图片" title="从保险库/本地发送图片与附件">图</button>
                <button id="video-attach-btn" class="media-button chat-classic-media-btn" type="button" aria-label="发送视频" title="发送视频附件">视</button>
                <button id="voice-record-btn" class="media-button chat-classic-media-btn ${isVoiceRecording ? 'recording' : ''}" type="button" aria-label="录制语音" title="录制语音消息">${isVoiceRecording ? '停' : '音'}</button>
                <input type="text" id="chat-input" class="chat-classic-input" maxlength="1000" enterkeyhint="send" autocomplete="off" placeholder="消息…" aria-label="消息">
                <button type="submit" id="chat-send-btn" class="media-button chat-classic-media-btn" aria-label="发送" style="background:#45d483; color:#07140d; font-weight:800;">发</button>
              </div>

            </div>

          </div>
        </div>
      </div>
    `;
  } else {
    // Modern Minimalist Chat View
    container.innerHTML = `
      <div class="chat-page-wrapper">
        <div class="chat-subheader">
          <div style="display: flex; align-items: center; gap: 10px;">
            <span style="font-weight: 700; color: var(--accent-cyan); font-size: 0.95rem;">💬 ${t('chat.title')}</span>
            <span class="status-badge" style="font-size: 0.7rem; color: var(--accent-green);">
              <span class="status-dot"></span> XChaCha20-Poly1305
            </span>
          </div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 0.78rem; color: var(--text-muted);">${t('chat.dual_ui')}:</span>
            <div class="dual-ui-toggle-group">
              <button id="toggle-minimalist" class="btn btn-sm btn-primary" style="border:none;">${t('chat.ui_minimalist')}</button>
              <button id="toggle-classic" class="btn btn-sm btn-secondary" style="border:none;">${t('chat.ui_classic')}</button>
            </div>
            <button id="chat-logout-btn" class="btn btn-secondary btn-sm" title="${t('chat.logout_btn')}" style="padding: 4px 8px; font-size: 0.75rem;">🔒 ${t('chat.logout_btn')}</button>
          </div>
        </div>

        <div class="chat-container">
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

          <div class="chat-main">
            <div style="padding: 12px 16px; border-bottom: 1px solid var(--border-subtle); display: flex; justify-content: space-between; align-items: center; background: var(--bg-sidebar);">
              <div>
                <div style="font-weight: 600; font-size: 0.95rem; color: var(--text-main);">${activeContact === 'genesis-node' ? 'Genesis Node (Node #0)' : 'Community Bot'}</div>
                <div style="font-size: 0.72rem; color: var(--accent-cyan); font-family: var(--font-mono);">did:ziokt:mesh:${activeContact}</div>
              </div>
            </div>

            <div id="messages-box" class="chat-messages">
              ${(messagesStore[activeContact] || []).map(m => `
                <div class="chat-bubble ${m.sender === 'me' ? 'bubble-mine' : 'bubble-theirs'}">
                  <div>${m.text}</div>
                  <div style="font-size: 0.65rem; text-align: right; margin-top: 4px; opacity: 0.75;">${m.time}</div>
                </div>
              `).join('')}
            </div>

            <div class="chat-input-bar">
              <div style="display: flex; gap: 10px;">
                <input type="text" id="chat-input" class="input-text" placeholder="${t('chat.input_placeholder')}" style="flex: 1;">
                <button id="chat-send-btn" class="btn btn-primary">${t('chat.send')}</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

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
    showToast('已切换至腕聊经典丰富版', 'info');
    renderChat(container);
  };

  // Logout / Lock Session Handler
  const logoutBtn = container.querySelector('#chat-logout-btn');
  if (logoutBtn) {
    logoutBtn.onclick = () => {
      isChatLoggedIn = false;
      setStorage('watchat_logged_in', 'false');
      showToast('已锁定会话并返回登录页', 'info');
      renderChat(container);
    };
  }

  // Admin button handler (Classic mode)
  const adminBtn = container.querySelector('#chat-admin-btn');
  const adminPanel = container.querySelector('#chat-admin-panel');
  if (adminBtn && adminPanel) {
    adminBtn.onclick = () => {
      adminPanel.style.display = adminPanel.style.display === 'none' ? 'block' : 'none';
    };
    const closeAdminBtn = container.querySelector('#chat-close-admin-btn');
    if (closeAdminBtn) closeAdminBtn.onclick = () => { adminPanel.style.display = 'none'; };
  }

  // Contact Switcher
  container.querySelectorAll('.contact-item, .chat-classic-contact').forEach(item => {
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

  // Classic Bar Attachment ("图")
  const attachBtn = container.querySelector('#attach-vault-btn');
  if (attachBtn) {
    attachBtn.onclick = () => {
      const filename = prompt('输入图片或 UFS/SafeFS 附件文件名发送 (例如: PHOTO.jpg 或 WELCOME.txt):', 'PHOTO.jpg');
      if (filename) {
        inputEl.value = `[图: ${filename} | ufs://${filename}]`;
        doSend();
      }
    };
  }

  // Classic Bar Video ("视")
  const videoBtn = container.querySelector('#video-attach-btn');
  if (videoBtn) {
    videoBtn.onclick = () => {
      const filename = prompt('输入视频附件名称发送 (例如: clip.mp4):', 'clip.mp4');
      if (filename) {
        inputEl.value = `[视: ${filename}]`;
        doSend();
      }
    };
  }

  // Classic Bar Voice ("音")
  const voiceBtn = container.querySelector('#voice-record-btn');
  if (voiceBtn) {
    voiceBtn.onclick = () => {
      if (!isVoiceRecording) {
        isVoiceRecording = true;
        showToast('正在录音… 再次点击发送', 'info');
        renderChat(container);
      } else {
        isVoiceRecording = false;
        inputEl.value = `[音: 语音 3秒]`;
        doSend();
        showToast('语音已发送', 'success');
      }
    };
  }
}


  // --- Module: modules/forum.js ---
function renderForum(container) {
  return renderToolPanel(container, '真实社区论坛', n => /forum|cbb|wiki/.test(n), false);
}


  // --- Module: modules/files.js ---
function renderFiles(container) {
  return renderToolPanel(container, 'SafeFS 分块对象存储', n => n.startsWith('safefs_') || n.startsWith('ufs_'), true);
}


  // --- Module: modules/apps.js ---
function renderApps(container) {
  return renderToolPanel(container, 'dCPM 与原生应用管理', n => n.startsWith('dcpm_') || n.includes('package_'), true);
}


  // --- Module: modules/network.js ---
function renderNetwork(container) {
  return renderToolPanel(container, 'Shadow6 / ETP 实时网络能力', n => n.startsWith('shadow6_') || n.startsWith('etp_'), false);
}


  // --- Module: modules/identity.js ---
function renderIdentity(container) {
  return renderToolPanel(container, '身份、所有权与白名单审批', n => /registration|identity|zkn|zkc|recovery/.test(n), false);
}


  // --- Module: modules/devtools.js ---
function renderDevtools(container) {
  return renderToolPanel(container, '原生开发工具与 MCP 目录', n => /^(corium_|tri_|zda_|tc16_|ziokt_)/.test(n), false);
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
            const statusText = node.status === 'online' ? `${t('settings.auth_valid')} (${node.latency || '--'})` : (node.status === 'unauthenticated' ? t('settings.auth_required') : (node.status === 'auth_failed' ? t('settings.auth_invalid') : (node.status === 'offline' ? t('app.status_offline') : '未验证')));

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
                  <input type="password" class="input-text node-token-input" data-id="${node.id}" value="" placeholder="${t('settings.auth_token_tip')}" style="font-size: 0.78rem; font-family: var(--font-mono); height: 30px; padding: 4px 8px;">
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

  // Lifecycle operations require an actual native service manager; browser UIs cannot claim process control.
  container.querySelectorAll('.toggle-comp-btn').forEach(btn => {
    btn.onclick = async () => {
      const invoke = window.__TAURI_INTERNALS__?.invoke;
      if (!invoke) { showToast('此浏览器没有本地进程管理权限；请通过原生客户端或服务管理器操作', 'error'); return; }
      btn.disabled = true;
      try {
        const key = btn.dataset.key;
        const observed = await invoke('manage_component', {name:key,action:'status'});
        const result = await invoke('manage_component', {name:key,action:observed.status==='active'?'stop':'start'});
        State.components[key].status = result.status === 'active' ? 'online' : result.status;
        showToast(result.message, 'info'); renderSettings(container);
      } catch (error) { showToast(String(error), 'error'); }
      finally { btn.disabled = false; }
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
