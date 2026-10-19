'use strict';
// A lifecycle boundary only: no page injection, browsing history, Gateway calls
// or background transmission. Credentials remain in storage.session.
(globalThis.browser||globalThis.chrome).runtime.onInstalled.addListener(()=>{});
