'use strict';
(()=>{let credential='';let compilerConfig=null;const $=s=>document.querySelector(s);const prefix=new URL('.',document.currentScript.src).pathname.replace(/\/$/,'');const origin=location.origin;$('#origin').value=origin;$('#enroll-command').textContent='python -m openci worker-enroll --server '+origin+prefix+' --invite-file invite.json --worker my-node --signing-key-file worker.key --credential-file worker.token';

const I18N = {
  'zh-CN': {
    title: 'OpenCI · 节点准入与构建',
    heroTitle: '把编译交给协作，<br>把信任留给证据。',
    flowLabel: '构建流程',
    flow1: '<strong>01 · 准入</strong><br>项目、架构与资源额度',
    flow2: '<strong>02 · 编译</strong><br>受限执行器与签名产物',
    flow3: '<strong>03 · 核验</strong><br>独立重建后提交原生结算',
    compilerReading: '正在读取节点编译能力…',
    compilerUnavailable: '轻量编译器暂不可用；完整 OCI Worker 准入与构建记录仍可查询。',
    compilerSummary: (arch, targets, cross) => `节点架构 ${arch} · 已批准目标 ${targets.join(', ')} · ${cross ? '交叉编译已启用' : '使用本机目标'}`,
    heroDesc: '独立 Worker、签名回执与原生治理。普通构建成功不会自动取得链上奖励或出块权。',
    downloadsLink: '下载组件 · Downloads',
    joinTitle: '1 · 接入节点',
    joinDesc: '向运营者获取限时邀请，下载邀请文件。在自己的设备上生成并保管签名密钥。邀请只授权指定项目和资源额度。',
    labelOrigin: '当前 Controller',
    joinNote: '运营者完成镜像、故障域和来源核验后，节点才能参与独立验证。节点准入不代表硬件认证。',
    sessionTitle: '2 · 管理工作区',
    labelToken: '应用专用凭证',
    loginDesc: '凭证仅保存在当前页面内存。关闭页面或退出会清除；不要填写钱包私钥。',
    btnLogin: '连接',
    btnLogout: '退出',
    sessionDisconnected: '尚未连接',
    inviteTitle: '3 · 审批限时邀请',
    labelProjects: '项目（逗号分隔）',
    labelArch: '架构',
    labelCpu: 'CPU 上限',
    labelMemory: '内存 MiB',
    labelSlots: '并发槽位',
    labelTtl: '有效期（秒）',
    inviteDesc: '邀请默认授予 community Worker。Trusted 身份、签名镜像和独立故障域需要运营者另行核验，不在此页面自动提升权限。',
    btnInvite: '审批并下载一次性邀请',
    inviteDownloaded: d => `邀请已下载 / Invitation downloaded. ${d}`,
    buildTitle: '构建与核验记录',
    labelProject: '项目 ID',
    btnInspect: '查询构建',
    summarySubmit: '提交轻量 C 编译任务',
    labelSubmitProject: '项目 ID',
    labelCompileSource: '预处理 C 文件（unit.i，最大 128 KiB）',
    labelCompileTarget: '产物目标架构',
    submitDesc: '客户端架构必须等于节点架构。目标不同则需要节点启用并批准对应交叉工具链；此入口生成对象文件，不替代完整 LFS 的原生工具链构建。',
    btnSubmit: '上传源码并提交任务',
    submitResult: id => `任务已提交：${id}；等待符合架构与工具链准入的 Worker。`,
    summaryRebuild: '独立重建与核验',
    labelPipelineId: '流水线 ID',
    labelTaskId: '原始任务 ID',
    btnRebuild: '选择独立 Worker 并提交重建',
    labelVerifyPipeline: '重建流水线 ID',
    labelVerifyFirst: '第一份任务 ID',
    labelVerifySecond: '独立任务 ID',
    btnVerify: '核验签名产物与独立故障域',
    lightTitle: 'OpenCI · 轻量分布式 C 编译',
    lightDesc: '设备架构必须与连接节点一致。仅处理最多 128 KiB 的预处理 C 翻译单元，生成最多 1 MiB 的 ELF 对象，不运行任务代码。跨架构目标须由节点另行启用工具链。',
    lightArch: '开始前检测设备与节点架构。',
    lightControllerLink: 'OpenCI 节点准入与独立核验',
    labelLightWorkerId: 'Worker ID',
    labelLightInvite: '运营者批准的限时邀请 JSON',
    btnLightEnroll: '生成专用密钥并接入',
    labelLightImport: '或导入自己的 Worker 私有凭证',
    lightCredDesc: '私有凭证含专用密钥与 Token，请妥善保存。页面只在内存中使用，关闭即清除。请勿导入钱包密钥。',
    btnLightStart: '开始轻量编译',
    btnLightStop: '停止轻量编译',
    btnLightLogout: '清除凭证',
    lightStatusInitial: '尚未接入。任务完成、独立核验、链上登记和奖励到账分别确认。',
    footerText: '连接状态、Worker 准入、产物核验、原生共识接纳与结算分别记录。未验证的维度保持 not_assessed。'
  },
  'en': {
    title: 'OpenCI · Node Admission & Builds',
    heroTitle: 'Delegate compilation to collaboration,<br>ground trust in verifiable evidence.',
    flowLabel: 'Build Pipeline Flow',
    flow1: '<strong>01 · Admission</strong><br>Projects, architecture & quotas',
    flow2: '<strong>02 · Compilation</strong><br>Constrained runner & signed artifacts',
    flow3: '<strong>03 · Verification</strong><br>Independent rebuild & native settlement',
    compilerReading: 'Reading node compilation capabilities…',
    compilerUnavailable: 'Lightweight compiler unavailable; full OCI Worker admission and build records remain accessible.',
    compilerSummary: (arch, targets, cross) => `Node arch ${arch} · Approved targets ${targets.join(', ')} · ${cross ? 'Cross-compilation enabled' : 'Host target only'}`,
    heroDesc: 'Independent workers, signed receipts and native governance. Successful builds do not automatically grant on-chain rewards or block production rights.',
    downloadsLink: 'Downloads & Components',
    joinTitle: '1 · Join as a Worker',
    joinDesc: 'Obtain a scoped time-bounded invite from the operator and download the invitation file. Generate and retain the signing key on your device. Invites authorize only designated projects and quotas.',
    labelOrigin: 'Current Controller',
    joinNote: 'Nodes participate in independent verification only after the operator verifies images, failure domains, and provenance. Node admission is not hardware certification.',
    sessionTitle: '2 · Operator Workspace',
    labelToken: 'Application Token',
    loginDesc: 'Credentials reside in page memory only. Closing the page or logging out clears them; never enter wallet private keys.',
    btnLogin: 'Connect',
    btnLogout: 'Disconnect',
    sessionDisconnected: 'Disconnected',
    inviteTitle: '3 · Approve Scoped Invitation',
    labelProjects: 'Projects (comma-separated)',
    labelArch: 'Architecture',
    labelCpu: 'CPU Limit',
    labelMemory: 'Memory (MiB)',
    labelSlots: 'Concurrent Slots',
    labelTtl: 'Validity (seconds)',
    inviteDesc: 'Invites grant community Worker tier by default. Trusted identity, signed images, and independent failure domains require separate operator audit; privileges are not auto-elevated here.',
    btnInvite: 'Approve & Download One-Time Invite',
    inviteDownloaded: d => `Invitation downloaded. ${d}`,
    buildTitle: 'Build & Verification Records',
    labelProject: 'Project ID',
    btnInspect: 'Query Builds',
    summarySubmit: 'Submit Lightweight C Build',
    labelSubmitProject: 'Project ID',
    labelCompileSource: 'Preprocessed C file (unit.i, max 128 KiB)',
    labelCompileTarget: 'Target Architecture',
    submitDesc: 'Client architecture must match node architecture. Cross-targets require the node to enable and approve corresponding toolchains; this endpoint generates object files and does not replace full LFS toolchain builds.',
    btnSubmit: 'Upload Source & Submit Task',
    submitResult: id => `Task submitted: ${id}; awaiting Worker matching architecture and toolchain admission.`,
    summaryRebuild: 'Independent Rebuild & Verification',
    labelPipelineId: 'Pipeline ID',
    labelTaskId: 'Original Task ID',
    btnRebuild: 'Select Independent Worker & Submit Rebuild',
    labelVerifyPipeline: 'Rebuild Pipeline ID',
    labelVerifyFirst: 'First Task ID',
    labelVerifySecond: 'Independent Task ID',
    btnVerify: 'Verify Signed Artifacts & Independent Failure Domains',
    lightTitle: 'OpenCI · Lightweight Distributed C Compilation',
    lightDesc: 'Device architecture must match connected node. Handles preprocessed C translation units up to 128 KiB, producing ELF objects up to 1 MiB without executing task code. Cross-targets require operator-enabled toolchains.',
    lightArch: 'Detect device and node architecture before starting.',
    lightControllerLink: 'OpenCI Node Admission & Independent Verification',
    labelLightWorkerId: 'Worker ID',
    labelLightInvite: 'Operator-Approved Invitation JSON',
    btnLightEnroll: 'Generate Dedicated Key & Join',
    labelLightImport: 'Or import existing Worker private credential',
    lightCredDesc: 'Private credentials contain dedicated keys and tokens; retain securely. Used in page memory only and cleared on close. Never import wallet keys.',
    btnLightStart: 'Start Lightweight Build',
    btnLightStop: 'Stop Lightweight Build',
    btnLightLogout: 'Clear Credentials',
    lightStatusInitial: 'Not enrolled. Task completion, independent verification, on-chain recording, and settlement are confirmed separately.',
    footerText: 'Connection state, worker admission, artifact verification, native consensus acceptance, and settlement are recorded separately. Unverified dimensions remain not_assessed.'
  }
};

function applyLanguage(lang){
  const t = I18N[lang] || I18N['zh-CN'];
  document.documentElement.lang = lang;
  document.title = t.title;
  const heroTitle = $('#hero-title'); if(heroTitle) heroTitle.innerHTML = t.heroTitle;
  const flow = $('.flow'); if(flow) flow.setAttribute('aria-label', t.flowLabel);
  const f1 = $('#flow-1'); if(f1) f1.innerHTML = t.flow1;
  const f2 = $('#flow-2'); if(f2) f2.innerHTML = t.flow2;
  const f3 = $('#flow-3'); if(f3) f3.innerHTML = t.flow3;
  const heroDesc = $('#hero-desc'); if(heroDesc) heroDesc.textContent = t.heroDesc;
  const dl = $('#download-link'); if(dl) dl.textContent = t.downloadsLink;
  const joinTitle = $('#join-title'); if(joinTitle) joinTitle.textContent = t.joinTitle;
  const joinDesc = $('#join-desc'); if(joinDesc) joinDesc.textContent = t.joinDesc;
  const lblOrigin = $('#label-origin'); if(lblOrigin) lblOrigin.textContent = t.labelOrigin;
  const joinNote = $('#join-note'); if(joinNote) joinNote.textContent = t.joinNote;
  const sessionTitle = $('#session-title'); if(sessionTitle) sessionTitle.textContent = t.sessionTitle;
  const lblToken = $('#label-token'); if(lblToken) lblToken.textContent = t.labelToken;
  const loginDesc = $('#login-desc'); if(loginDesc) loginDesc.textContent = t.loginDesc;
  const btnLogin = $('#btn-login'); if(btnLogin) btnLogin.textContent = t.btnLogin;
  const btnLogout = $('#logout'); if(btnLogout) btnLogout.textContent = t.btnLogout;
  const session = $('#session'); if(session && !session.dataset.connected) session.textContent = t.sessionDisconnected;
  const inviteTitle = $('#invite-title'); if(inviteTitle) inviteTitle.textContent = t.inviteTitle;
  const pProj = $('#txt-label-projects'); if(pProj) pProj.textContent = t.labelProjects;
  const pArch = $('#txt-label-arch'); if(pArch) pArch.textContent = t.labelArch;
  const pCpu = $('#txt-label-cpu'); if(pCpu) pCpu.textContent = t.labelCpu;
  const pMem = $('#txt-label-memory'); if(pMem) pMem.textContent = t.labelMemory;
  const pSlots = $('#txt-label-slots'); if(pSlots) pSlots.textContent = t.labelSlots;
  const pTtl = $('#txt-label-ttl'); if(pTtl) pTtl.textContent = t.labelTtl;
  const inviteDesc = $('#invite-desc'); if(inviteDesc) inviteDesc.textContent = t.inviteDesc;
  const btnInvite = $('#btn-invite'); if(btnInvite) btnInvite.textContent = t.btnInvite;
  const buildTitle = $('#build-title'); if(buildTitle) buildTitle.textContent = t.buildTitle;
  const lblProject = $('#label-project'); if(lblProject) lblProject.textContent = t.labelProject;
  const btnInspect = $('#btn-inspect'); if(btnInspect) btnInspect.textContent = t.btnInspect;
  const sumSubmit = $('#summary-submit'); if(sumSubmit) sumSubmit.textContent = t.summarySubmit;
  const lblSubProj = $('#label-submit-project'); if(lblSubProj) lblSubProj.textContent = t.labelSubmitProject;
  const lblCompSrc = $('#label-compile-source'); if(lblCompSrc) lblCompSrc.textContent = t.labelCompileSource;
  const lblCompTgt = $('#label-compile-target'); if(lblCompTgt) lblCompTgt.textContent = t.labelCompileTarget;
  const submitDesc = $('#submit-desc'); if(submitDesc) submitDesc.textContent = t.submitDesc;
  const btnSubmit = $('#btn-submit'); if(btnSubmit) btnSubmit.textContent = t.btnSubmit;
  const sumRebuild = $('#summary-rebuild'); if(sumRebuild) sumRebuild.textContent = t.summaryRebuild;
  const lblPipeId = $('#label-pipeline-id'); if(lblPipeId) lblPipeId.textContent = t.labelPipelineId;
  const lblTaskId = $('#label-task-id'); if(lblTaskId) lblTaskId.textContent = t.labelTaskId;
  const btnRebuild = $('#btn-rebuild'); if(btnRebuild) btnRebuild.textContent = t.btnRebuild;
  const lblVerPipe = $('#label-verify-pipeline'); if(lblVerPipe) lblVerPipe.textContent = t.labelVerifyPipeline;
  const lblVerFirst = $('#label-verify-first'); if(lblVerFirst) lblVerFirst.textContent = t.labelVerifyFirst;
  const lblVerSec = $('#label-verify-second'); if(lblVerSec) lblVerSec.textContent = t.labelVerifySecond;
  const btnVerify = $('#btn-verify'); if(btnVerify) btnVerify.textContent = t.btnVerify;
  const lightTitle = $('#light-title'); if(lightTitle) lightTitle.textContent = t.lightTitle;
  const lightDesc = $('#light-desc'); if(lightDesc) lightDesc.textContent = t.lightDesc;
  const lightArch = $('#light-architecture'); if(lightArch && !lightArch.dataset.detected) lightArch.textContent = t.lightArch;
  const lightCtrl = $('#light-controller'); if(lightCtrl) lightCtrl.textContent = t.lightControllerLink;
  const lblLightWorker = $('#label-light-worker-id'); if(lblLightWorker) lblLightWorker.textContent = t.labelLightWorkerId;
  const lblLightInvite = $('#label-light-invite'); if(lblLightInvite) lblLightInvite.textContent = t.labelLightInvite;
  const btnLightEnroll = $('#btn-light-enroll'); if(btnLightEnroll) btnLightEnroll.textContent = t.btnLightEnroll;
  const lblLightImport = $('#label-light-import'); if(lblLightImport) lblLightImport.textContent = t.labelLightImport;
  const lightCredDesc = $('#light-cred-desc'); if(lightCredDesc) lightCredDesc.textContent = t.lightCredDesc;
  const lightStart = $('#light-start');
  if(lightStart){
    const active = lightStart.getAttribute('aria-pressed') === 'true';
    lightStart.textContent = active ? t.btnLightStop : t.btnLightStart;
  }
  const lightLogout = $('#light-logout'); if(lightLogout) lightLogout.textContent = t.btnLightLogout;
  const lightStatus = $('#light-status'); if(lightStatus && !lightStatus.dataset.active) lightStatus.textContent = t.lightStatusInitial;
  const footerText = $('#footer-text'); if(footerText) footerText.textContent = t.footerText;

  const compSum = $('#compiler-summary');
  if(compSum){
    if(compilerConfig){
      compSum.textContent = t.compilerSummary(compilerConfig.node_arch, Object.keys(compilerConfig.targets), compilerConfig.cross_compile);
    } else if(compSum.dataset.error){
      compSum.textContent = t.compilerUnavailable;
    }
  }
  document.dispatchEvent(new CustomEvent('languagechange', {detail: {lang}}));
}

async function api(path,body){const response=await fetch(prefix+path,{method:body?'POST':'GET',headers:{...(credential?{Authorization:'Bearer '+credential}:{}),...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined,cache:'no-store',credentials:'omit',redirect:'error'});const value=await response.json();if(!response.ok)throw Error(value.error?.code+': '+value.error?.message);return value}
function logout(){credential='';$('#token').value='';$('#operator').hidden=true;$('#workspace').hidden=true;const sess=$('#session');sess.dataset.connected='';sess.textContent=document.documentElement.lang==='en'?'Disconnected':'尚未连接';$('#pipelines').textContent='';$('#invite-result').textContent=''}
$('#logout').addEventListener('click',logout);addEventListener('pagehide',logout);addEventListener('pageshow',event=>{if(event.persisted)logout()});
$('#login').addEventListener('submit',async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;credential=$('#token').value.trim();$('#token').value='';try{const me=await api('/v1/me');const sess=$('#session');sess.dataset.connected='1';sess.textContent=me.principal+' · '+me.role+' · '+me.projects.join(', ');$('#operator').hidden=me.role!=='admin';$('#workspace').hidden=me.role==='worker';if(me.projects.length)$('#project').value=me.projects[0]}catch(error){logout();$('#session').textContent=error.message}finally{button.disabled=false}});
$('#invite').addEventListener('submit',async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;try{const form=new FormData(event.currentTarget);const request={arch:form.get('arch'),pool:'community',projects:form.get('projects').split(',').map(v=>v.trim()).filter(Boolean)};for(const key of ['cpu','memory_mb','slots','ttl'])request[key]=Number(form.get(key));const invite=await api('/v1/enrollments/invites',request);invite.controller_origin=origin;const data=new Blob([JSON.stringify(invite,null,2)+'\n'],{type:'application/json'}),url=URL.createObjectURL(data),link=document.createElement('a');link.href=url;link.download='invite.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);const expDate=new Date(invite.expires*1000).toLocaleString();const t=I18N[document.documentElement.lang]||I18N['zh-CN'];$('#invite-result').textContent=t.inviteDownloaded(expDate)}catch(error){$('#invite-result').textContent=error.message}finally{button.disabled=false}});
$('#inspect').addEventListener('submit',async event=>{event.preventDefault();event.submitter.disabled=true;try{const value=await api('/v1/pipelines?project='+encodeURIComponent($('#project').value.trim()));$('#pipelines').textContent=JSON.stringify(value,null,2)}catch(error){$('#pipelines').textContent=error.message}finally{event.submitter.disabled=false}});
$('#language').addEventListener('click',()=>{const nextLang=document.documentElement.lang==='en'?'zh-CN':'en';applyLanguage(nextLang)});

api('/v1/light/config').then(value=>{compilerConfig=value;const t=I18N[document.documentElement.lang]||I18N['zh-CN'];$('#compiler-summary').textContent=t.compilerSummary(value.node_arch,Object.keys(value.targets),value.cross_compile);for(const option of $('#compile-target').options)option.disabled=!value.targets[option.value];$('#compile-target').value=value.node_arch}).catch(()=>{$('#compiler-summary').dataset.error='1';const t=I18N[document.documentElement.lang]||I18N['zh-CN'];$('#compiler-summary').textContent=t.compilerUnavailable});
async function uploadSource(project,data){const id='source-'+crypto.randomUUID().replaceAll('-',''),digest='sha256:'+Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data)),v=>v.toString(16).padStart(2,'0')).join(''),query='?project='+encodeURIComponent(project);await api('/v1/objects/begin'+query,{upload:id,size:data.length,digest,mime:'application/json'});for(let p=0;p*16384<data.length;p++){const response=await fetch(prefix+'/v1/objects/'+id+'/chunks/'+p+query,{method:'PUT',headers:{Authorization:'Bearer '+credential,'Content-Type':'application/octet-stream'},body:data.slice(p*16384,(p+1)*16384),credentials:'omit',redirect:'error'});if(!response.ok)throw Error('Source upload rejected')}return (await api('/v1/objects/finish'+query,{upload:id})).reference}
$('#submit-build').addEventListener('submit',async event=>{event.preventDefault();event.submitter.disabled=true;try{const project=$('#submit-project').value.trim(),file=$('#compile-source').files[0];if(!file||file.size>131072)throw Error('128 KiB preprocessed C file required');const settings=await api('/v1/light/config'),target=$('#compile-target').value,compiler=settings.targets[target];if(!compiler)throw Error('Target compiler not approved');const text=new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());if(text.includes('\u0000'))throw Error('NUL source byte rejected');const source=await uploadSource(project,new TextEncoder().encode(JSON.stringify({schema:'openci.light-source.v1',name:'unit.i',source:text})));const value=await api('/v1/pipelines',{schema:'openci.pipeline.v1',project,nonce:'web-'+crypto.randomUUID().replaceAll('-',''),source,tasks:[{id:'build',needs:[],executor:'light-c',image:compiler.image,argv:['light-c',target,'unit.i','unit.o'],arch:settings.node_arch,pool:'community',cpu:1,memory_mb:64,timeout:20,attempts:2,outputs:['unit.o']}]});const t=I18N[document.documentElement.lang]||I18N['zh-CN'];$('#submit-result').textContent=t.submitResult(value.pipeline);$('#pipeline-id').value=value.pipeline;$('#project').value=project}catch(error){$('#submit-result').textContent=error.message}finally{event.submitter.disabled=false}});
$('#rebuild').addEventListener('submit',async event=>{event.preventDefault();event.submitter.disabled=true;try{const value=await api('/v1/rebuilds',{pipeline:$('#pipeline-id').value.trim(),task:$('#task-id').value.trim(),nonce:'rebuild-'+crypto.randomUUID().replaceAll('-',''),minimum:2});$('#verification-result').textContent=JSON.stringify(value,null,2);if(value.pipeline)$('#verify-pipeline').value=value.pipeline}catch(error){$('#verification-result').textContent=error.message}finally{event.submitter.disabled=false}});
$('#verify').addEventListener('submit',async event=>{event.preventDefault();event.submitter.disabled=true;try{$('#verification-result').textContent=JSON.stringify(await api('/v1/verify',{pipeline:$('#verify-pipeline').value.trim(),task:$('#verify-first').value.trim(),independent_task:$('#verify-second').value.trim()}),null,2)}catch(error){$('#verification-result').textContent=error.message}finally{event.submitter.disabled=false}});
})();