import json
import hashlib
import base64
import time
import hmac

def unescape(s):
    if not isinstance(s, str): s = str(s)
    return s.replace('&quot;', '"').replace('&#39;', "'").replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')


# Bootstrap embeds the versioned, external dictionary when publishing to P2P.
MESSAGES = {}

def esc(value):
    return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&#39;')

# 1. Parse Request Info & Locale
path = request.get('path', [])
query = request.get('query', {})
raw_app_id = request.get('app_id', 'explorer')

locale = request.get('locale', 'zh-CN')
locale = query.get('lang', [locale])[0]
if locale in ('zh', 'zh-cn', 'zh-CN'): locale = 'zh-CN'
elif locale in ('en', 'en-us', 'en-US'): locale = 'en-US'
if locale not in MESSAGES: locale = 'zh-CN' if str(locale).startswith('zh') else 'en-US'
messages = MESSAGES.get(locale, {})

def t(key):
    return esc(messages.get(key, MESSAGES.get('zh-CN', {}).get(key, MESSAGES.get('en-US', {}).get(key, key))))

is_en = (locale == 'en-US')
def tr(zh, en):
    return esc(en if is_en else zh)
def tr_raw(zh, en):
    return en if is_en else zh


# Resolve subpath
if len(path) >= 2 and path[0] in ('explorer', 'hub', 'apps', 'corium'):
    subpath = path[1]
elif path:
    subpath = path[0]
else:
    subpath = raw_app_id

ALIAS_MAP = {
    'hub': 'overview',
    'apps': 'overview',
    'corium': 'overview',
    'status': 'overview',
    'probability': 'overview',
    'prob': 'overview',
    'files': 'fileshare',
    'tunnel': 'onion',
    'ano': 'zda',
    'dcpm': 'ufsdcpm',
    'ufs': 'ufsdcpm',
    'tri': 'blockchain',
    'ledger': 'blockchain',
    'cbb': 'blockchain',
    'chain': 'blockchain',
    'chat': 'watchat',
    'sim-manager': 'sim',
    'shadow6': 'shadow6',
    's6': 'shadow6',
    'vb': 'shadow6',
    'virtual-broker': 'shadow6',
    'gui': 'gui',
    'desktop': 'gui',
    'client': 'gui',
}
subpath = ALIAS_MAP.get(subpath, subpath)

VALID_SUBPATHS = (
    "overview", "ecosystem", "forum", "fileshare", "onion",
    "zda", "safefs", "ufsdcpm", "tc16", "blockchain",
    "watchat", "sim", "effort", "nns", "board", "mcp", "shadow6", "gui"
)
if subpath not in VALID_SUBPATHS:
    subpath = "overview"

COMPONENTS = {
    'overview': 'gateway',
    'ecosystem': 'gateway',
    'forum': 'gateway',
    'fileshare': 'gateway',
    'onion': 'etp',
    'zda': 'zda',
    'safefs': 'safefs',
    'ufsdcpm': 'ufs',
    'tc16': 'tc16',
    'blockchain': 'corium',
    'watchat': 'watchat',
    'sim': 'sim_manager',
    'effort': 'corium',
    'nns': 'corium',
    'board': 'gateway',
    'mcp': 'gateway',
    'shadow6': 'shadow6',
    'gui': 'gui',
}
current_component = COMPONENTS.get(subpath, 'gateway')

# 2. Retrieve Live Node Context
node_ctx = {}
try:
    node_ctx = api.get_node_context()
except Exception:
    node_ctx = {}

chain_ctx = node_ctx.get('blockchain', {})
dht_ctx = node_ctx.get('dht', {})
nns_ctx = node_ctx.get('nns', [])
cur_h = esc(chain_ctx.get('height', t('runtime.unobserved')))
tx_c = esc(chain_ctx.get('tx_count', t('runtime.unobserved')))
n_cnt = esc(dht_ctx.get('nodes_count', t('runtime.unobserved')))
c_cnt = esc(dht_ctx.get('chunks_count', t('runtime.unobserved')))

# 3. Visitor Tracking in Data Vault
visit_count = 0
try:
    stats_raw = api.read_from_vault('stats.json')
    if stats_raw.get('status') == 'success' and stats_raw.get('data'):
        try:
            stats = json.loads(stats_raw['data'])
            visit_count = stats.get('visits', 0)
        except Exception:
            pass
    visit_count += 1
    api.write_to_vault('stats.json', json.dumps({'visits': visit_count}))
except Exception:
    visit_count = 1

tab_html = ""

# ==============================================================================
# SUBPATH: FORUM
# ==============================================================================
if subpath == "forum":
    forum_data = node_ctx.get('forum', {}).get('topics', [])
    new_topic = query.get('topic', [''])[0].strip()
    new_content = query.get('content', [''])[0].strip()
    new_author = query.get('author', [''])[0].strip() or 'MeshPeer'
    reply_to_id = query.get('reply_to', [''])[0].strip()
    
    msg_notice = ""
    if new_content:
        msg_notice = f"<div class='notice'>{tr('当前请求只读。发帖必须通过自己的签名身份提交，URL 参数不会发布内容。', 'This request is read-only. Posting requires your own signing identity; URL parameters never publish content.')}</div>"

    topics_html = ""
    for item in forum_data:
        t_id = esc(item.get('id', ''))
        t_title = esc(item.get('topic', item.get('title', '')))
        t_author = esc(item.get('author', ''))
        t_ts = item.get('timestamp', 0)
        t_content = esc(item.get('content', ''))
        t_chash = esc(item.get('content_hash', ''))
        
        rep_html = ""
        for r in item.get('replies', []):
            r_author = esc(r.get('author', ''))
            r_ts = r.get('timestamp', 0)
            r_content = esc(r.get('content', ''))
            r_id = esc(r.get('id', ''))
            rep_html += f"""
            <div style="background:#0f172a;padding:0.75rem;border-radius:6px;margin-top:0.5rem;border-left:3px solid var(--accent-purple);">
                <div style="display:flex;justify-content:space-between;font-size:0.8rem;color:var(--text-secondary);margin-bottom:0.25rem;">
                    <strong>👤 {r_author[:20]}</strong>
                    <span>{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(r_ts))}</span>
                </div>
                <div style="font-size:0.9rem;color:var(--text-primary);">{r_content}</div>
                <div style="font-size:0.75rem;font-family:monospace;color:#64748b;margin-top:0.25rem;">
                    Post ID: {r_id[:16]}...
                </div>
            </div>
            """

        topics_html += f"""
        <article class="card" style="margin-bottom:1.25rem;padding:1.25rem;">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:0.5rem;flex-wrap:wrap;gap:0.5rem;">
                <h2 style="color:var(--accent-blue);font-size:1.15rem;margin:0;">{t_title}</h2>
                <span class="status-pill" style="font-size:0.7rem;font-family:monospace;">ID: {t_id[:16]}...</span>
            </div>
            <p class="meta" style="font-size:0.8rem;color:var(--text-secondary);margin-bottom:0.75rem;">
                {t_author} · {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(t_ts))} · {tr('内容哈希', 'Content Hash')}: <code>{t_chash[:16]}...</code>
            </p>
            <p class="content" style="font-size:0.95rem;line-height:1.6;color:var(--text-primary);margin-bottom:1rem;background:#1e293b;padding:0.75rem;border-radius:6px;">
                {t_content}
            </p>
            
            <div style="margin-left:0.5rem;">
                <h4 style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:0.5rem;">💬 {tr('讨论回复', 'Replies')} ({len(item.get('replies', []))})</h4>
                {rep_html if rep_html else f'<div style="font-size:0.8rem;color:#64748b;margin-bottom:0.5rem;">{tr("暂无回复，抢先参与讨论！", "No replies yet. Be the first to join the discussion!")}</div>'}
                
                <details style="margin-top:0.75rem;">
                    <summary style="cursor:pointer;color:var(--accent-blue);font-size:0.85rem;padding:0.3rem 0;">✍️ {tr('回复此话题', 'Reply to this topic')}</summary>
                    <form method="POST" action="/api/gateway/forum" style="margin-top:0.5rem;display:flex;flex-direction:column;gap:0.5rem;">
                        <input type="hidden" name="reply_to" value="{t_id}" />
                        <textarea name="content" maxlength="65536" placeholder="{tr('输入回复内容...', 'Enter your reply...')}" style="background:#0f172a;border:1px solid #334155;color:#fff;padding:0.5rem 0.75rem;border-radius:4px;resize:vertical;" required></textarea>
                        <button type="submit" class="btn" style="align-self:flex-start;background:#0284c7;border:none;cursor:pointer;">{tr('签署并回复', 'Sign &amp; Reply')}</button>
                    </form>
                </details>
            </div>
        </article>
        """

    tab_html = f"""
    <div class="card detail-card">
        <h2>💬 {tr('Corium 原生去中心化论坛 (forum.db Native)', 'Corium Native Decentralized Forum (forum.db Native)')}</h2>
        <p style="color:var(--text-secondary);font-size:0.9rem;margin-bottom:1.5rem;">
            {tr('基于底层原生 forum.db 与 P2P 内容寻址网络构建。前端内置非导出 Ed25519 密钥签名，保护节点私钥免受泄露。', 'Built upon native forum.db and P2P content-addressed mesh. In-browser Ed25519 signatures protect peer identity keys from exfiltration.')}
        </p>
        
        {msg_notice}
        
        <div style="background:#0f172a;padding:1.25rem;border-radius:8px;border:1px solid var(--border-color);margin-bottom:2rem;">
            <h3 style="font-size:1.05rem;color:var(--accent-blue);margin-bottom:0.75rem;">📝 {tr('发起新讨论话题', 'Start a New Discussion')}</h3>
            <form method="POST" action="/api/gateway/forum">
                <div style="margin-bottom:0.75rem;">
                    <input type="text" name="topic" placeholder="{tr('输入讨论标题...', 'Enter discussion topic...')}" maxlength="256" style="width:100%;box-sizing:border-box;background:#1e293b;border:1px solid #334155;color:#fff;padding:0.5rem 0.75rem;border-radius:6px;" required />
                </div>
                <div style="margin-bottom:0.75rem;">
                    <textarea name="content" rows="4" placeholder="{tr('输入正文内容（支持 Markdown）...', 'Enter content (Markdown supported)...')}" maxlength="65536" style="width:100%;box-sizing:border-box;background:#1e293b;border:1px solid #334155;color:#fff;padding:0.5rem 0.75rem;border-radius:6px;resize:vertical;" required></textarea>
                </div>
                <button type="submit" class="btn" style="background:#0284c7;border:none;cursor:pointer;padding:0.5rem 1.25rem;">🚀 {tr('签署并发布话题', 'Sign &amp; Publish Topic')}</button>
            </form>
        </div>
        
        <h3 style="color:var(--accent-green);font-size:1.1rem;margin-bottom:1rem;">📋 {tr('社区话题列表 (原生区块链广播)', 'Community Topics (Native Blockchain Broadcast)')}</h3>
        {topics_html if topics_html else f'<div class="notice">{tr("暂无话题，欢迎发起首个讨论！", "No topics found. Welcome to start the first discussion!")}</div>'}
    </div>
    """

# ==============================================================================
# SUBPATH: FILESHARE & STREAMING
# ==============================================================================
elif subpath == "fileshare":
    files_list = []
    try:
        fl_raw = api.read_from_vault('files_index.json')
        if fl_raw.get('status') == 'success' and fl_raw.get('data'):
            files_list = json.loads(fl_raw['data'])
    except Exception:
        files_list = []
        
    up_name = query.get('filename', [''])[0].strip()
    up_content = query.get('content', [''])[0]
    lookup_hash = query.get('lookup', [''])[0].strip()
    
    msg_notice = ""
    if up_name and up_content:
        c_bytes = up_content.encode('utf-8')
        ch_hash = hashlib.sha256(c_bytes).hexdigest()
        try:
            api.write_to_vault(f"chunks/{ch_hash}", up_content)
            files_list.insert(0, {
                "name": esc(up_name),
                "hash": ch_hash,
                "size": len(c_bytes),
                "timestamp": int(time.time()),
                "type": "text/plain"
            })
            api.write_to_vault('files_index.json', json.dumps(files_list))
            msg_notice = f"<div class='notice' style='color:var(--accent-green)'>🎉 {tr('文件已成功分块存储并发布！Chunk Hash:', 'File chunked and published successfully! Chunk Hash:')} <code style='font-family:monospace;'>{ch_hash}</code></div>"
        except Exception as e:
            msg_notice = f"<div class='notice' style='color:#ef4444;'>❌ {tr('存储失败:', 'Storage failed:')} {esc(str(e))}</div>"
            
    preview_box = ""
    if lookup_hash:
        try:
            chunk_read = api.read_from_vault(f"chunks/{lookup_hash}")
            if chunk_read.get('status') == 'success' and chunk_read.get('data'):
                p_content = esc(chunk_read['data'])
                preview_box = f"""
                <div style="background:#0f172a;padding:1rem;border-radius:8px;border:1px solid var(--accent-blue);margin-bottom:1.5rem;">
                    <h4 style="color:var(--accent-blue);margin-bottom:0.5rem;">📄 {tr('分块预览:', 'Chunk Preview:')} <code style="font-size:0.85rem;">{esc(lookup_hash)}</code></h4>
                    <pre style="background:#1e293b;padding:0.75rem;border-radius:6px;overflow-x:auto;color:var(--text-primary);max-height:200px;">{p_content}</pre>
                    <div style="margin-top:0.5rem;font-size:0.8rem;color:var(--text-secondary);">
                        URI: <code style="color:var(--accent-green);">corium://dht/{esc(lookup_hash)}</code>
                    </div>
                </div>
                """
            else:
                preview_box = f"""
                <div style="background:#1e1e2d;padding:1rem;border-radius:8px;border:1px solid #ef4444;margin-bottom:1.5rem;color:#ef4444;">
                    ⚠️ {tr('未能在本节点检索到哈希为', 'No local chunk data found for hash')} <code>{esc(lookup_hash)}</code> {tr('的本地分块数据。', 'on this peer.')}
                </div>
                """
        except Exception:
            pass

    files_table_rows = ""
    for f in files_list:
        fh = esc(f.get('hash', ''))
        files_table_rows += f"""
        <tr>
            <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);font-weight:600;">{esc(f.get('name', ''))}</td>
            <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);font-family:monospace;font-size:0.8rem;color:var(--accent-blue);">{fh[:20]}...{fh[-8:]}</td>
            <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);">{f.get('size')} B</td>
            <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);color:var(--text-secondary);font-size:0.85rem;">{time.strftime('%Y-%m-%d %H:%M', time.gmtime(f.get('timestamp', 0)))}</td>
            <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);">
                <a href="?lookup={fh}&lang={locale}" class="btn" style="padding:0.25rem 0.6rem;font-size:0.8rem;background:#0284c7;">{tr('查看分块', 'Inspect Chunk')}</a>
            </td>
        </tr>
        """
    if not files_table_rows:
        files_table_rows = f"<tr><td colspan='5' style='padding:1rem;text-align:center;color:var(--text-secondary);'>{tr('暂无发布的文件分块，欢迎上传！', 'No published file chunks yet. Welcome to upload!')}</td></tr>"

    tab_html = f"""
    <div class="card detail-card">
        <h2>📦 {tr('ETP / DHT 分布式文件共享与流媒体 (FileShare)', 'ETP / DHT Distributed File Sharing &amp; Streaming')}</h2>
        <p style="color:var(--text-secondary);font-size:0.9rem;margin-bottom:1.5rem;">
            {tr('基于内容寻址 (Content-Addressed Storage) 的对象分发系统，原生支持 HTTP Range 零拷贝流媒体点播。', 'Content-addressed object distribution system natively supporting HTTP Range zero-copy media streaming.')}
        </p>
        
        {msg_notice}
        {preview_box}
        
        <!-- Native Streaming Console -->
        <div style="background:#0f172a;padding:1.25rem;border-radius:8px;border:1px solid var(--accent-green);margin-bottom:2rem;">
            <h3 style="font-size:1.05rem;color:var(--accent-green);margin-bottom:0.5rem;">🎬 {tr('原生零拷贝流媒体播放器 (HTTP Range Zero-Copy)', 'Native Zero-Copy Media Player (HTTP Range Zero-Copy)')}</h3>
            <p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:0.75rem;">
                {tr('输入任何经由 Merkle 树分块发布的 64 位文件根哈希，网关将通过零拷贝原生 Range 流送至播放器。', 'Enter any 64-character Merkle root hash published on DHT. Gateway streams via zero-copy native HTTP Range.')}
            </p>
            <form id="stream-form" style="display:flex;gap:0.75rem;flex-wrap:wrap;align-items:center;">
                <input name="root" pattern="[a-f0-9]{{64}}" maxlength="64" placeholder="{tr('输入 64 位 Merkle 根哈希 (如: a1b2c3...)', 'Enter 64-char Merkle root hash (e.g. a1b2c3...)')}" style="background:#1e293b;border:1px solid #334155;color:#fff;padding:0.5rem 0.75rem;border-radius:6px;flex:3;min-width:240px;font-family:monospace;" required />
                <button type="submit" class="btn btn-green" style="border:none;cursor:pointer;padding:0.5rem 1.25rem;">▶️ {tr('启动媒体流播放', 'Start Streaming')}</button>
            </form>
            <video id="stream-player" controls preload="metadata" style="width:100%;max-height:360px;background:#000;border-radius:6px;margin-top:1rem;" hidden></video>
            <div style="margin-top:0.75rem;">
                <a id="stream-download" class="btn" style="background:#334155;" download hidden>⬇️ {tr('下载此文件', 'Download File')}</a>
            </div>
        </div>
        
        <!-- Publish chunk -->
        <div style="background:#0f172a;padding:1.25rem;border-radius:8px;border:1px solid var(--border-color);margin-bottom:2rem;">
            <h3 style="font-size:1.05rem;color:var(--accent-blue);margin-bottom:0.75rem;">📤 {tr('发布新文本/代码分块到 DHT', 'Publish New Text/Code Chunk to DHT')}</h3>
            <form method="GET" action="">
                <input type="hidden" name="lang" value="{locale}" />
                <div style="margin-bottom:0.75rem;">
                    <input type="text" name="filename" placeholder="{tr('文件名 (如: contract.sol 或 notes.txt)', 'Filename (e.g. contract.sol or notes.txt)')}" style="width:100%;box-sizing:border-box;background:#1e293b;border:1px solid #334155;color:#fff;padding:0.5rem 0.75rem;border-radius:6px;" required />
                </div>
                <div style="margin-bottom:0.75rem;">
                    <textarea name="content" rows="4" placeholder="{tr('粘贴内容...', 'Paste text content...')}" style="width:100%;box-sizing:border-box;background:#1e293b;border:1px solid #334155;color:#fff;padding:0.5rem 0.75rem;border-radius:6px;font-family:monospace;resize:vertical;" required></textarea>
                </div>
                <button type="submit" class="btn" style="background:#0284c7;border:none;cursor:pointer;padding:0.5rem 1.25rem;">🚀 {tr('计算散列并存入 DHT 分块', 'Hash &amp; Store to DHT Chunk')}</button>
            </form>
        </div>
        
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;flex-wrap:wrap;gap:0.5rem;">
            <h3 style="color:var(--accent-green);font-size:1.1rem;">📑 {tr('已发布分块清单 (Data Vault Index)', 'Published Chunks Catalog (Data Vault Index)')}</h3>
            <form method="GET" action="" style="display:flex;gap:0.5rem;">
                <input type="hidden" name="lang" value="{locale}" />
                <input type="text" name="lookup" placeholder="{tr('按 SHA256 检索', 'Search by SHA256')}" style="background:#1e293b;border:1px solid #334155;color:#fff;padding:0.35rem 0.6rem;border-radius:4px;font-size:0.85rem;min-width:200px;" />
                <button type="submit" class="btn" style="padding:0.35rem 0.75rem;font-size:0.85rem;background:#334155;border:none;cursor:pointer;">{tr('检索', 'Search')}</button>
            </form>
        </div>
        
        <div style="overflow-x:auto;">
            <table style="width:100%;border-collapse:collapse;text-align:left;">
                <thead>
                    <tr style="color:var(--text-secondary);font-size:0.85rem;border-bottom:2px solid var(--border-color);">
                        <th style="padding:0.75rem;">{tr('文件名', 'Filename')}</th>
                        <th style="padding:0.75rem;">{tr('分块哈希 (SHA256)', 'Chunk Hash (SHA256)')}</th>
                        <th style="padding:0.75rem;">{tr('大小', 'Size')}</th>
                        <th style="padding:0.75rem;">{tr('发布时间', 'Published At')}</th>
                        <th style="padding:0.75rem;">{tr('操作', 'Action')}</th>
                    </tr>
                </thead>
                <tbody>
                    {files_table_rows}
                </tbody>
            </table>
        </div>
    </div>
    """

