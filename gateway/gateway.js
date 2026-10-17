/* Public rendering never signs with a node key. User keys are non-extractable. */
(async () => {
  'use strict';
  const dictionaries = await fetch('/gateway-assets/i18n.json').then(r => r.json());
  const aliases = language => Object.keys(dictionaries).find(k => k.toLowerCase() === language?.toLowerCase()) || (language?.startsWith('zh') ? 'zh-CN' : 'en-US');
  const cookie = document.cookie.split('; ').find(s => s.startsWith('ziokt_lang='))?.split('=')[1];
  let locale = aliases(new URL(location.href).searchParams.get('lang') || cookie || localStorage.getItem('ziokt_lang') || navigator.languages?.[0] || navigator.language);
  const original = new WeakMap();
  const t = key => dictionaries[locale][key] || dictionaries['en-US'][key] || key;
  function translate() {
    document.documentElement.lang = locale;
    document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      if (['SCRIPT','STYLE','PRE','CODE','TEXTAREA'].includes(node.parentElement?.tagName) || node.parentElement?.closest('form')) continue;
      if (!original.has(node)) original.set(node, node.nodeValue);
      const source = original.get(node), clean = source.trim();
      const mapping = dictionaries['zh-CN'];
      const key = Object.keys(mapping).find(k => mapping[k] === clean);
      if (key) node.nodeValue = source.replace(clean,t(key));
    }
  }
  const toolbar = document.createElement('div');
  toolbar.id = 'ziokt-top-bar';
  toolbar.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin:12px auto;max-width:1080px;padding:8px 16px;background:#111827;border:1px solid #1f2937;border-radius:8px;position:relative;z-index:30;flex-wrap:wrap;gap:10px';

  const langBox = document.createElement('div');
  langBox.style.cssText = 'display:flex;align-items:center;gap:8px';
  const langLabel = document.createElement('span');
  langLabel.textContent = '🌐 Language:';
  langLabel.style.cssText = 'font-size:0.85rem;color:#9ca3af';
  const select = document.createElement('select'); select.setAttribute('aria-label','Language / 语言');
  select.style.cssText = 'min-height:36px;padding:4px 8px;background:#172338;color:#fff;border:1px solid #64748b;border-radius:6px;font-size:0.85rem';
  for (const code of Object.keys(dictionaries)) select.add(new Option(dictionaries[code]['language.name'], code));
  select.value = locale; langBox.append(langLabel, select);

  const uiCookie = document.cookie.split('; ').find(s => s.startsWith('ziokt_ui='))?.split('=')[1];
  let uiMode = new URL(location.href).searchParams.get('ui') || uiCookie || localStorage.getItem('ziokt_ui') || 'panoramic';
  if (uiMode !== 'simple' && uiMode !== 'panoramic') uiMode = 'panoramic';

  const modeBox = document.createElement('div');
  modeBox.style.cssText = 'display:flex;align-items:center;gap:6px';
  const modeSpan = document.createElement('span');
  modeSpan.textContent = t('mode.label') + ':';
  modeSpan.style.cssText = 'font-size:0.85rem;color:#9ca3af';

  const btnPanoramic = document.createElement('button');
  btnPanoramic.type = 'button';
  btnPanoramic.textContent = '🌐 ' + t('mode.panoramic');
  btnPanoramic.style.cssText = 'padding:6px 12px;border-radius:6px;font-size:0.82rem;font-weight:600;cursor:pointer;border:1px solid #334155;transition:all 0.2s;' + (uiMode === 'panoramic' ? 'background:#0284c7;color:#fff;border-color:#38bdf8;' : 'background:#1e293b;color:#94a3b8;');

  const btnSimple = document.createElement('button');
  btnSimple.type = 'button';
  btnSimple.textContent = '⚡ ' + t('mode.minimalist');
  btnSimple.style.cssText = 'padding:6px 12px;border-radius:6px;font-size:0.82rem;font-weight:600;cursor:pointer;border:1px solid #334155;transition:all 0.2s;' + (uiMode === 'simple' ? 'background:#0284c7;color:#fff;border-color:#38bdf8;' : 'background:#1e293b;color:#94a3b8;');

  modeBox.append(modeSpan, btnPanoramic, btnSimple);
  toolbar.append(langBox, modeBox);
  document.body.prepend(toolbar);

  function applyUiMode(mode) {
    uiMode = mode;
    localStorage.setItem('ziokt_ui', mode);
    document.cookie = `ziokt_ui=${mode}; Path=/; SameSite=Lax`;
    const next = new URL(location.href);
    next.searchParams.set('ui', mode);
    const pano = document.querySelector('#panoramic-view');
    const simp = document.querySelector('#simple-view');
    if (pano && simp) {
      if (mode === 'simple') { pano.hidden = true; simp.hidden = false; }
      else { pano.hidden = false; simp.hidden = true; }
      btnPanoramic.style.cssText = 'padding:6px 12px;border-radius:6px;font-size:0.82rem;font-weight:600;cursor:pointer;border:1px solid #334155;transition:all 0.2s;' + (mode === 'panoramic' ? 'background:#0284c7;color:#fff;border-color:#38bdf8;' : 'background:#1e293b;color:#94a3b8;');
      btnSimple.style.cssText = 'padding:6px 12px;border-radius:6px;font-size:0.82rem;font-weight:600;cursor:pointer;border:1px solid #334155;transition:all 0.2s;' + (mode === 'simple' ? 'background:#0284c7;color:#fff;border-color:#38bdf8;' : 'background:#1e293b;color:#94a3b8;');
      history.replaceState(null, '', next.pathname + next.search);
    } else {
      location.assign(next.pathname + next.search);
    }
  }
  window.applyUiMode = applyUiMode;
  btnPanoramic.addEventListener('click', () => applyUiMode('panoramic'));
  btnSimple.addEventListener('click', () => applyUiMode('simple'));

  const initPano = document.querySelector('#panoramic-view');
  const initSimp = document.querySelector('#simple-view');
  if (initPano && initSimp) {
    if (uiMode === 'simple') { initPano.hidden = true; initSimp.hidden = false; }
    else { initPano.hidden = false; initSimp.hidden = true; }
  }

  select.addEventListener('change', () => {
    locale = select.value; localStorage.setItem('ziokt_lang',locale);
    document.cookie = `ziokt_lang=${locale}; Path=/; SameSite=Lax; Secure`;
    const next=new URL(location.href);next.searchParams.set('lang',locale);location.assign(next.pathname+next.search);
  });
  translate();
  const hex = bytes => Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2,'0')).join('');
  const canonical = value => JSON.stringify(Object.fromEntries(Object.keys(value).sort().map(k => [k,value[k]])));
  async function identity() {
    const database = await new Promise((resolve,reject) => {
      const request = indexedDB.open('ziokt-identity',1);
      request.onupgradeneeded = () => request.result.createObjectStore('keys');
      request.onerror = () => reject(request.error); request.onsuccess = () => resolve(request.result);
    });
    const existing = await new Promise((resolve,reject) => {
      const request = database.transaction('keys').objectStore('keys').get('forum');
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
    if (existing) { database.close(); return existing; }
    const keys = await crypto.subtle.generateKey('Ed25519',false,['sign','verify']);
    // Add rather than overwrite handles concurrent first-use tabs.
    await new Promise((resolve,reject) => {
      const tx = database.transaction('keys','readwrite'); tx.objectStore('keys').add(keys,'forum');
      tx.oncomplete = resolve; tx.onerror = () => reject(tx.error);
    }); database.close(); return keys;
  }
  for (const form of document.querySelectorAll('form')) {
    if (!form.querySelector('[name="topic"], [name="reply_to"]')) continue;
    form.method = 'POST'; form.action = '/api/gateway/forum';
    for (const field of form.querySelectorAll('input:not([type="hidden"]),textarea')) {
      field.required = field.name !== 'author';
      if(field.closest('label'))continue;
      const fieldLabel = document.createElement('label'); fieldLabel.textContent = t('forum.' + field.name);
      fieldLabel.style.cssText='display:block;flex:1'; field.before(fieldLabel); fieldLabel.append(field);
      field.style.minHeight='44px';
    }
    const modeLabel = document.createElement('label'); modeLabel.textContent=t('forum.mode');
    const mode = document.createElement('select'); mode.add(new Option(t('forum.user'),'user')); mode.add(new Option(t('forum.admin'),'admin'));
    mode.style.minHeight='44px'; modeLabel.append(mode); form.prepend(modeLabel);
    const tokenLabel = document.createElement('label'); tokenLabel.textContent=t('forum.token'); tokenLabel.hidden=true;
    const token = document.createElement('input'); token.type='password'; token.autocomplete='off'; token.style.minHeight='44px';
    tokenLabel.append(token); modeLabel.after(tokenLabel);
    mode.onchange = () => { tokenLabel.hidden = mode.value !== 'admin'; token.value=''; };
    const status = document.createElement('p'); status.setAttribute('role','status'); status.setAttribute('aria-live','polite'); form.append(status);
    form.addEventListener('submit',async event => {
      event.preventDefault(); const button=form.querySelector('button[type="submit"]'); button.disabled=true; status.textContent=t('forum.sending');
      try {
        const title=form.querySelector('[name="topic"]')?.value || '', content=form.querySelector('[name="content"]').value;
        const reply_to=form.querySelector('[name="reply_to"]')?.value || '';
        let payload={title,content,reply_to}; const headers={'Content-Type':'application/json'};
        if (mode.value==='admin') { if (!token.value) throw new Error(t('forum.token')); headers.Authorization='Bearer '+token.value; }
        else {
          const keys=await identity();
          const node=await fetch('/api/gateway/status').then(r=>r.json());
          payload={schema:'ziokt.forum.v3',network:node.network,title,content,reply_to,timestamp:Math.floor(Date.now()/1000),nonce:hex(crypto.getRandomValues(new Uint8Array(32))),public_key:hex(await crypto.subtle.exportKey('raw',keys.publicKey))};
          payload.signature=hex(await crypto.subtle.sign('Ed25519',keys.privateKey,new TextEncoder().encode(canonical(payload))));
        }
        const response=await fetch('/api/gateway/forum',{method:'POST',headers,body:JSON.stringify(payload)});
        const result=await response.json(); if (!response.ok) throw new Error(result.error);
        token.value=''; status.textContent=t('forum.sent');
        setTimeout(()=>location.assign(location.pathname),800);
      } catch (error) { status.textContent=t('forum.failed')+' '+error.message; }
      finally { button.disabled=false; }
    });
  }
})();
