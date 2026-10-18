import { renderToolPanel } from '../core.js';
export function renderHome(container) {
  return renderToolPanel(container, '节点实时总览', n => /status|components|stats/.test(n), false);
}