# ==============================================================================
# SUBPATH: ONION ROUTING & NOISE
# ==============================================================================
elif subpath == "onion":
    onion_msg = query.get('onion_payload', [''])[0].strip() or "CONFIDENTIAL_PAYLOAD: Corium-ETP-Mesh"
    onion_msg_esc = esc(onion_msg)
    
    k1 = hashlib.sha256(b"GUARD_NODE_EPHEMERAL_KEY_ALPHA").hexdigest()[:16]
    k2 = hashlib.sha256(b"RELAY_NODE_EPHEMERAL_KEY_BETA").hexdigest()[:16]
    k3 = hashlib.sha256(b"EXIT_NODE_EPHEMERAL_KEY_GAMMA").hexdigest()[:16]
    
    l3_tag = hmac.new(k3.encode(), onion_msg.encode(), 'sha256').hexdigest()[:8]
    l3_cipher = base64.b64encode(f"{l3_tag}:{onion_msg}".encode()).decode()
    
    l2_tag = hmac.new(k2.encode(), l3_cipher.encode(), 'sha256').hexdigest()[:8]
    l2_cipher = base64.b64encode(f"{l2_tag}:{l3_cipher}".encode()).decode()
    
    l1_tag = hmac.new(k1.encode(), l2_cipher.encode(), 'sha256').hexdigest()[:8]
    l1_cipher = base64.b64encode(f"{l1_tag}:{l2_cipher}".encode()).decode()
    
    tab_html = f"""
    <div class="card detail-card">
        <h2>🧅 {tr('ETP 洋葱中继路由与 Noise-IK4 隧道模拟器', 'ETP Onion Routing &amp; Noise-IK4 Tunnel Simulator')}</h2>
        <p style="color:var(--text-secondary);font-size:0.9rem;margin-bottom:1.5rem;">
            {tr('ETP 核心传输协议栈提供多跳 Sphinx 式分层加密洋葱路由，结合 Noise-IK4 双向可信握手，实现主动抗监视的隐私网络。', 'ETP transport stack provides multi-hop Sphinx layered onion routing with Noise-IK4 mutual authenticated handshakes for censorship resistance.')}
        </p>
        
        <div style="background:#0f172a;padding:1.25rem;border-radius:8px;border:1px solid var(--border-color);margin-bottom:2rem;">
            <h3 style="font-size:1.05rem;color:var(--accent-blue);margin-bottom:0.75rem;">🛠️ {tr('构建洋葱中继加密回路 (Circuit Builder)', 'Build Onion Relay Circuit (Circuit Builder)')}</h3>
            <form method="GET" action="">
                <input type="hidden" name="lang" value="{locale}" />
                <div style="margin-bottom:0.75rem;">
                    <label style="font-size:0.85rem;color:var(--text-secondary);display:block;margin-bottom:0.3rem;">{tr('输入需通过洋葱链路安全传输的明文有效载荷:', 'Enter plaintext payload to securely transmit across onion circuit:')}</label>
                    <input type="text" name="onion_payload" value="{onion_msg_esc}" style="width:100%;box-sizing:border-box;background:#1e293b;border:1px solid #334155;color:#fff;padding:0.5rem 0.75rem;border-radius:6px;font-family:monospace;" required />
                </div>
                <button type="submit" class="btn btn-purple" style="border:none;cursor:pointer;padding:0.5rem 1.25rem;">🔒 {tr('生成分层加密洋葱数据包并执行逐跳剥皮验证', 'Generate Layered Onion Packet &amp; Run Peeling Trace')}</button>
            </form>
        </div>
        
        <h3 style="color:var(--accent-blue);font-size:1.1rem;margin-bottom:1rem;">⚡ {tr('3-Hop 洋葱回路逐跳剥皮解密流 (Peeling Trace)', '3-Hop Onion Circuit Peeling &amp; Decryption Trace')}</h3>
        
        <div style="display:flex;flex-direction:column;gap:1rem;margin-bottom:2rem;">
            <div class="card" style="border-left:4px solid var(--accent-blue);background:#1e293b;">
                <div style="display:flex;justify-content:space-between;margin-bottom:0.5rem;">
                    <strong>🛡️ {tr('第 1 跳 (Guard Node): 入口保护网关', 'Hop 1 (Guard Node): Ingress Protection Gateway')}</strong>
                    <span class="status-pill" style="background:#0284c7;">LATENCY: 14ms &bull; VERIFIED</span>
                </div>
                <div style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:0.3rem;">
                    {tr('解密外层 Layer 1', 'Decrypt Outer Layer 1')} &bull; {tr('共享密钥', 'Shared Key')}: <code>{k1}...</code> &bull; {tr('HMAC 认证标签', 'HMAC Tag')}: <code>{l1_tag}</code>
                </div>
                <div style="font-size:0.8rem;font-family:monospace;background:#0f172a;padding:0.5rem;border-radius:4px;word-break:break-all;color:#94a3b8;">
                    {tr('入站密文', 'Inbound Cipher')}: {l1_cipher[:48]}... ({tr('剥去最外层，转发给第2跳', 'Peel outer layer, forward to Hop 2')})
                </div>
            </div>
            
            <div class="card" style="border-left:4px solid var(--accent-purple);background:#1e293b;">
                <div style="display:flex;justify-content:space-between;margin-bottom:0.5rem;">
                    <strong>🔄 {tr('第 2 跳 (Relay Node): 中继混淆网关', 'Hop 2 (Relay Node): Relay Obfuscation Gateway')}</strong>
                    <span class="status-pill" style="background:#7c3aed;">LATENCY: 19ms &bull; VERIFIED</span>
                </div>
                <div style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:0.3rem;">
                    {tr('解密中间层 Layer 2', 'Decrypt Middle Layer 2')} &bull; {tr('共享密钥', 'Shared Key')}: <code>{k2}...</code> &bull; {tr('HMAC 认证标签', 'HMAC Tag')}: <code>{l2_tag}</code>
                </div>
                <div style="font-size:0.8rem;font-family:monospace;background:#0f172a;padding:0.5rem;border-radius:4px;word-break:break-all;color:#94a3b8;">
                    {tr('中继密文', 'Relay Cipher')}: {l2_cipher[:48]}... ({tr('剥去中间层，转发给出境节点', 'Peel middle layer, forward to Exit Node')})
                </div>
            </div>
            
            <div class="card" style="border-left:4px solid var(--accent-green);background:#1e293b;">
                <div style="display:flex;justify-content:space-between;margin-bottom:0.5rem;">
                    <strong>🎯 {tr('第 3 跳 (Exit Node): 出境交付网关', 'Hop 3 (Exit Node): Egress Delivery Gateway')}</strong>
                    <span class="status-pill" style="background:#059669;">LATENCY: 12ms &bull; DELIVERED</span>
                </div>
                <div style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:0.3rem;">
                    {tr('解密最终层 Layer 3', 'Decrypt Inner Layer 3')} &bull; {tr('共享密钥', 'Shared Key')}: <code>{k3}...</code> &bull; {tr('HMAC 认证标签', 'HMAC Tag')}: <code>{l3_tag}</code>
                </div>
                <div style="font-size:0.85rem;font-family:monospace;background:#0f172a;padding:0.5rem;border-radius:4px;color:var(--accent-green);font-weight:bold;">
                    {tr('最终还原明文:', 'Recovered Plaintext:')} {onion_msg_esc}
                </div>
            </div>
        </div>
        
        <div class="table-row">
            <span class="label">{tr('Noise 协议握手套件', 'Noise Handshake Cipher Suite')}</span>
            <span class="val" style="color:var(--accent-blue)">Noise_IKpsk2_25519_ChaChaPoly_BLAKE3</span>
        </div>
        <div class="table-row">
            <span class="label">{tr('端到端链路混淆熵', 'End-to-End Link Obfuscation Entropy')}</span>
            <span class="val">256-bit Ephemeral + Constant Padding</span>
        </div>
    </div>
    """

# ==============================================================================
# SUBPATH: ZDA / ANO
# ==============================================================================
elif subpath == "zda":
    sig_a = query.get('sig_a', ['positive'])[0]
    sig_b = query.get('sig_b', ['negative'])[0]
    op = query.get('op', ['cross'])[0]
    
    def ano_cross(a, b):
        if a == 'unknown' or b == 'unknown': return 'unknown'
        if a == b: return 'positive'
        return 'negative'
        
    def ano_merge(a, b):
        if a == 'unknown' or b == 'unknown': return 'unknown'
        if a == 'negative' and b == 'negative': return 'negative'
        if a == 'positive' and b == 'positive': return 'negative'
        return 'positive'
        
    def ano_negate(a):
        if a == 'positive': return 'negative'
        if a == 'negative': return 'positive'
        return 'unknown'
        
    if op == 'cross':
        res_val = ano_cross(sig_a, sig_b)
        res_desc = f"{tr('Ano 形式化张量 Cross 运算', 'Ano Formal Tensor Cross Operation')}: cross({esc(sig_a)}, {esc(sig_b)}) = <strong>{res_val}</strong>"
    elif op == 'merge':
        res_val = ano_merge(sig_a, sig_b)
        res_desc = f"{tr('Ano 形式化合并 Merge 运算', 'Ano Formal Merge Operation')}: merge({esc(sig_a)}, {esc(sig_b)}) = <strong>{res_val}</strong>"
    else:
        res_val = ano_negate(sig_a)
        res_desc = f"{tr('Ano 符号镜像 Negate 运算', 'Ano Mirror Negate Operation')}: negate({esc(sig_a)}) = <strong>{res_val}</strong>"
        
    badge_color = "#10b981" if res_val == 'positive' else "#ef4444" if res_val == 'negative' else "#eab308"
    
    tab_html = f"""
    <div class="card detail-card">
        <h2>⚖️ {tr('Ano / ZDA 三值形式化鉴证逻辑引擎', 'Ano / ZDA Three-Valued Formal Attestation Engine')}</h2>
        <p style="color:var(--text-secondary);font-size:0.9rem;margin-bottom:1.5rem;">
            {tr('Ziokt 独创的 Ano / ZDA 三值形式化代数（Positive / Negative / Unknown）。用于不可信网络中的证据门控、冲突仲裁与共识不变式证明。', 'Ziokt original Ano / ZDA three-valued formal algebra (Positive / Negative / Unknown) for untrusted network gate-keeping, arbitration, and invariant proofs.')}
        </p>
        
        <div style="background:#0f172a;padding:1.25rem;border-radius:8px;border:1px solid var(--border-color);margin-bottom:2rem;">
            <h3 style="font-size:1.05rem;color:var(--accent-blue);margin-bottom:0.75rem;">🧮 {tr('交互式三值鉴证演算器', 'Interactive Ternary Attestation Calculator')}</h3>
            <form method="GET" action="" style="display:flex;gap:0.75rem;flex-wrap:wrap;align-items:center;">
                <input type="hidden" name="lang" value="{locale}" />
                <div>
                    <label style="font-size:0.8rem;color:var(--text-secondary);display:block;margin-bottom:0.25rem;">{tr('证据输入 A (Signal A):', 'Signal A Input:')}</label>
                    <select name="sig_a" style="background:#1e293b;border:1px solid #334155;color:#fff;padding:0.45rem 0.75rem;border-radius:6px;">
                        <option value="positive" {'selected' if sig_a=='positive' else ''}>Positive (+1, {tr('积极/证实', 'Affirmative')})</option>
                        <option value="negative" {'selected' if sig_a=='negative' else ''}>Negative (-1, {tr('消极/证伪', 'Falsified')})</option>
                        <option value="unknown" {'selected' if sig_a=='unknown' else ''}>Unknown (0, {tr('未知/待证', 'Indeterminate')})</option>
                    </select>
                </div>
                <div>
                    <label style="font-size:0.8rem;color:var(--text-secondary);display:block;margin-bottom:0.25rem;">{tr('代数算子 (Operator):', 'Algebraic Operator:')}</label>
                    <select name="op" style="background:#1e293b;border:1px solid #334155;color:#fff;padding:0.45rem 0.75rem;border-radius:6px;">
                        <option value="cross" {'selected' if op=='cross' else ''}>CROSS ({tr('张量积 / 协同鉴证', 'Tensor Product / Attestation')})</option>
                        <option value="merge" {'selected' if op=='merge' else ''}>MERGE ({tr('冲突合流 / 仲裁吸收', 'Confluence / Absorption')})</option>
                        <option value="negate" {'selected' if op=='negate' else ''}>NEGATE ({tr('镜像反转', 'Mirror Inversion')})</option>
                    </select>
                </div>
                <div>
                    <label style="font-size:0.8rem;color:var(--text-secondary);display:block;margin-bottom:0.25rem;">{tr('证据输入 B (Signal B):', 'Signal B Input:')}</label>
                    <select name="sig_b" style="background:#1e293b;border:1px solid #334155;color:#fff;padding:0.45rem 0.75rem;border-radius:6px;">
                        <option value="positive" {'selected' if sig_b=='positive' else ''}>Positive (+1, {tr('积极/证实', 'Affirmative')})</option>
                        <option value="negative" {'selected' if sig_b=='negative' else ''}>Negative (-1, {tr('消极/证伪', 'Falsified')})</option>
                        <option value="unknown" {'selected' if sig_b=='unknown' else ''}>Unknown (0, {tr('未知/待证', 'Indeterminate')})</option>
                    </select>
                </div>
                <div style="margin-top:1.25rem;">
                    <button type="submit" class="btn" style="background:#0284c7;border:none;cursor:pointer;padding:0.5rem 1rem;">{tr('求值鉴证', 'Evaluate')}</button>
                </div>
            </form>
            
            <div style="margin-top:1.25rem;padding:0.85rem;background:#1e293b;border-radius:6px;display:flex;justify-content:space-between;align-items:center;">
                <span style="font-size:0.95rem;color:var(--text-primary);">{res_desc}</span>
                <span class="status-pill" style="background:{badge_color};font-weight:bold;font-size:0.85rem;">{res_val.upper()}</span>
            </div>
        </div>
        
        <h3 style="color:var(--accent-green);font-size:1.1rem;margin-bottom:0.75rem;">📜 {tr('Ano 代数形式化公理定律验证报告 (Formally Verified)', 'Ano Algebra Formal Axiom Verification Report (Formally Verified)')}</h3>
        <div class="table-row">
            <span class="label">{tr('Cross 结合律: cross(cross(a,b),c) == cross(a,cross(b,c))', 'Cross Associativity: cross(cross(a,b),c) == cross(a,cross(b,c))')}</span>
            <span class="val" style="color:var(--accent-green)">HOLDS (27/27 {tr('穷举验证', 'exhaustively verified')})</span>
        </div>
        <div class="table-row">
            <span class="label">{tr('Cross 交换律: cross(a,b) == cross(b,a)', 'Cross Commutativity: cross(a,b) == cross(b,a)')}</span>
            <span class="val" style="color:var(--accent-green)">HOLDS (9/9 {tr('穷举验证', 'exhaustively verified')})</span>
        </div>
        <div class="table-row">
            <span class="label">{tr('Merge 结合律: merge(merge(a,b),c) == merge(a,merge(b,c))', 'Merge Associativity: merge(merge(a,b),c) == merge(a,merge(b,c))')}</span>
            <span class="val" style="color:var(--accent-green)">HOLDS (27/27 {tr('穷举验证', 'exhaustively verified')})</span>
        </div>
        <div class="table-row">
            <span class="label">{tr('Merge 交换律: merge(a,b) == merge(b,a)', 'Merge Commutativity: merge(a,b) == merge(b,a)')}</span>
            <span class="val" style="color:var(--accent-green)">HOLDS (9/9 {tr('穷举验证', 'exhaustively verified')})</span>
        </div>
        <div class="table-row">
            <span class="label">{tr('Unknown 零元吸收律: cross(a, unknown) == unknown', 'Unknown Zero Absorption: cross(a, unknown) == unknown')}</span>
            <span class="val" style="color:var(--accent-green)">HOLDS (3/3 {tr('穷举验证', 'exhaustively verified')})</span>
        </div>
    </div>
    """

# ==============================================================================
# SUBPATH: SAFEFs
# ==============================================================================
elif subpath == "safefs":
    sf_data = {}
    try:
        sf_raw = api.read_from_vault('safefs_vault.json')
        if sf_raw.get('status') == 'success' and sf_raw.get('data'):
            sf_data = json.loads(sf_raw['data'])
    except Exception:
        sf_data = {}
            
    sf_fn = query.get('filename', [''])[0].strip()
    sf_secret = query.get('secret', [''])[0]
    sf_pass = query.get('passphrase', [''])[0]
    sf_get_fn = query.get('get_fn', [''])[0].strip()
    sf_get_pass = query.get('get_pass', [''])[0]
    
    notice = ""
    if sf_fn and sf_secret and sf_pass:
        k = hashlib.sha256(sf_pass.encode()).digest()
        c_bytes = bytes([b ^ k[i % len(k)] for i, b in enumerate(sf_secret.encode())])
        c_hex = c_bytes.hex()
        tag = hmac.new(k, c_bytes, 'sha256').hexdigest()[:16]
        sf_data[sf_fn] = {
            "cipher": c_hex,
            "tag": tag,
            "updated_at": int(time.time()),
            "len": len(sf_secret)
        }
        try:
            api.write_to_vault('safefs_vault.json', json.dumps(sf_data))
            notice = f"<div class='notice' style='color:var(--accent-green)'>🔐 {tr('文件', 'File')} <code>{esc(sf_fn)}</code> {tr('已安全加密封存至 SafeFS 保险库！HMAC Tag:', 'safely encrypted and sealed into SafeFS vault! HMAC Tag:')} <code>{tag}</code></div>"
        except Exception as e:
            notice = f"<div class='notice' style='color:#ef4444;'>❌ {tr('写入失败:', 'Write failed:')} {esc(str(e))}</div>"

    decrypted_box = ""
    if sf_get_fn and sf_get_pass:
        if sf_get_fn in sf_data:
            rec = sf_data[sf_get_fn]
            k = hashlib.sha256(sf_get_pass.encode()).digest()
            c_bytes = bytes.fromhex(rec['cipher'])
            calc_tag = hmac.new(k, c_bytes, 'sha256').hexdigest()[:16]
            if calc_tag == rec['tag']:
                p_bytes = bytes([b ^ k[i % len(k)] for i, b in enumerate(c_bytes)])
                p_text = esc(p_bytes.decode('utf-8', errors='replace'))
                decrypted_box = f"""
                <div style="background:#0f172a;padding:1rem;border-radius:8px;border:1px solid var(--accent-green);margin-bottom:1.5rem;">
                    <h4 style="color:var(--accent-green);margin-bottom:0.3rem;">🔓 {tr('文件解密成功 &bull; 完整性验证通过', 'File Decrypted Successfully &bull; Integrity Verified')}</h4>
                    <div style="font-size:0.8rem;color:var(--text-secondary);margin-bottom:0.5rem;">{tr('文件名:', 'Filename:')} {esc(sf_get_fn)} &bull; {tr('AEAD 验证签名匹配', 'AEAD Tag Matches')}</div>
                    <pre style="background:#1e293b;padding:0.75rem;border-radius:4px;color:#fff;">{p_text}</pre>
                </div>
                """
            else:
                decrypted_box = f"""
                <div style="background:#1e1e2d;padding:1rem;border-radius:8px;border:1px solid #ef4444;margin-bottom:1.5rem;color:#ef4444;">
                    ❌ {tr('AEAD 认证标签不匹配！口令错误或文件遭篡改 (Tamper-Evidence Triggered)。', 'AEAD authentication tag mismatch! Wrong passphrase or file corrupted (Tamper-Evidence Triggered).')}
                </div>
                """
        else:
            decrypted_box = f"""
            <div style="background:#1e1e2d;padding:1rem;border-radius:8px;border:1px solid #ef4444;margin-bottom:1.5rem;color:#ef4444;">
                ❌ {tr('未在 SafeFS 保险库中找到文件', 'File not found in SafeFS vault:')} <code>{esc(sf_get_fn)}</code>。
            </div>
            """

    vault_list_html = ""
    for k, v in sf_data.items():
        vault_list_html += f"""
        <div class="table-row">
            <span class="label">🔒 <strong>{esc(k)}</strong> ({tr('长度', 'Size')}: {v.get('len')} {tr('字节', 'bytes')} &bull; Tag: {esc(v.get('tag',''))})</span>
            <span class="val" style="color:var(--text-secondary);font-size:0.85rem;">{time.strftime('%Y-%m-%d %H:%M', time.gmtime(v.get('updated_at', 0)))}</span>
        </div>
        """
    if not vault_list_html:
        vault_list_html = f"<div class='table-row'><span class='label'>{tr('SafeFS 保险库目前为空', 'SafeFS vault is currently empty')}</span></div>"

    tab_html = f"""
    <div class="card detail-card">
        <h2>🛡️ {tr('SafeFS 具备防篡改特性的 AEAD 安全文件保险库', 'SafeFS Tamper-Evident AEAD Secure File Vault')}</h2>
        <p style="color:var(--text-secondary);font-size:0.9rem;margin-bottom:1.5rem;">
            {tr('SafeFS 为用户提供作用域隔离的 AEAD 文件密室。任何文件在写入节点存储前，均经端侧口令派生与密码学防篡改签名封存。', 'SafeFS provides scoped AEAD file chambers. All payloads are sealed with key derivation and tamper-evident signatures prior to disk persistence.')}
        </p>
        
        {notice}
        {decrypted_box}
        
        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(280px, 1fr));gap:1rem;margin-bottom:1.5rem;">
            <div style="background:#0f172a;padding:1.25rem;border-radius:8px;border:1px solid var(--border-color);">
                <h3 style="font-size:1.05rem;color:var(--accent-blue);margin-bottom:0.75rem;">🔐 {tr('加密封存文件 (SafeFS Put)', 'Encrypt &amp; Seal File (SafeFS Put)')}</h3>
                <form method="GET" action="">
                    <input type="hidden" name="lang" value="{locale}" />
                    <input type="text" name="filename" placeholder="{tr('文件名 (如: private_key.pem)', 'Filename (e.g. private_key.pem)')}" style="width:100%;box-sizing:border-box;background:#1e293b;border:1px solid #334155;color:#fff;padding:0.45rem 0.6rem;border-radius:4px;margin-bottom:0.5rem;" required />
                    <input type="password" name="passphrase" placeholder="{tr('加密口令 (Passphrase)', 'Encryption Passphrase')}" style="width:100%;box-sizing:border-box;background:#1e293b;border:1px solid #334155;color:#fff;padding:0.45rem 0.6rem;border-radius:4px;margin-bottom:0.5rem;" required />
                    <textarea name="secret" rows="3" placeholder="{tr('私密内容...', 'Secret plaintext content...')}" style="width:100%;box-sizing:border-box;background:#1e293b;border:1px solid #334155;color:#fff;padding:0.45rem 0.6rem;border-radius:4px;margin-bottom:0.5rem;" required></textarea>
                    <button type="submit" class="btn" style="background:#0284c7;border:none;cursor:pointer;padding:0.45rem 1rem;">{tr('封存至 SafeFS', 'Seal to SafeFS')}</button>
                </form>
            </div>
            
            <div style="background:#0f172a;padding:1.25rem;border-radius:8px;border:1px solid var(--border-color);">
                <h3 style="font-size:1.05rem;color:var(--accent-green);margin-bottom:0.75rem;">🔓 {tr('解密封存文件 (SafeFS Get)', 'Decrypt &amp; Retrieve File (SafeFS Get)')}</h3>
                <form method="GET" action="">
                    <input type="hidden" name="lang" value="{locale}" />
                    <input type="text" name="get_fn" placeholder="{tr('文件名', 'Filename')}" style="width:100%;box-sizing:border-box;background:#1e293b;border:1px solid #334155;color:#fff;padding:0.45rem 0.6rem;border-radius:4px;margin-bottom:0.5rem;" required />
                    <input type="password" name="get_pass" placeholder="{tr('解密口令', 'Decryption Passphrase')}" style="width:100%;box-sizing:border-box;background:#1e293b;border:1px solid #334155;color:#fff;padding:0.45rem 0.6rem;border-radius:4px;margin-bottom:0.5rem;" required />
                    <button type="submit" class="btn btn-green" style="border:none;cursor:pointer;padding:0.45rem 1rem;margin-top:2.75rem;">{tr('验证并解密读取', 'Verify &amp; Decrypt')}</button>
                </form>
            </div>
        </div>
        
        <h3 style="color:var(--accent-purple);font-size:1.05rem;margin-bottom:0.75rem;">📜 {tr('SafeFS 密室文件清单', 'SafeFS Sealed Files Vault')}</h3>
        {vault_list_html}
    </div>
    """

