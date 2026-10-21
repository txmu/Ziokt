/* ES5 transport client: no WebCrypto, Service Worker, Worker, fetch or Promise. */
(function () {
  'use strict';
  var button = document.getElementById('start'), mode = document.getElementById('help-mode');
  var input = document.getElementById('help-invitation'), status = document.getElementById('status');
  var background = document.getElementById('background'), active = false, epoch = 0;
  var wakeLock = null;
  var peers = [], timers = [], requests = [], bytes = 0, completed = 0, origins = null;
  function modern() { return window.isSecureContext === true && window.crypto && window.crypto.subtle && typeof Worker === 'function' && typeof fetch === 'function' && typeof BigInt === 'function' && typeof AbortController === 'function' && typeof TextEncoder === 'function'; }
  function networkMode() { return mode.value === 'network' || mode.value === 'auto' && !modern(); }
  function later(fn, ms) { var timer = setTimeout(function () { var i = timers.indexOf(timer); if (i >= 0) timers.splice(i, 1); fn(); }, ms); timers.push(timer); }
  function keepAwake() {
    if (!active || hide() || !background.checked || wakeLock || !navigator.wakeLock) return;
    var generation = epoch;
    try { navigator.wakeLock.request('screen').then(function (lock) { if (!active || epoch !== generation) { lock.release(); return; } wakeLock = lock; lock.addEventListener('release', function () { if (wakeLock === lock) wakeLock = null; }); }, function () {}); } catch (_) {}
  }
  function hide() { return document.hidden === true || document.webkitHidden === true; }
  function request(peer, operation, value, callback, generation, retries) {
    var xhr = new XMLHttpRequest(), attempt = retries || 0;
    requests.push(xhr); xhr.open('POST', peer.origin + '/relay/v1/' + operation, true);
    xhr.setRequestHeader('Content-Type', 'application/json'); xhr.setRequestHeader('Authorization', 'Bearer ' + peer.token);
    xhr.timeout = 12000;
    function done(error, result, retry) {
      var index = requests.indexOf(xhr); if (index >= 0) requests.splice(index, 1);
      xhr.onload = xhr.onerror = xhr.ontimeout = xhr.onabort = null;
      if (!active || epoch !== generation) return;
      if (error && retry && attempt < 3) return later(function () { request(peer, operation, value, callback, generation, attempt + 1); }, 500 * (attempt + 1));
      callback(error, result);
    }
    xhr.onload = function () {
      var value;
      try { value = JSON.parse(xhr.responseText); } catch (_) { return done('INVALID_RESPONSE'); }
      if (xhr.status !== 200 || value.error) return done(value.error && value.error.code || 'HTTP_ERROR', null, xhr.status >= 500 || value.error && value.error.code === 'RELAY_THROTTLED');
      done(null, value);
    };
    xhr.onerror = xhr.ontimeout = function () { done('NETWORK_UNAVAILABLE', null, true); };
    xhr.onabort = function () { done('STOPPED'); };
    var wire = {arguments: value, padding: ''}, payload = JSON.stringify(wire);
    if (operation === 'write') wire.padding = new Array(Math.max(0, 6144 - payload.length) + 1).join('0');
    xhr.send(JSON.stringify(wire));
  }
  function stop(message) {
    var old = peers, pending = requests.slice(0), i;
    if (wakeLock) { wakeLock.release(); wakeLock = null; }
    active = false; epoch += 1; peers = []; requests = [];
    for (i = 0; i < timers.length; i += 1) clearTimeout(timers[i]); timers = [];
    for (i = 0; i < pending.length; i += 1) pending[i].abort();
    for (i = 0; i < old.length; i += 1) if (old[i].session) {
      try {
        var xhr = new XMLHttpRequest(); xhr.open('POST', old[i].origin + '/relay/v1/close', true);
        xhr.setRequestHeader('Content-Type', 'application/json'); xhr.setRequestHeader('Authorization', 'Bearer ' + old[i].token);
        xhr.timeout = 3000; xhr.send(JSON.stringify({session: old[i].session}));
      } catch (_) {}
    }
    button.textContent = '一键人民助力'; button.setAttribute('aria-pressed', 'false');
    status.textContent = message || '已停止';
  }
  function failed(error) { stop('协作已停止：' + error + '。连接恢复后可重新开始。'); }
  function pump(from, to, generation) {
    if (!active || epoch !== generation) return;
    request(from, 'read', {session: from.session}, function (error, value) {
      if (error) return failed(error);
      if (value.state === 'idle') return later(function () { pump(from, to, generation); }, 500);
      var frame = value.frame;
      if (value.state !== 'frame' || !frame || typeof frame.sequence !== 'number' || frame.sequence < 0 || frame.sequence % 1 || (frame.kind !== 'data' && frame.kind !== 'fin') || typeof frame.data !== 'string' || frame.data.length > 5464) return failed('INVALID_FRAME');
      request(to, 'write', {session: to.session, frame: frame}, function (error, receipt) {
        if (error) return failed(error);
        if (receipt.state !== 'native_written') return failed('WRITE_UNCONFIRMED');
        request(from, 'ack', {session: from.session, sequence: frame.sequence}, function (error, ack) {
          if (error || ack.state !== 'acknowledged') return failed(error || 'ACK_UNCONFIRMED');
          if (frame.kind === 'fin') { completed += 1; if (completed === 2) stop('本次网络协作已完成；尚未结算链上贡献。'); return; }
          bytes += frame.data.length / 4 * 3 - (frame.data.slice(-2) === '==' ? 2 : frame.data.slice(-1) === '=' ? 1 : 0);
          document.getElementById('metrics').textContent = '网络协作已传输 ' + Math.floor(bytes / 1024) + ' KiB · 尚未结算链上贡献';
          later(function () { pump(from, to, generation); }, 500);
        }, generation);
      }, generation);
    }, generation);
  }
  function open(peer, generation, callback) {
    request(peer, 'open', {}, function (error, value) {
      if (error) return failed(error);
      if (value.state === 'waiting') { status.textContent = '等待可用网络协作任务，不进行无效计算'; return later(function () { open(peer, generation, callback); }, 1000); }
      if (value.state !== 'open' || typeof value.session !== 'string' || !/^[a-f0-9]{48}$/.test(value.session)) return failed('INVALID_SESSION');
      peer.session = value.session; callback();
    }, generation);
  }
  function start() {
    var invitation, list, i;
    if (!window.XMLHttpRequest || !window.JSON) return stop('此浏览器缺少安全网络协作所需的基础支持。');
    if (!origins || !origins.length) return stop('尚未配置可用协作节点，请联系节点运营者。');
    try {
      if (input.value.length > 2048) throw Error();
      invitation = JSON.parse(input.value); list = [invitation.a, invitation.b];
      if (invitation.v !== 1) throw Error();
      for (i = 0; i < 2; i += 1) if (!list[i] || origins.indexOf(list[i].origin) < 0 || typeof list[i].token !== 'string' || !/^[A-Za-z0-9_-]{32,128}$/.test(list[i].token)) throw Error();
      if (list[0].origin === list[1].origin) throw Error();
    } catch (_) { return stop('请输入运营者提供的有效参与码；需要两个已批准的独立接入点。'); }
    if (hide() && !background.checked) return stop('请在前台开始，或主动允许后台继续。');
    if (window.ZioktCompute) window.ZioktCompute.stop();
    active = true; peers = list; bytes = 0; completed = 0; var generation = ++epoch; keepAwake();
    button.textContent = '停止助力'; button.setAttribute('aria-pressed', 'true'); status.textContent = '正在连接网络协作节点';
    open(peers[0], generation, function () { open(peers[1], generation, function () {
      status.textContent = '人民助力运行中 · 加密网络协作'; pump(peers[0], peers[1], generation); pump(peers[1], peers[0], generation);
    }); });
  }
  button.addEventListener('click', function (event) {
    if (!networkMode() && !active) return;
    if (event.stopImmediatePropagation) event.stopImmediatePropagation(); event.preventDefault();
    if (active) stop(); else start();
  }, true);
  mode.addEventListener('change', function () { stop(); if (window.ZioktCompute) window.ZioktCompute.stop(); });
  function visibility() { if (active && hide() && !background.checked) stop('已按设置暂停后台协作'); else if (active && background.checked) keepAwake(); else if (wakeLock) { wakeLock.release(); wakeLock = null; } }
  document.addEventListener('visibilitychange', visibility); document.addEventListener('webkitvisibilitychange', visibility);
  background.addEventListener('change', visibility);
  window.addEventListener('pagehide', function () { if (active) stop('页面已离开；网络协作已停止'); });
  var config = new XMLHttpRequest(); config.open('GET', '/api/people/config', true); config.timeout = 5000;
  config.onload = function () { try { var value = JSON.parse(config.responseText); if (config.status === 200 && value.schema === 'ziokt.people-help.v1' && Object.prototype.toString.call(value.relay_origins) === '[object Array]') origins = value.relay_origins; } catch (_) {} };
  config.send();
  window.ZioktPeopleRelay = {stop: stop, supported: function () { return !!(window.XMLHttpRequest && window.JSON); }};
}());
