package com.ziokt.effort;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.webkit.*;

/** Third mode runs bounded WASM compilation in the system browser renderer.
 * Only a write-only credential export bridge; no JNI, wallet keys, task execution or implicit background grant. */
public final class OpenCiActivity extends Activity {
    private WebView web;
    private android.webkit.ValueCallback<Uri[]> selection;
    private byte[] pendingExport;
    private static boolean allowed(Uri uri) {
        return uri!=null && "https".equals(uri.getScheme()) && "fendou.ziokt.com".equals(uri.getHost())
            && (uri.getPort()==-1 || uri.getPort()==443) && uri.getUserInfo()==null;
    }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        web=new WebView(this);setContentView(web);
        WebSettings settings=web.getSettings();settings.setJavaScriptEnabled(true);
        settings.setAllowFileAccess(false);settings.setAllowContentAccess(false);
        settings.setDomStorageEnabled(false);settings.setDatabaseEnabled(false);
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);settings.setSaveFormData(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        CookieManager.getInstance().setAcceptCookie(false);
        web.addJavascriptInterface(new Object(){
            @JavascriptInterface public void save(String raw){
                if(raw==null||raw.length()>16384)return;
                runOnUiThread(()->{
                    if(web==null||!allowed(Uri.parse(web.getUrl()))||pendingExport!=null)return;
                    try {
                        org.json.JSONObject value=new org.json.JSONObject(raw);
                        if(value.length()!=5||!"openci.light-credential.v1".equals(value.getString("schema"))||!value.getString("seed_hex").matches("[a-f0-9]{64}")||value.getString("token").length()>256||!value.getString("worker").matches("[A-Za-z0-9][A-Za-z0-9_-]{0,63}")||!"https://openci.ziokt.com".equals(value.getString("controller")))return;
                        pendingExport=raw.getBytes(java.nio.charset.StandardCharsets.UTF_8);
                        Intent intent=new Intent(Intent.ACTION_CREATE_DOCUMENT);intent.addCategory(Intent.CATEGORY_OPENABLE);intent.setType("application/json");intent.putExtra(Intent.EXTRA_TITLE,"openci-worker-private.json");startActivityForResult(intent,42);
                    }catch(Exception error){pendingExport=null;}
                });
            }
        },"ZioktCredentialExport");
        web.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request){return !allowed(request.getUrl());}
            @Override public void onReceivedSslError(WebView view,android.webkit.SslErrorHandler handler,android.net.http.SslError error){handler.cancel();}
            @Override public void onPageFinished(WebView view,String url){
                if(!allowed(Uri.parse(url)))return;
                String architecture="unsupported";
                for(String abi:Build.SUPPORTED_64_BIT_ABIS){if("arm64-v8a".equals(abi)){architecture="aarch64";break;}if("x86_64".equals(abi)){architecture="x86_64";break;}}
                view.evaluateJavascript("window.ZioktHostArchitecture='"+architecture+"';(()=>{const m=document.getElementById('help-mode');if(m){m.value='openci';m.dispatchEvent(new Event('change'));}})()",null);
            }
        });
        web.setWebChromeClient(new WebChromeClient(){
            @Override public boolean onShowFileChooser(WebView view,android.webkit.ValueCallback<Uri[]> callback,FileChooserParams params){
                if(selection!=null)selection.onReceiveValue(null);selection=callback;
                Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT);intent.addCategory(Intent.CATEGORY_OPENABLE);intent.setType("application/json");
                try{startActivityForResult(intent,41);return true;}catch(RuntimeException error){selection.onReceiveValue(null);selection=null;return false;}
            }
            @Override public void onPermissionRequest(PermissionRequest request){request.deny();}
        });
        web.loadUrl(Work.ORIGIN+"/");
    }
    @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);if(request==42&&pendingExport!=null){try{Uri uri=result==RESULT_OK&&data!=null?data.getData():null;if(uri!=null&&"content".equals(uri.getScheme())){try(java.io.OutputStream output=getContentResolver().openOutputStream(uri,"w")){if(output!=null)output.write(pendingExport);}}}catch(java.io.IOException error){android.widget.Toast.makeText(this,"凭证未保存，请保留页面并重试导出",android.widget.Toast.LENGTH_LONG).show();}finally{java.util.Arrays.fill(pendingExport,(byte)0);pendingExport=null;}return;}if(request==41&&selection!=null){Uri uri=result==RESULT_OK&&data!=null?data.getData():null;selection.onReceiveValue(uri!=null&&"content".equals(uri.getScheme())?new Uri[]{uri}:null);selection=null;}}
    @Override protected void onPause(){if(web!=null)web.evaluateJavascript("window.ZioktLight&&window.ZioktLight.stop()",null);super.onPause();}
    @Override protected void onDestroy(){if(selection!=null)selection.onReceiveValue(null);if(pendingExport!=null)java.util.Arrays.fill(pendingExport,(byte)0);if(web!=null){web.removeJavascriptInterface("ZioktCredentialExport");web.stopLoading();web.loadUrl("about:blank");web.clearHistory();web.clearCache(true);web.destroy();web=null;}super.onDestroy();}
}