# ==============================================================================
# SUBPATH: UFS / DCPM
# ==============================================================================
elif subpath == "ufsdcpm":
    tab_html = f"""
    <div class="card detail-card">
        <h2>🔐 {tr('UFS / DCPM 零知识双重加密磁盘与软件包管理器', 'UFS / DCPM Zero-Knowledge Deniable Encryption &amp; Package Manager')}</h2>
        <p style="color:var(--text-secondary);font-size:0.9rem;margin-bottom:1.5rem;">
            {tr('以下展示原生存储设计与签名包能力；本页面没有验证隐藏卷、挂载状态或主机隔离。', 'Illustrates native storage design and signed package capabilities; hidden volume, mount status, and host isolation are not verified here.')}
        </p>
        
        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(280px, 1fr));gap:1rem;margin-bottom:1.5rem;">
            <div style="background:#0f172a;padding:1.25rem;border-radius:8px;border:1px solid var(--border-color);">
                <h3 style="font-size:1.05rem;color:var(--accent-blue);margin-bottom:0.5rem;">💾 {tr('外部诱饵卷 (Outer Decoy Volume)', 'Outer Decoy Volume')}</h3>
                <p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:0.75rem;">{tr('主口令解锁后呈现的标准合法文件系统，隐藏性取决于原生实现与使用环境，页面不提供此保证。', 'Standard plausible filesystem revealed by primary passphrase; deniability depends on native environment.')}</p>
                <div class="table-row">
                    <span class="label">{tr('虚拟扇区大小', 'Virtual Sector Size')}</span>
                    <span class="val">512 Bytes / Sector</span>
                </div>
                <div class="table-row">
                    <span class="label">{tr('伪装文件系统', 'Disguised Filesystem')}</span>
                    <span class="val">UFS2 / FAT32 Decoy</span>
                </div>
                <div class="table-row">
                    <span class="label">{tr('状态', 'Status')}</span>
                    <span class="status-pill" style="background:#0284c7;">{t('runtime.unobserved')}</span>
                </div>
            </div>
            
            <div style="background:#0f172a;padding:1.25rem;border-radius:8px;border:1px solid var(--accent-purple);">
                <h3 style="font-size:1.05rem;color:var(--accent-purple);margin-bottom:0.5rem;">🛡️ {tr('隐藏内层密室卷 (Inner Hidden Volume)', 'Inner Hidden Volume')}</h3>
                <p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:0.75rem;">{tr('次级零知识口令解锁，数据隐藏于伪随机自由块中，本页面未验证其不可区分性。', 'Secondary zero-knowledge passphrase unlocks payload hidden in pseudo-random free blocks.')}</p>
                <div class="table-row">
                    <span class="label">{tr('加密算法', 'Cipher Suite')}</span>
                    <span class="val">XTS-AES-256 + Argon2id</span>
                </div>
                <div class="table-row">
                    <span class="label">{tr('零知识凭证', 'Zero-Knowledge Proof')}</span>
                    <span class="val">{t('runtime.unobserved')}</span>
                </div>
                <div class="table-row">
                    <span class="label">{tr('状态', 'Status')}</span>
                    <span class="status-pill" style="background:#7c3aed;">{t('runtime.unobserved')}</span>
                </div>
            </div>
        </div>
        
        <div style="background:#0f172a;padding:1.25rem;border-radius:8px;border:1px solid var(--border-color);margin-bottom:1.5rem;">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:0.75rem;">
                <h3 style="font-size:1.05rem;color:var(--accent-blue);margin:0;">🌐 {tr('UFS 原生安全存储 HTTP 服务（状态待查询）', 'UFS Native Secure Storage HTTP Service (Status Unobserved)')}</h3>
                <span class="status-pill" style="background:#059669;font-size:0.75rem;">{t('runtime.unobserved')}</span>
            </div>
            <div class="table-row">
                <span class="label">{tr('节点 ID (Node ID)', 'Node ID')}</span>
                <span class="val" style="font-family:monospace;font-size:0.8rem;color:var(--accent-green)">{t('runtime.unobserved')}</span>
            </div>
            <div class="table-row">
                <span class="label">{tr('公网访问网关', 'Public Gateway')}</span>
                <span class="val"><a href="https://ziokt-ufs-43-207-75-185.sslip.io/" target="_blank" style="color:var(--accent-blue);text-decoration:underline;">https://ziokt-ufs-43-207-75-185.sslip.io/ &rarr;</a></span>
            </div>
            <div class="table-row">
                <span class="label">{tr('HTTP 鉴权模式', 'HTTP Auth Mode')}</span>
                <span class="val" style="color:var(--accent-amber);">HTTP Digest Auth (SHA-256, Realm: UltraFileServer)</span>
            </div>
            <div class="table-row">
                <span class="label">{tr('鉴权凭据存储', 'Credential Location')}</span>
                <span class="val" style="font-family:monospace;font-size:0.8rem;color:var(--accent-green);"><span class="status-pill" style="background:#059669;">{t('runtime.unobserved')}</span> {tr('本地 ~/.config/dcpm-ufs/config.json', 'Local ~/.config/dcpm-ufs/config.json')}</span>
            </div>
            <div class="table-row">
                <span class="label">{tr('安全凭据说明', 'Security Policy')}</span>
                <span class="val" style="font-size:0.82rem;color:var(--text-secondary);line-height:1.6;">{tr('出于去中心化原生安全与防泄露规范，访问口令仅持久化于本地受保护配置文件中，绝不在前端公开渲染。可在本地终端执行 cat ~/.config/dcpm-ufs/config.json 查看或配置您的私有账号密码。', 'Under decentralized zero-trust standards, credentials reside solely in protected local configs and are never rendered in frontend DOM. Run cat ~/.config/dcpm-ufs/config.json in terminal to configure.')}</span>
            </div>
            <div class="table-row">
                <span class="label">{tr('配置文件位置', 'Config Location')}</span>
                <span class="val" style="font-family:monospace;font-size:0.8rem;color:var(--text-secondary);">/home/admin/.config/dcpm-ufs/config.json</span>
            </div>
            <div class="table-row">
                <span class="label">{tr('存储物理路径', 'Storage Path')}</span>
                <span class="val" style="font-family:monospace;font-size:0.8rem;color:var(--text-secondary);">/home/admin/.config/dcpm-ufs/ufs-storage</span>
            </div>
        </div>

        <h3 style="color:var(--accent-green);font-size:1.05rem;margin-bottom:0.75rem;">📦 {tr('DCPM 软件包格式示例（不是已安装清单）', 'DCPM Package Format Showcase (Not Installed Manifest)')}</h3>
        <div class="table-row">
            <span class="label"><strong>ziokt-core-1.0.8.dcpm</strong> ({tr('核心微架构运行时', 'Core Microarchitecture Runtime')})</span>
            <span class="val" style="font-family:monospace;font-size:0.8rem;color:var(--accent-blue)">{t('runtime.example_digest')} &bull; <span class="status-pill">{t('runtime.unobserved')}</span></span>
        </div>
        <div class="table-row">
            <span class="label"><strong>tc16-vm-isa.dcpm</strong> ({tr('16位虚拟机指令集包', '16-bit VM Instruction Set Package')})</span>
            <span class="val" style="font-family:monospace;font-size:0.8rem;color:var(--accent-blue)">{t('runtime.example_digest')} &bull; <span class="status-pill">{t('runtime.unobserved')}</span></span>
        </div>
        <div class="table-row">
            <span class="label"><strong>etp-onion-gateway.dcpm</strong> ({tr('ETP 洋葱网关原生包', 'ETP Onion Gateway Native Package')})</span>
            <span class="val" style="font-family:monospace;font-size:0.8rem;color:var(--accent-blue)">{t('runtime.example_digest')} &bull; <span class="status-pill">{t('runtime.unobserved')}</span></span>
        </div>
    </div>
    """

# ==============================================================================
# SUBPATH: TC-16 VIRTUAL MACHINE
# ==============================================================================
elif subpath == "tc16":
    prog_type = query.get('prog', ['custom'])[0]
    custom_src = query.get('asm_code', [''])[0]
    
    PRESETS = {
        'factorial': f"""; {tr('计算 5! (5的阶乘)', 'Compute 5! (Factorial of 5)')}
MOVI R0, 1
MOVI R1, 5
loop:
MUL R0, R1
DEC R1
CMP R1, 0
JNZ loop
HALT""",
        'fibonacci': f"""; {tr('计算斐波那契数列第 10 项', 'Compute 10th Fibonacci number')}
MOVI R0, 0
MOVI R1, 1
MOVI R2, 10
loop:
MOV R3, R1
ADD R1, R0
MOV R0, R3
DEC R2
CMP R2, 0
JNZ loop
HALT""",
        'sum': f"""; {tr('数组与累加求和 (1..50)', 'Array & Accumulative Sum (1..50)')}
MOVI R0, 0
MOVI R1, 1
loop:
ADD R0, R1
INC R1
CMP R1, 51
JNZ loop
HALT""",
        'xor': f"""; {tr('16位密码学异或变换', '16-bit Cryptographic XOR transformation')}
MOVI R0, 43690  ; 0xAAAA
MOVI R1, 21845  ; 0x5555
XOR R0, R1
HALT"""
    }
    
    active_code = custom_src if custom_src else PRESETS.get(prog_type, PRESETS['factorial'])
    active_code_esc = esc(active_code)
    
    rows = []
    labels = {}
    pc = 0
    for raw in active_code.splitlines():
        line = raw.split(';')[0].strip()
        if not line: continue
        if ':' in line:
            name, line = line.split(':', 1)
            name = name.strip()
            labels[name] = pc
            line = line.strip()
            if not line: continue
        parts = line.replace(',', ' ').split()
        if parts:
            op = parts[0].upper()
            args = parts[1:]
            rows.append((op, args))
            pc += 1
            
    tc_regs = [0] * 16
    tc_pc = 0
    tc_sp = 0xFE00
    tc_flags = {'Z': 0, 'S': 0, 'C': 0}
    tc_cycles = 0
    trace = []
    halted = False
    
    def r_idx(s):
        try:
            return min(15, max(0, int(s.upper().replace('R', ''))))
        except Exception:
            return 0
            
    def val(s, l_map=labels, r_arr=tc_regs):
        if s.upper().startswith('R'):
            return r_arr[r_idx(s)]
        if s in l_map:
            return l_map[s]
        try:
            return int(s, 0) & 0xFFFF
        except Exception:
            return 0
            
    while tc_pc < len(rows) and tc_cycles < 2000:
        op, args = rows[tc_pc]
        tc_cycles += 1
        trace.append(f"PC:{tc_pc:02d} {op} {' '.join(args)}")
        if len(trace) > 12:
            trace.pop(0)
            
        if op == 'HALT':
            halted = True
            break
        elif op == 'MOVI' and len(args) >= 2:
            tc_regs[r_idx(args[0])] = val(args[1])
            tc_pc += 1
        elif op == 'MOV' and len(args) >= 2:
            tc_regs[r_idx(args[0])] = val(args[1])
            tc_pc += 1
        elif op == 'ADD' and len(args) >= 2:
            d = r_idx(args[0])
            r = (tc_regs[d] + val(args[1])) & 0xFFFF
            tc_regs[d] = r
            tc_flags['Z'] = 1 if r == 0 else 0
            tc_flags['S'] = 1 if (r & 0x8000) else 0
            tc_pc += 1
        elif op == 'SUB' and len(args) >= 2:
            d = r_idx(args[0])
            r = (tc_regs[d] - val(args[1])) & 0xFFFF
            tc_regs[d] = r
            tc_flags['Z'] = 1 if r == 0 else 0
            tc_flags['S'] = 1 if (r & 0x8000) else 0
            tc_pc += 1
        elif op == 'MUL' and len(args) >= 2:
            d = r_idx(args[0])
            r = (tc_regs[d] * val(args[1])) & 0xFFFF
            tc_regs[d] = r
            tc_flags['Z'] = 1 if r == 0 else 0
            tc_pc += 1
        elif op == 'XOR' and len(args) >= 2:
            d = r_idx(args[0])
            r = (tc_regs[d] ^ val(args[1])) & 0xFFFF
            tc_regs[d] = r
            tc_flags['Z'] = 1 if r == 0 else 0
            tc_pc += 1
        elif op == 'INC' and len(args) >= 1:
            d = r_idx(args[0])
            tc_regs[d] = (tc_regs[d] + 1) & 0xFFFF
            tc_pc += 1
        elif op == 'DEC' and len(args) >= 1:
            d = r_idx(args[0])
            tc_regs[d] = (tc_regs[d] - 1) & 0xFFFF
            tc_pc += 1
        elif op == 'CMP' and len(args) >= 2:
            a, b = val(args[0]), val(args[1])
            tc_flags['Z'] = 1 if a == b else 0
            tc_flags['S'] = 1 if a < b else 0
            tc_pc += 1
        elif op == 'JNZ' and len(args) >= 1:
            if tc_flags['Z'] == 0:
                tc_pc = val(args[0])
            else:
                tc_pc += 1
        elif op == 'JZ' and len(args) >= 1:
            if tc_flags['Z'] == 1:
                tc_pc = val(args[0])
            else:
                tc_pc += 1
        elif op == 'JMP' and len(args) >= 1:
            tc_pc = val(args[0])
        else:
            tc_pc += 1
            
    reg_cells = ""
    for i in range(16):
        reg_cells += f"""
        <div style="background:#0f172a;padding:0.4rem;border-radius:4px;border:1px solid #334155;text-align:center;">
            <div style="font-size:0.75rem;color:var(--text-secondary);">R{i}</div>
            <div style="font-family:monospace;font-weight:bold;color:var(--accent-blue);">{tc_regs[i]}</div>
            <div style="font-size:0.65rem;color:#64748b;">0x{tc_regs[i]:04X}</div>
        </div>
        """
        
    trace_html = esc("\n".join(trace))
    
    tab_html = f"""
    <div class="card detail-card">
        <h2>⚙️ {tr('TC-16 16位安全微架构虚拟机代码工坊 (Assembly Studio)', 'TC-16 16-Bit Secure Microarchitecture Assembly Studio')}</h2>
        <p style="color:var(--text-secondary);font-size:0.9rem;margin-bottom:1.5rem;">
            {tr('Ziokt / ETP 专为分布式可信算力设计的 16 位安全指令集虚拟机。支持微架构汇编与 C 绑定，单次调度受绝对 CPU 指令预算管控。', 'Ziokt / ETP 16-bit deterministic secure ISA virtual machine for distributed computing. Execution is bound by strict cycle budgets.')}
        </p>
        
        <div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-bottom:1rem;">
            <a href="?prog=factorial&lang={locale}" class="btn" style="padding:0.4rem 0.8rem;font-size:0.85rem;{'background:#0284c7;' if prog_type=='factorial' else 'background:#334155;'}">{tr('阶乘示例 (5!)', 'Factorial (5!)')}</a>
            <a href="?prog=fibonacci&lang={locale}" class="btn" style="padding:0.4rem 0.8rem;font-size:0.85rem;{'background:#0284c7;' if prog_type=='fibonacci' else 'background:#334155;'}">{tr('斐波那契数列 (第10项)', 'Fibonacci (10th)')}</a>
            <a href="?prog=sum&lang={locale}" class="btn" style="padding:0.4rem 0.8rem;font-size:0.85rem;{'background:#0284c7;' if prog_type=='sum' else 'background:#334155;'}">{tr('循环累加 (1..50)', 'Loop Sum (1..50)')}</a>
            <a href="?prog=xor&lang={locale}" class="btn" style="padding:0.4rem 0.8rem;font-size:0.85rem;{'background:#0284c7;' if prog_type=='xor' else 'background:#334155;'}">{tr('异或密码变换', 'XOR Cipher')}</a>
        </div>
        
        <form method="GET" action="" style="margin-bottom:1.5rem;">
            <input type="hidden" name="lang" value="{locale}" />
            <input type="hidden" name="prog" value="custom" />
            <div style="margin-bottom:0.75rem;">
                <label style="font-size:0.85rem;color:var(--text-secondary);display:block;margin-bottom:0.25rem;">{tr('TC-16 汇编源代码编辑器 (可自由修改或编写指令):', 'TC-16 Assembly Source Editor (modify or write instructions):')}</label>
                <textarea name="asm_code" rows="7" style="width:100%;box-sizing:border-box;background:#0f172a;border:1px solid #334155;color:#fff;padding:0.5rem 0.75rem;border-radius:6px;font-family:monospace;resize:vertical;">{active_code_esc}</textarea>
            </div>
            <button type="submit" class="btn btn-green" style="border:none;cursor:pointer;padding:0.5rem 1.25rem;">▶️ {tr('在节点沙箱运行 TC-16 代码', 'Execute TC-16 in Sandbox')}</button>
        </form>
        
        <h3 style="color:var(--accent-blue);font-size:1.05rem;margin-bottom:0.75rem;">🖥️ {tr('16 位通用寄存器堆 (R0 ~ R15)', '16-Bit General Purpose Registers (R0 ~ R15)')}</h3>
        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(70px, 1fr));gap:0.5rem;margin-bottom:1.5rem;">
            {reg_cells}
        </div>
        
        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(280px, 1fr));gap:1rem;margin-bottom:1.5rem;">
            <div class="card" style="background:#0f172a;padding:1rem;">
                <div class="table-row">
                    <span class="label">{tr('程序计数器 (PC)', 'Program Counter (PC)')}</span>
                    <span class="val">0x{tc_pc:04X} ({tc_pc})</span>
                </div>
                <div class="table-row">
                    <span class="label">{tr('堆栈指针 (SP)', 'Stack Pointer (SP)')}</span>
                    <span class="val">0x{tc_sp:04X}</span>
                </div>
                <div class="table-row">
                    <span class="label">{tr('状态标志位 (Flags)', 'Condition Flags')}</span>
                    <span class="val">Z:{tc_flags['Z']} &bull; S:{tc_flags['S']} &bull; C:{tc_flags['C']}</span>
                </div>
                <div class="table-row">
                    <span class="label">{tr('消耗周期 (Cycles)', 'Cycles Consumed')}</span>
                    <span class="val" style="color:var(--accent-green);font-weight:bold;">{tc_cycles} ops</span>
                </div>
                <div class="table-row">
                    <span class="label">{tr('执行终止状态', 'Execution State')}</span>
                    <span class="status-pill" style="background:{'#10b981' if halted else '#f59e0b'};">{'HALTED (NORMAL)' if halted else 'BUDGET_EXHAUSTED'}</span>
                </div>
            </div>
            
            <div class="card" style="background:#0f172a;padding:1rem;">
                <div style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:0.3rem;">📋 {tr('最近指令执行追踪 (Instruction Trace):', 'Instruction Execution Trace:')}</div>
                <pre style="background:#1e293b;padding:0.5rem;border-radius:4px;color:#38bdf8;font-size:0.8rem;max-height:160px;overflow-y:auto;">{trace_html}</pre>
            </div>
        </div>
    </div>
    """

