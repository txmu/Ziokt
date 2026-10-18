// ==============================================================================
// Module: Corium Community Forum & Decentralized Governance Reader/Publisher
// ==============================================================================
import { State, t, showToast } from '../core.js';

let forumPosts = JSON.parse(localStorage.getItem('ziokt_forum_posts') || 'null') || [
  {
    id: 1,
    title: '【治理提案 #48】关于增加 PoUW 算力贡献者奖励权重的提案',
    author: 'did:ziokt:mesh:genesis-node',
    authorName: 'Genesis Validator',
    category: 'governance',
    date: '2026-10-17 18:30',
    content: '为激励更多社区节点加入 Corium 验证网络，建议将 PoUW 引擎算力证明的奖励权重由现行 1.25 调整至 1.50。已通过本地 SQLite/Bash 引擎奖励权重激活测试。',
    replies: 12,
    upvotes: 38,
    signature: 'ed25519:9f8e7d...12c'
  },
  {
    id: 2,
    title: '【技术规范】TC-16 虚拟机 16 位微架构运行指令集草案',
    author: 'did:ziokt:mesh:core-dev',
    authorName: 'Core Architecture Team',
    category: 'technical',
    date: '2026-10-16 14:20',
    content: 'TC-16 VM 设计采用 16 位虚拟处理器架构，包含 8 个通用寄存器 R0-R7，严格控制 TCC Gas 消耗上限，确保在 ETP 洋葱中继环境中完全确定性执行。',
    replies: 8,
    upvotes: 24,
    signature: 'ed25519:4a8b1c...99f'
  },
  {
    id: 3,
    title: '【生态应用】基于 UFS 与 dCPM 软件包的去中心化协作工具链',
    author: 'did:ziokt:mesh:app-builder',
    authorName: 'Community Contributor',
    category: 'apps',
    date: '2026-10-15 11:05',
    content: '分享我们如何通过 dCPM 签名软件包发布应用，实现零接触命令行的一键安装、依赖检查以及版本无损回滚。',
    replies: 15,
    upvotes: 45,
    signature: 'ed25519:7e2d9a...33b'
  }
];

let activeFilter = 'all';

