import { renderToolPanel } from '../core.js';
export function renderForum(container) {
  return renderToolPanel(container, '真实社区论坛', n => /forum|cbb|wiki/.test(n), false);
}