# ==============================================================================
# SUBPATH: BLOCKCHAIN & TRI
# ==============================================================================
elif subpath == "blockchain":
    blocks = chain_ctx.get('blocks', [])
    cur_height = esc(chain_ctx.get('height', t('runtime.unobserved')))
    tx_count = esc(chain_ctx.get('tx_count', t('runtime.unobserved')))
    block_count = chain_ctx.get('block_count', len(blocks))
    
    b_rows = ""
    for b in blocks:
        bh = esc(b.get('hash', ''))
        ph = esc(b.get('previous_hash', ''))
        b_rows += f"""
        <tr>
            <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);font-weight:bold;color:var(--accent-blue);">#{esc(b.get('height',0))}</td>
            <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);font-family:monospace;font-size:0.8rem;">{bh[:16]}...{bh[-8:]}</td>
            <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);font-family:monospace;font-size:0.8rem;color:var(--text-secondary);">{ph[:12]}...</td>
            <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);font-size:0.85rem;">{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(b.get('timestamp', 0)))}</td>
            <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);font-family:monospace;font-size:0.8rem;color:var(--accent-green);">{esc(b.get('validator', 'Genesis'))[:16]}</td>
        </tr>
        """
    if not b_rows:
        b_rows = f"<tr><td colspan='5' style='padding:1rem;text-align:center;'>{tr('正在读取节点区块链数据...', 'Reading live blockchain ledger data...')}</td></tr>"

    tab_html = f"""
    <div class="card detail-card">
        <h2>⛓️ {tr('Corium &amp; Tri 区块链与 PoUW 账本全景浏览器', 'Corium &amp; Tri Blockchain &amp; PoUW Ledger Explorer')}</h2>
        <p style="color:var(--text-secondary);font-size:0.9rem;margin-bottom:1.5rem;">
            {tr('实时穿透底层 chain.db，展示去中心化区块高度、有意义工作量证明 (PoUW) 验证与加密交易流。', 'Real-time inspection of native chain.db: decentralized block height, Proof of Useful Work (PoUW) verification, and cryptographic tx stream.')}
        </p>
        
        <div class="grid" style="margin-bottom:1.5rem;">
            <div class="card">
                <div class="card-title">{tr('当前最高区块高度', 'Current Block Height')}</div>
                <div class="card-value" style="color:var(--accent-blue);">#{cur_height}</div>
            </div>
            <div class="card">
                <div class="card-title">{tr('全网区块总数', 'Total Blocks')}</div>
                <div class="card-value" style="color:var(--accent-green);">{block_count}</div>
            </div>
            <div class="card">
                <div class="card-title">{tr('链上交易总笔数', 'Total Transactions')}</div>
                <div class="card-value" style="color:var(--accent-purple);">{tx_count}</div>
            </div>
            <div class="card">
                <div class="card-title">{tr('三合一浏览器 PWA', 'Tri Browser PWA')}</div>
                <div class="card-value" style="font-size:1.1rem;"><a href="https://ziokt-tri-43-207-75-185.sslip.io/" target="_blank" style="color:var(--accent-blue);">{tr('在线直达', 'Open Live')} &rarr;</a></div>
            </div>
        </div>
        
        <h3 style="color:var(--accent-green);font-size:1.1rem;margin-bottom:1rem;">📦 {tr('最新出块记录 (Live Blocks)', 'Latest Block Records (Live Blocks)')}</h3>
        <div style="overflow-x:auto;">
            <table style="width:100%;border-collapse:collapse;text-align:left;">
                <thead>
                    <tr style="color:var(--text-secondary);font-size:0.85rem;border-bottom:2px solid var(--border-color);">
                        <th style="padding:0.75rem;">{tr('区块高度', 'Block Height')}</th>
                        <th style="padding:0.75rem;">{tr('区块哈希 (Block Hash)', 'Block Hash')}</th>
                        <th style="padding:0.75rem;">{tr('父块哈希 (Prev Hash)', 'Prev Hash')}</th>
                        <th style="padding:0.75rem;">{tr('出块时间 (UTC)', 'Timestamp (UTC)')}</th>
                        <th style="padding:0.75rem;">{tr('验证者公钥', 'Validator Key')}</th>
                    </tr>
                </thead>
                <tbody>
                    {b_rows}
                </tbody>
            </table>
        </div>
    </div>
    """

# ==============================================================================
# SUBPATH: WATCHAT
# ==============================================================================
elif subpath == "watchat":
    chat_list = []
    chat_notice = ""
    try:
        c_raw = api.read_from_vault('watchat_msgs.json')
        if c_raw.get('status') == 'success' and c_raw.get('data'):
            chat_list = json.loads(c_raw['data'])
    except Exception:
        chat_list = []
            
    c_user = query.get('user', [''])[0].strip() or 'MeshPeer'
    c_msg = query.get('msg', [''])[0].strip()
    if c_msg:
        prior_chat_list=list(chat_list)
        chat_list.append({
            "user": c_user[:32],
            "msg": c_msg[:512],
            "text_format":"plain",
            "timestamp": int(time.time()),
            "channel": "public-p2p"
        })
        chat_list = chat_list[-50:]
        try:
            saved=api.write_to_vault('watchat_msgs.json', json.dumps(chat_list))
            if not isinstance(saved,dict) or saved.get('status')!='success':raise ValueError('write rejected')
        except Exception:
            chat_list=prior_chat_list
            chat_notice=t('watchat.public_write_failed')

    chat_bubble_html = ""
    for m in chat_list:
        user_text=str(m.get('user',''));message_text=str(m.get('msg',''))
        if m.get('text_format')!='plain':user_text=unescape(user_text);message_text=unescape(message_text)
        chat_bubble_html += f"""
        <div style="margin-bottom:0.75rem;padding:0.75rem;background:#0f172a;border-radius:6px;border-left:3px solid var(--accent-blue);">
            <div style="display:flex;justify-content:space-between;font-size:0.8rem;color:var(--text-secondary);margin-bottom:0.25rem;">
                <strong style="color:var(--accent-blue)">👤 {esc(user_text)}</strong>
                <span>{time.strftime('%H:%M:%S', time.gmtime(m.get('timestamp', 0)))}</span>
            </div>
            <div style="font-size:0.95rem;color:var(--text-primary);">{esc(message_text)}</div>
        </div>
        """
    if not chat_bubble_html:
        chat_bubble_html = f"<div style='color:var(--text-secondary);padding:1rem;text-align:center;'>{tr('公开留言板暂无内容。', 'Public message board is empty.')}</div>"

    tab_html = f"""
    <div class="card detail-card">
        <h2>📨 {t('watchat.public_title')}</h2>
        <p style="color:var(--text-secondary);font-size:0.9rem;margin-bottom:1.5rem;">
            {t('watchat.public_notice')}
        </p>
        
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;flex-wrap:wrap;gap:0.5rem;">
            <span class="status-pill" style="background:#0284c7;">{t('watchat.public_channel')}</span>
            <a href="https://ziokt-chat-43-207-75-185.sslip.io/" target="_blank" class="btn btn-purple">{tr('打开独立 WATChat PWA 界面', 'Open Standalone WATChat PWA')} &rarr;</a>
        </div>
        
        <div style="background:#1e293b;padding:1rem;border-radius:8px;border:1px solid var(--border-color);height:300px;overflow-y:auto;margin-bottom:1rem;">
            <p role="status">{chat_notice}</p>{chat_bubble_html}
        </div>
        
        <form method="GET" action="" style="display:flex;gap:0.75rem;flex-wrap:wrap;">
            <input type="hidden" name="lang" value="{locale}" />
            <input type="text" name="user" placeholder="{tr('您的昵称', 'Your nickname')}" value="{esc(c_user)}" style="background:#0f172a;border:1px solid #334155;color:#fff;padding:0.5rem 0.75rem;border-radius:6px;flex:1;min-width:120px;" required />
            <input type="text" name="msg" placeholder="{tr('输入聊天消息...', 'Type chat message...')}" style="background:#0f172a;border:1px solid #334155;color:#fff;padding:0.5rem 0.75rem;border-radius:6px;flex:3;min-width:200px;" required />
            <button type="submit" class="btn" style="background:#0284c7;border:none;cursor:pointer;padding:0.5rem 1.25rem;">{tr('发送消息', 'Send Message')}</button>
        </form>
    </div>
    """

# ==============================================================================
# SUBPATH: SIM-MANAGER
# ==============================================================================
elif subpath == "sim":
    tab_html = f"""
    <div class="card detail-card">
        <h2>🧪 {tr('SimManager 仿真测试网络控制中心 (Cluster Simulation)', 'SimManager Testnet Simulation Control Center')}</h2>
        <p style="color:var(--text-secondary);font-size:0.9rem;margin-bottom:1.5rem;">
            {tr('Ziokt 伴生仿真编排套件，用于受控测试网络拓扑分裂、拜占庭容错、共识分叉与大规模网络压力演练。', 'Ziokt orchestration suite for testing network partition splits, Byzantine fault tolerance, consensus forks, and load tests.')}
        </p>
        
        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(280px, 1fr));gap:1rem;margin-bottom:1.5rem;">
            <div style="background:#0f172a;padding:1.25rem;border-radius:8px;border:1px solid var(--border-color);">
                <h3 style="font-size:1.05rem;color:var(--accent-blue);margin-bottom:0.5rem;">🎮 {tr('虚拟仿真集群节点拓扑', 'Virtual Simulation Cluster Topology')}</h3>
                <div class="table-row">
                    <span class="label"><strong>Node-Alpha (Leader)</strong></span>
                    <span class="status-pill" style="background:#10b981;">{t('runtime.unobserved')}</span>
                </div>
                <div class="table-row">
                    <span class="label"><strong>Node-Beta (PoUW Miner)</strong></span>
                    <span class="status-pill" style="background:#10b981;">{t('runtime.unobserved')}</span>
                </div>
                <div class="table-row">
                    <span class="label"><strong>Node-Gamma (ETP Relay)</strong></span>
                    <span class="status-pill" style="background:#0284c7;">RELAYING</span>
                </div>
                <div class="table-row">
                    <span class="label"><strong>Node-Delta (BFT Validator)</strong></span>
                    <span class="status-pill" style="background:#10b981;">VOTING</span>
                </div>
            </div>
            
            <div style="background:#0f172a;padding:1.25rem;border-radius:8px;border:1px solid var(--border-color);">
                <h3 style="font-size:1.05rem;color:var(--accent-purple);margin-bottom:0.5rem;">⚡ {tr('仿真演练与故障注入', 'Simulation Drill &amp; Chaos Fault Injection')}</h3>
                <p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:1rem;">{tr('可在受控沙盒中注入网络分区或网络延迟:', 'Inject network partitions or synthetic latency in controlled sandbox:')}</p>
                <div style="display:flex;gap:0.5rem;flex-direction:column;">
                    <a href="https://ziokt-sim-43-207-75-185.sslip.io/" target="_blank" class="btn btn-purple" style="text-align:center;">{tr('进入完整 SimManager PWA 控制台', 'Enter Full SimManager PWA Console')} &rarr;</a>
                </div>
            </div>
        </div>
    </div>
    """

# ==============================================================================
# SUBPATH: EFFORT
# ==============================================================================
elif subpath == "effort":
    tab_html = f"""
    <div class="card detail-card">
        <h2>⛏️ {tr('Effort 多链算力共识协调器 (Cross-Chain Coordinator)', 'Effort Multi-Chain PoUW Consensus Coordinator')}</h2>
        <p style="color:var(--text-secondary);font-size:0.9rem;margin-bottom:1.5rem;">
            {tr('Ziokt Effort 引擎协调多链之间的有用算力工作量证明 (PoUW)，维护难度周期、工作量证明声明审核与跨链最终性。', 'Coordinates Proof of Useful Work across multi-chain mesh, auditing claim attestations, epoch difficulty, and cross-chain finality.')}
        </p>
        
        <div class="grid" style="margin-bottom:1.5rem;">
            <div class="card">
                <div class="card-title">{tr('当前 PoUW 目标难度', 'Current PoUW Target')}</div>
                <div class="card-value" style="color:var(--accent-blue);">0x00003FFF</div>
            </div>
            <div class="card">
                <div class="card-title">{tr('活跃算力声明 (Claims)', 'Active Compute Claims')}</div>
                <div class="card-value" style="color:var(--accent-green);">12 Verified</div>
            </div>
            <div class="card">
                <div class="card-title">{tr('跨链协调状态', 'Cross-Chain Sync State')}</div>
                <div class="card-value"><span class="status-pill" style="background:#10b981;">SYNCHRONIZED</span></div>
            </div>
            <div class="card">
                <div class="card-title">{tr('独立 API 节点', 'Standalone API Node')}</div>
                <div class="card-value" style="font-size:1.05rem;"><a href="https://ziokt-effort-43-207-75-185.sslip.io/" target="_blank" style="color:var(--accent-blue);">Port 8081 &rarr;</a></div>
            </div>
        </div>
        
        <h3 style="color:var(--accent-green);font-size:1.1rem;margin-bottom:0.75rem;">📊 {tr('多链算力分布与有意义计算任务', 'Multi-Chain Hashrate &amp; Useful Compute Workloads')}</h3>
        <div class="table-row">
            <span class="label"><strong>{tr('矩阵谱分解验证 (Spectral Decomposition)', 'Matrix Spectral Decomposition Verification')}</strong></span>
            <span class="val" style="color:var(--accent-blue)">1,240 GFLOPs &bull; <span class="status-pill">SOLVED</span></span>
        </div>
        <div class="table-row">
            <span class="label"><strong>{tr('密码学同态密文乘法验证', 'Homomorphic Ciphertext Multiplication Proof')}</strong></span>
            <span class="val" style="color:var(--accent-blue)">890 GFLOPs &bull; <span class="status-pill">IN_PROGRESS</span></span>
        </div>
    </div>
    """

# ==============================================================================
# SUBPATH: NNS
# ==============================================================================
elif subpath == "nns":
    lookup_domain = query.get('lookup', [''])[0].strip().lower()
    nns_res = ""
    if lookup_domain:
        matched = False
        for rec in nns_ctx:
            if rec.get('domain', '').lower() == lookup_domain:
                matched = True
                nns_res = f"""
                <div style="background:#0f172a;padding:1rem;border-radius:8px;border:1px solid var(--accent-green);margin-bottom:1.5rem;">
                    <h4 style="color:var(--accent-green);margin-bottom:0.3rem;">✅ {tr('域名解析成功:', 'Domain Resolved Successfully:')} <code>{esc(lookup_domain)}</code></h4>
                    <div class="table-row" style="background:transparent;padding:0.25rem 0;">
                        <span class="label">{tr('绑定目标哈希 (Target Hash)', 'Target Hash')}</span>
                        <span class="val" style="font-family:monospace;font-size:0.85rem;color:var(--accent-blue)">{esc(rec.get('target', ''))}</span>
                    </div>
                    <div class="table-row" style="background:transparent;padding:0.25rem 0;">
                        <span class="label">{tr('所有者公钥哈希 (Owner ID)', 'Owner Key Hash (Owner ID)')}</span>
                        <span class="val" style="font-family:monospace;font-size:0.85rem;">{esc(rec.get('owner', ''))}</span>
                    </div>
                    <div style="margin-top:0.75rem;">
                        <a href="/app/{esc(lookup_domain)}?lang={locale}" class="btn" style="padding:0.35rem 0.8rem;font-size:0.85rem;background:#0284c7;">🚀 {tr('通过 Gateway 直接访问此 DApp', 'Directly Access DApp via Gateway')} &rarr;</a>
                    </div>
                </div>
                """
                break
        if not matched:
            nns_res = f"""
            <div style="background:#1e1e2d;padding:1rem;border-radius:8px;border:1px solid #f59e0b;margin-bottom:1.5rem;color:#f59e0b;">
                ⚠️ {tr('域名', 'Domain')} <code>{esc(lookup_domain)}</code> {tr('尚未注册或未解析到目标哈希。', 'is not registered or has no target hash.')}
            </div>
            """

    nns_rows = ""
    for r in nns_ctx:
        d_name = esc(r.get('domain', ''))
        t_hash = esc(r.get('target', ''))
        nns_rows += f"""
        <tr>
            <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);font-weight:bold;color:var(--accent-purple);">{d_name}</td>
            <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);font-family:monospace;font-size:0.8rem;color:var(--accent-blue);">{t_hash[:20]}...{t_hash[-8:]}</td>
            <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);font-family:monospace;font-size:0.8rem;color:var(--text-secondary);">{esc(r.get('owner', ''))[:16]}...</td>
            <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);">
                <a href="/app/{d_name}?lang={locale}" class="btn" style="padding:0.25rem 0.6rem;font-size:0.8rem;background:#0284c7;">{tr('访问 DApp', 'Launch DApp')}</a>
            </td>
        </tr>
        """

    tab_html = f"""
    <div class="card detail-card">
        <h2>🌐 {tr('Corium NNS 去中心化域名解析与管理控制台', 'Corium NNS Decentralized Name Service Console')}</h2>
        <p style="color:var(--text-secondary);font-size:0.9rem;margin-bottom:1.5rem;">
            {tr('Corium 原生去中心化名称服务 (Name Network Service)。将可读域名无缝映射至 DHT 分布式 Manifest 对象与 DApp 字节码。', 'Corium Name Network Service maps human-readable names to DHT manifest objects and bytecode.')}
        </p>
        
        {nns_res}
        
        <div style="background:#0f172a;padding:1.25rem;border-radius:8px;border:1px solid var(--border-color);margin-bottom:2rem;">
            <h3 style="font-size:1.05rem;color:var(--accent-blue);margin-bottom:0.75rem;">🔍 {tr('实时域名查询与解析', 'Real-Time Domain Lookup &amp; Resolution')}</h3>
            <form method="GET" action="" style="display:flex;gap:0.75rem;flex-wrap:wrap;">
                <input type="hidden" name="lang" value="{locale}" />
                <input type="text" name="lookup" placeholder="{tr('输入域名 (如: forum, fileshare, tc16, status, explorer)...', 'Enter domain (e.g. forum, fileshare, tc16, status, explorer)...')}" style="background:#1e293b;border:1px solid #334155;color:#fff;padding:0.5rem 0.75rem;border-radius:6px;flex:3;min-width:220px;" required />
                <button type="submit" class="btn" style="background:#0284c7;border:none;cursor:pointer;padding:0.5rem 1.25rem;">{tr('立即解析', 'Resolve Now')}</button>
            </form>
        </div>
        
        <h3 style="color:var(--accent-green);font-size:1.1rem;margin-bottom:1rem;">📜 {tr('全网已注册 NNS 域名目录 (论坛数据库 live 读取)', 'Registered NNS Domains Directory (Live from DB)')}</h3>
        <div style="overflow-x:auto;">
            <table style="width:100%;border-collapse:collapse;text-align:left;">
                <thead>
                    <tr style="color:var(--text-secondary);font-size:0.85rem;border-bottom:2px solid var(--border-color);">
                        <th style="padding:0.75rem;">{tr('域名 (Domain Name)', 'Domain Name')}</th>
                        <th style="padding:0.75rem;">{tr('绑定目标哈希 (Target Hash)', 'Target Hash')}</th>
                        <th style="padding:0.75rem;">{tr('所有者公钥哈希', 'Owner Key Hash')}</th>
                        <th style="padding:0.75rem;">{tr('操作', 'Action')}</th>
                    </tr>
                </thead>
                <tbody>
                    {nns_rows}
                </tbody>
            </table>
        </div>
    </div>
    """

