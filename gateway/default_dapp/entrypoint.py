import json
import time

# Bootstrap embeds the versioned, external dictionary when publishing to P2P.
MESSAGES = {}

def esc(value):
    return str(value).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;').replace("'",'&#39;')

query = request.get('query', {})
locale = request.get('locale', 'en-US')
locale = query.get('lang',[locale])[0]
if locale in ('zh','zh-cn'): locale = 'zh-CN'
if locale in ('en','en-us'): locale = 'en-US'
if locale not in MESSAGES: locale = 'en-US'
messages = MESSAGES.get(locale,{})
def t(key):
    return esc(messages.get(key,MESSAGES.get('en-US',{}).get(key,key)))

path = request.get('path', [])
page = path[0] if path else request.get('app_id','explorer')
aliases = {'explorer':'overview','hub':'overview','corium':'overview','files':'fileshare','ufs':'ufsdcpm','dcpm':'ufsdcpm','chain':'blockchain','tri':'blockchain','ano':'zda','chat':'watchat','tunnel':'onion','sim':'sim-manager','ecosystem':'overview'}
page = aliases.get(page,page)
components = {'cbb':'corium','overview':'gateway','forum':'gateway','fileshare':'gateway','onion':'etp','zda':'zda','safefs':'safefs','ufsdcpm':'ufs','tc16':'tc16','blockchain':'corium','watchat':'watchat','sim-manager':'sim_manager','effort':'corium','nns':'corium','nodes':'corium','vault':'safefs','board':'gateway'}
if page not in components: page = 'overview'
ctx = api.get_node_context()
chain = ctx.get('blockchain',{})
dht = ctx.get('dht',{})
navigation = ''
for key in components:
    if key not in ('nodes','vault','board'):
        navigation += '<a href="/app/explorer/'+key+'?lang='+locale+'"'+(' aria-current="page"' if key==page else '')+'>'+t('nav.'+key)+'</a>'

body = '<h1>'+t('nav.'+page)+'</h1><p>'+t('portal.readonly')+'</p>'
if page == 'overview':
    body += '<div class="grid"><article><h2>'+t('chain.height')+'</h2><p>'+esc(chain.get('height',0))+'</p></article><article><h2>'+t('chain.transactions')+'</h2><p>'+esc(chain.get('tx_count',0))+'</p></article><article><h2>'+t('dht.objects')+'</h2><p>'+esc(dht.get('chunks_count',0))+'</p></article></div>'
if page in ('forum','board'):
    body += '<section><h2 data-i18n="forum.new_topic">'+t('forum.new_topic')+'</h2><form><label>'+t('forum.topic')+'<input name="topic" maxlength="256" required></label><label>'+t('forum.content')+'<textarea name="content" maxlength="65536" required></textarea></label><button type="submit" data-i18n="forum.submit">'+t('forum.submit')+'</button></form></section>'
    for topic in ctx.get('forum',{}).get('topics',[]):
        tid = esc(topic.get('id',''))
        body += '<article><h2>'+esc(topic.get('topic',''))+'</h2><p class="meta">'+esc(topic.get('author',''))+' · '+esc(topic.get('timestamp',0))+'</p><p class="content">'+esc(topic.get('content',''))+'</p><details><summary>'+t('forum.reply')+'</summary>'
        for reply in topic.get('replies',[]):
            body += '<blockquote><p>'+esc(reply.get('content',''))+'</p><cite>'+esc(reply.get('author',''))+'</cite></blockquote>'
        body += '<form><input type="hidden" name="reply_to" value="'+tid+'"><label>'+t('forum.content')+'<textarea name="content" maxlength="65536" required></textarea></label><button type="submit" data-i18n="forum.reply">'+t('forum.reply')+'</button></form></details></article>'
