import { renderToolPanel } from '../core.js';
export function renderDevtools(container) {
  return renderToolPanel(container, '原生开发工具与 MCP 目录', n => /^(corium_|tri_|zda_|tc16_|ziokt_)/.test(n), false);
}