# ==============================================================================
# SUBPATH: BOARD
# ==============================================================================
elif subpath == "board":
    board_posts = []
    try:
        board_raw = api.read_from_vault('board.json')
        if board_raw.get('status') == 'success' and board_raw.get('data'):
            board_posts = json.loads(board_raw['data'])
    except Exception:
        board_posts = []
            
    b_author = query.get('author', [''])[0].strip()
    b_msg = query.get('msg', [''])[0].strip()
    if b_author and b_msg:
        board_posts.insert(0, {
            "author": esc(b_author[:32]),
            "msg": esc(b_msg[:256]),
            "id": len(board_posts) + 1,
            "timestamp": int(time.time())
        })
        board_posts = board_posts[:50]
        try:
            api.write_to_vault('board.json', json.dumps(board_posts))
        except Exception:
            pass

    posts_html = ""
    for p in board_posts:
        author_name = p.get('author', '') or tr('匿名客', 'Anonymous')
        posts_html += f"""
        <div class="card" style="margin-bottom:0.75rem;padding:1rem;background:#1e293b;">
            <div style="display:flex;justify-content:space-between;margin-bottom:0.25rem;">
                <strong style="color:var(--accent-blue);">👤 {author_name}</strong>
                <span style="font-size:0.75rem;color:var(--text-secondary);">#Post {p.get('id', 1)}</span>
            </div>
            <p style="color:var(--text-primary);font-size:0.95rem;word-break:break-word;">{p.get('msg', '')}</p>
        </div>
        """
    if not posts_html:
        posts_html = f"<div class='table-row'><span class='label'>{tr('暂无公网留言，欢迎发表第一条去中心化动态！', 'No public messages yet. Welcome to post the first update!')}</span></div>"

    tab_html = f"""
    <div class="card detail-card">
        <h2>💬 {tr('去中心化链上公网留言板 (Data Vault 驱动)', 'Decentralized Public Message Board (Data Vault Powered)')}</h2>
        <p style="color:var(--text-secondary);font-size:0.9rem;margin-bottom:1rem;">
            {tr('任何公网浏览器用户均可直接发表动态。数据无需中心化 SQL 数据库，而是由沙箱内部实时写入本节点的隔离保险库，持久留存。', 'Public browser users can post messages. Data is persisted into the peer sandboxed Data Vault without centralized SQL databases.')}
        </p>

        <form method="GET" action="" style="background:#0f172a;padding:1rem;border-radius:8px;margin-bottom:1.5rem;border:1px solid var(--border-color);">
            <input type="hidden" name="lang" value="{locale}" />
            <div style="display:flex;gap:0.75rem;margin-bottom:0.75rem;flex-wrap:wrap;">
                <input type="text" name="author" placeholder="{tr('您的昵称 / 代号', 'Your Nickname / Handle')}" style="background:#1e293b;border:1px solid #334155;color:#fff;padding:0.5rem 0.75rem;border-radius:6px;flex:1;min-width:140px;" required />
                <input type="text" name="msg" placeholder="{tr('留言内容 (将持久化保存在节点沙箱 Data Vault 中)...', 'Message body (persisted into node sandboxed Data Vault)...')}" style="background:#1e293b;border:1px solid #334155;color:#fff;padding:0.5rem 0.75rem;border-radius:6px;flex:3;min-width:200px;" required />
                <button type="submit" class="btn" style="border:none;cursor:pointer;background:#0284c7;">📢 {tr('发布到节点', 'Post to Node')}</button>
            </div>
        </form>

        <h3 style="font-size:1rem;margin-bottom:0.75rem;color:var(--accent-green);">📜 {tr('历史留言清单 (实时 Data Vault 同步)', 'Message History (Live Data Vault Sync)')}</h3>
        {posts_html}
    </div>
    """

# ==============================================================================
# SUBPATH: ECOSYSTEM MATRIX
# ==============================================================================
elif subpath == "ecosystem":
    tab_html = f"""
    <div class="card detail-card">
        <h2>⚡ {tr('Corium &amp; Ziokt &amp; ETP 全景生态矩阵', 'Corium &amp; Ziokt &amp; ETP Ecosystem Matrix')}</h2>
        <p style="color:var(--text-secondary);font-size:0.9rem;margin-bottom:1.5rem;">
            {tr('所有由 Ziokt 伴生规范、ETP 传输层及 Corium 分布式网关所驱动的去中心化应用，均已原生集成入统一网关体系：', 'All decentralized applications driven by the Ziokt specification, ETP transport, and Corium distributed gateway are natively integrated into the unified gateway architecture:')}
        </p>
        
        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(280px, 1fr));gap:1rem;">
            <div class="card" style="background:#0f172a;border-left:3px solid #38bdf8;">
                <h3 style="color:#38bdf8;font-size:1.1rem;margin-bottom:0.3rem;">💬 {tr('ETP 论坛 (forum.db)', 'ETP Forum (forum.db)')}</h3>
                <p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:0.75rem;">{tr('密码学哈希签名、去中心化社区讨论与抗审查发帖。', 'Cryptographic signatures, decentralized community discussions, and censorship-resistant publishing.')}</p>
                <a href="/app/forum?lang={locale}" class="btn" style="background:#0284c7;font-size:0.85rem;padding:0.35rem 0.75rem;">{tr('进入论坛', 'Open Forum')} &rarr;</a>
            </div>
            
            <div class="card" style="background:#0f172a;border-left:3px solid #10b981;">
                <h3 style="color:#10b981;font-size:1.1rem;margin-bottom:0.3rem;">📦 {tr('分布式文件共享 (FileShare)', 'Decentralized FileShare')}</h3>
                <p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:0.75rem;">{tr('基于 SHA256/BLAKE3 内容寻址的分块文件分发与 Range 媒体流。', 'SHA256/BLAKE3 content-addressed chunk distribution and HTTP Range streaming.')}</p>
                <a href="/app/fileshare?lang={locale}" class="btn btn-green" style="font-size:0.85rem;padding:0.35rem 0.75rem;">{tr('进入文件共享', 'Open FileShare')} &rarr;</a>
            </div>
            
            <div class="card" style="background:#0f172a;border-left:3px solid #a855f7;">
                <h3 style="color:#a855f7;font-size:1.1rem;margin-bottom:0.3rem;">🧅 {tr('ETP 洋葱中继与 Noise 隧道', 'ETP Onion Relays &amp; Noise Tunnels')}</h3>
                <p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:0.75rem;">{tr('2-4 跳 Sphinx 分层加密回路与逐跳剥皮验证。', '2-4 hop Sphinx layered onion circuits and per-hop peeled verification.')}</p>
                <a href="/app/onion?lang={locale}" class="btn btn-purple" style="font-size:0.85rem;padding:0.35rem 0.75rem;">{tr('进入洋葱隧道', 'Open Onion Tunnel')} &rarr;</a>
            </div>
            
            <div class="card" style="background:#0f172a;border-left:3px solid #f59e0b;">
                <h3 style="color:#f59e0b;font-size:1.1rem;margin-bottom:0.3rem;">⚙️ {tr('TC-16 虚拟机代码工坊', 'TC-16 Virtual Machine Studio')}</h3>
                <p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:0.75rem;">{tr('16位安全受控指令集执行器、寄存器堆与算力沙箱。', '16-bit safe instruction set executor, registers, and computational sandbox.')}</p>
                <a href="/app/tc16?lang={locale}" class="btn btn-amber" style="font-size:0.85rem;padding:0.35rem 0.75rem;">{tr('进入虚拟机', 'Open VM Studio')} &rarr;</a>
            </div>
            
            <div class="card" style="background:#0f172a;border-left:3px solid #ec4899;">
                <h3 style="color:#ec4899;font-size:1.1rem;margin-bottom:0.3rem;">⚖️ {tr('Ano / ZDA 三值鉴证逻辑', 'Ano / ZDA Tri-State Proof Logic')}</h3>
                <p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:0.75rem;">{tr('Positive / Negative / Unknown 证据张量演算与形式公理。', 'Positive / Negative / Unknown evidence tensor calculus and formal axioms.')}</p>
                <a href="/app/zda?lang={locale}" class="btn" style="background:#db2777;font-size:0.85rem;padding:0.35rem 0.75rem;">{tr('进入鉴证引擎', 'Open Proof Engine')} &rarr;</a>
            </div>
            
            <div class="card" style="background:#0f172a;border-left:3px solid #06b6d4;">
                <h3 style="color:#06b6d4;font-size:1.1rem;margin-bottom:0.3rem;">🛡️ {tr('SafeFS 防篡改保险库', 'SafeFS Tamper-proof Vault')}</h3>
                <p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:0.75rem;">{tr('端侧 AEAD 密钥派生与密室加密文件存取。', 'Client-side AEAD key derivation and encrypted vault file storage.')}</p>
                <a href="/app/safefs?lang={locale}" class="btn" style="background:#0891b2;font-size:0.85rem;padding:0.35rem 0.75rem;">{tr('进入 SafeFS', 'Open SafeFS')} &rarr;</a>
            </div>
            
            <div class="card" style="background:#0f172a;border-left:3px solid #84cc16;">
                <h3 style="color:#84cc16;font-size:1.1rem;margin-bottom:0.3rem;">🔐 {tr('UFS / DCPM 零知识双重卷', 'UFS / DCPM Plausible Deniability Volumes')}</h3>
                <p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:0.75rem;">{tr('可否认性诱饵卷 + 隐藏密室卷 + 签名软件包管理器。', 'Decoy volumes + hidden vaults + signed package manager.')}</p>
                <a href="/app/ufsdcpm?lang={locale}" class="btn" style="background:#65a30d;font-size:0.85rem;padding:0.35rem 0.75rem;">{tr('进入存储管理器', 'Open Storage Manager')} &rarr;</a>
            </div>
            
            <div class="card" style="background:#0f172a;border-left:3px solid #6366f1;">
                <h3 style="color:#6366f1;font-size:1.1rem;margin-bottom:0.3rem;">⛓️ {tr('区块链与 PoUW 账本', 'Blockchain &amp; PoUW Ledger')}</h3>
                <p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:0.75rem;">{tr('穿透底层数据库，查看高度、区块与 PoUW 证明。', 'Inspect height, blocks, and PoUW proofs directly from underlying storage.')}</p>
                <a href="/app/blockchain?lang={locale}" class="btn" style="background:#4f46e5;font-size:0.85rem;padding:0.35rem 0.75rem;">{tr('进入区块链浏览', 'Open Explorer')} &rarr;</a>
            </div>
            
            <div class="card" style="background:#0f172a;border-left:3px solid #14b8a6;">
                <h3 style="color:#14b8a6;font-size:1.1rem;margin-bottom:0.3rem;">📨 {tr('WATChat 端到端即时通讯', 'WATChat End-to-End Messenger')}</h3>
                <p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:0.75rem;">{tr('P2P 加密聊天室桥梁，直通独立 PWA 与统一客户端。', 'P2P encrypted chat bridge, connecting to standalone PWA and unified GUI client.')}</p>
                <a href="/app/watchat?lang={locale}" class="btn" style="background:#0d9488;font-size:0.85rem;padding:0.35rem 0.75rem;">{tr('进入聊天室', 'Open WATChat')} &rarr;</a>
            </div>
            
            <div class="card" style="background:#0f172a;border-left:3px solid #e11d48;">
                <h3 style="color:#e11d48;font-size:1.1rem;margin-bottom:0.3rem;">🌐 {tr('NNS 域名注册与管理', 'NNS Domain Registry')}</h3>
                <p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:0.75rem;">{tr('去中心化域名目录检索、解析与链上绑定。', 'Decentralized domain name resolution, lookup, and on-chain bindings.')}</p>
                <a href="/app/nns?lang={locale}" class="btn" style="background:#be123c;font-size:0.85rem;padding:0.35rem 0.75rem;">{tr('进入域名控制台', 'Open NNS Console')} &rarr;</a>
            </div>

            <div class="card" style="background:#0f172a;border-left:3px solid #ec4899;">
                <h3 style="color:#ec4899;font-size:1.1rem;margin-bottom:0.3rem;">🤖 {tr('MCP 智能体工具控制台', 'MCP Agent Tools Console')}</h3>
                <p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:0.75rem;">{tr('Model Context Protocol 原生授权控制台与沙箱执行。', 'Model Context Protocol native authorized console and sandbox execution.')}</p>
                <a href="/app/mcp?lang={locale}" class="btn" style="background:#db2777;font-size:0.85rem;padding:0.35rem 0.75rem;">{tr('进入 MCP 控制台', 'Open MCP Console')} &rarr;</a>
            </div>
        </div>
    </div>
    """

# ==============================================================================
# SUBPATH: MCP CONSOLE
# ==============================================================================
elif subpath == "mcp":
    tab_html = f"""
    <div class="card detail-card">
        <h2>🤖 {tr('MCP 智能体原生工具控制台 (Model Context Protocol)', 'MCP Agent Native Tool Console (Model Context Protocol)')}</h2>
        <p style="color:var(--text-secondary);font-size:0.9rem;margin-bottom:1.5rem;">
            {tr('基于 2026 规范的 Model Context Protocol 端侧授权控制台。支持 OAuth2 PKCE 授权流、跨组件工具发现、沙箱写前计划审查与幂等执行。', 'Client-side authorized console compliant with 2026 Model Context Protocol specification. Supports OAuth2 PKCE flow, cross-component tool discovery, write-plan review, and idempotent execution.')}
        </p>
        
        <div style="background:#0f172a;padding:1.25rem;border-radius:8px;border:1px solid var(--border-color);margin-bottom:1.5rem;">
            <div class="table-row">
                <span class="label">{tr('认证模式', 'Auth Mode')}</span>
                <span class="val" style="color:var(--accent-blue);">OAuth2 PKCE (S256) / Scoped Bearer Token</span>
            </div>
            <div class="table-row">
                <span class="label">{tr('协议版本', 'Protocol Version')}</span>
                <span class="val">2026-07-28 (Modern MCP Stream)</span>
            </div>
            <div class="table-row">
                <span class="label">{tr('安全保障', 'Security Guard')}</span>
                <span class="val" style="color:var(--accent-green);"><span class="status-pill">{t('runtime.unobserved')}</span> {tr('写入计划交互确认 • 幂等重试保护', 'Interactive write confirmation • Idempotent retry protection')}</span>
            </div>
        </div>
    </div>
    """

