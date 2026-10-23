async function loadEvidence(){
  const status=document.getElementById('load-status');
  try{
    const response=await fetch('/api/gateway/status',{cache:'no-store',credentials:'omit',signal:AbortSignal.timeout(8000)});
    if(!response.ok)throw Error('Gateway HTTP '+response.status);
    const data=await response.json();
    if(data.schema!=='ziokt.gateway.v1'||data.assurance?.schema!=='ziokt.assurance-scope.v1')throw Error('Gateway 尚未提供本版本验证范围');
    document.getElementById('revision').textContent=data.build?.source_commit||'未确认';
    document.getElementById('native').textContent=data.native_entrypoint_digest||'未确认';
    const privacy=data.assurance.privacy;
    document.getElementById('privacy').textContent=`主网功能开关：${privacy.mainnet_feature_enabled?'已启用':'已禁用'}；独立第三方审计：${privacy.independently_audited?'已声明（需核对审计报告）':'未提供证据'}。`;
    document.getElementById('evidence').textContent=JSON.stringify(data.assurance,null,2);
    status.textContent='已取得当前 Gateway 状态；服务自报版本不替代独立历史验证。';
  }catch(error){status.textContent='无法确认当前部署：'+error.message;}
}
loadEvidence();