if page in ('blockchain','effort'):
    body += '<div class="scroll"><table><caption>'+t('chain.blocks')+'</caption><thead><tr><th>'+t('chain.height')+'</th><th>'+t('chain.hash')+'</th><th>'+t('chain.validator')+'</th></tr></thead><tbody>'
    for block in chain.get('blocks',[]):
        body += '<tr><td>'+esc(block.get('height',0))+'</td><td>'+esc(block.get('hash',''))+'</td><td>'+esc(block.get('validator',''))+'</td></tr>'
    body += '</tbody></table></div>'
if page == 'nns':
    for record in ctx.get('nns',[]):
        body += '<article><h2>'+esc(record.get('domain',''))+'</h2><code>'+esc(record.get('target',''))+'</code></article>'
if page == 'fileshare':
    body += '<section><h2>'+t('files.open')+'</h2><form id="stream-form"><label>'+t('files.root')+'<input name="root" pattern="[a-f0-9]{64}" maxlength="64" required></label><button type="submit">'+t('files.open')+'</button></form><video id="stream-player" controls preload="metadata" hidden></video><a id="stream-download" hidden>'+t('files.download')+'</a></section>'
links = {'watchat':'https://ziokt-chat-43-207-75-185.sslip.io/','sim-manager':'https://ziokt-sim-43-207-75-185.sslip.io/','effort':'https://ziokt-effort-43-207-75-185.sslip.io/','ufsdcpm':'https://ziokt-ufs-43-207-75-185.sslip.io/api/stats'}
if page in links:
    body += '<p><a class="button" href="'+links[page]+'" rel="noreferrer">'+t('app.open')+'</a></p>'
body += '<p><a href="/gateway-assets/registry.html">Corium 权重白名单 / Weight registry</a></p>'
body += '<section id="mcp-console" data-component="'+components[page]+'"><h2>'+t('mcp.title')+'</h2><p>'+t('mcp.help')+'</p><button id="mcp-connect" type="button">'+t('mcp.connect')+'</button><button id="mcp-disconnect" type="button" hidden>'+t('mcp.disconnect')+'</button><form id="mcp-form" hidden><label>'+t('mcp.tool')+'<select id="mcp-tool"></select></label><p id="mcp-description"></p><label>'+t('mcp.arguments')+'<textarea id="mcp-arguments" rows="8">{}</textarea></label><button type="submit">'+t('mcp.execute')+'</button></form><pre id="mcp-result" role="status" aria-live="polite"></pre></section>'
response = '<!doctype html><html lang="'+locale+'"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+t('portal.title')+'</title><style>:root{color-scheme:dark;--bg:#0b1220;--card:#142035;--text:#f1f5f9;--muted:#b5c4d8;--accent:#7dd3fc;--line:#52657e}*{box-sizing:border-box}body{background:var(--bg);color:var(--text);font:16px/1.6 system-ui;margin:0;padding:24px}main{max-width:1100px;margin:auto}nav{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}a{color:var(--accent)}nav a,button,.button{padding:10px 14px;min-height:44px}a[aria-current]{outline:2px solid var(--accent)}article,section{padding:20px;margin:16px 0;background:var(--card);border:1px solid var(--line);border-radius:10px}label{display:block;margin:12px 0}input,textarea,select,button{font:inherit;color:var(--text);background:var(--bg);border:1px solid var(--line);border-radius:6px;min-height:44px;padding:10px}input,textarea{width:100%}button{cursor:pointer}button:disabled{opacity:.5;cursor:wait}:focus-visible{outline:3px solid var(--accent);outline-offset:3px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px}.content,pre{white-space:pre-wrap;overflow-wrap:anywhere}.meta,cite{color:var(--muted);overflow-wrap:anywhere}.scroll{overflow:auto}th,td{text-align:left;padding:10px;max-width:300px;overflow-wrap:anywhere}video{max-width:100%}code{overflow-wrap:anywhere}</style><script src="/gateway-assets/gateway.js" defer></script><script src="/gateway-assets/mcp-console.js" defer></script></head><body><main><header><strong>'+t('portal.title')+'</strong><nav aria-label="'+t('nav.label')+'">'+navigation+'</nav></header>'+body+'</main></body></html>'