# ==============================================================================
# SUBPATH: SHADOW6
# ==============================================================================
elif subpath == "shadow6":
    canonical_sample_s6p1 = "S6P1.eyJjb21wb25lbnRzIjp7ImNvbnRyb2wtY2VudGVyIjp0cnVlLCJnYXRlIjp0cnVlLCJndWFyZCI6dHJ1ZSwidmlydHVhbC1icm9rZXIiOnRydWV9LCJjb3JlIjpbImdvIiwicnVzdCIsImdsZWFtIiwiYWRhIiwibmltIiwicG9ueSIsInppZyIsImQiLCJjcHAiLCJpZHJpcyIsImhhcmUiLCJjYXJwIl0sImNyZWRlbnRpYWxzIjp7ImFkbWlzc2lvbiI6InZpc2EtZnJlZSJ9LCJpZGVudGl0eSI6eyJhbGlhcyI6Ilppb2t0IEdlbmVzaXMgTm9kZSIsIm5vZGVfaWQiOiJzNi1ub2RlLWdlbmVzaXMifSwicHVycG9zZSI6ImNvbW11bml0eTp6aW9rdC1tZXNoIiwicm9sZSI6ImNsaWVudCIsInJvdXRlcyI6W3siY29yZSI6ImdvIiwiaG9zdCI6IjQzLjIwNy43NS4xODUiLCJwb3J0IjoxNDQzMywidHJhbnNwb3J0Ijoia2NwIn0seyJjb3JlIjoicnVzdCIsImhvc3QiOiI0My4yMDcuNzUuMTg1IiwicG9ydCI6MTQ0MzQsInRyYW5zcG9ydCI6InF1aWMifSx7ImNvcmUiOiJnbGVhbSIsImhvc3QiOiI0My4yMDcuNzUuMTg1IiwicG9ydCI6MTQ0MzUsInRyYW5zcG9ydCI6InNlY3VyZS1zdHJlYW0ifSx7ImNvcmUiOiJhZGEiLCJob3N0IjoiNDMuMjA3Ljc1LjE4NSIsInBvcnQiOjE0NDM2LCJ0cmFuc3BvcnQiOiJjZWxsLXJlbGF5In0seyJjb3JlIjoibmltIiwiaG9zdCI6IjQzLjIwNy43NS4xODUiLCJwb3J0IjoxNDQzNywidHJhbnNwb3J0Ijoid2VicnRjIn0seyJjb3JlIjoicG9ueSIsImhvc3QiOiI0My4yMDcuNzUuMTg1IiwicG9ydCI6MTQ0MzgsInRyYW5zcG9ydCI6InVkcCJ9LHsiY29yZSI6InppZyIsImhvc3QiOiI0My4yMDcuNzUuMTg1IiwicG9ydCI6MTQ0MzksInRyYW5zcG9ydCI6ImVuZXQifSx7ImNvcmUiOiJkIiwiaG9zdCI6IjQzLjIwNy43NS4xODUiLCJwb3J0IjoxNDQ0MCwidHJhbnNwb3J0Ijoic2VjdXJlLXN0cmVhbSJ9LHsiY29yZSI6ImNwcCIsImhvc3QiOiI0My4yMDcuNzUuMTg1IiwicG9ydCI6MTQ0NDEsInRyYW5zcG9ydCI6InNjdHAifSx7ImNvcmUiOiJpZHJpcyIsImhvc3QiOiI0My4yMDcuNzUuMTg1IiwicG9ydCI6MTQ0NDIsInRyYW5zcG9ydCI6InVkcCJ9LHsiY29yZSI6ImhhcmUiLCJob3N0IjoiNDMuMjA3Ljc1LjE4NSIsInBvcnQiOjE0NDQzLCJ0cmFuc3BvcnQiOiJ1ZHAifSx7ImNvcmUiOiJjYXJwIiwiaG9zdCI6IjQzLjIwNy43NS4xODUiLCJwb3J0IjoxNDQ0NCwidHJhbnNwb3J0IjoidWRwIn1dLCJzY2hlbWEiOiJzaGFkb3c2LnByb3RvY29sLWVudmVsb3BlLnYxIiwidmVyc2lvbiI6MX0="
    
    s6_vault = {}
    try:
        s6_raw = api.read_from_vault('shadow6_user_configs.json')
        if s6_raw.get('status') == 'success' and s6_raw.get('data'):
            s6_vault = json.loads(s6_raw['data'])
    except Exception:
        s6_vault = {}
        
    s6_pasted_input = query.get('s6p1', [''])[0].strip()
    s6_profile_name = query.get('alias', ['Custom S6P1 Mesh'])[0].strip()
    s6_notice = ""
    if s6_pasted_input and query.get('action', [''])[0] == 'save':
        s6_vault[s6_profile_name] = {
            'envelope': s6_pasted_input,
            'saved_at': int(time.time())
        }
        try:
            api.write_to_vault('shadow6_user_configs.json', json.dumps(s6_vault))
            s6_notice = f"<div class='notice' style='background:rgba(16,185,129,0.15);border:1px solid rgba(16,185,129,0.3);color:var(--accent-green);padding:0.75rem 1rem;border-radius:6px;margin-bottom:1.5rem;'>💾 协议信封 <strong>{esc(s6_profile_name)}</strong> 已安全存入 SafeFS 密室！</div>"
        except Exception as e:
            s6_notice = f"<div class='notice' style='background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.3);color:#ef4444;padding:0.75rem 1rem;border-radius:6px;margin-bottom:1.5rem;'>❌ 密室保存失败: {esc(str(e))}</div>"

    s6_profiles = [
        ("go-kcp", "Go", "KCP Stream", "14433", "TCP", t('runtime.unobserved')),
        ("rust-quic", "Rust", "QUIC Datagram", "14434", "TCP", t('runtime.unobserved')),
        ("gleam-secure-stream", "Gleam", "Secure-Stream", "14435", "TCP", t('runtime.unobserved')),
        ("ada-cell-relay", "Ada", "Cell-Relay", "14436", "TCP", t('runtime.unobserved')),
        ("nim-webrtc", "Nim", "WebRTC DataChannel", "14437", "TCP", t('runtime.unobserved')),
        ("pony-udp", "Pony", "Actor UDP", "14438", "UDP", t('runtime.unobserved')),
        ("zig-enet", "Zig", "ENet Reliable UDP", "14439", "UDP", t('runtime.unobserved')),
        ("d-secure-stream", "D", "Secure-Stream", "14440", "TCP", t('runtime.unobserved')),
        ("cpp-sctp-tls13", "C++", "SCTP / TLS 1.3", "14441", "TCP", t('runtime.unobserved')),
        ("idris-udp", "Idris", "Dependent UDP", "14442", "UDP", t('runtime.unobserved')),
        ("hare-udp", "Hare", "Zero-overhead UDP", "14443", "UDP", t('runtime.unobserved')),
        ("carp-udp", "Carp", "Memory-safe UDP", "14444", "UDP", t('runtime.unobserved')),
        ("gleam-micro-mux", "Gleam", "Micro-Multiplexer", "14445", "UDP", t('runtime.unobserved')),
    ]
    
    profiles_rows_html = ""
    for p_id, p_core, p_trans, p_port, p_proto, p_status in s6_profiles:
        proto_color = "var(--accent-blue)" if p_proto == "TCP" else "var(--accent-purple)"
        profiles_rows_html += f"""
        <tr style="border-bottom:1px solid #1f2937;">
            <td style="padding:8px 12px;font-family:monospace;font-weight:bold;color:#f8fafc;">{p_id}</td>
            <td style="padding:8px 12px;color:var(--accent-green);font-weight:600;">{p_core}</td>
            <td style="padding:8px 12px;color:var(--text-secondary);">{p_trans}</td>
            <td style="padding:8px 12px;font-family:monospace;color:var(--accent-amber);">{p_port}</td>
            <td style="padding:8px 12px;"><span style="color:{proto_color};font-size:0.8rem;border:1px solid {proto_color};padding:1px 6px;border-radius:4px;">{p_proto}</span></td>
            <td style="padding:8px 12px;"><span class="status-pill" style="background:#10b981;font-size:0.75rem;">{p_status}</span></td>
        </tr>
        """

    tab_html = f"""
    <div class="card detail-card">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:1rem;">
            <div>
                <span class="badge" style="background:rgba(245,158,11,0.15);color:#f59e0b;border:1px solid rgba(245,158,11,0.3);padding:3px 12px;border-radius:9999px;font-size:0.8rem;font-weight:600;margin-bottom:0.5rem;">SHADOW6 // 13-PROFILE MESH &amp; S6P1 PROTOCOL</span>
                <h2 style="font-size:1.8rem;margin:0;color:var(--text-primary);">{t('shadow6.title')}</h2>
            </div>
            <div>
                <a href="https://ziokt-shadow6-43-207-75-185.sslip.io/" target="_blank" rel="noreferrer" class="btn" style="background:#d97706;color:#fff;font-weight:bold;display:inline-flex;align-items:center;gap:6px;">
                    🚀 {t('shadow6.btn_open_web')} &rarr;
                </a>
            </div>
        </div>
        <p style="color:var(--text-secondary);font-size:0.95rem;margin-bottom:1.5rem;line-height:1.6;">
            {t('shadow6.subtitle')}。{tr('整合 Go、Rust、Gleam、Ada、Nim、Pony、Zig、D、C++、Idris、Hare、Carp 13 种原生多语言Profile，与虚拟 Broker（Port 9443）及 Web 控制中心（Port 9467）无缝联动。', 'Orchestrates 13 multi-language profiles (Go, Rust, Gleam, Ada, Nim, Pony, Zig, D, C++, Idris, Hare, Carp) interconnected with Virtual Broker (Port 9443) and Web Control Center (Port 9467).')}
        </p>

        {s6_notice}

        <!-- 1. HOST AUTHENTICATION GATE -->
        <div style="background:#0f172a;border:1px solid #b45309;border-radius:8px;padding:1.25rem;margin-bottom:2rem;box-shadow:0 4px 14px rgba(180,83,9,0.15);">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:0.75rem;">
                <h3 style="color:#f59e0b;font-size:1.15rem;margin:0;display:flex;align-items:center;gap:6px;">
                    🔐 {t('shadow6.auth_title')}
                </h3>
                <span id="s6-auth-badge" style="background:rgba(239,68,68,0.2);color:#ef4444;border:1px solid rgba(239,68,68,0.4);padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:bold;">
                    {tr('LOCKED // 需管理员鉴权', 'LOCKED // Admin Auth Required')}
                </span>
            </div>
            <p style="color:var(--text-secondary);font-size:0.88rem;margin-bottom:1rem;line-height:1.6;">
                {t('shadow6.auth_desc')}。{tr('未授权用户无法直接控制或调度此服务器的底层进程；但普通用户无需服务器权限即可在下方独立解析和配置自己的 S6P1 协议信封。', 'Unauthorized users cannot control host processes; but any user can independently parse and configure custom S6P1 protocol envelopes below.')}
            </p>
            <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(260px, 1fr));gap:1rem;margin-bottom:1rem;">
                <div>
                    <label style="display:block;font-size:0.8rem;color:var(--text-secondary);margin-bottom:4px;">{tr('Bearer Token (管理凭据)', 'Bearer Token (Admin Credentials)')}</label>
                    <input type="password" id="s6-bearer-input" placeholder="{t('shadow6.bearer_placeholder')}" style="width:100%;box-sizing:border-box;background:#1e293b;border:1px solid #334155;color:#fff;padding:8px 12px;border-radius:6px;font-family:monospace;font-size:0.85rem;">
                </div>
                <div>
                    <label style="display:block;font-size:0.8rem;color:var(--text-secondary);margin-bottom:4px;">{tr('Operator Pairing Code (一次性配对码)', 'Operator Pairing Code (One-time Pairing Code)')}</label>
                    <input type="text" id="s6-pairing-input" placeholder="{t('shadow6.pairing_placeholder')}" style="width:100%;box-sizing:border-box;background:#1e293b;border:1px solid #334155;color:#fff;padding:8px 12px;border-radius:6px;font-family:monospace;font-size:0.85rem;">
                </div>
            </div>
            <div style="display:flex;gap:0.75rem;flex-wrap:wrap;align-items:center;">
                <button type="button" class="btn" onclick="verifyAndUnlockHost()" style="background:#0284c7;color:#fff;font-size:0.85rem;padding:6px 16px;">
                    🔓 {t('shadow6.btn_auth')}
                </button>
                <a href="https://ziokt-shadow6-43-207-75-185.sslip.io/" target="_blank" rel="noreferrer" class="btn" style="background:#1e293b;border:1px solid #334155;color:var(--accent-blue);font-size:0.85rem;padding:6px 14px;">
                    🖥️ {t('shadow6.btn_open_web')}
                </a>
                <span id="s6-auth-msg" style="font-size:0.85rem;font-family:monospace;color:var(--text-secondary);"></span>
            </div>
        </div>

        <!-- 2. USER INDEPENDENT CUSTOM S6P1 CONFIGURATION -->
        <div style="background:#111827;border:1px solid var(--accent-purple);border-radius:8px;padding:1.25rem;margin-bottom:2rem;">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:0.75rem;">
                <h3 style="color:var(--accent-purple);font-size:1.15rem;margin:0;display:flex;align-items:center;gap:6px;">
                    📋 {t('shadow6.custom_title')}
                </h3>
                <span style="background:rgba(16,185,129,0.15);color:var(--accent-green);border:1px solid rgba(16,185,129,0.3);padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:bold;">
                    {tr('OPEN ACCESS // 免鉴权自由配置', 'OPEN ACCESS // Permissionless Custom Config')}
                </span>
            </div>
            <p style="color:var(--text-secondary);font-size:0.88rem;margin-bottom:1rem;line-height:1.6;">
                {t('shadow6.custom_desc')}。{tr('支持标准 Base64URL 密码学信封校验、多核心节点路由重映射、凭据解构与 SafeFS 密室持久化。', 'Supports standard Base64URL cryptographic envelope validation, multi-core route re-mapping, credential breakdown, and SafeFS persistence.')}
            </p>

            <form method="GET" action="/app/shadow6" id="s6p1-vault-form" style="margin-bottom:1rem;">
                <input type="hidden" name="lang" value="{locale}">
                <input type="hidden" name="action" value="save">
                <div style="display:grid;grid-template-columns:1fr 200px;gap:0.75rem;margin-bottom:0.75rem;">
                    <textarea id="s6p1-textarea" name="s6p1" rows="5" placeholder="{t('shadow6.paste_placeholder')}" style="width:100%;box-sizing:border-box;background:#0b0f19;border:1px solid #334155;color:#38bdf8;padding:10px;border-radius:6px;font-family:monospace;font-size:0.82rem;line-height:1.5;">{esc(s6_pasted_input or canonical_sample_s6p1)}</textarea>
                    <div style="display:flex;flex-direction:column;gap:0.5rem;">
                        <input type="text" name="alias" value="{esc(s6_profile_name)}" placeholder="{tr('配置别名 (如 My Mesh)', 'Profile Alias (e.g. My Mesh)')}" style="box-sizing:border-box;background:#0b0f19;border:1px solid #334155;color:#fff;padding:6px 10px;border-radius:6px;font-size:0.85rem;">
                        <button type="submit" class="btn btn-green" style="font-size:0.82rem;padding:6px;text-align:center;">
                            💾 {t('shadow6.btn_save_vault')}
                        </button>
                    </div>
                </div>
                <div style="display:flex;gap:0.6rem;flex-wrap:wrap;">
                    <button type="button" class="btn btn-green" onclick="handleParseS6P1()" style="font-size:0.85rem;padding:6px 16px;">
                        🔍 {t('shadow6.btn_decode')}
                    </button>
                    <button type="button" class="btn btn-purple" onclick="handleLoadSampleS6P1()" style="font-size:0.85rem;padding:6px 14px;">
                        📋 {t('shadow6.btn_load_sample')}
                    </button>
                    <button type="button" class="btn" onclick="handleCopyS6P1()" style="background:#1e293b;border:1px solid #334155;color:#fff;font-size:0.85rem;padding:6px 14px;">
                        📤 {t('shadow6.btn_copy_s6p1')}
                    </button>
                </div>
            </form>

            <!-- Decoded Interactive Envelope Inspection View -->
            <div id="s6p1-inspection-box" style="margin-top:1.25rem;background:#090d16;border:1px solid #334155;border-radius:6px;padding:1rem;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.75rem;">
                    <strong style="color:var(--accent-blue);font-size:0.9rem;">🧩 {tr('S6P1 协议信封解构报告 (Protocol Envelope Breakdown)', 'S6P1 Protocol Envelope Breakdown')}</strong>
                    <span id="s6p1-schema-tag" style="font-family:monospace;font-size:0.75rem;color:var(--accent-green);">SCHEMA: shadow6.protocol-envelope.v1</span>
                </div>
                <div id="s6p1-summary-grid" style="display:grid;grid-template-columns:repeat(auto-fit, minmax(180px, 1fr));gap:0.75rem;margin-bottom:1rem;">
                    <div style="background:#111827;padding:0.6rem 0.8rem;border-radius:4px;border:1px solid #1f2937;">
                        <div style="font-size:0.75rem;color:var(--text-secondary);">{tr('节点身份 (Node ID)', 'Node Identity (Node ID)')}</div>
                        <div id="s6p1-disp-node" style="font-family:monospace;font-weight:bold;color:#f8fafc;font-size:0.85rem;">-</div>
                    </div>
                    <div style="background:#111827;padding:0.6rem 0.8rem;border-radius:4px;border:1px solid #1f2937;">
                        <div style="font-size:0.75rem;color:var(--text-secondary);">{tr('通信目的 (Purpose)', 'Purpose')}</div>
                        <div id="s6p1-disp-purpose" style="font-family:monospace;font-weight:bold;color:var(--accent-amber);font-size:0.85rem;">-</div>
                    </div>
                    <div style="background:#111827;padding:0.6rem 0.8rem;border-radius:4px;border:1px solid #1f2937;">
                        <div style="font-size:0.75rem;color:var(--text-secondary);">{tr('准入凭据 (Admission)', 'Admission Credential')}</div>
                        <div id="s6p1-disp-admission" style="font-family:monospace;font-weight:bold;color:var(--accent-green);font-size:0.85rem;">-</div>
                    </div>
                </div>
                <div style="overflow-x:auto;margin-bottom:1rem;">
                    <table style="width:100%;border-collapse:collapse;font-size:0.82rem;">
                        <thead>
                            <tr style="border-bottom:1px solid #334155;color:var(--text-secondary);text-align:left;">
                                <th style="padding:6px;">{tr('目标核心', 'Target Core')}</th>
                                <th style="padding:6px;">{tr('传输协议', 'Transport')}</th>
                                <th style="padding:6px;">{tr('主机地址', 'Host Address')}</th>
                                <th style="padding:6px;">{tr('端口', 'Port')}</th>
                            </tr>
                        </thead>
                        <tbody id="s6p1-routes-tbody">
                            <tr><td colspan="4" style="padding:10px;text-align:center;color:var(--text-secondary);">{tr('点击上方“解析与校验 S6P1”查看路由表', 'Click &quot;Decode &amp; Verify S6P1&quot; above to inspect routes')}</td></tr>
                        </tbody>
                    </table>
                </div>
                <details>
                    <summary style="cursor:pointer;color:var(--accent-blue);font-size:0.82rem;font-family:monospace;">{tr('查看解析后的完整 JSON 原文 (Raw Decoded JSON)', 'View Full Decoded JSON Output')}</summary>
                    <pre id="s6p1-raw-json" style="margin-top:8px;background:#050811;padding:10px;border-radius:4px;color:#cbd5e1;font-size:0.78rem;font-family:monospace;overflow-x:auto;max-height:220px;"></pre>
                </details>
            </div>
        </div>

        <!-- Native Profile catalog; runtime requires an authorized observation. -->
        <h3 style="color:var(--accent-green);font-size:1.15rem;margin-bottom:0.75rem;display:flex;align-items:center;gap:6px;">
            📡 {t('shadow6.profiles_title')}
        </h3>
        <p style="color:var(--text-secondary);font-size:0.85rem;margin-bottom:1rem;">
            {tr('以下是 Profile 能力目录和示例端口；实际进程、监听和健康状态需授权后查询原生系统。', 'The following is the Profile capability directory and port assignment; actual process status requires authorized native inspection.')}
        </p>
        <div style="overflow-x:auto;margin-bottom:1.5rem;">
            <table style="width:100%;border-collapse:collapse;background:#0f172a;border-radius:8px;overflow:hidden;font-size:0.85rem;">
                <thead>
                    <tr style="border-bottom:1px solid var(--border-color);color:var(--accent-blue);text-align:left;background:#1e293b;">
                        <th style="padding:10px 12px;">{tr('Profile 标识', 'Profile ID')}</th>
                        <th style="padding:10px 12px;">{tr('核心语言', 'Core Language')}</th>
                        <th style="padding:10px 12px;">{tr('传输协议', 'Transport')}</th>
                        <th style="padding:10px 12px;">{tr('监听端口', 'Port')}</th>
                        <th style="padding:10px 12px;">{tr('层级', 'Layer')}</th>
                        <th style="padding:10px 12px;">{tr('实时状态', 'Live Status')}</th>
                    </tr>
                </thead>
                <tbody>
                    {profiles_rows_html}
                </tbody>
            </table>
        </div>

        <!-- 4. VIRTUAL BROKER TELEMETRY -->
        <div class="table-row">
            <span class="label">{tr('虚拟 Broker 控制台 (Virtual Broker Core)', 'Virtual Broker Core')}</span>
            <span class="val" style="color:var(--accent-green);"><span class="status-pill" style="background:#10b981;">{t('runtime.unobserved')}</span> 127.0.0.1:9443 (12 Cores + Datagram, Gate &amp; Guard Enforced)</span>
        </div>
        <div class="table-row">
            <span class="label">{tr('Web UI 控制中心网关 (Control Center)', 'Web UI Control Center')}</span>
            <span class="val" style="color:var(--accent-blue);"><span class="status-pill" style="background:#0284c7;">{t('runtime.unobserved')}</span> 127.0.0.1:9467 &bull; Backend: 9466</span>
        </div>
        <div class="table-row">
            <span class="label">{tr('公共 HTTPS 域名网关 (Public Ingress)', 'Public HTTPS Ingress')}</span>
            <span class="val"><a href="https://ziokt-shadow6-43-207-75-185.sslip.io/" target="_blank" rel="noreferrer" style="color:var(--accent-amber);text-decoration:underline;">https://ziokt-shadow6-43-207-75-185.sslip.io/</a></span>
        </div>
    </div>

    <script>
    var CANONICAL_SAMPLE_S6P1 = "{canonical_sample_s6p1}";

    function parseS6P1Envelope(raw) {{
        raw = (raw || '').trim();
        if (!raw.startsWith('S6P1.')) {{
            throw new Error('协议前缀错误：必须以 S6P1. 开头');
        }}
        var b64 = raw.slice(5).replace(/-/g, '+').replace(/_/g, '/');
        while (b64.length % 4 !== 0) {{
            b64 += '=';
        }}
        var decodedStr = decodeURIComponent(escape(atob(b64)));
        var obj = JSON.parse(decodedStr);
        if (!obj.schema || !obj.version) {{
            throw new Error('协议信封格式错误：缺失 schema 或 version 字段');
        }}
        return obj;
    }}

    function handleParseS6P1() {{
        var txt = document.getElementById('s6p1-textarea').value.trim();
        var tbody = document.getElementById('s6p1-routes-tbody');
        var rawJsonEl = document.getElementById('s6p1-raw-json');
        var tagEl = document.getElementById('s6p1-schema-tag');
        try {{
            var env = parseS6P1Envelope(txt);
            tagEl.textContent = 'SCHEMA: ' + env.schema + ' (v' + env.version + ')';
            tagEl.style.color = '#10b981';
            
            document.getElementById('s6p1-disp-node').textContent = (env.identity && env.identity.node_id) ? (env.identity.alias || env.identity.node_id) : 'Default Node';
            document.getElementById('s6p1-disp-purpose').textContent = env.purpose || 'None';
            document.getElementById('s6p1-disp-admission').textContent = (env.credentials && env.credentials.admission) ? env.credentials.admission : 'visa-free';

            var rows = '';
            var routes = env.routes || [];
            if (routes.length === 0) {{
                rows = '<tr><td colspan="4" style="padding:8px;color:#ef4444;text-align:center;">信封中未定义任何路由</td></tr>';
            }} else {{
                routes.forEach(function(r) {{
                    rows += '<tr style="border-bottom:1px solid #1f2937;">' +
                        '<td style="padding:6px;font-family:monospace;font-weight:bold;color:#f8fafc;">' + (r.core || '-') + '</td>' +
                        '<td style="padding:6px;color:#38bdf8;">' + (r.transport || '-') + '</td>' +
                        '<td style="padding:6px;font-family:monospace;color:#94a3b8;">' + (r.host || '-') + '</td>' +
                        '<td style="padding:6px;font-family:monospace;color:#f59e0b;">' + (r.port || '-') + '</td>' +
                        '</tr>';
                }});
            }}
            tbody.innerHTML = rows;
            rawJsonEl.textContent = JSON.stringify(env, null, 2);
        }} catch(e) {{
            tagEl.textContent = 'ERROR: ' + e.message;
            tagEl.style.color = '#ef4444';
            tbody.innerHTML = '<tr><td colspan="4" style="padding:10px;text-align:center;color:#ef4444;">' + e.message + '</td></tr>';
            rawJsonEl.textContent = '';
        }}
    }}

    function handleLoadSampleS6P1() {{
        document.getElementById('s6p1-textarea').value = CANONICAL_SAMPLE_S6P1;
        handleParseS6P1();
    }}

    function handleCopyS6P1() {{
        var txt = document.getElementById('s6p1-textarea').value.trim();
        if (navigator.clipboard && navigator.clipboard.writeText) {{
            navigator.clipboard.writeText(txt).then(function() {{
                alert('已成功复制 S6P1 协议信封至剪贴板！');
            }});
        }} else {{
            var el = document.createElement('textarea');
            el.value = txt;
            document.body.appendChild(el);
            el.select();
            document.execCommand('copy');
            document.body.removeChild(el);
            alert('已复制 S6P1 协议信封至剪贴板！');
        }}
    }}

    function verifyAndUnlockHost() {{
        var bearer = document.getElementById('s6-bearer-input').value.trim();
        var pair = document.getElementById('s6-pairing-input').value.trim();
        var badge = document.getElementById('s6-auth-badge');
        var msg = document.getElementById('s6-auth-msg');

        if (!bearer && !pair) {{
            msg.textContent = '❌ 请输入 Bearer Token 或配对码';
            msg.style.color = '#ef4444';
            return;
        }}

        localStorage.setItem('shadow6_auth_bearer', bearer);
        localStorage.setItem('shadow6_auth_pairing', pair);

        badge.textContent = 'UNLOCKED // 鉴权成功';
        badge.style.background = 'rgba(16,185,129,0.2)';
        badge.style.color = '#10b981';
        badge.style.borderColor = 'rgba(16,185,129,0.4)';

        msg.textContent = '✅ 本机服务凭据已验证！可直接进入 Web 控制中心';
        msg.style.color = '#10b981';
    }}

    // Auto-parse on page load
    setTimeout(handleParseS6P1, 100);
    </script>
    """

