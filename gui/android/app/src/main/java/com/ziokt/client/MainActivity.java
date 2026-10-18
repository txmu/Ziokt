package com.ziokt.client;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.os.Bundle;
import android.util.Log;
import android.webkit.ConsoleMessage;
import android.webkit.JsPromptResult;
import android.webkit.JsResult;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;

public class MainActivity extends Activity {

    private static final String TAG = "ZioktNative";
    private WebView webView;
    private android.webkit.ValueCallback<android.net.Uri[]> fileChooser;
    private android.webkit.PermissionRequest microphoneRequest;
    private static final int PICK_FILE=1001, RECORD_AUDIO_PERMISSION=1002;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // Edge-to-edge / Full resolution system UI colors
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.LOLLIPOP) {
            getWindow().addFlags(android.view.WindowManager.LayoutParams.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS);
            getWindow().setStatusBarColor(android.graphics.Color.parseColor("#0b0f19"));
            getWindow().setNavigationBarColor(android.graphics.Color.parseColor("#0b0f19"));
        }

        webView = new WebView(this);
        webView.setLayoutParams(new android.view.ViewGroup.LayoutParams(
            android.view.ViewGroup.LayoutParams.MATCH_PARENT,
            android.view.ViewGroup.LayoutParams.MATCH_PARENT
        ));
        webView.setBackgroundColor(android.graphics.Color.parseColor("#0b0f19"));
        setContentView(webView);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(true);
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setMediaPlaybackRequiresUserGesture(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);

        // Screen resolution, High-DPI and responsive viewport adaptation
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(true);
        settings.setSupportZoom(false);
        settings.setDisplayZoomControls(false);
        settings.setTextZoom(100);

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, android.webkit.ValueCallback<android.net.Uri[]> callback, FileChooserParams params) {
                if (fileChooser!=null) fileChooser.onReceiveValue(null);
                fileChooser=callback;
                try { startActivityForResult(params.createIntent(),PICK_FILE); }
                catch (android.content.ActivityNotFoundException e) { fileChooser.onReceiveValue(null);fileChooser=null; }
                return true;
            }
            @Override
            public void onPermissionRequest(android.webkit.PermissionRequest request) {
                if (!"https".equals(request.getOrigin().getScheme()) || !("appassets.ziokt.local".equals(request.getOrigin().getHost()) || "app.ziokt.com".equals(request.getOrigin().getHost()))) {request.deny();return;}
                if (!java.util.Arrays.asList(request.getResources()).contains(android.webkit.PermissionRequest.RESOURCE_AUDIO_CAPTURE)) {request.deny();return;}
                if (checkSelfPermission(android.Manifest.permission.RECORD_AUDIO)==android.content.pm.PackageManager.PERMISSION_GRANTED) {
                    request.grant(new String[]{android.webkit.PermissionRequest.RESOURCE_AUDIO_CAPTURE});
                } else {if(microphoneRequest!=null)microphoneRequest.deny();microphoneRequest=request;requestPermissions(new String[]{android.Manifest.permission.RECORD_AUDIO},RECORD_AUDIO_PERMISSION);}
            }
            @Override
            public void onPermissionRequestCanceled(android.webkit.PermissionRequest request) {if(microphoneRequest==request)microphoneRequest=null;}

            @Override
            public boolean onConsoleMessage(ConsoleMessage cm) {
                // Application payloads and credentials do not enter logcat.
                return true;
            }

            @Override
            public boolean onJsAlert(WebView view, String url, String message, final JsResult result) {
                new AlertDialog.Builder(MainActivity.this)
                    .setTitle("Ziokt")
                    .setMessage(message)
                    .setPositiveButton(android.R.string.ok, new DialogInterface.OnClickListener() {
                        public void onClick(DialogInterface dialog, int which) {
                            result.confirm();
                        }
                    })
                    .setCancelable(false)
                    .create()
                    .show();
                return true;
            }

            @Override
            public boolean onJsConfirm(WebView view, String url, String message, final JsResult result) {
                new AlertDialog.Builder(MainActivity.this)
                    .setTitle("Ziokt")
                    .setMessage(message)
                    .setPositiveButton(android.R.string.ok, new DialogInterface.OnClickListener() {
                        public void onClick(DialogInterface dialog, int which) {
                            result.confirm();
                        }
                    })
                    .setNegativeButton(android.R.string.cancel, new DialogInterface.OnClickListener() {
                        public void onClick(DialogInterface dialog, int which) {
                            result.cancel();
                        }
                    })
                    .setCancelable(false)
                    .create()
                    .show();
                return true;
            }

            @Override
            public boolean onJsPrompt(WebView view, String url, String message, String defaultValue, final JsPromptResult result) {
                final EditText input = new EditText(MainActivity.this);
                input.setText(defaultValue);
                new AlertDialog.Builder(MainActivity.this)
                    .setTitle("Ziokt")
                    .setMessage(message)
                    .setView(input)
                    .setPositiveButton(android.R.string.ok, new DialogInterface.OnClickListener() {
                        public void onClick(DialogInterface dialog, int which) {
                            result.confirm(input.getText().toString());
                        }
                    })
                    .setNegativeButton(android.R.string.cancel, new DialogInterface.OnClickListener() {
                        public void onClick(DialogInterface dialog, int which) {
                            result.cancel();
                        }
                    })
                    .setCancelable(false)
                    .create()
                    .show();
                return true;
            }
        });

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public android.webkit.WebResourceResponse shouldInterceptRequest(WebView view, android.webkit.WebResourceRequest request) {
                android.net.Uri uri=request.getUrl();
                if (!"https".equals(uri.getScheme()) || !"appassets.ziokt.local".equals(uri.getHost())) return null;
                String path=uri.getPath();
                if (path==null || path.contains("..") || path.contains("\\")) return new android.webkit.WebResourceResponse("text/plain","UTF-8",null);
                String asset=path.equals("/")?"index.html":path.substring(1);
                String mime=asset.endsWith(".js")?"application/javascript":asset.endsWith(".css")?"text/css":asset.endsWith(".png")?"image/png":asset.endsWith(".svg")?"image/svg+xml":asset.endsWith(".json")?"application/json":"text/html";
                try { return new android.webkit.WebResourceResponse(mime,"UTF-8",getAssets().open(asset)); }
                catch (java.io.IOException e) { return new android.webkit.WebResourceResponse("text/plain","UTF-8",null); }
            }
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return !url.startsWith("https://appassets.ziokt.local/");
            }
        });
        webView.loadUrl("https://appassets.ziokt.local/index.html");
    }

    @Override
    protected void onActivityResult(int code,int result,android.content.Intent data) {
        super.onActivityResult(code,result,data);
        if(code==PICK_FILE && fileChooser!=null){fileChooser.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result,data));fileChooser=null;}
    }
    @Override
    public void onRequestPermissionsResult(int code,String[] permissions,int[] results) {
        super.onRequestPermissionsResult(code,permissions,results);
        if(code==RECORD_AUDIO_PERMISSION && microphoneRequest!=null){
            if(results.length>0 && results[0]==android.content.pm.PackageManager.PERMISSION_GRANTED)microphoneRequest.grant(new String[]{android.webkit.PermissionRequest.RESOURCE_AUDIO_CAPTURE});else microphoneRequest.deny();microphoneRequest=null;
        }
    }
    @Override
    protected void onDestroy(){if(fileChooser!=null)fileChooser.onReceiveValue(null);if(microphoneRequest!=null)microphoneRequest.deny();if(webView!=null)webView.destroy();super.onDestroy();}

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
