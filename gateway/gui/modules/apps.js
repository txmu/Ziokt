import { renderToolPanel } from '../core.js';
export function renderApps(container) {
  return renderToolPanel(container, 'dCPM 与原生应用管理', n => n.startsWith('dcpm_') || n.includes('package_'), true);
}
