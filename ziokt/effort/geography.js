/* Small offline geography lesson; ES5, no external map tiles or device APIs. */
(function () {
  'use strict';
  var input = document.getElementById('latitude');
  function draw() {
    var angle = Number(input.value), ratio = Math.cos(angle * Math.PI / 180);
    if ([0, 30, 60, 80].indexOf(angle) < 0) return;
    var line = document.getElementById('selected-latitude');
    line.setAttribute('cy', String(157 - 118 * Math.sin(angle * Math.PI / 180)));
    line.setAttribute('rx', String(118 * ratio)); line.setAttribute('ry', String(21.2 * ratio));
    document.getElementById('latitude-leader').setAttribute('d', 'M' + (200 + 118 * ratio) + ' ' + (157 - 118 * Math.sin(angle * Math.PI / 180)) + 'H355');
    document.getElementById('latitude-label').setAttribute('y', String(Math.max(20, 143 - 118 * Math.sin(angle * Math.PI / 180))));
    document.getElementById('latitude-label').textContent = angle + '°' + (angle ? ' N' : '');
    document.getElementById('latitude-ratio').textContent = (ratio * 100).toFixed(1) + '%';
  }
  input.addEventListener('change', draw); draw();
}());