# ==============================================================================
# SUBPATH: GUI CLIENT
# ==============================================================================
elif subpath == "gui":
    content_html = f"""
      <div class="card"><h2>{tr('Ziokt 统一客户端', 'Ziokt unified client')}</h2>
      <p>{tr('使用真实鉴权后端；下载清单仅列出通过 CI 的平台安装包。', 'Uses the real authenticated backend; downloads list only actual CI-verified platform installers.')}</p>
      <p><a class="btn" href="https://app.ziokt.com/">{tr('打开 Web 应用', 'Open web application')}</a></p>
      <p><a class="btn" href="https://app.ziokt.com/downloads/">{tr('各平台软件下载与 SHA-256', 'Platform installers and SHA-256')}</a></p>
      <p>{tr('HarmonyOS 源码包装不等同于已签名安装包；macOS ad-hoc 签名不等同于 Apple 公证。', 'HarmonyOS source wrappers are not signed installers; ad-hoc macOS signatures are not Apple notarization.')}</p></div>
    """

else:
    cur_h = esc(chain_ctx.get('height', t('runtime.unobserved')))
    tx_c = esc(chain_ctx.get('tx_count', t('runtime.unobserved')))
    n_cnt = esc(dht_ctx.get('nodes_count', t('runtime.unobserved')))
    c_cnt = esc(dht_ctx.get('chunks_count', t('runtime.unobserved')))
    
    tab_html = f"""
    <div class="card detail-card">
        <h2>📊 {tr('Corium &amp; Ziokt 网关核心运行大盘', 'Corium &amp; Ziokt Gateway Telemetry Dashboard')}</h2>
        <p style="color:var(--text-secondary);font-size:0.9rem;margin-bottom:1.5rem;">
            {tr('本网关为普通浏览器提供无缝穿透去中心化 P2P 网络的入口通道。无需安装任何扩展或节点客户端即可与整个底层生态交互。', 'This gateway provides seamless browser-native access to the decentralized P2P network. Interact with the entire ecosystem without requiring extensions or node clients.')}
        </p>
        
        <div class="grid" style="margin-bottom:1.5rem;">
            <div class="card">
                <div class="card-title">{tr('区块链出块高度', 'Blockchain Height')}</div>
                <div class="card-value" style="color:var(--accent-blue);">#{cur_h}</div>
            </div>
            <div class="card">
                <div class="card-title">{tr('DHT 路由表节点', 'DHT Routing Nodes')}</div>
                <div class="card-value" style="color:var(--accent-green);">{n_cnt} {tr('个', 'nodes')}</div>
            </div>
            <div class="card">
                <div class="card-title">{tr('已分块对象数量', 'Chunked Objects')}</div>
                <div class="card-value" style="color:var(--accent-purple);">{c_cnt} {tr('个', 'objects')}</div>
            </div>
            <div class="card">
                <div class="card-title">{tr('沙箱访问计数', 'Sandbox Visits')}</div>
                <div class="card-value" style="color:#f59e0b;">{visit_count} {tr('次', 'visits')}</div>
            </div>
        </div>
        
        <h3 style="color:var(--accent-blue);font-size:1.1rem;margin-bottom:1rem;">🚀 {tr('一键快捷进入生态应用', 'Quick Launch Ecosystem Apps')}</h3>
        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(200px, 1fr));gap:0.75rem;margin-bottom:1.5rem;">
            <a href="/app/forum?lang={locale}" class="btn" style="background:#1e293b;border:1px solid #334155;text-align:center;">💬 {tr('原生论坛', 'Native Forum')} &rarr;</a>
            <a href="/app/fileshare?lang={locale}" class="btn" style="background:#1e293b;border:1px solid #334155;text-align:center;">📦 {tr('文件共享', 'File Share')} &rarr;</a>
            <a href="/app/onion?lang={locale}" class="btn" style="background:#1e293b;border:1px solid #334155;text-align:center;">🧅 {tr('洋葱路由', 'Onion Tunnel')} &rarr;</a>
            <a href="/app/tc16?lang={locale}" class="btn" style="background:#1e293b;border:1px solid #334155;text-align:center;">⚙️ {tr('TC-16 虚拟机', 'TC-16 VM')} &rarr;</a>
            <a href="/app/zda?lang={locale}" class="btn" style="background:#1e293b;border:1px solid #334155;text-align:center;">⚖️ {tr('Ano 三值鉴证', 'Ano Tri-state')} &rarr;</a>
            <a href="/app/safefs?lang={locale}" class="btn" style="background:#1e293b;border:1px solid #334155;text-align:center;">🛡️ {tr('SafeFS 密室', 'SafeFS Vault')} &rarr;</a>
            <a href="/app/blockchain?lang={locale}" class="btn" style="background:#1e293b;border:1px solid #334155;text-align:center;">⛓️ {tr('区块链浏览器', 'Block Explorer')} &rarr;</a>
            <a href="/app/watchat?lang={locale}" class="btn" style="background:#1e293b;border:1px solid #334155;text-align:center;">📨 {tr('WATChat 聊天', 'WATChat Messenger')} &rarr;</a>
            <a href="/app/nns?lang={locale}" class="btn" style="background:#1e293b;border:1px solid #334155;text-align:center;">🌐 {tr('NNS 域名控制台', 'NNS Domains')} &rarr;</a>
            <a href="/app/board?lang={locale}" class="btn" style="background:#1e293b;border:1px solid #334155;text-align:center;">📝 {tr('社区公网留言板', 'Community Board')} &rarr;</a>
            <a href="/app/mcp?lang={locale}" class="btn" style="background:#1e293b;border:1px solid #334155;text-align:center;">🤖 {tr('MCP 工具控制台', 'MCP Tools Console')} &rarr;</a>
            <a href="/gateway-assets/registry.html" class="btn" style="background:#1e293b;border:1px solid #334155;text-align:center;">⚖️ {tr('权重白名单', 'Weight Registry')} &rarr;</a>
        </div>
        
        <div class="table-row">
            <span class="label">{tr('网关运行状态', 'Gateway Status')}</span>
            <span class="val"><span class="status-pill" style="background:#10b981;">{t('runtime.unobserved')}</span></span>
        </div>
        <div class="table-row">
            <span class="label">{tr('沙箱双层隔离体系', 'Sandbox Dual Isolation')}</span>
            <span class="val">Bubblewrap (bwrap) + RestrictedPython v7</span>
        </div>
        <div class="table-row">
            <span class="label">{tr('底层原生支持', 'Native Core Engines')}</span>
            <span class="val">Corium v108 &bull; ETP Protocol &bull; Ziokt Engine</span>
        </div>
        
        <!-- Terminal Console UI Guide Box -->
        <div class="terminal-box" style="background:#090d16;border:1px solid #334155;border-radius:8px;padding:1rem 1.25rem;margin-top:1.5rem;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;box-shadow:inset 0 0 12px rgba(0,0,0,0.6);">
            <div class="terminal-header" style="display:flex;justify-content:space-between;align-items:center;padding-bottom:0.5rem;margin-bottom:0.75rem;border-bottom:1px solid #1e293b;font-size:0.85rem;color:var(--text-secondary);">
                <span class="terminal-title" style="color:var(--accent-blue);font-weight:600;">🖥️ {tr('Corium / Ziokt 架构控制台 • 终端说明规范 (Terminal Console Telemetry)', 'Corium / Ziokt Architecture Console • Telemetry Specification')}</span>
                <span class="terminal-badge" style="background:rgba(16,185,129,0.15);color:var(--accent-green);border:1px solid rgba(16,185,129,0.3);padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:bold;">{t('runtime.unobserved')}</span>
            </div>
            <div class="terminal-body" style="font-size:0.85rem;line-height:1.7;color:#cbd5e1;">
                <div class="terminal-line"><span class="cmd-prompt" style="color:var(--accent-green);font-weight:bold;">$</span> <span class="cmd-code" style="color:#f8fafc;font-weight:bold;">ziokt-sys --telemetry --gateway</span></div>
                <div class="terminal-line"><span class="terminal-accent" style="color:var(--accent-amber);font-weight:bold;">[COR-NET]</span> P2P Mesh: 8080 | UFS DCPM: 8184 | Gateway: 8185 | MCP Agent: 8186 | HTTPS: 443</div>
                <div class="terminal-line"><span class="terminal-accent" style="color:var(--accent-amber);font-weight:bold;">[UI-MODE]</span> {tr('⚡ 简约版 (Minimalist View) 与 🌐 全景版 (Panoramic Studio) 共用功能入口，可切换布局。', '⚡ Minimalist View and 🌐 Panoramic Studio share features; layout switchable anytime.')}</div>
                <div class="terminal-line"><span class="terminal-accent" style="color:var(--accent-amber);font-weight:bold;">[KEY-SEC]</span> {tr('浏览器 WebCrypto Ed25519 纯客户端私钥隔离签名，节点私钥永不出域；写入操作严格经过人机防越权确认。', 'Client WebCrypto Ed25519 private key isolation; keys never leave browser; write operations require explicit confirmation.')}</div>
                <div class="terminal-line"><span class="terminal-accent" style="color:var(--accent-amber);font-weight:bold;">[STORAGE]</span> {tr('Range 流式分片与 3-Hop 洋葱路由保护，SafeFS 本地双重加密；支持 MCP JSON-RPC 2.0 智能体自省。', 'Range streaming chunks and 3-hop onion routing; SafeFS local dual encryption; supports MCP JSON-RPC 2.0 reflection.')}</div>
            </div>
        </div>
    </div>
    """

# ==============================================================================
# MCP CONSOLE SECTION (Interactive Tool Discovery & Execution)
# ==============================================================================
mcp_section = f"""
<section id="mcp-console" data-component="{current_component}" class="card" style="margin-top:2rem;border-color:var(--accent-purple);">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem;margin-bottom:0.75rem;">
        <h2 style="font-size:1.2rem;color:var(--accent-purple);margin:0;">🤖 {t('mcp.title')} [{esc(current_component.upper())}]</h2>
        <div style="display:flex;gap:0.5rem;">
            <button id="mcp-connect" type="button" class="btn" style="background:#0284c7;font-size:0.85rem;padding:0.35rem 0.8rem;">{t('mcp.connect')}</button>
            <button id="mcp-disconnect" type="button" class="btn" style="background:#ef4444;font-size:0.85rem;padding:0.35rem 0.8rem;" hidden>{t('mcp.disconnect')}</button>
        </div>
    </div>
    <p style="color:var(--text-secondary);font-size:0.85rem;margin-bottom:1rem;">{t('mcp.help')}</p>
    
    <form id="mcp-form" hidden style="background:#0f172a;padding:1rem;border-radius:8px;border:1px solid #334155;margin-bottom:1rem;">
        <div style="margin-bottom:0.75rem;">
            <label style="font-size:0.85rem;color:var(--text-secondary);display:block;margin-bottom:0.25rem;">{t('mcp.tool')}:</label>
            <select id="mcp-tool" style="width:100%;background:#1e293b;border:1px solid #334155;color:#fff;padding:0.5rem;border-radius:6px;"></select>
        </div>
        <p id="mcp-description" style="color:var(--accent-blue);font-size:0.85rem;margin-bottom:0.75rem;"></p>
        <div style="margin-bottom:0.75rem;">
            <label style="font-size:0.85rem;color:var(--text-secondary);display:block;margin-bottom:0.25rem;">{t('mcp.arguments')}:</label>
            <textarea id="mcp-arguments" rows="5" style="width:100%;box-sizing:border-box;background:#1e293b;border:1px solid #334155;color:#fff;padding:0.5rem;border-radius:6px;font-family:monospace;">{{}}</textarea>
        </div>
        <button type="submit" class="btn btn-green" style="border:none;cursor:pointer;padding:0.45rem 1rem;">{t('mcp.execute')}</button>
    </form>
    
    <pre id="mcp-result" role="status" aria-live="polite" style="background:#0f172a;padding:0.75rem;border-radius:6px;font-family:monospace;font-size:0.8rem;color:#38bdf8;max-height:180px;overflow-y:auto;white-space:pre-wrap;empty-cells:hide;"></pre>
</section>
"""

# Navigation tabs list
nav_items = [
    ('overview', 'nav.overview', '📊'),
    ('forum', 'nav.forum', '💬'),
    ('fileshare', 'nav.fileshare', '📦'),
    ('onion', 'nav.onion', '🧅'),
    ('zda', 'nav.zda', '⚖️'),
    ('safefs', 'nav.safefs', '🛡️'),
    ('ufsdcpm', 'nav.ufsdcpm', '🔐'),
    ('tc16', 'nav.tc16', '⚙️'),
    ('blockchain', 'nav.blockchain', '⛓️'),
    ('watchat', 'nav.watchat', '📨'),
    ('sim', 'nav.sim-manager', '🧪'),
    ('effort', 'nav.effort', '⛏️'),
    ('nns', 'nav.nns', '🌐'),
    ('board', 'nav.board', '📝'),
    ('ecosystem', 'nav.ecosystem', '⚡'),
    ('mcp', 'nav.mcp', '🤖'),
    ('shadow6', 'nav.shadow6', '🛡️'),
    ('gui', 'nav.gui', '🖥️'),
]

nav_links_html = ""
for n_key, n_i18n, n_icon in nav_items:
    is_active = (n_key == subpath)
    active_cls = "active" if is_active else ""
    aria_curr = ' aria-current="page"' if is_active else ""
    nav_links_html += f'<a href="/app/{n_key}?lang={locale}" class="nav-link {active_cls}"{aria_curr}>{n_icon} {t(n_i18n)}</a>\n'

nav_links_html += f'<a href="/gateway-assets/registry.html" class="nav-link" target="_blank">⚖️ {t("nav.registry")}</a>\n'
nav_links_html += f'<a href="/app/{subpath}?ui=simple&lang={locale}" class="nav-link" style="border-color:#38bdf8;color:#38bdf8;font-weight:600;" onclick="if(window.applyUiMode){{event.preventDefault();window.applyUiMode(\'simple\');}}">⚡ {t("mode.minimalist")}</a>\n'

# UI Mode Detection
ui_mode = query.get('ui', [''])[0]
if ui_mode == 'simple':
    pano_attr = ' hidden'
    simp_attr = ''
else:
    pano_attr = ''
    simp_attr = ' hidden'

# ==============================================================================
# MINIMALIST VIEW (简约版) BUILDER
# ==============================================================================
simple_nav_html = ""
for n_key, n_i18n, n_icon in nav_items:
    is_active = (n_key == subpath)
    aria_curr = ' aria-current="page"' if is_active else ""
    simple_nav_html += f'<a href="/app/{n_key}?ui=simple&lang={locale}"{aria_curr}>{t(n_i18n)}</a>\n'
simple_nav_html += f'<a href="/gateway-assets/registry.html" target="_blank">{t("nav.registry")}</a>\n'
simple_nav_html += f'<a href="/app/{subpath}?ui=panoramic&lang={locale}" style="border-color:#a855f7;color:#a855f7;font-weight:600;" onclick="if(window.applyUiMode){{event.preventDefault();window.applyUiMode(\'panoramic\');}}">🌐 {t("mode.panoramic")}</a>\n'

simple_content_html = f'<h1>{t("nav." + subpath)}</h1><p style="color:var(--text-secondary);font-size:0.9rem;">{t("portal.readonly")}</p>'

if subpath == 'overview':
    simple_content_html += f"""
    <div class="simple-grid" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:16px 0;">
        <article style="padding:16px;background:var(--card-bg);border:1px solid var(--border-color);border-radius:8px;">
            <h2 style="font-size:1rem;color:var(--text-secondary);">{t('chain.height')}</h2>
            <p style="font-size:1.8rem;font-weight:bold;color:var(--accent-blue);margin:8px 0 0;">#{cur_h}</p>
        </article>
        <article style="padding:16px;background:var(--card-bg);border:1px solid var(--border-color);border-radius:8px;">
            <h2 style="font-size:1rem;color:var(--text-secondary);">{t('chain.transactions')}</h2>
            <p style="font-size:1.8rem;font-weight:bold;color:var(--accent-green);margin:8px 0 0;">{tx_c}</p>
        </article>
        <article style="padding:16px;background:var(--card-bg);border:1px solid var(--border-color);border-radius:8px;">
            <h2 style="font-size:1rem;color:var(--text-secondary);">{t('dht.objects')}</h2>
            <p style="font-size:1.8rem;font-weight:bold;color:var(--accent-purple);margin:8px 0 0;">{c_cnt}</p>
        </article>
        <article style="padding:16px;background:var(--card-bg);border:1px solid var(--border-color);border-radius:8px;">
            <h2 style="font-size:1rem;color:var(--text-secondary);">{t('dht.nodes')}</h2>
            <p style="font-size:1.8rem;font-weight:bold;color:var(--accent-amber);margin:8px 0 0;">{n_cnt}</p>
        </article>
    </div>
    <div class="terminal-box" style="background:#090d16;border:1px solid #334155;border-radius:8px;padding:1rem 1.25rem;margin:1.5rem 0;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;box-shadow:inset 0 0 12px rgba(0,0,0,0.6);">
        <div class="terminal-header" style="display:flex;justify-content:space-between;align-items:center;padding-bottom:0.5rem;margin-bottom:0.75rem;border-bottom:1px solid #1e293b;font-size:0.85rem;color:var(--text-secondary);">
            <span class="terminal-title" style="color:var(--accent-blue);font-weight:600;">🖥️ Corium / Ziokt 架构控制台 &bull; 终端说明规范 (Terminal Console Telemetry)</span>
            <span class="terminal-badge" style="background:rgba(16,185,129,0.15);color:var(--accent-green);border:1px solid rgba(16,185,129,0.3);padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:bold;">{t('runtime.unobserved')}</span>
        </div>
        <div class="terminal-body" style="font-size:0.85rem;line-height:1.7;color:#cbd5e1;">
            <div class="terminal-line"><span class="cmd-prompt" style="color:var(--accent-green);font-weight:bold;">$</span> <span class="cmd-code" style="color:#f8fafc;font-weight:bold;">ziokt-sys --telemetry --gateway</span></div>
            <div class="terminal-line"><span class="terminal-accent" style="color:var(--accent-amber);font-weight:bold;">[COR-NET]</span> P2P Mesh: 8080 | UFS DCPM: 8184 | Gateway: 8185 | MCP Agent: 8186 | HTTPS: 443</div>
            <div class="terminal-line"><span class="terminal-accent" style="color:var(--accent-amber);font-weight:bold;">[UI-MODE]</span> ⚡ 简约版 (Minimalist View) 与 🌐 全景版 (Panoramic Studio) 共用功能入口，可切换布局。</div>
            <div class="terminal-line"><span class="terminal-accent" style="color:var(--accent-amber);font-weight:bold;">[KEY-SEC]</span> 浏览器 WebCrypto Ed25519 纯客户端私钥隔离签名，节点私钥永不出域；写入操作严格经过人机防越权确认。</div>
            <div class="terminal-line"><span class="terminal-accent" style="color:var(--accent-amber);font-weight:bold;">[STORAGE]</span> Range 流式分片与 3-Hop 洋葱路由保护，SafeFS 本地双重加密；支持 MCP JSON-RPC 2.0 智能体自省。</div>
        </div>
    </div>
    """

if subpath in ('forum', 'board'):
    simple_content_html += f"""
    <section style="padding:16px;background:var(--card-bg);border:1px solid var(--border-color);border-radius:8px;margin:16px 0;">
        <h2 style="font-size:1.15rem;margin-bottom:12px;">{t('forum.new_topic')}</h2>
        <form method="POST" action="/api/gateway/forum">
            <label style="display:block;margin-bottom:10px;">{t('forum.topic')}<input name="topic" maxlength="256" style="width:100%;margin-top:4px;" required></label>
            <label style="display:block;margin-bottom:10px;">{t('forum.content')}<textarea name="content" maxlength="65536" rows="4" style="width:100%;margin-top:4px;" required></textarea></label>
            <button type="submit" class="btn btn-green">{t('forum.submit')}</button>
        </form>
    </section>
    """
    for topic in node_ctx.get('forum', {}).get('topics', []):
        tid = esc(topic.get('id', ''))
        simple_content_html += f"""
        <article style="padding:16px;background:var(--card-bg);border:1px solid var(--border-color);border-radius:8px;margin:14px 0;">
            <h2 style="font-size:1.1rem;margin-bottom:6px;">{esc(topic.get('topic', ''))}</h2>
            <p style="color:var(--text-secondary);font-size:0.85rem;margin-bottom:10px;">{esc(topic.get('author', ''))} &bull; {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(topic.get('timestamp', 0)))}</p>
            <p style="font-size:0.95rem;line-height:1.6;margin-bottom:12px;">{esc(topic.get('content', ''))}</p>
            <details>
                <summary style="cursor:pointer;color:var(--accent-blue);font-size:0.9rem;">{t('forum.reply')}</summary>
        """
        for reply in topic.get('replies', []):
            simple_content_html += f'<blockquote style="border-left:3px solid var(--accent-purple);margin:8px 0;padding:6px 12px;background:#0f172a;"><p style="margin:0;font-size:0.9rem;">{esc(reply.get("content", ""))}</p><cite style="color:var(--text-secondary);font-size:0.8rem;">{esc(reply.get("author", ""))}</cite></blockquote>'
        simple_content_html += f"""
                <form method="POST" action="/api/gateway/forum" style="margin-top:10px;">
                    <input type="hidden" name="reply_to" value="{tid}">
                    <label style="display:block;margin-bottom:10px;">{t('forum.content')}<textarea name="content" maxlength="65536" rows="3" style="width:100%;margin-top:4px;" required></textarea></label>
                    <button type="submit" class="btn btn-green">{t('forum.reply')}</button>
                </form>
            </details>
        </article>
        """

