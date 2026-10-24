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
      if (['SCRIPT','STYLE','PRE','CODE','TEXTAREA','OPTION','SELECT'].includes(node.parentElement?.tagName) || node.parentElement?.closest('form') || node.parentElement?.closest('#ziokt-top-bar')) continue;
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
  for (const code of Object.keys(dictionaries)) {
    const label = code.startsWith('zh') ? '简体中文' : (dictionaries[code]['language.name'] || 'English');
    select.add(new Option(label, code));
  }
  function syncLocaleSelection() {
    // URL/rendered locale wins over stale browser-restored form values.
    for (const option of select.options) {
      option.defaultSelected = option.value === locale;
      option.selected = option.value === locale;
    }
    select.value = locale;
  }
  syncLocaleSelection(); langBox.append(langLabel, select);

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
  syncLocaleSelection();
  window.addEventListener('pageshow', () => {
    syncLocaleSelection();
    // Some browsers restore persisted form state after dispatching pageshow.
    requestAnimationFrame(syncLocaleSelection);
  });

  // Older immutable DApp templates contain literal link labels. Keep those
  // published templates readable without changing their content-addressed bytes.
  const unifiedLinks = document.querySelector('nav[aria-label="Unified client"]');
  unifiedLinks?.querySelectorAll('a').forEach(link => {
    const url = new URL(link.href);
    if (url.origin !== 'https://app.ziokt.com') return;
    if (url.pathname === '/') link.dataset.i18n = 'links.web_app';
    if (url.pathname === '/downloads/') link.dataset.i18n = 'links.downloads';
  });
  const inspection = document.getElementById('s6p1-inspection-box');
  if (inspection && !document.getElementById('s6p1-example-notice')) {
    const notice = document.createElement('p');
    notice.id = 's6p1-example-notice';
    notice.dataset.i18n = 'shadow6.example_notice';
    notice.style.cssText = 'margin:0 0 1rem;color:var(--text-secondary);font-size:0.85rem';
    inspection.querySelector('#s6p1-summary-grid')?.before(notice);
  }
  if (inspection && Array.isArray(window.S6_PROFILES)) {
    const example = {schema:'shadow6.protocol-envelope.v1',version:1,role:'client',
      purpose:'example:fictional',identity:{alias:'Fictional example'},components:{},credentials:{},
      core:[...new Set(window.S6_PROFILES.map(profile => profile.core))],
      routes:window.S6_PROFILES.map((profile,index) => ({core:profile.core,
        transport:profile.transport,host:'192.0.2.1',port:24000+index}))};
    const sample = 'S6P1.' + btoa(JSON.stringify(example)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
    const input = document.getElementById('s6p1-textarea');
    const previousSample = window.CANONICAL_SAMPLE_S6P1;
    const loadSample = () => {
      window.CANONICAL_SAMPLE_S6P1 = sample;
      input.value = sample;
      window.handleParseS6P1();
    };
    // Also replaces the sample button on already-published templates. A pending
    // legacy address lookup cannot replace this nonempty sample or imported text.
    window.loadFictionalS6Example = loadSample;
    window.discoverS6Example = loadSample;
    window.handleLoadSampleS6P1 = loadSample;
    if (!input.value.trim() || input.value === previousSample) loadSample();
  }

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
  async function identity(create = false, imported = null) {
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
    if (!create && !imported) { database.close(); return null; }
    const keys = imported || await crypto.subtle.generateKey('Ed25519',false,['sign','verify']);
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
    const identityPanel=document.createElement('div'),identityStatus=document.createElement('p');identityStatus.dataset.forumIdentity='';
    const createIdentity=document.createElement('button');createIdentity.type='button';createIdentity.textContent=t('forum.createIdentity');
    const importLabel=document.createElement('label');importLabel.textContent=t('forum.importIdentity');
    const importIdentity=document.createElement('input');importIdentity.type='file';importIdentity.accept='application/json,.json';importLabel.append(importIdentity);
    identityPanel.append(identityStatus,createIdentity,importLabel);form.prepend(identityPanel);
    const submit=form.querySelector('button[type="submit"]');submit.disabled=true;
    async function showIdentity() {
      const keys=await identity();submit.disabled=!keys;
      identityStatus.textContent=keys?t('forum.identity')+': '+hex(await crypto.subtle.digest('SHA-256',await crypto.subtle.exportKey('raw',keys.publicKey))):t('forum.readOnly');
      createIdentity.disabled=!!keys;importIdentity.disabled=!!keys;
    }
    createIdentity.onclick=async()=>{try{await identity(true);await showIdentity()}catch(error){identityStatus.textContent=t('forum.failed')+' '+error.message}};
    importIdentity.onchange=async()=>{try{
      const file=importIdentity.files[0];if(!file||file.size>8192)throw new Error('Identity file limit');
      const value=JSON.parse(await file.text());
      if(Object.keys(value).sort().join(',')!=='private_key_pkcs8,public_key'||!/^[a-f0-9]{64}$/.test(value.public_key))throw new Error('Invalid identity format');
      const privateKey=await crypto.subtle.importKey('pkcs8',Uint8Array.from(atob(value.private_key_pkcs8),c=>c.charCodeAt(0)),{name:'Ed25519'},false,['sign']);
      const publicKey=await crypto.subtle.importKey('raw',Uint8Array.from(value.public_key.match(/../g),h=>parseInt(h,16)),{name:'Ed25519'},true,['verify']);
      const challenge=crypto.getRandomValues(new Uint8Array(32)),signature=await crypto.subtle.sign('Ed25519',privateKey,challenge);
      if(!await crypto.subtle.verify('Ed25519',publicKey,signature,challenge))throw new Error('Identity key mismatch');
      await identity(false,{privateKey,publicKey});importIdentity.value='';await showIdentity();
    }catch(error){identityStatus.textContent=t('forum.failed')+' '+error.message}};
    await showIdentity();
    const status = document.createElement('p'); status.setAttribute('role','status'); status.setAttribute('aria-live','polite'); form.append(status);
    form.addEventListener('submit',async event => {
      event.preventDefault(); const button=form.querySelector('button[type="submit"]'); button.disabled=true; status.textContent=t('forum.sending');
      try {
        const title=form.querySelector('[name="topic"]')?.value || '', content=form.querySelector('[name="content"]').value;
        const reply_to=form.querySelector('[name="reply_to"]')?.value || '';
        const keys=await identity();if(!keys)throw new Error(t('forum.readOnly'));
        const headers={'Content-Type':'application/json'};
        const node=await fetch('/api/gateway/status').then(r=>r.json());
        const payload={schema:'ziokt.forum.v3',network:node.network,title,content,reply_to,timestamp:Math.floor(Date.now()/1000),nonce:hex(crypto.getRandomValues(new Uint8Array(32))),public_key:hex(await crypto.subtle.exportKey('raw',keys.publicKey))};
        payload.signature=hex(await crypto.subtle.sign('Ed25519',keys.privateKey,new TextEncoder().encode(canonical(payload))));
        const response=await fetch('/api/gateway/forum',{method:'POST',headers,body:JSON.stringify(payload)});
        const result=await response.json(); if (!response.ok) throw new Error(result.error);
        status.textContent=t('forum.sent');
        setTimeout(()=>location.assign(location.pathname),800);
      } catch (error) { status.textContent=t('forum.failed')+' '+error.message; }
      finally { button.disabled=false; }
    });
  }
})();
