// ==============================================================================
// Ziokt Unified Graphical Client - Core Application Framework & State Manager
// ==============================================================================

export function getStorage(key, fallback = '') {
  if (key === 'ziokt_auth_token') return '';
  try {
    const v = localStorage.getItem(key);
    return v !== null ? v : fallback;
  } catch (e) {
    return fallback;
  }
}

export function setStorage(key, val) {
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

export const DEFAULT_REMOTE_NODES = [
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

export function getRemoteNodes() {
  try {
    const raw = localStorage.getItem('ziokt_remote_nodes');
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) return parsed.map(n => ({...n,authToken: nodeSecrets.get(n.id) || '',status:'unverified'}));
    }
  } catch (e) {}
  return [...DEFAULT_REMOTE_NODES];
}

export function saveRemoteNodes(nodes) {
  nodes.forEach(n => nodeSecrets.set(n.id, n.authToken || ''));
  setStorage('ziokt_remote_nodes', JSON.stringify(nodes.map(({authToken, ...n}) => n)));
  State.remoteNodes = nodes;
  Events.emit('remote_nodes_changed', nodes);
}

export function getActiveRemoteNode() {
  const nodes = State.remoteNodes || getRemoteNodes();
  const activeId = State.activeRemoteNodeId || getStorage('ziokt_active_node_id', 'node-official-tokyo');
  return nodes.find(n => n.id === activeId) || nodes[0] || DEFAULT_REMOTE_NODES[0];
}

