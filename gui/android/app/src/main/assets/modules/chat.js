/* Native WATChat owns authentication, keys, encryption and delivery receipts. */
import { State, getStorage, setStorage } from '../core.js';

export function renderChat(container) {
  const label = (zh, en) => State.language === 'en' ? en : zh;
  const node = (tag, text) => { const el = document.createElement(tag); el.textContent = text; return el; };
  container.replaceChildren();
  const card = node('section', ''); card.className = 'card';
  card.append(node('h2', 'WATChat'), node('p', label(
    '请在原生 WATChat 中登录、核对联系人指纹并发送消息。网关登录不代表聊天身份已登录。',
    'Sign in, verify contact fingerprints and send messages in native WATChat. Gateway authentication does not sign in to chat.')),
    node('p', label('当前随附原生实现：ECDH P-256 / HKDF-SHA256 / AES-256-GCM。此说明不代表握手或投递已完成。',
    'Bundled native implementation: ECDH P-256 / HKDF-SHA256 / AES-256-GCM. This description is not handshake or delivery evidence.')));
  const form = node('form', ''), caption = node('label', label('原生 WATChat 地址', 'Native WATChat URL'));
  const input = document.createElement('input'); input.type = 'url'; input.required = true;
  input.id = 'watchat-native-url'; input.className = 'input-text';
  input.value = getStorage('ziokt_endpoint_watchat') || (State.serviceEndpoints || {}).watchat || '';
  input.placeholder = 'https://'; caption.htmlFor = input.id;
  const save = node('button', label('保存入口', 'Save entrypoint')); save.className = 'btn btn-secondary';
  const status = node('p', label('尚未验证原生会话或消息投递。', 'Native session and delivery have not been verified.')); status.setAttribute('role', 'status');
  const link = node('a', label('打开原生 WATChat', 'Open native WATChat'));
  link.id = 'watchat-native-open'; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.hidden = true;
  const validate = () => {
    const url = new URL(input.value);
    if ((url.protocol !== 'https:' && !(url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))) || url.username || url.password || url.search || url.hash)
      throw Error(label('请使用 HTTPS 地址或本机 HTTP 地址，不含凭证、查询或片段。', 'Use HTTPS or loopback HTTP without credentials, query or fragment.'));
    return url.href;
  };
  const refresh = () => { link.hidden = true; link.removeAttribute('href'); if (input.value) { link.href = validate(); link.hidden = false; } };
  input.oninput = () => { link.hidden = true; link.removeAttribute('href'); };
  form.onsubmit = event => { event.preventDefault(); try { const url = validate(); setStorage('ziokt_endpoint_watchat', url); refresh(); status.textContent = label('入口已保存；会话和投递状态仍需原生应用验证。', 'Entrypoint saved; session and delivery still require native verification.'); } catch(error) { link.hidden = true; status.textContent = error.message; } };
  try { refresh(); } catch(error) { status.textContent = error.message; }
  form.append(caption, input, save); card.append(form, link, status); container.append(card);
}