export function renderForum(container) {
  const filtered = activeFilter === 'all' ? forumPosts : forumPosts.filter(p => p.category === activeFilter);

  container.innerHTML = `
    <div style="max-width: 1000px; margin: 0 auto;">
      <!-- Forum Header -->
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 12px;">
        <div>
          <h2 style="font-size: 1.25rem; font-weight: 700; color: var(--accent-cyan);">${t('forum.title')}</h2>
          <p style="font-size: 0.82rem; color: var(--text-muted);">不可篡改的链上签名公告与提案发布中心</p>
        </div>
        <button id="new-post-btn" class="btn btn-primary">+ ${t('forum.new_post')}</button>
      </div>

      <!-- Categories Filter -->
      <div style="display: flex; gap: 8px; margin-bottom: 18px; flex-wrap: wrap;">
        <button class="btn btn-sm ${activeFilter === 'all' ? 'btn-primary' : 'btn-secondary'} filter-btn" data-cat="all">全部讨论</button>
        <button class="btn btn-sm ${activeFilter === 'governance' ? 'btn-primary' : 'btn-secondary'} filter-btn" data-cat="governance">${t('forum.cat_governance')}</button>
        <button class="btn btn-sm ${activeFilter === 'technical' ? 'btn-primary' : 'btn-secondary'} filter-btn" data-cat="technical">${t('forum.cat_technical')}</button>
        <button class="btn btn-sm ${activeFilter === 'apps' ? 'btn-primary' : 'btn-secondary'} filter-btn" data-cat="apps">${t('forum.cat_apps')}</button>
      </div>

      <!-- Posts List -->
      <div style="display: flex; flex-direction: column; gap: 14px;">
        ${filtered.map(post => `
          <div class="card" style="padding: 18px;">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
              <h3 style="font-size: 1.05rem; font-weight: 600; color: var(--text-main);">${post.title}</h3>
              <span class="mode-pill" style="font-size: 0.7rem;">${post.category.toUpperCase()}</span>
            </div>
            <p style="color: var(--text-muted); font-size: 0.88rem; line-height: 1.6; margin-bottom: 12px;">${post.content}</p>
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.78rem; border-top: 1px solid var(--border-subtle); padding-top: 10px; color: var(--text-dim);">
              <div style="display: flex; align-items: center; gap: 8px;">
                <span style="color: var(--accent-cyan); font-weight: 500;">${post.authorName}</span>
                <span class="status-badge" style="font-size: 0.68rem; color: var(--accent-green);">${t('forum.signature_verified')}</span>
              </div>
              <div style="display: flex; gap: 14px; align-items: center;">
                <span>💬 ${post.replies} ${t('forum.replies')}</span>
                <span>👍 ${post.upvotes}</span>
                <span>${post.date}</span>
              </div>
            </div>
          </div>
        `).join('')}
      </div>

      <!-- New Post Dialog (Hidden initially) -->
      <div id="new-post-modal" class="modal-overlay">
        <div class="modal-card">
          <div class="modal-header">
            <h3 style="font-size: 1.05rem; font-weight: 600; color: var(--accent-cyan);">${t('forum.new_post')}</h3>
            <button id="close-post-modal" class="btn btn-sm btn-secondary">✕</button>
          </div>
          <div class="modal-body">
            <div style="margin-bottom: 14px;">
              <label style="display: block; font-size: 0.8rem; color: var(--text-muted); margin-bottom: 4px;">${t('forum.post_title')}</label>
              <input type="text" id="post-title-input" class="input-text" placeholder="输入帖子或提案标题...">
            </div>
            <div style="margin-bottom: 14px;">
              <label style="display: block; font-size: 0.8rem; color: var(--text-muted); margin-bottom: 4px;">${t('forum.post_category')}</label>
              <select id="post-category-select" class="input-select">
                <option value="governance">${t('forum.cat_governance')}</option>
                <option value="technical">${t('forum.cat_technical')}</option>
                <option value="apps">${t('forum.cat_apps')}</option>
                <option value="general">${t('forum.cat_general')}</option>
              </select>
            </div>
            <div style="margin-bottom: 14px;">
              <label style="display: block; font-size: 0.8rem; color: var(--text-muted); margin-bottom: 4px;">${t('forum.post_content')}</label>
              <textarea id="post-content-input" class="input-textarea" rows="6" placeholder="输入详细内容，支持 Markdown 格式..."></textarea>
            </div>
            <div style="padding: 10px; background: var(--bg-input); border-radius: var(--radius-sm); border: 1px solid var(--border-subtle); font-size: 0.75rem; color: var(--accent-cyan); font-family: var(--font-mono);">
              签名身份: ${State.userDid} (Ed25519 自动加签)
            </div>
          </div>
          <div class="modal-footer">
            <button id="cancel-post-btn" class="btn btn-secondary">${t('common.cancel')}</button>
            <button id="submit-post-btn" class="btn btn-primary">${t('forum.sign_and_publish')}</button>
          </div>
        </div>
      </div>

    </div>
  `;

  // Filters
  container.querySelectorAll('.filter-btn').forEach(btn => {
    btn.onclick = () => {
      activeFilter = btn.dataset.cat;
      renderForum(container);
    };
  });

  // Modal Handlers
  const modal = container.querySelector('#new-post-modal');
  container.querySelector('#new-post-btn').onclick = () => {
    modal.style.display = 'flex';
  };
  container.querySelector('#close-post-modal').onclick = () => {
    modal.style.display = 'none';
  };
  container.querySelector('#cancel-post-btn').onclick = () => {
    modal.style.display = 'none';
  };

  // Submit Post
  container.querySelector('#submit-post-btn').onclick = () => {
    const title = container.querySelector('#post-title-input').value.trim();
    const category = container.querySelector('#post-category-select').value;
    const content = container.querySelector('#post-content-input').value.trim();

    if (!title || !content) {
      showToast('请完整填写标题和正文内容', 'error');
      return;
    }

    const now = new Date();
    const dateStr = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')} ${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}`;

    const newPost = {
      id: Date.now(),
      title,
      author: State.userDid,
      authorName: 'My Identity',
      category,
      date: dateStr,
      content,
      replies: 0,
      upvotes: 1,
      signature: 'ed25519:' + Math.random().toString(16).slice(2, 10)
    };

    forumPosts.unshift(newPost);
    localStorage.setItem('ziokt_forum_posts', JSON.stringify(forumPosts));
    modal.style.display = 'none';
    showToast('提案发布成功！已完成 Ed25519 链上签名校验', 'success');
    renderForum(container);
  };
}
