import { renderToolPanel } from '../core.js';
export function renderNetwork(container) {
  return renderToolPanel(container, 'Shadow6 / ETP 实时网络能力', n => n.startsWith('shadow6_') || n.startsWith('etp_'), false);
}
