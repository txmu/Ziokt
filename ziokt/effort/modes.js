/* Relevant controls only. Keep the network mode compatible with ES5 browsers. */
(function () {
  'use strict';
  var selector=document.getElementById('help-mode');
  function effective() {
    if(selector.value!=='auto')return selector.value;
    return window.isSecureContext===true&&window.crypto&&window.crypto.subtle&&typeof Worker==='function'&&typeof fetch==='function'&&typeof BigInt==='function'&&typeof AbortController==='function'&&typeof TextEncoder==='function'?'compute':'network';
  }
  function refresh() {
    var selected=effective(),groups=document.querySelectorAll('[data-effort-modes]');
    for(var index=0;index<groups.length;index++){
      var group=groups[index],visible=(' '+group.getAttribute('data-effort-modes')+' ').indexOf(' '+selected+' ')>=0;
      group.hidden=!visible;
      var inputs=group.querySelectorAll('input,select,textarea,button');
      for(var field=0;field<inputs.length;field++)inputs[field].disabled=!visible;
    }
    document.querySelector('.connection-settings').hidden=selected==='openci';
    var receipt=document.getElementById('relay-receipt-export');
    if(receipt)receipt.hidden=selected!=='network'||!window.ZioktRelayReceipt;
  }
  selector.addEventListener('change',refresh);
  window.ZioktEffortMode={effective:effective,refresh:refresh};
  refresh();
}());
