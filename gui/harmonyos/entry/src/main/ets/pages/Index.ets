// ==============================================================================
// HarmonyOS NEXT Native ArkUI / Web Component Adapter for Ziokt Client
// ==============================================================================

import webview from '@ohos.web.webview';
import promptAction from '@ohos.promptAction';

@Entry
@Component
struct Index {
  controller: webview.WebviewController = new webview.WebviewController();
  @State localEndpoint: string = 'http://127.0.0.1:8185/gui';
  @State isOnline: boolean = false;

  aboutToAppear() {
    // Enable modern web debugging for development builds
    webview.WebviewController.setWebDebuggingAccess(false);
  }

  build() {
    Column() {
      // Main Webview Container running the Unified Ziokt GUI Client
      Web({ src: 'https://app.ziokt.com/', controller: this.controller })
        .domStorageAccess(true)
        .fileAccess(false)
        .imageAccess(true)
        .javaScriptAccess(true)
        .onlineImageAccess(true)
        .databaseAccess(true)
        .width('100%')
        .height('100%')
        .onConfirm((event) => {
          promptAction.showDialog({
            title: '操作确认',
            message: event.message,
            buttons: [
              { text: '取消', color: '#888888' },
              { text: '确定', color: '#0284c7' }
            ]
          }).then((result) => {
            if (result.index === 1) {
              event.result.handleConfirm();
            } else {
              event.result.handleCancel();
            }
          });
          return true;
        })
        .onErrorReceive((event) => {
          console.error('[Ziokt ArkUI] Webview load error: ' + event?.error?.getErrorInfo());
        })
    }
    .width('100%')
    .height('100%')
    .backgroundColor('#070a12')
  }
}
