(async()=>{
 try{
  const params=new URL(location.href).searchParams;history.replaceState(null,'',location.pathname);
  const issuer=sessionStorage.getItem('ziokt_oauth_issuer')||location.origin;
  const expected=sessionStorage.getItem('ziokt_oauth_state'),verifier=sessionStorage.getItem('ziokt_oauth_verifier');
  sessionStorage.removeItem('ziokt_oauth_state');sessionStorage.removeItem('ziokt_oauth_verifier');
  if(!expected||params.get('state')!==expected||params.get('iss')!==issuer||!verifier||!params.get('code'))throw new Error('Authorization scope or state rejected');
  const response=await fetch(issuer+'/oauth/token',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({grant_type:'authorization_code',client_id:'ziokt-browser',code:params.get('code'),code_verifier:verifier,redirect_uri:location.origin+location.pathname,resource:issuer+'/mcp'})});
  const result=await response.json();if(!response.ok||result.token_type!=='Bearer')throw new Error('Token exchange rejected');
  sessionStorage.setItem('ziokt_mcp_access',result.access_token);sessionStorage.setItem('ziokt_mcp_issuer',issuer);sessionStorage.removeItem('ziokt_oauth_issuer');
  const back=sessionStorage.getItem('ziokt_oauth_return');sessionStorage.removeItem('ziokt_oauth_return');
  location.replace(back?.startsWith('/app/')?back:'/app/explorer');
 }catch(error){document.querySelector('#status').textContent=error.message;}
})();
