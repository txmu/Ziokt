import { renderToolPanel } from '../core.js';
export function renderFiles(container) {
  return renderToolPanel(container, 'SafeFS 分块对象存储', n => n.startsWith('safefs_') || n.startsWith('ufs_'), true);
}
