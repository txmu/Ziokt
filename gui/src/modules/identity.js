import { renderToolPanel } from '../core.js';
export function renderIdentity(container) {
  return renderToolPanel(container, '身份、所有权与白名单审批', n => /registration|identity|zkn|zkc|recovery/.test(n), false);
}