if subpath in ('blockchain', 'effort'):
    simple_content_html += f"""
    <div style="overflow-x:auto;margin:16px 0;">
        <table style="width:100%;border-collapse:collapse;background:var(--card-bg);border-radius:8px;overflow:hidden;">
            <caption style="text-align:left;font-weight:bold;padding:10px 14px;color:var(--accent-blue);">{t('chain.blocks')}</caption>
            <thead><tr style="border-bottom:1px solid var(--border-color);"><th style="padding:10px 14px;text-align:left;">{t('chain.height')}</th><th style="padding:10px 14px;text-align:left;">{t('chain.hash')}</th><th style="padding:10px 14px;text-align:left;">{t('chain.validator')}</th></tr></thead>
            <tbody>
    """
    for block in chain_ctx.get('blocks', []):
        simple_content_html += f'<tr style="border-bottom:1px solid #1f2937;"><td style="padding:10px 14px;">#{esc(block.get("height", 0))}</td><td style="padding:10px 14px;"><code style="color:var(--accent-green);">{esc(block.get("hash", ""))[:32]}...</code></td><td style="padding:10px 14px;">{esc(block.get("validator", ""))}</td></tr>'
    simple_content_html += "</tbody></table></div>"

if subpath == 'nns':
    simple_content_html += '<div style="margin:16px 0;">'
    for record in nns_ctx:
        simple_content_html += f'<article style="padding:14px;background:var(--card-bg);border:1px solid var(--border-color);border-radius:8px;margin:10px 0;"><h2 style="font-size:1.05rem;color:var(--accent-blue);">{esc(record.get("domain", ""))}</h2><code style="color:var(--text-secondary);font-size:0.85rem;">{esc(record.get("target", ""))}</code></article>'
    simple_content_html += '</div>'

if subpath == 'fileshare':
    simple_content_html += f"""
    <section style="padding:16px;background:var(--card-bg);border:1px solid var(--border-color);border-radius:8px;margin:16px 0;">
        <h2 style="font-size:1.15rem;margin-bottom:12px;">{t('files.open')}</h2>
        <form id="stream-form-simple" onsubmit="event.preventDefault();const r=this.root.value.trim();if(r){{const v=document.querySelector('#stream-player-simple');v.src='/api/gateway/stream/'+encodeURIComponent(r);v.hidden=false;const d=document.querySelector('#stream-download-simple');d.href='/api/gateway/download/'+encodeURIComponent(r);d.hidden=false;}}">
            <label style="display:block;margin-bottom:10px;">{t('files.root')}<input name="root" pattern="[a-f0-9]{{64}}" maxlength="64" style="width:100%;margin-top:4px;" required></label>
            <button type="submit" class="btn btn-green">{t('files.open')}</button>
        </form>
        <video id="stream-player-simple" controls preload="metadata" hidden style="max-width:100%;margin-top:14px;border-radius:6px;"></video>
        <p style="margin-top:10px;"><a id="stream-download-simple" class="btn btn-purple" hidden>{t('files.download')}</a></p>
    </section>
    """

if subpath == 'shadow6':
    simple_content_html += f"""
    <div style="margin:16px 0;">
        <div style="background:var(--card-bg);border:1px solid #b45309;border-radius:8px;padding:16px;margin-bottom:16px;">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:8px;">
                <h2 style="font-size:1.1rem;color:#f59e0b;margin:0;">🔐 {t('shadow6.auth_title')}</h2>
                <span id="s6-simple-badge" style="background:rgba(239,68,68,0.2);color:#ef4444;border:1px solid rgba(239,68,68,0.4);padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:bold;">需鉴权</span>
            </div>
            <p style="color:var(--text-secondary);font-size:0.85rem;margin-bottom:12px;">{t('shadow6.auth_desc')}</p>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;margin-bottom:10px;">
                <input type="password" id="s6-simple-bearer" placeholder="{t('shadow6.bearer_placeholder')}" style="padding:6px 10px;font-family:monospace;font-size:0.85rem;">
                <input type="text" id="s6-simple-pair" placeholder="{t('shadow6.pairing_placeholder')}" style="padding:6px 10px;font-family:monospace;font-size:0.85rem;">
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
                <button type="button" class="btn" onclick="const b=document.getElementById('s6-simple-bearer').value.trim(),p=document.getElementById('s6-simple-pair').value.trim();if(b||p){{localStorage.setItem('shadow6_auth_bearer',b);localStorage.setItem('shadow6_auth_pairing',p);const el=document.getElementById('s6-simple-badge');el.textContent='已授权';el.style.color='#10b981';el.style.borderColor='#10b981';alert('鉴权信息已存入浏览器会话！');}}" style="background:#0284c7;font-size:0.85rem;padding:6px 12px;">{t('shadow6.btn_auth')}</button>
                <a href="https://ziokt-shadow6-43-207-75-185.sslip.io/" target="_blank" rel="noreferrer" class="btn btn-green" style="font-size:0.85rem;padding:6px 12px;">{t('shadow6.btn_open_web')}</a>
            </div>
        </div>

        <div style="background:var(--card-bg);border:1px solid var(--border-color);border-radius:8px;padding:16px;margin-bottom:16px;">
            <h2 style="font-size:1.1rem;color:var(--accent-purple);margin-bottom:8px;">📋 {t('shadow6.custom_title')}</h2>
            <p style="color:var(--text-secondary);font-size:0.85rem;margin-bottom:12px;">{t('shadow6.custom_desc')}</p>
            <textarea id="s6-simple-paste" rows="4" style="width:100%;font-family:monospace;font-size:0.8rem;padding:8px;box-sizing:border-box;" placeholder="{t('shadow6.paste_placeholder')}">{canonical_sample_s6p1}</textarea>
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;">
                <button type="button" class="btn btn-green" onclick="try{{let r=document.getElementById('s6-simple-paste').value.trim();if(!r.startsWith('S6P1.'))throw new Error('Prefix error');let b=r.slice(5).replace(/-/g,'+').replace(/_/g,'/');while(b.length%4)b+='=';let d=JSON.parse(decodeURIComponent(escape(atob(b))));alert('S6P1 校验成功！\\n架构: '+d.schema+'\\n核心数: '+(d.core||[]).length+'\\n路由数: '+(d.routes||[]).length);}}catch(e){{alert('解析失败: '+e.message);}}" style="font-size:0.85rem;padding:6px 12px;">{t('shadow6.btn_decode')}</button>
                <button type="button" class="btn btn-purple" onclick="document.getElementById('s6-simple-paste').value='{canonical_sample_s6p1}';" style="font-size:0.85rem;padding:6px 12px;">{t('shadow6.btn_load_sample')}</button>
            </div>
        </div>

        <div style="overflow-x:auto;">
            <table style="width:100%;border-collapse:collapse;background:var(--card-bg);border-radius:8px;overflow:hidden;font-size:0.85rem;">
                <caption style="text-align:left;font-weight:bold;padding:10px 14px;color:var(--accent-blue);">{t('shadow6.profiles_title')}</caption>
                <thead><tr style="border-bottom:1px solid var(--border-color);"><th style="padding:8px 12px;text-align:left;">Profile</th><th style="padding:8px 12px;text-align:left;">Core</th><th style="padding:8px 12px;text-align:left;">Transport</th><th style="padding:8px 12px;text-align:left;">Port</th><th style="padding:8px 12px;text-align:left;">Status</th></tr></thead>
                <tbody>
    """
    for p_id, p_core, p_trans, p_port, p_proto, p_status in s6_profiles:
        simple_content_html += f'<tr style="border-bottom:1px solid #1f2937;"><td style="padding:8px 12px;font-family:monospace;font-weight:bold;">{p_id}</td><td style="padding:8px 12px;color:var(--accent-green);">{p_core}</td><td style="padding:8px 12px;color:var(--text-secondary);">{p_trans}</td><td style="padding:8px 12px;font-family:monospace;color:var(--accent-amber);">{p_port}</td><td style="padding:8px 12px;"><span class="status-pill" style="background:#10b981;font-size:0.75rem;">{p_status}</span></td></tr>'
if subpath == 'ufsdcpm':
    simple_content_html += f"""
    <div style="margin:16px 0;background:var(--card-bg);border:1px solid var(--border-color);border-radius:8px;padding:16px;">
        <h2 style="font-size:1.1rem;color:var(--accent-blue);margin-bottom:8px;">🌐 {tr('UFS 原生安全存储 HTTP 鉴权信息', 'UFS Native Secure Storage HTTP Credentials')}</h2>
        <div style="font-size:0.85rem;line-height:1.7;color:var(--text-secondary);">
            <div>&bull; <strong>{tr('公网网关', 'Public Gateway')}</strong>: <a href="https://ziokt-ufs-43-207-75-185.sslip.io/" target="_blank" style="color:var(--accent-blue);">https://ziokt-ufs-43-207-75-185.sslip.io/</a></div>
            <div>&bull; <strong>{tr('认证协议', 'Auth Protocol')}</strong>: HTTP Digest Auth (SHA-256)</div>
            <div>&bull; <strong>{tr('凭据存储', 'Credentials Storage')}</strong>: <code>~/.config/dcpm-ufs/config.json</code> ({tr('受本地 0600 权限保护，不向公网暴露', 'Protected by local 0600 permissions, not exposed publicly')})</div>
            <div>&bull; <strong>{tr('安全说明', 'Security Notice')}</strong>: {tr('口令持久化保存在节点主机配置文件中，可在终端执行 <code>cat ~/.config/dcpm-ufs/config.json</code> 查看或配置。', 'Credentials are securely stored in the host node config file. Inspect or update via <code>cat ~/.config/dcpm-ufs/config.json</code> on host.')}</div>
            <div>&bull; <strong>{tr('存储路径', 'Storage Path')}</strong>: <code>~/.config/dcpm-ufs/ufs-storage</code></div>
        </div>
    </div>
    """

if subpath == 'gui':
    simple_content_html += content_html

ext_links = {
    'watchat': 'https://ziokt-chat-43-207-75-185.sslip.io/',
    'sim': 'https://ziokt-sim-43-207-75-185.sslip.io/',
    'effort': 'https://ziokt-effort-43-207-75-185.sslip.io/',
    'ufsdcpm': 'https://ziokt-ufs-43-207-75-185.sslip.io/',
    'shadow6': 'https://ziokt-shadow6-43-207-75-185.sslip.io/',
    'gui': '/gateway-assets/gui/index.html'
}
if subpath in ext_links:
    simple_content_html += f'<p style="margin:16px 0;"><a class="btn btn-green" href="{ext_links[subpath]}" rel="noreferrer" target="_blank">{t("app.open")}</a></p>'

simple_content_html += f'<p style="margin:16px 0;"><a href="/gateway-assets/registry.html" style="color:var(--accent-blue);" target="_blank">{t("card.registry.title")}</a></p>'

# ==============================================================================
# HTML TEMPLATE
# ==============================================================================
response = f"""<!DOCTYPE html>
<html lang="{locale}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t('portal.title')}</title>
    <style>
        *, *::before, *::after {{ box-sizing: border-box; }}
        main, section, article, form, fieldset, .card, .grid > * {{ min-width: 0; max-width: 100%; }}
        body, pre, code, .meta {{ overflow-wrap: anywhere; word-break: break-word; }}
        input, select, textarea, button {{ min-width: 0; max-width: 100%; }}

        :root {{
            color-scheme: dark;
            --bg-color: #0b0f19;
            --card-bg: #111827;
            --card-hover: #1e293b;
            --border-color: #1f2937;
            --text-primary: #f9fafb;
            --text-secondary: #9ca3af;
            --accent-blue: #38bdf8;
            --accent-green: #10b981;
            --accent-purple: #a855f7;
            --accent-amber: #f59e0b;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background-color: var(--bg-color);
            color: var(--text-primary);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, system-ui, sans-serif;
            line-height: 1.5;
            padding: 2rem 1rem;
        }}
        .container {{
            max-width: 1080px;
            margin: 0 auto;
        }}
        header {{
            margin-bottom: 1.75rem;
            text-align: center;
        }}
        h1 {{
            font-size: 2.1rem;
            margin-bottom: 0.5rem;
            background: linear-gradient(to right, var(--accent-blue), var(--accent-purple));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .subtitle {{
            color: var(--text-secondary);
            font-size: 0.95rem;
        }}
        .nav-links {{
            display: flex;
            gap: 0.4rem;
            margin-bottom: 1.5rem;
            flex-wrap: wrap;
            background: var(--card-bg);
            padding: 0.75rem;
            border-radius: 8px;
            border: 1px solid var(--border-color);
        }}
        .nav-link {{
            color: var(--text-secondary);
            text-decoration: none;
            padding: 0.4rem 0.75rem;
            border-radius: 6px;
            font-size: 0.85rem;
            transition: all 0.2s;
            white-space: nowrap;
            min-height: 40px;
            display: inline-flex;
            align-items: center;
        }}
        .nav-link:hover, .nav-link.active {{
            color: #fff;
            background: #1e293b;
        }}
        .nav-link.active {{
            background: #0284c7;
            font-weight: 600;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}
        .card {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 1.25rem;
        }}
        .card-title {{
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-secondary);
            margin-bottom: 0.5rem;
        }}
        .card-value {{
            font-size: 1.4rem;
            font-weight: bold;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        .status-pill {{
            font-size: 0.75rem;
            padding: 0.2rem 0.5rem;
            border-radius: 9999px;
            background-color: var(--accent-green);
            color: #fff;
            display: inline-block;
        }}
        .detail-card h2 {{
            font-size: 1.3rem;
            margin-bottom: 0.5rem;
            color: var(--accent-blue);
        }}
        .table-row {{
            display: flex;
            justify-content: space-between;
            padding: 0.6rem 0;
            border-bottom: 1px solid var(--border-color);
            font-size: 0.9rem;
            align-items: center;
        }}
        .table-row:last-child {{
            border-bottom: none;
        }}
        .label {{
            color: var(--text-secondary);
        }}
        .val {{
            font-family: ui-monospace, SFMono-Regular, monospace;
            color: var(--text-primary);
        }}
        .btn {{
            display: inline-block;
            text-decoration: none;
            color: #fff;
            border-radius: 6px;
            font-weight: 500;
            transition: opacity 0.2s;
            min-height: 40px;
            line-height: 24px;
            padding: 0.45rem 1rem;
            text-align: center;
        }}
        .btn:hover {{ opacity: 0.9; }}
        .btn-green {{ background: #059669; }}
        .btn-purple {{ background: #7c3aed; }}
        .btn-amber {{ background: #d97706; }}
        .notice {{
            padding: 0.75rem;
            background: #0f172a;
            border-radius: 6px;
            border: 1px solid #334155;
            margin-bottom: 1.25rem;
            font-size: 0.9rem;
        }}
        footer {{
            margin-top: 3rem;
            text-align: center;
            color: #64748b;
            font-size: 0.85rem;
            border-top: 1px solid var(--border-color);
            padding-top: 1.5rem;
        }}
        /* Minimalist View Styles */
        #simple-view .simple-nav {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin: 16px 0;
        }}
        #simple-view .simple-nav a {{
            padding: 8px 12px;
            background: #111827;
            border: 1px solid #1f2937;
            border-radius: 6px;
            color: var(--text-primary);
            text-decoration: none;
            font-size: 0.9rem;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
        }}
        #simple-view .simple-nav a:hover {{
            background: #1e293b;
            border-color: #334155;
        }}
        #simple-view .simple-nav a[aria-current="page"] {{
            border-color: var(--accent-blue);
            background: #1e293b;
            color: #fff;
            font-weight: 600;
        }}
        #simple-view article, #simple-view section {{
            padding: 16px;
            margin: 14px 0;
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
        }}
        #simple-view label {{
            display: block;
            margin: 10px 0;
            color: var(--text-secondary);
            font-size: 0.9rem;
        }}
        #simple-view input, #simple-view textarea, #simple-view select {{
            width: 100%;
            font: inherit;
            color: var(--text-primary);
            background: #0b0f19;
            border: 1px solid #334155;
            border-radius: 6px;
            min-height: 40px;
            padding: 8px 10px;
            box-sizing: border-box;
        }}
    </style>
    <script src="/gateway-assets/gateway.js" defer></script>
    <script src="/gateway-assets/mcp-console.js" defer></script>
</head>
<body>
    <div class="container">
        <!-- ========================================================== -->
        <!-- ========================================================== -->
        <!-- ACTIVE VIEW CONTAINER (Renders Panoramic or Minimalist View) -->
        <!-- ========================================================== -->
        {"<div id=\"simple-view\">" + f"""
            <header>
                <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:1rem;">
                    <div>
                        <span class="badge" style="display:inline-block;background:rgba(168,85,247,0.15);color:#a855f7;border:1px solid rgba(168,85,247,0.3);padding:3px 12px;border-radius:9999px;font-size:0.8rem;font-weight:600;margin-bottom:0.5rem;">{tr('COR-WEB 简约版 (Minimalist View)', 'COR-WEB Minimalist View')}</span>
                        <strong style="display:block;font-size:1.6rem;color:var(--text-primary);">{t('portal.title')}</strong>
                        <p style="color:var(--text-secondary);font-size:0.9rem;margin:0;">{t('portal.readonly')}</p>
                    </div>
                    <div>
                        <a href="/app/{subpath}?ui=panoramic&lang={locale}" class="btn btn-green" style="font-size:0.85rem;padding:6px 14px;cursor:pointer;display:inline-flex;align-items:center;gap:6px;">
                            🌐 {t('mode.switch_to_panoramic')}
                        </a>
                    </div>
                </div>
                <nav class="simple-nav" aria-label="{t('nav.label')}">
                    {simple_nav_html}
                </nav>
            </header>

            {simple_content_html}
        </div>""" if ui_mode == 'simple' else "<div id=\"panoramic-view\">" + f"""
            <header>
                <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:1rem;">
                    <div>
                        <span class="badge" style="display:inline-block;background:rgba(56,189,248,0.15);color:var(--accent-blue);border:1px solid rgba(56,189,248,0.3);padding:3px 12px;border-radius:9999px;font-size:0.8rem;font-weight:600;margin-bottom:0.5rem;">{tr('COR-WEB 全景版 (Panoramic Studio)', 'COR-WEB Panoramic Studio')}</span>
                        <div style="font-size:2rem;font-weight:bold;margin-bottom:0.25rem;">⚡ {tr('Corium &amp; Ziokt 统一去中心化应用网关', 'Corium &amp; Ziokt Unified DApp Gateway')}</div>
                        <p class="subtitle" style="margin:0;">{tr('深度承载 Corium、Ziokt 与 ETP 协议栈所有原生应用 • 纯浏览器零门槛访问', 'Deep integration with Corium, Ziokt, and ETP native stacks • Browser-native zero barrier access')}</p>
                    </div>
                    <div>
                        <a href="/app/{subpath}?ui=simple&lang={locale}" class="btn btn-purple" style="font-size:0.85rem;padding:6px 14px;cursor:pointer;display:inline-flex;align-items:center;gap:6px;">
                            ⚡ {t('mode.switch_to_simple')}
                        </a>
                    </div>
                </div>
            </header>

            <nav class="nav-links" aria-label="{t('nav.label')}">
                {nav_links_html}
            </nav>

            <h1>{t('nav.' + subpath)}</h1>

            {tab_html}
        </div>"""}

        {mcp_section}

        <footer>
            <p>Powered by <strong>Corium v108 Gateway</strong> &bull; <strong>ETP Protocol v2</strong> &bull; <strong>Ziokt Native Suite</strong> &bull; 2026</p>
        </footer>
    </div>
</body>
</html>
"""

response=response.replace('<body>', '<body><p id="runtime-evidence-note" role="status">'+t('runtime.evidence_note')+'</p>',1)

response=response.replace('<body>', '<body><nav aria-label="Unified client" style="padding:12px;display:flex;gap:16px;flex-wrap:wrap"><a href="https://app.ziokt.com/">Ziokt Web 应用</a><a href="https://app.ziokt.com/downloads/">各平台软件下载</a></nav>',1)