export function setActiveRemoteNode(id) {
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

export function addRemoteNode({ name, url, authToken }) {
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

export function removeRemoteNode(id) {
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

export const State = {
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

export const BUILTIN_I18N = {"zh": {"app": {"title": "Ziokt 统一图形客户端", "subtitle": "去中心化原生操作系统与应用生态控制中心", "version": "v1.0.0 (Core Native)", "status_online": "正常运行", "status_offline": "已断开", "status_connecting": "连接中...", "mode_local": "本地节点", "mode_remote": "远程网关", "mode_hybrid": "混合模式", "switch_lang": "语言 / Language", "theme_dark": "赛博深黑", "theme_light": "清爽明亮", "theme_contrast": "高对比度"}, "nav": {"home": "首页总览", "chat": "加密通讯", "forum": "社区论坛", "files": "安全存储", "apps": "应用中心", "network": "网络节点", "identity": "身份与贡献", "devtools": "开发工具", "settings": "系统设置", "library": "Library", "netnews": "Netnews", "ecosystem": "应用与离线"}, "common": {"confirm": "确认", "cancel": "取消", "delete": "删除", "save": "保存", "edit": "编辑", "copy": "复制", "copied": "已复制到剪贴板", "refresh": "刷新", "search": "搜索...", "loading": "加载中...", "success": "操作成功", "error": "操作失败", "details": "查看详情", "actions": "操作", "status": "状态", "name": "名称", "version": "版本", "size": "大小", "date": "时间", "upload": "上传", "download": "下载", "view_raw": "查看原始数据", "advanced": "高级选项", "close": "关闭"}, "home": {"welcome": "欢迎使用 Ziokt 统一图形客户端", "welcome_sub": "集成零知识加密通讯、去中心化包管理、多协议隧道及链上可信微架构", "quick_actions": "快捷功能入口", "system_health": "核心组件健康状态", "gateway_telemetry": "网关实时遥测", "recent_activity": "近期网络活动", "act_chat": "快速发起加密对话", "act_files": "打开原生文件保险库", "act_forum": "浏览社区最新提案", "act_apps": "管理与运行扩展包", "act_network": "查看 Shadow6 / ETP 网格", "local_offline_alert": "⚠️ 未检测到本地真实节点: 当前处于本地模式，但 http://127.0.0.1:8185 未响应。使用本地节点需要用户本地真实有节点运行。", "remote_unauth_alert": "🔒 远程节点需要身份鉴权: 当前活跃远程节点尚未配置有效的 Auth Token 凭证。", "switch_remote": "切换至远程网关", "config_auth": "前往配置凭证", "probe_local": "重新检测本地节点"}, "chat": {"title": "WATChat 端到端加密通讯", "dual_ui": "界面风格切换", "ui_minimalist": "现代简约版", "ui_classic": "经典丰富版", "ui_switch_tip": "随时切换界面布局，聊天记录与加密密钥实时同步无损保留", "contacts": "联系人 / 对话列表", "new_conversation": "新建加密对话", "enter_recipient": "输入对方 DID 或公钥地址", "send": "发送", "input_placeholder": "输入加密消息...", "attach_file": "发送文件附件", "encryption_badge": "XChaCha20-Poly1305 端到端保密", "empty_messages": "暂无历史消息，发送一条问候开启端到端密聊吧", "login_title": "WATChat 密聊身份登录", "login_desc": "选择您偏好的 UI 风格并解锁端到端加密会话凭证", "login_btn": "登录并进入加密通讯", "username_placeholder": "输入用户名或 DID", "passphrase_placeholder": "输入加密私钥密码 / 会话密令", "logout_btn": "锁定会话 / 退出", "classic_telemetry": "经典版实时安全信令与拓扑遥测", "ratchet_status": "双棘轮状态: 就绪", "cipher_info": "加密套件: XChaCha20-Poly1305 / HKDF-SHA256", "onion_route": "中继节点: ETP Onion 3-Hop Multi-Path"}, "forum": {"title": "Corium 去中心化社区论坛", "new_post": "发布新帖 / 提案", "post_title": "标题", "post_category": "分类", "post_content": "正文内容 (支持 Markdown)", "sign_and_publish": "使用当前身份签名并发布", "cat_governance": "生态治理", "cat_technical": "核心技术", "cat_apps": "应用开发", "cat_general": "综合讨论", "signature_verified": "Ed25519 链上签名已验证", "replies": "条回复"}, "files": {"title": "UFS & SafeFS 安全存储保险库", "vault_type": "存储驱动", "vault_ufs": "UFS 原生文件系统", "vault_safefs": "SafeFS AEAD 加密保险箱", "upload_file": "上传文件", "create_folder": "新建目录", "stealth_mode": "双层可抵赖卷 (Outer Decoy / Inner Stealth)", "drop_tip": "拖拽文件至此处，自动执行安全分块持久化", "download": "下载文件", "delete_confirm": "确定永久删除此文件吗？此操作不可逆。"}, "apps": {"title": "dCPM 去中心化应用中心", "subtitle": "基于 UFS 与 dCPM 签名软件包体系，支持依赖审查、自动验签与安全沙箱执行", "install_pkg": "安装 / 导入 .dcpm 软件包", "installed_tab": "已安装应用", "market_tab": "生态软件包仓库", "rollback": "版本回滚", "uninstall": "卸载", "update": "检查更新", "publisher": "发布者签名", "digest": "SHA-256 校验摘要", "dependencies": "依赖组件", "dep_check_ok": "依赖项完整", "install_confirm": "确定安装此签名软件包吗？将严格在隔离沙箱中运行。", "uninstall_confirm": "确定卸载该应用及其本地缓存吗？"}, "network": {"title": "Shadow6 & ETP 网络节点网格", "subtitle": "管理 13 核心 Profile 运行集群、Virtual Broker 以及洋葱代理链路", "profiles_title": "13 语言核心 Profile 实时集群", "virtual_broker": "虚拟 Broker 代理状态", "s6p1_import": "粘贴导入自定义 S6P1 凭据信封", "etp_title": "ETP 原生洋葱多跳链路", "hops": "跳路由路径", "ping_test": "网络延迟诊断", "privacy_masked": "非管理员模式已自动脱敏保护敏感 IP 与密钥", "node_topology": "节点与网关拓扑", "local_node": "本地节点", "remote_nodes": "远程节点集群", "manage_nodes": "管理自定义节点"}, "identity": {"title": "身份管理与贡献证明 (PoUW)", "did": "去中心化身份 (DID)", "nns_domain": "NNS 绑定域名", "pouw_status": "PoUW 算力与共识贡献状态", "engine_reward": "治理奖励权重", "apply_weight": "申请加入验证者权重白名单", "export_keys": "导出加密密钥备份", "switch_account": "切换身份"}, "devtools": {"title": "原生组件全功能开发工具箱", "subtitle": "提供 Corium、Tri、ZDA、TC-16 虚拟机及 MCP 接口全功能调试与执行界面", "tab_corium": "Corium 控制台", "tab_tri": "Tri 状态机快照", "tab_zda": "ZDA / Ano 门限计算", "tab_tc16": "TC-16 虚拟机工作台", "tab_mcp": "MCP 211 工具探针", "corium_query": "查询区块与交易事实", "tri_run": "执行快照离线隔离沙箱", "zda_calc": "验证精确 ZDA 证据算术", "tc16_asm": "TC-16 汇编与字节码单步调试", "tc16_run": "运行虚拟机", "tc16_step": "单步执行 (Step)", "tc16_reset": "重置寄存器"}, "settings": {"title": "系统与组件生命周期设置", "runtime_mode": "客户端运行模式配置", "local_gateway_url": "本地/远程网关地址", "components_lifecycle": "按需组件启动管理 (On-demand Launcher)", "comp_corium": "Corium 原生区块链服务", "comp_shadow6": "Shadow6 多核心代理网络", "comp_ufs": "UFS & dCPM 安全存储引擎", "comp_watchat": "WATChat 联邦通讯桥接", "comp_etp": "ETP 洋葱网关路由", "accessibility": "无障碍与键盘导航", "keyboard_shortcuts": "快捷键说明: [1-9] 切换模块，[Esc] 关闭弹窗，[Ctrl+K] 全局搜索", "local_node_title": "本地节点连接与真实状态", "local_node_desc": "使用本地节点需要用户本地真实有节点运行。若本地未启动，客户端将无法进行写操作与本地 RPC 交互。", "local_node_probe": "探测本地节点", "local_node_online": "本地真实节点在线", "local_node_offline": "未检测到本地真实节点", "local_node_checking": "检测本地节点中...", "local_node_help": "本地启动指引: 请在终端执行 systemctl start ziokt-gateway 或运行 ./tools/control_center.sh", "remote_nodes_title": "远程节点网关与鉴权管理", "remote_nodes_desc": "使用远程节点需要身份鉴权 (Auth Token)。您可以自定义添加新的远程节点并测试连接与鉴权有效性。", "add_node": "添加新远程节点", "node_name": "节点名称", "node_url": "节点地址 (URL)", "auth_token": "鉴权凭证 (Auth Token)", "auth_token_tip": "用于 Bearer / X-Ziokt-Auth 远程身份验证", "test_auth": "测试鉴权", "set_active": "设为活跃", "active_badge": "当前活跃", "auth_valid": "鉴权通过", "auth_invalid": "鉴权失败", "auth_required": "待鉴权", "delete_node": "删除节点", "cannot_delete_default": "系统默认节点不可删除", "add_node_btn": "添加并测试该节点"}}, "en": {"app": {"title": "Ziokt Unified Graphical Client", "subtitle": "Decentralized Native OS & Application Ecosystem Console", "version": "v1.0.0 (Core Native)", "status_online": "Online", "status_offline": "Disconnected", "status_connecting": "Connecting...", "mode_local": "Local Node", "mode_remote": "Remote Gateway", "mode_hybrid": "Hybrid Mode", "switch_lang": "Language / 语言", "theme_dark": "Cyber Dark", "theme_light": "Clean Light", "theme_contrast": "High Contrast"}, "nav": {"home": "Home", "chat": "WATChat", "forum": "Forum", "files": "Files & Vault", "apps": "App Store", "network": "Network Nodes", "identity": "Identity & PoUW", "devtools": "Dev Tools", "settings": "Settings", "library": "Library", "netnews": "Netnews", "ecosystem": "Applications & offline"}, "common": {"confirm": "Confirm", "cancel": "Cancel", "delete": "Delete", "save": "Save", "edit": "Edit", "copy": "Copy", "copied": "Copied to clipboard", "refresh": "Refresh", "search": "Search...", "loading": "Loading...", "success": "Success", "error": "Error", "details": "Details", "actions": "Actions", "status": "Status", "name": "Name", "version": "Version", "size": "Size", "date": "Date", "upload": "Upload", "download": "Download", "view_raw": "View Raw JSON", "advanced": "Advanced", "close": "Close"}, "home": {"welcome": "Welcome to Ziokt Unified Graphical Client", "welcome_sub": "Integrating Zero-Knowledge communications, dCPM packages, Shadow6 mesh tunnels, and verifiable native compute", "quick_actions": "Quick Actions", "system_health": "Component Health", "gateway_telemetry": "Gateway Telemetry", "recent_activity": "Recent Activity", "act_chat": "Start Encrypted Chat", "act_files": "Open Secure File Vault", "act_forum": "Browse Latest Proposals", "act_apps": "Manage dCPM Packages", "act_network": "Inspect Shadow6 & ETP Mesh", "local_offline_alert": "⚠️ No local real node detected: Currently in local mode, but http://127.0.0.1:8185 is not responding. Local mode requires an actual running Ziokt node.", "remote_unauth_alert": "🔒 Remote node requires authentication: Active remote node does not have a valid Auth Token configured.", "switch_remote": "Switch to Remote Gateway", "config_auth": "Configure Auth Credentials", "probe_local": "Probe Local Node"}, "chat": {"title": "WATChat End-to-End Encrypted Messenger", "dual_ui": "UI Switcher", "ui_minimalist": "Modern Minimalist", "ui_classic": "Classic Rich", "ui_switch_tip": "Seamlessly switch between layouts; message history and cryptographic keys are synchronized without loss", "contacts": "Contacts / Dialogs", "new_conversation": "New Secure Chat", "enter_recipient": "Enter recipient DID or public key", "send": "Send", "input_placeholder": "Type encrypted message...", "attach_file": "Attach Vault File", "encryption_badge": "XChaCha20-Poly1305 Sealed", "empty_messages": "No messages yet. Send a greeting to start secure chatting.", "login_title": "WATChat Identity Sign In", "login_desc": "Choose your preferred UI style and unlock your end-to-end encrypted session", "login_btn": "Sign In & Enter Encrypted Chat", "username_placeholder": "Enter username or DID", "passphrase_placeholder": "Enter private key passphrase / session secret", "logout_btn": "Lock Session / Sign Out", "classic_telemetry": "Classic Mode Real-Time Security Signaling & Telemetry", "ratchet_status": "Double Ratchet: Ready", "cipher_info": "Cipher Suite: XChaCha20-Poly1305 / HKDF-SHA256", "onion_route": "Relay Router: ETP Onion 3-Hop Multi-Path"}, "forum": {"title": "Corium Decentralized Community Forum", "new_post": "New Post / Proposal", "post_title": "Title", "post_category": "Category", "post_content": "Content (Markdown supported)", "sign_and_publish": "Sign with Ed25519 & Publish", "cat_governance": "Governance", "cat_technical": "Technical", "cat_apps": "App Development", "cat_general": "General Discussion", "signature_verified": "Ed25519 On-Chain Signature Verified", "replies": "replies"}, "files": {"title": "UFS & SafeFS Secure Storage Vault", "vault_type": "Storage Driver", "vault_ufs": "UFS Native Storage", "vault_safefs": "SafeFS AEAD Encrypted Vault", "upload_file": "Upload File", "create_folder": "New Folder", "stealth_mode": "Deniable Volume (Outer Decoy / Inner Stealth)", "drop_tip": "Drag and drop files here for chunked persistent storage", "download": "Download File", "delete_confirm": "Are you sure you want to permanently delete this file? This cannot be undone."}, "apps": {"title": "dCPM Decentralized App Center", "subtitle": "Built on UFS and signed dCPM package architecture with dependency verification and sandbox isolation", "install_pkg": "Install / Import .dcpm Package", "installed_tab": "Installed Applications", "market_tab": "Ecosystem Repository", "rollback": "Rollback Version", "uninstall": "Uninstall", "update": "Check Updates", "publisher": "Publisher Key", "digest": "SHA-256 Digest", "dependencies": "Dependencies", "dep_check_ok": "All Dependencies Satisfied", "install_confirm": "Confirm installation of this signed package? It will execute inside an isolated sandbox.", "uninstall_confirm": "Confirm uninstallation of this package and its local cache?"}, "network": {"title": "Shadow6 & ETP Network Mesh", "subtitle": "Manage 13 language core Profile cluster, Virtual Broker, and onion routing paths", "profiles_title": "13 Core Language Profiles Cluster", "virtual_broker": "Virtual Broker Status", "s6p1_import": "Import Custom S6P1 Credential Envelope", "etp_title": "ETP Native Onion Multi-Hop Paths", "hops": "hop route path", "ping_test": "Latency Diagnostics", "privacy_masked": "Non-admin mode has automatically masked sensitive IPs and private keys", "node_topology": "Node & Gateway Topology", "local_node": "Local Node", "remote_nodes": "Remote Nodes Cluster", "manage_nodes": "Manage Custom Nodes"}, "identity": {"title": "Identity & Proof of Useful Work (PoUW)", "did": "Decentralized ID (DID)", "nns_domain": "NNS Bound Domain", "pouw_status": "PoUW Compute & Consensus Contribution", "engine_reward": "Governance Reward Weight", "apply_weight": "Apply for Validator Weight Whitelist", "export_keys": "Export Encrypted Backup", "switch_account": "Switch Identity"}, "devtools": {"title": "Native Component Developer Studio", "subtitle": "Fully functional GUIs for Corium, Tri, ZDA, TC-16 Virtual Machine, and MCP diagnostics", "tab_corium": "Corium Console", "tab_tri": "Tri Snapshots", "tab_zda": "ZDA / Ano Gate", "tab_tc16": "TC-16 VM Studio", "tab_mcp": "MCP Tool Catalog", "corium_query": "Query Ledger Facts & Blocks", "tri_run": "Execute Isolated Sandbox Snapshot", "zda_calc": "Verify Exact ZDA Evidence Arithmetic", "tc16_asm": "TC-16 Assembly & Bytecode Debugger", "tc16_run": "Run Virtual Machine", "tc16_step": "Step Execution", "tc16_reset": "Reset Registers"}, "settings": {"title": "System & Component Lifecycle Settings", "runtime_mode": "Client Runtime Mode", "local_gateway_url": "Gateway Endpoint", "components_lifecycle": "On-Demand Component Launcher", "comp_corium": "Corium Native Blockchain", "comp_shadow6": "Shadow6 Multi-Core Tunnel", "comp_ufs": "UFS & dCPM Storage Engine", "comp_watchat": "WATChat Federation Bridge", "comp_etp": "ETP Onion Gateway Router", "accessibility": "Accessibility & Keyboard Navigation", "keyboard_shortcuts": "Shortcuts: [1-9] Switch Modules, [Esc] Close Modals, [Ctrl+K] Global Search", "local_node_title": "Local Node Connection & Real Verification", "local_node_desc": "Using local node requires an actual Ziokt node daemon running locally. If not running, local RPC and write operations are blocked.", "local_node_probe": "Probe Local Node", "local_node_online": "Local Real Node Online", "local_node_offline": "No Local Real Node Detected", "local_node_checking": "Probing Local Node...", "local_node_help": "Start local node daemon: run 'systemctl start ziokt-gateway' or './tools/control_center.sh' in terminal.", "remote_nodes_title": "Remote Node Gateways & Auth Management", "remote_nodes_desc": "Using a remote node requires authentication (Auth Token). You can add custom remote nodes and test their connection and auth validity.", "add_node": "Add New Remote Node", "node_name": "Node Name", "node_url": "Node Endpoint (URL)", "auth_token": "Auth Token", "auth_token_tip": "Used for Bearer / X-Ziokt-Auth remote authentication", "test_auth": "Test Auth", "set_active": "Set Active", "active_badge": "Active", "auth_valid": "Auth Verified", "auth_invalid": "Auth Failed", "auth_required": "Auth Required", "delete_node": "Delete Node", "cannot_delete_default": "Default system node cannot be deleted", "add_node_btn": "Add & Verify Node"}}};

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
  updateAppNodeBadge();
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

// Probe Real Local Node Health
export async function checkLocalNodeHealth() {
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
export async function verifyRemoteNodeAuth(nodeId) {
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
export function isLocalNodeOffline() {
  return State.runtimeMode === 'local' && State.localNodeStatus === 'offline';
}

export function canUseWithoutLocalNode(tab) {return ['settings','ecosystem'].includes(tab);}

// Update Navigation Lock State for Non-Settings tabs
export function updateNavLockState() {
  const isOffline = isLocalNodeOffline();
  const isEn = State.language === 'en';

  document.querySelectorAll('.nav-item, .bottom-item').forEach(item => {
    const tab = item.dataset.tab;
    if (!canUseWithoutLocalNode(tab)) {
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
export function updateAppNodeBadge() {
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
export async function apiRequest(endpoint, options = {}) {
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
    // Mandate authentication for remote nodes when required (e.g. destructive writes or private APIs)
    const activeNode = getActiveRemoteNode();
    const token = activeNode?.authToken || State.authToken || getStorage('ziokt_auth_token');
    if (options.requireAuth && (!token || token.trim() === '')) {
      const msg = State.language === 'en'
        ? 'Remote node requires authentication credentials (Auth Token). Please configure a valid token in Settings.'
        : '使用该功能需要身份鉴权 (Auth Token)。请在“系统设置”中配置有效的访问凭证。';
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
export async function callTool(name, arguments_, {confirm = false, key = crypto.randomUUID(), requireAuth = false} = {}) {
  const result = await apiRequest('/api/gateway/tools/call', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name, arguments: arguments_, confirm, idempotency_key: key}),
    requireAuth: requireAuth || confirm
  });
  const text = (result.content || []).filter(c => c.type === 'text').map(c => c.text).join('\n');
  if (result.isError) throw new Error(text || 'Tool execution failed');
  if (result.structuredContent) return result.structuredContent;
  try { return JSON.parse(text); } catch (_) { return {text}; }
}

export async function sha256(bytes) {
  return 'sha256:' + Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), b => b.toString(16).padStart(2, '0')).join('');
}

export async function uploadObject(file, app, progress = () => {}) {
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

export async function renderToolPanel(container, title, filter, fileOperations = false) {
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
